BEGIN;
-- Explicit policy grants are data, not an assumption that TECH_ADMIN can grade.
CREATE TABLE academic_action_grants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id),
  department_id uuid NOT NULL REFERENCES departments(id),
  action_code text NOT NULL CHECK(action_code IN ('APPROVE_SCHEME','PUBLISH_RESULTS','CORRECT_RESULTS')),
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_until timestamptz,
  CHECK(valid_until IS NULL OR valid_until>valid_from)
);
CREATE UNIQUE INDEX uq_current_academic_action ON academic_action_grants(user_id,department_id,action_code) WHERE valid_until IS NULL;
ALTER TABLE result_releases ADD COLUMN sealed_at timestamptz;
ALTER TABLE result_releases ADD COLUMN correction_reason text;
ALTER TABLE result_releases ADD COLUMN authorization_grant_id uuid REFERENCES academic_action_grants(id);
DROP TRIGGER lock_result_releases ON result_releases;
UPDATE result_releases SET sealed_at=released_at;
ALTER TABLE result_releases ADD CHECK(supersedes_id IS DISTINCT FROM id);
CREATE UNIQUE INDEX uq_release_successor ON result_releases(supersedes_id) WHERE supersedes_id IS NOT NULL;

CREATE FUNCTION smartpro_academic_grant(uid uuid,dept uuid,act text) RETURNS uuid LANGUAGE sql STABLE AS $$
  SELECT g.id FROM academic_action_grants g JOIN users u ON u.id=g.user_id
    WHERE g.user_id=uid AND g.department_id=dept AND g.action_code=act AND u.account_status='ACTIVE'
    AND g.valid_from<=statement_timestamp() AND (g.valid_until IS NULL OR statement_timestamp()<g.valid_until)
    ORDER BY g.valid_from,g.id LIMIT 1
$$;

CREATE FUNCTION smartpro_scheme_approver() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE dept uuid;
BEGIN
  IF OLD.state='DRAFT' AND NEW.state='APPROVED' THEN
    SELECT es.department_id INTO dept FROM evaluation_schemes es WHERE es.id=NEW.scheme_id;
    IF smartpro_academic_grant(NEW.approved_by,dept,'APPROVE_SCHEME') IS NULL THEN
      RAISE EXCEPTION 'scheme approval requires explicit department authority' USING ERRCODE='42501'; END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER authorize_scheme_approval BEFORE UPDATE ON scheme_versions
  FOR EACH ROW EXECUTE FUNCTION smartpro_scheme_approver();

CREATE FUNCTION smartpro_release_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r project_reviews; prev result_releases; dept uuid; action_name text;
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'release history immutable' USING ERRCODE='23514'; END IF;
  IF TG_OP='UPDATE' THEN
    IF OLD.sealed_at IS NOT NULL OR (to_jsonb(NEW)-'sealed_at') IS DISTINCT FROM (to_jsonb(OLD)-'sealed_at') THEN
      RAISE EXCEPTION 'release is immutable; only initial sealing allowed' USING ERRCODE='23514'; END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO r FROM project_reviews WHERE id=NEW.review_id FOR UPDATE;
  IF r.review_state NOT IN ('FINALIZED','RELEASED') OR r.roster_locked_at IS NULL THEN
    RAISE EXCEPTION 'publication requires finalized frozen review' USING ERRCODE='23514'; END IF;
  SELECT department_id INTO dept FROM projects WHERE id=r.project_id;
  SELECT * INTO prev FROM result_releases WHERE review_id=r.id ORDER BY release_no DESC LIMIT 1;
  IF prev.id IS NULL THEN
    IF NEW.release_no<>1 OR NEW.supersedes_id IS NOT NULL THEN
      RAISE EXCEPTION 'initial release must be version 1' USING ERRCODE='23514'; END IF;
    action_name:='PUBLISH_RESULTS';
  ELSE
    IF NEW.release_no<>prev.release_no+1 OR NEW.supersedes_id IS DISTINCT FROM prev.id
      OR NEW.correction_reason IS NULL OR btrim(NEW.correction_reason)='' THEN
      RAISE EXCEPTION 'correction requires latest release and a reason' USING ERRCODE='23514'; END IF;
    action_name:='CORRECT_RESULTS';
  END IF;
  NEW.authorization_grant_id:=smartpro_academic_grant(NEW.released_by,dept,action_name);
  IF NEW.authorization_grant_id IS NULL THEN
    RAISE EXCEPTION 'publication/correction requires explicit scoped grant' USING ERRCODE='42501'; END IF;
  IF NEW.sealed_at IS NOT NULL THEN RAISE EXCEPTION 'release must be assembled then sealed' USING ERRCODE='23514'; END IF;
  NEW.released_at:=statement_timestamp();
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_release BEFORE INSERT OR UPDATE OR DELETE ON result_releases
  FOR EACH ROW EXECUTE FUNCTION smartpro_release_guard();

CREATE FUNCTION smartpro_release_child() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE stamp timestamptz;
BEGIN
  SELECT sealed_at INTO stamp FROM result_releases WHERE id=NEW.release_id FOR UPDATE;
  IF stamp IS NOT NULL THEN RAISE EXCEPTION 'published release cannot accept new source/score rows' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER zz_guard_release_student_insert AFTER INSERT ON result_student_scores
  FOR EACH ROW EXECUTE FUNCTION smartpro_release_child();
CREATE TRIGGER zz_guard_release_source_insert AFTER INSERT ON result_source_assessments
  FOR EACH ROW EXECUTE FUNCTION smartpro_release_child();

CREATE FUNCTION smartpro_release_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE rr result_releases; aid uuid; sid uuid; roster_n integer; score_n integer;
        v record; team_total numeric; student_total numeric;
BEGIN
  SELECT * INTO rr FROM result_releases WHERE id=NEW.id;
  IF rr.sealed_at IS NULL THEN RAISE EXCEPTION 'release must be sealed before commit' USING ERRCODE='23514'; END IF;
  -- Deliberately narrow, named TEST policy. Other/multiple-evaluator methods are unconfigured.
  IF rr.calculation_snapshot->>'method' IS DISTINCT FROM 'single_evaluator_sum'
    OR rr.calculation_snapshot->>'exampleOnly' IS DISTINCT FROM 'true' THEN
    RAISE EXCEPTION 'no approved aggregation policy configured (test single-evaluator policy only)' USING ERRCODE='23514'; END IF;
  IF (SELECT count(*) FROM result_source_assessments WHERE release_id=rr.id)<>1 THEN
    RAISE EXCEPTION 'test publication requires exactly one explicit source' USING ERRCODE='23514'; END IF;
  IF (SELECT count(*) FROM assessments WHERE review_id=rr.review_id AND state='FINALIZED')<>1 THEN
    RAISE EXCEPTION 'multi-evaluator aggregation policy is not configured' USING ERRCODE='23514'; END IF;
  SELECT a.id INTO aid FROM result_source_assessments s JOIN assessments a ON a.id=s.assessment_id
    WHERE s.release_id=rr.id AND a.review_id=rr.review_id AND a.scheme_mode_id=rr.scheme_mode_id AND a.state='FINALIZED';
  IF aid IS NULL THEN RAISE EXCEPTION 'source must be finalized in exact review/mode' USING ERRCODE='23514'; END IF;
  SELECT count(*) INTO roster_n FROM review_roster_members WHERE review_id=rr.review_id;
  SELECT count(*) INTO score_n FROM result_student_scores WHERE release_id=rr.id;
  IF roster_n=0 OR roster_n<>score_n THEN RAISE EXCEPTION 'release must include complete frozen roster' USING ERRCODE='23514'; END IF;
  SELECT coalesce(sum(marks),0) INTO team_total FROM team_criterion_scores WHERE assessment_id=aid;
  FOR v IN SELECT * FROM result_student_scores WHERE release_id=rr.id LOOP
    SELECT coalesce(sum(marks),0) INTO student_total FROM student_criterion_scores WHERE assessment_id=aid AND roster_member_id=v.roster_member_id;
    IF v.total_marks<>team_total+student_total
      OR NOT(v.breakdown @> jsonb_build_object('team',team_total,'individual',student_total)) THEN
      RAISE EXCEPTION 'published score/breakdown differs from finalized source marks' USING ERRCODE='23514'; END IF;
  END LOOP;
  RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER verify_release_complete AFTER INSERT OR UPDATE ON result_releases
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION smartpro_release_complete();

CREATE FUNCTION smartpro_publication_audit() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE pid uuid;
BEGIN
  IF OLD.sealed_at IS NULL AND NEW.sealed_at IS NOT NULL THEN
    SELECT project_id INTO pid FROM project_reviews WHERE id=NEW.review_id;
    INSERT INTO audit_events(actor_id,project_id,action,target_type,target_id,metadata)
      VALUES(NEW.released_by,pid,'RESULT_RELEASED','RESULT_RELEASE',NEW.id,
        jsonb_build_object('releaseNo',NEW.release_no,'supersedesId',NEW.supersedes_id,'reason',NEW.correction_reason,'grantId',NEW.authorization_grant_id));
    INSERT INTO outbox_events(event_type,aggregate_id,payload)
      VALUES('RESULT_RELEASED',NEW.id,jsonb_build_object('releaseId',NEW.id,'releaseNo',NEW.release_no));
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER audit_publication AFTER UPDATE ON result_releases
  FOR EACH ROW EXECUTE FUNCTION smartpro_publication_audit();

CREATE FUNCTION smartpro_grant_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS(SELECT 1 FROM result_releases WHERE authorization_grant_id=OLD.id) THEN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'release authorization history immutable' USING ERRCODE='23514'; END IF;
    IF (to_jsonb(NEW)-'valid_until') IS DISTINCT FROM (to_jsonb(OLD)-'valid_until') OR EXISTS(
      SELECT 1 FROM result_releases WHERE authorization_grant_id=OLD.id AND NEW.valid_until<=released_at) THEN
      RAISE EXCEPTION 'grant edit would falsify historical authority' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER freeze_grant_history BEFORE UPDATE OR DELETE ON academic_action_grants
  FOR EACH ROW EXECUTE FUNCTION smartpro_grant_history();
COMMIT;
