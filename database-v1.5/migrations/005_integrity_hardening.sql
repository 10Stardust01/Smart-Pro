-- Forward hardening for the supplied v1.5 prototype; existing evidence is sealed.
BEGIN;
ALTER TABLE submission_attempts ADD COLUMN sealed_at timestamptz;
UPDATE submission_attempts SET sealed_at=submitted_at;
ALTER TABLE approval_decisions ADD COLUMN faculty_assignment_id uuid;
ALTER TABLE faculty_assignments ADD UNIQUE(id,project_id,faculty_user_id);
ALTER TABLE approval_decisions ADD FOREIGN KEY(faculty_assignment_id,project_id,reviewer_user_id)
  REFERENCES faculty_assignments(id,project_id,faculty_user_id);
ALTER TABLE file_assets ADD CONSTRAINT ready_has_verification
  CHECK(upload_status<>'READY' OR verified_at IS NOT NULL) NOT VALID;
-- Fail, rather than manufacture verification for existing inconsistent READY rows.
ALTER TABLE file_assets VALIDATE CONSTRAINT ready_has_verification;
ALTER TABLE rubric_criteria ADD CHECK(maximum::text<>'NaN');
ALTER TABLE team_criterion_scores ADD CHECK(marks::text<>'NaN');
ALTER TABLE student_criterion_scores ADD CHECK(marks::text<>'NaN');
ALTER TABLE result_student_scores ADD CHECK(total_marks::text<>'NaN');

CREATE FUNCTION smartpro_has_role(uid uuid, dept uuid, role_name text, at_time timestamptz)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT EXISTS(SELECT 1 FROM department_role_assignments r JOIN users u ON u.id=r.user_id
    WHERE r.user_id=uid AND r.department_id=dept AND r.role_code=role_name
    AND r.valid_from<=at_time AND (r.valid_until IS NULL OR at_time<r.valid_until)
    AND u.account_status='ACTIVE')
$$;

CREATE FUNCTION smartpro_project_policy_binding() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='INSERT' OR (NEW.policy_version_id,NEW.department_id,NEW.project_type)
    IS DISTINCT FROM (OLD.policy_version_id,OLD.department_id,OLD.project_type) THEN
    PERFORM 1 FROM project_policy_versions WHERE id=NEW.policy_version_id
      AND department_id=NEW.department_id AND project_type=NEW.project_type
      AND policy_status='APPROVED' FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'new project binding requires approved scoped policy' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER check_project_policy BEFORE INSERT OR UPDATE ON projects
  FOR EACH ROW EXECUTE FUNCTION smartpro_project_policy_binding();

CREATE FUNCTION smartpro_immutable_configuration() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE st text;
BEGIN
  IF TG_TABLE_NAME='scheme_versions' THEN st:=CASE WHEN TG_OP='INSERT' THEN NEW.state ELSE OLD.state END;
  ELSE st:=CASE WHEN TG_OP='INSERT' THEN NEW.policy_status ELSE OLD.policy_status END; END IF;
  IF TG_OP='INSERT' THEN
    -- Policies may be imported already approved; schemes must validate their child mappings.
    IF TG_TABLE_NAME='scheme_versions' AND st<>'DRAFT' THEN
      RAISE EXCEPTION 'scheme must start DRAFT and pass approval validation' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  IF st<>'DRAFT' THEN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'approved configuration is immutable' USING ERRCODE='23514'; END IF;
    IF (to_jsonb(NEW)-'state'-'policy_status') IS DISTINCT FROM (to_jsonb(OLD)-'state'-'policy_status') THEN
      RAISE EXCEPTION 'approved configuration identity and metadata are immutable' USING ERRCODE='23514';
    END IF;
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER freeze_scheme_version BEFORE INSERT OR UPDATE OR DELETE ON scheme_versions
  FOR EACH ROW EXECUTE FUNCTION smartpro_immutable_configuration();
CREATE TRIGGER freeze_policy_metadata BEFORE UPDATE OR DELETE ON project_policy_versions
  FOR EACH ROW EXECUTE FUNCTION smartpro_immutable_configuration();

CREATE FUNCTION smartpro_mode_scope_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (NEW.mode_code='TEAM' AND EXISTS(SELECT 1 FROM mode_criteria WHERE scheme_mode_id=OLD.id AND score_scope<>'TEAM'))
    OR (NEW.mode_code='INDIVIDUAL' AND EXISTS(SELECT 1 FROM mode_criteria WHERE scheme_mode_id=OLD.id AND score_scope<>'STUDENT')) THEN
    RAISE EXCEPTION 'mode conflicts with existing criterion scopes' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER validate_mode_scope_change BEFORE UPDATE ON scheme_modes
  FOR EACH ROW EXECUTE FUNCTION smartpro_mode_scope_change();

CREATE FUNCTION smartpro_attempt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'formal attempt history is append-only' USING ERRCODE='23514';
  END IF;
  IF (to_jsonb(NEW)-'sealed_at'-'attempt_state') IS DISTINCT FROM (to_jsonb(OLD)-'sealed_at'-'attempt_state')
    OR (OLD.sealed_at IS NOT NULL AND NEW.sealed_at IS DISTINCT FROM OLD.sealed_at) THEN
    RAISE EXCEPTION 'attempt identity/item-set seal is immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.attempt_state IS DISTINCT FROM OLD.attempt_state AND OLD.sealed_at IS NOT NULL THEN
    IF OLD.attempt_state<>'SUBMITTED' OR NOT EXISTS(SELECT 1 FROM approval_decisions
      WHERE attempt_id=OLD.id AND CASE decision WHEN 'APPROVE' THEN 'APPROVED'
        WHEN 'REQUEST_CHANGES' THEN 'CHANGES_REQUESTED' ELSE 'REJECTED' END=NEW.attempt_state) THEN
      RAISE EXCEPTION 'attempt outcome requires its own decision' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER freeze_attempt_identity BEFORE UPDATE OR DELETE ON submission_attempts
  FOR EACH ROW EXECUTE FUNCTION smartpro_attempt_guard();

CREATE FUNCTION smartpro_submission_item_set() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE stamp timestamptz;
BEGIN
  IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'submitted item references are immutable' USING ERRCODE='23514'; END IF;
  SELECT sealed_at INTO stamp FROM submission_attempts WHERE id=NEW.attempt_id FOR UPDATE;
  IF stamp IS NOT NULL THEN RAISE EXCEPTION 'sealed attempt cannot accept additional items' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END;
$$;
-- AFTER insertion permits composite foreign keys to report ownership violations first.
CREATE TRIGGER zz_guard_item_set AFTER INSERT OR UPDATE OR DELETE ON submission_items
  FOR EACH ROW EXECUTE FUNCTION smartpro_submission_item_set();

CREATE FUNCTION smartpro_attempt_complete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM 1 FROM submission_attempts a WHERE a.id=NEW.id AND a.sealed_at IS NOT NULL
    AND EXISTS(SELECT 1 FROM submission_items i WHERE i.attempt_id=a.id);
  IF NOT FOUND THEN RAISE EXCEPTION 'formal attempt requires sealed nonempty item set at commit' USING ERRCODE='23514'; END IF;
  RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER complete_attempt AFTER INSERT OR UPDATE ON submission_attempts
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION smartpro_attempt_complete();

CREATE FUNCTION smartpro_decision_authority() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a submission_attempts; c submission_cases; dept uuid;
BEGIN
  SELECT * INTO a FROM submission_attempts WHERE id=NEW.attempt_id FOR UPDATE;
  IF NOT FOUND OR a.project_id<>NEW.project_id THEN RAISE EXCEPTION 'wrong attempt/project' USING ERRCODE='23503'; END IF;
  SELECT * INTO c FROM submission_cases WHERE id=a.case_id FOR UPDATE;
  SELECT department_id INTO dept FROM projects WHERE id=a.project_id;
  IF a.sealed_at IS NULL OR a.attempt_state<>'SUBMITTED' OR c.state<>'AWAITING_REVIEW'
     OR EXISTS(SELECT 1 FROM submission_attempts WHERE case_id=a.case_id AND attempt_no>a.attempt_no) THEN
    RAISE EXCEPTION 'decision requires the latest pending sealed attempt' USING ERRCODE='23514';
  END IF;
  NEW.decided_at:=statement_timestamp();
  SELECT id INTO NEW.faculty_assignment_id FROM faculty_assignments
    WHERE project_id=a.project_id AND faculty_user_id=NEW.reviewer_user_id
      AND assignment_type IN ('GUIDE','REVIEWER') AND valid_from<=NEW.decided_at
      AND (valid_until IS NULL OR NEW.decided_at<valid_until) ORDER BY valid_from,id LIMIT 1 FOR SHARE;
  IF NEW.faculty_assignment_id IS NULL OR NOT smartpro_has_role(NEW.reviewer_user_id,dept,'FACULTY',NEW.decided_at) THEN
    RAISE EXCEPTION 'decision requires active project faculty authority' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER check_decision_authority BEFORE INSERT ON approval_decisions
  FOR EACH ROW EXECUTE FUNCTION smartpro_decision_authority();

CREATE FUNCTION smartpro_membership_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS(SELECT 1 FROM review_roster_members WHERE membership_id=OLD.id) THEN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'membership is referenced by review history' USING ERRCODE='23514'; END IF;
    IF (NEW.id,NEW.team_id,NEW.user_id,NEW.joined_at) IS DISTINCT FROM (OLD.id,OLD.team_id,OLD.user_id,OLD.joined_at)
      OR EXISTS(SELECT 1 FROM review_roster_members rm JOIN project_reviews r ON r.id=rm.review_id
        WHERE rm.membership_id=OLD.id AND r.roster_locked_at IS NOT NULL
        AND NEW.left_at IS NOT NULL AND NEW.left_at<=r.roster_locked_at) THEN
      RAISE EXCEPTION 'membership edit would falsify frozen eligibility' USING ERRCODE='23514';
    END IF;
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER freeze_membership_history BEFORE UPDATE OR DELETE ON team_memberships
  FOR EACH ROW EXECUTE FUNCTION smartpro_membership_history();

CREATE FUNCTION smartpro_roster_freeze_eligibility() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE member record; dept uuid;
BEGIN
  IF OLD.roster_locked_at IS NULL AND NEW.roster_locked_at IS NOT NULL THEN
    SELECT department_id INTO dept FROM projects WHERE id=NEW.project_id;
    FOR member IN SELECT m.* FROM review_roster_members rm JOIN team_memberships m ON m.id=rm.membership_id
      WHERE rm.review_id=OLD.id ORDER BY m.id FOR UPDATE OF m LOOP
      IF member.joined_at>NEW.roster_locked_at OR (member.left_at IS NOT NULL AND member.left_at<=NEW.roster_locked_at)
         OR NOT smartpro_has_role(member.user_id,dept,'STUDENT',NEW.roster_locked_at) THEN
        RAISE EXCEPTION 'roster student not eligible at freeze instant' USING ERRCODE='23514';
      END IF;
    END LOOP;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER validate_roster_eligibility BEFORE UPDATE ON project_reviews
  FOR EACH ROW EXECUTE FUNCTION smartpro_roster_freeze_eligibility();

CREATE FUNCTION smartpro_assignment_integrity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE dept uuid; uid uuid; pid uuid;
BEGIN
  IF TG_TABLE_NAME='evaluator_assignments' THEN
    IF TG_OP<>'INSERT' AND EXISTS(SELECT 1 FROM assessments WHERE evaluator_assignment_id=OLD.id) THEN
      RAISE EXCEPTION 'evaluator assignment is historical assessment evidence' USING ERRCODE='23514';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    SELECT p.department_id INTO dept FROM project_reviews r JOIN projects p ON p.id=r.project_id WHERE r.id=NEW.review_id;
  ELSE
    IF TG_OP<>'INSERT' AND EXISTS(SELECT 1 FROM approval_decisions WHERE faculty_assignment_id=OLD.id) THEN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'decision authority is historical evidence' USING ERRCODE='23514'; END IF;
      IF (to_jsonb(NEW)-'valid_until') IS DISTINCT FROM (to_jsonb(OLD)-'valid_until') OR EXISTS(
        SELECT 1 FROM approval_decisions WHERE faculty_assignment_id=OLD.id AND NEW.valid_until<=decided_at) THEN
        RAISE EXCEPTION 'assignment edit would falsify decision authority' USING ERRCODE='23514';
      END IF;
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    SELECT department_id INTO dept FROM projects WHERE id=NEW.project_id;
  END IF;
  IF NOT smartpro_has_role(NEW.faculty_user_id,dept,'FACULTY',statement_timestamp()) THEN
    RAISE EXCEPTION 'faculty assignment requires scoped faculty role' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER validate_faculty_assignment BEFORE INSERT OR UPDATE OR DELETE ON faculty_assignments
  FOR EACH ROW EXECUTE FUNCTION smartpro_assignment_integrity();
CREATE TRIGGER validate_evaluator_assignment BEFORE INSERT OR UPDATE OR DELETE ON evaluator_assignments
  FOR EACH ROW EXECUTE FUNCTION smartpro_assignment_integrity();

CREATE FUNCTION smartpro_assessment_identity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r project_reviews;
BEGIN
  IF TG_OP='DELETE' THEN
    IF OLD.state='FINALIZED' THEN RAISE EXCEPTION 'finalized assessment immutable' USING ERRCODE='23514'; END IF;
    RETURN OLD;
  END IF;
  IF TG_OP='INSERT' THEN
    SELECT * INTO r FROM project_reviews WHERE id=NEW.review_id FOR UPDATE;
    IF NEW.state<>'DRAFT' OR NEW.finalized_at IS NOT NULL THEN
      RAISE EXCEPTION 'assessment must start DRAFT' USING ERRCODE='23514'; END IF;
    IF r.review_state<>'OPEN' OR r.roster_locked_at IS NULL THEN
      RAISE EXCEPTION 'assessment requires open frozen review' USING ERRCODE='23514'; END IF;
  ELSE
    IF OLD.state='FINALIZED' THEN RAISE EXCEPTION 'finalized assessment immutable' USING ERRCODE='23514'; END IF;
    IF (NEW.id,NEW.review_id,NEW.scheme_mode_id,NEW.evaluator_assignment_id)
      IS DISTINCT FROM (OLD.id,OLD.review_id,OLD.scheme_mode_id,OLD.evaluator_assignment_id) THEN
      RAISE EXCEPTION 'assessment scoring identity cannot be reparented' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER freeze_assessment_identity BEFORE INSERT OR UPDATE OR DELETE ON assessments
  FOR EACH ROW EXECUTE FUNCTION smartpro_assessment_identity();

-- Check FK/scoring scope before mutable-state locks; a finalized row must not hide
-- a cross-mode/cross-review corruption behind a generic finalized-state error.
CREATE OR REPLACE FUNCTION smartpro_validate_score() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE max_marks numeric(9,2); a assessments; expected_scope text;
BEGIN
  expected_scope:=CASE WHEN TG_TABLE_NAME='team_criterion_scores' THEN 'TEAM' ELSE 'STUDENT' END;
  SELECT * INTO a FROM assessments WHERE id=NEW.assessment_id FOR UPDATE;
  SELECT rc.maximum INTO max_marks FROM mode_criteria mc JOIN rubric_criteria rc ON rc.id=mc.criterion_id
    WHERE mc.id=NEW.mode_criterion_id AND mc.scheme_mode_id=NEW.scheme_mode_id AND mc.score_scope=expected_scope;
  IF NOT FOUND OR a.id IS NULL OR a.scheme_mode_id<>NEW.scheme_mode_id THEN
    RAISE EXCEPTION 'invalid assessment/criterion scope' USING ERRCODE='23503'; END IF;
  IF TG_TABLE_NAME='student_criterion_scores' THEN
    IF NEW.review_id<>a.review_id OR NOT EXISTS(SELECT 1 FROM review_roster_members WHERE id=NEW.roster_member_id AND review_id=a.review_id) THEN
      RAISE EXCEPTION 'student score outside exact review roster' USING ERRCODE='23503'; END IF;
  END IF;
  IF TG_OP='UPDATE' AND OLD.assessment_id<>NEW.assessment_id THEN
    RAISE EXCEPTION 'score identity cannot move between assessments' USING ERRCODE='23514'; END IF;
  IF a.state<>'DRAFT' THEN RAISE EXCEPTION 'cannot edit finalized assessment' USING ERRCODE='23514'; END IF;
  IF NEW.marks::text='NaN' OR NEW.marks<0 OR NEW.marks>max_marks THEN
    RAISE EXCEPTION 'marks outside finite criterion range' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END;
$$;
COMMIT;
