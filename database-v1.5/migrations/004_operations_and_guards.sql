BEGIN;
CREATE TABLE audit_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id uuid REFERENCES users(id),
  project_id uuid REFERENCES projects(id),
  action text NOT NULL,
  target_type text NOT NULL,
  target_id uuid,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(metadata)='object'),
  occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_project_time ON audit_events(project_id,occurred_at DESC);
CREATE TABLE outbox_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type text NOT NULL,
  aggregate_id uuid NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(payload)='object'),
  status text NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','CLAIMED','PROCESSED','DEAD')),
  attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
  available_at timestamptz NOT NULL DEFAULT now(),
  claimed_until timestamptz,
  processed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_outbox_pending ON outbox_events(available_at,created_at) WHERE status='PENDING';
CREATE INDEX ix_outbox_expired_claims ON outbox_events(claimed_until) WHERE status='CLAIMED';
CREATE TABLE idempotency_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id uuid NOT NULL REFERENCES users(id),
  operation text NOT NULL,
  key text NOT NULL,
  request_sha256 char(64) NOT NULL CHECK(request_sha256 ~ '^[0-9a-f]{64}$'),
  state text NOT NULL CHECK(state IN ('IN_PROGRESS','COMPLETE','FAILED')),
  response_status integer,
  response_body jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(actor_id,operation,key)
);
CREATE TABLE notification_deliveries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  outbox_event_id uuid NOT NULL REFERENCES outbox_events(id),
  recipient_user_id uuid NOT NULL REFERENCES users(id),
  channel text NOT NULL CHECK(channel IN ('EMAIL','IN_APP')),
  dedupe_key text NOT NULL UNIQUE,
  status text NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','SENT','FAILED')),
  attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
  provider_reference text,
  last_attempt_at timestamptz
);

-- An approved academic lifecycle policy cannot be rewritten in place.
CREATE FUNCTION smartpro_guard_project_policy() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    IF OLD.policy_status <> 'DRAFT' THEN
      RAISE EXCEPTION 'approved academic policy is historical evidence' USING ERRCODE='23514';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.policy_status <> 'DRAFT' THEN
    IF NEW.policy_data IS DISTINCT FROM OLD.policy_data OR
       NEW.department_id IS DISTINCT FROM OLD.department_id OR
       NEW.project_type IS DISTINCT FROM OLD.project_type OR
       NEW.version_no IS DISTINCT FROM OLD.version_no OR
       NOT (OLD.policy_status='APPROVED' AND NEW.policy_status='RETIRED' OR NEW.policy_status=OLD.policy_status) THEN
      RAISE EXCEPTION 'approved academic policy is immutable' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_academic_policy BEFORE UPDATE OR DELETE ON project_policy_versions
  FOR EACH ROW EXECUTE FUNCTION smartpro_guard_project_policy();

-- A historic document version must keep pointing to the same actual stored bytes.
CREATE FUNCTION smartpro_guard_file_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  IF EXISTS(SELECT 1 FROM document_versions WHERE file_asset_id=OLD.id) AND
     (NEW.storage_key IS DISTINCT FROM OLD.storage_key OR
      NEW.sha256 IS DISTINCT FROM OLD.sha256 OR
      NEW.size_bytes IS DISTINCT FROM OLD.size_bytes OR
      NEW.mime_type IS DISTINCT FROM OLD.mime_type OR
      NEW.uploaded_by IS DISTINCT FROM OLD.uploaded_by) THEN
    RAISE EXCEPTION 'referenced file identity is immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_file_asset_identity BEFORE UPDATE ON file_assets
  FOR EACH ROW EXECUTE FUNCTION smartpro_guard_file_identity();

-- A formal submission may reference only verified, ready-to-use file assets.
CREATE FUNCTION smartpro_guard_submitted_file() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE fstate text;
BEGIN
  SELECT fa.upload_status INTO fstate
    FROM document_versions dv JOIN file_assets fa ON fa.id=dv.file_asset_id
    WHERE dv.id=NEW.document_version_id FOR UPDATE OF fa;
  IF fstate IS DISTINCT FROM 'READY' THEN
    RAISE EXCEPTION 'unverified file cannot be submitted' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER verify_submission_item_file BEFORE INSERT OR UPDATE ON submission_items
  FOR EACH ROW EXECUTE FUNCTION smartpro_guard_submitted_file();

-- Records representing academic evidence are append-only at the SQL layer.
CREATE FUNCTION smartpro_forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'academic evidence is append-only: %', TG_TABLE_NAME USING ERRCODE='23514';
END;
$$;
CREATE TRIGGER lock_document_versions BEFORE UPDATE OR DELETE ON document_versions
  FOR EACH ROW EXECUTE FUNCTION smartpro_forbid_mutation();
CREATE TRIGGER lock_approval_decisions BEFORE UPDATE OR DELETE ON approval_decisions
  FOR EACH ROW EXECUTE FUNCTION smartpro_forbid_mutation();
CREATE TRIGGER lock_audit_events BEFORE UPDATE OR DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION smartpro_forbid_mutation();
CREATE TRIGGER lock_result_releases BEFORE UPDATE OR DELETE ON result_releases
  FOR EACH ROW EXECUTE FUNCTION smartpro_forbid_mutation();
CREATE TRIGGER lock_result_student_scores BEFORE UPDATE OR DELETE ON result_student_scores
  FOR EACH ROW EXECUTE FUNCTION smartpro_forbid_mutation();
CREATE TRIGGER lock_result_source_assessments BEFORE UPDATE OR DELETE ON result_source_assessments
  FOR EACH ROW EXECUTE FUNCTION smartpro_forbid_mutation();

-- Freeze approved scheme criteria and allowed marking modes.
CREATE FUNCTION smartpro_guard_scheme_child() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE ver_id uuid; vstate text;
BEGIN
  IF TG_TABLE_NAME='rubric_criteria' THEN
    ver_id := CASE WHEN TG_OP='DELETE' THEN OLD.scheme_version_id ELSE NEW.scheme_version_id END;
  ELSIF TG_TABLE_NAME='scheme_modes' THEN
    ver_id := CASE WHEN TG_OP='DELETE' THEN OLD.scheme_version_id ELSE NEW.scheme_version_id END;
  ELSE
    ver_id := CASE WHEN TG_OP='DELETE' THEN OLD.scheme_version_id ELSE NEW.scheme_version_id END;
  END IF;
  SELECT state INTO vstate FROM scheme_versions WHERE id=ver_id FOR UPDATE;
  IF vstate <> 'DRAFT' THEN
    RAISE EXCEPTION 'scheme % is locked in state %', ver_id, vstate USING ERRCODE='23514';
  END IF;
  IF TG_OP='UPDATE' AND OLD.scheme_version_id IS DISTINCT FROM NEW.scheme_version_id THEN
    PERFORM 1 FROM scheme_versions WHERE id=OLD.scheme_version_id AND state='DRAFT' FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'cannot move a criterion out of locked scheme' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$;
CREATE TRIGGER lock_rubric_child BEFORE INSERT OR UPDATE OR DELETE ON rubric_criteria
  FOR EACH ROW EXECUTE FUNCTION smartpro_guard_scheme_child();
CREATE TRIGGER lock_mode_child BEFORE INSERT OR UPDATE OR DELETE ON scheme_modes
  FOR EACH ROW EXECUTE FUNCTION smartpro_guard_scheme_child();
CREATE TRIGGER lock_mode_criterion_child BEFORE INSERT OR UPDATE OR DELETE ON mode_criteria
  FOR EACH ROW EXECUTE FUNCTION smartpro_guard_scheme_child();

CREATE FUNCTION smartpro_validate_mode_criterion() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE mode_kind text;
BEGIN
  SELECT mode_code INTO mode_kind FROM scheme_modes WHERE id=NEW.scheme_mode_id;
  IF (mode_kind='TEAM' AND NEW.score_scope <> 'TEAM') OR
     (mode_kind='INDIVIDUAL' AND NEW.score_scope <> 'STUDENT') THEN
    RAISE EXCEPTION 'criterion scope not permitted for mode %',mode_kind USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER check_mode_criterion BEFORE INSERT OR UPDATE ON mode_criteria
  FOR EACH ROW EXECUTE FUNCTION smartpro_validate_mode_criterion();

CREATE FUNCTION smartpro_scheme_transition() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE missing_count integer; has_team boolean; has_student boolean; m record;
BEGIN
  IF OLD.state <> 'DRAFT' THEN
    IF NEW.scheme_id IS DISTINCT FROM OLD.scheme_id OR
       NEW.cycle_id IS DISTINCT FROM OLD.cycle_id OR
       NEW.review_definition_id IS DISTINCT FROM OLD.review_definition_id OR
       NEW.version_no IS DISTINCT FROM OLD.version_no OR
       NEW.approved_by IS DISTINCT FROM OLD.approved_by OR
       NEW.approved_at IS DISTINCT FROM OLD.approved_at OR
       NEW.created_at IS DISTINCT FROM OLD.created_at THEN
       RAISE EXCEPTION 'approved scheme identifiers cannot change' USING ERRCODE='23514';
    END IF;
  END IF;
  IF NEW.state <> OLD.state THEN
    IF NOT ((OLD.state='DRAFT' AND NEW.state='APPROVED') OR
            (OLD.state='APPROVED' AND NEW.state='ACTIVE') OR
            (OLD.state='ACTIVE' AND NEW.state='RETIRED') OR
            (OLD.state='APPROVED' AND NEW.state='RETIRED')) THEN
      RAISE EXCEPTION 'invalid scheme state transition' USING ERRCODE='23514';
    END IF;
  END IF;
  IF OLD.state='DRAFT' AND NEW.state='APPROVED' THEN
    IF NEW.approved_by IS NULL OR NEW.approved_at IS NULL THEN
      RAISE EXCEPTION 'approval requires approver and timestamp' USING ERRCODE='23514';
    END IF;
    IF NOT EXISTS(SELECT 1 FROM rubric_criteria WHERE scheme_version_id=NEW.id) OR
       NOT EXISTS(SELECT 1 FROM scheme_modes WHERE scheme_version_id=NEW.id) THEN
      RAISE EXCEPTION 'scheme needs criteria and permitted modes' USING ERRCODE='23514';
    END IF;
    SELECT count(*) INTO missing_count
      FROM scheme_modes sm CROSS JOIN rubric_criteria rc
      LEFT JOIN mode_criteria mc ON mc.scheme_mode_id=sm.id AND mc.criterion_id=rc.id
      WHERE sm.scheme_version_id=NEW.id AND rc.scheme_version_id=NEW.id AND mc.id IS NULL;
    IF missing_count > 0 THEN
      RAISE EXCEPTION 'every mode must cover every rubric criterion' USING ERRCODE='23514';
    END IF;
    FOR m IN SELECT id,mode_code FROM scheme_modes WHERE scheme_version_id=NEW.id LOOP
      IF m.mode_code='COMBINED' THEN
        SELECT EXISTS(SELECT 1 FROM mode_criteria WHERE scheme_mode_id=m.id AND score_scope='TEAM'),
               EXISTS(SELECT 1 FROM mode_criteria WHERE scheme_mode_id=m.id AND score_scope='STUDENT')
          INTO has_team,has_student;
        IF NOT (has_team AND has_student) THEN
          RAISE EXCEPTION 'combined mode needs both team and student criteria' USING ERRCODE='23514';
        END IF;
      END IF;
    END LOOP;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER validate_scheme_state BEFORE UPDATE ON scheme_versions
  FOR EACH ROW EXECUTE FUNCTION smartpro_scheme_transition();

CREATE FUNCTION smartpro_guard_review_roster() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE rid uuid; lock_time timestamptz;
BEGIN
  rid := CASE WHEN TG_OP='DELETE' THEN OLD.review_id ELSE NEW.review_id END;
  IF TG_OP='UPDATE' AND OLD.review_id IS DISTINCT FROM NEW.review_id THEN
    SELECT roster_locked_at INTO lock_time FROM project_reviews WHERE id=OLD.review_id FOR UPDATE;
    IF lock_time IS NOT NULL THEN
      RAISE EXCEPTION 'cannot move member out of locked roster' USING ERRCODE='23514';
    END IF;
  END IF;
  SELECT roster_locked_at INTO lock_time FROM project_reviews WHERE id=rid FOR UPDATE;
  IF lock_time IS NOT NULL THEN
    RAISE EXCEPTION 'review roster is locked' USING ERRCODE='23514';
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$;
CREATE TRIGGER guard_review_roster BEFORE INSERT OR UPDATE OR DELETE ON review_roster_members
  FOR EACH ROW EXECUTE FUNCTION smartpro_guard_review_roster();

-- Both score types are checked against the exact rubric criterion maximum.
CREATE FUNCTION smartpro_validate_score() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE max_marks numeric(9,2); assessment_state text;
BEGIN
  IF TG_OP='UPDATE' AND OLD.assessment_id IS DISTINCT FROM NEW.assessment_id THEN
    PERFORM 1 FROM assessments WHERE id=OLD.assessment_id AND state='DRAFT' FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'cannot move score out of finalized assessment' USING ERRCODE='23514'; END IF;
  END IF;
  SELECT rc.maximum,a.state INTO max_marks,assessment_state
    FROM assessments a
    JOIN mode_criteria mc ON mc.id=NEW.mode_criterion_id AND mc.scheme_mode_id=NEW.scheme_mode_id
    JOIN rubric_criteria rc ON rc.id=mc.criterion_id
    WHERE a.id=NEW.assessment_id FOR UPDATE OF a;
  IF NOT FOUND THEN RAISE EXCEPTION 'invalid assessment/criterion relation' USING ERRCODE='23503'; END IF;
  IF assessment_state <> 'DRAFT' THEN RAISE EXCEPTION 'cannot edit finalized assessment' USING ERRCODE='23514'; END IF;
  IF NEW.marks > max_marks THEN
    RAISE EXCEPTION 'marks % exceed maximum %',NEW.marks,max_marks USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER check_team_score BEFORE INSERT OR UPDATE ON team_criterion_scores
  FOR EACH ROW EXECUTE FUNCTION smartpro_validate_score();
CREATE TRIGGER check_student_score BEFORE INSERT OR UPDATE ON student_criterion_scores
  FOR EACH ROW EXECUTE FUNCTION smartpro_validate_score();

CREATE FUNCTION smartpro_guard_score_delete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE astate text;
BEGIN
  SELECT state INTO astate FROM assessments WHERE id=OLD.assessment_id FOR UPDATE;
  IF astate <> 'DRAFT' THEN RAISE EXCEPTION 'finalized assessment scores cannot be deleted' USING ERRCODE='23514'; END IF;
  RETURN OLD;
END;
$$;
CREATE TRIGGER guard_team_score_delete BEFORE DELETE ON team_criterion_scores
  FOR EACH ROW EXECUTE FUNCTION smartpro_guard_score_delete();
CREATE TRIGGER guard_student_score_delete BEFORE DELETE ON student_criterion_scores
  FOR EACH ROW EXECUTE FUNCTION smartpro_guard_score_delete();

-- Finalization must have one score for every mode-defined criterion and roster member.
CREATE FUNCTION smartpro_finalize_assessment() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected_team integer; actual_team integer; expected_student integer; actual_student integer;
        roster_count integer; lock_at timestamptz;
BEGIN
  IF OLD.state='FINALIZED' AND NEW.state <> OLD.state THEN
    RAISE EXCEPTION 'finalized assessment cannot be reopened directly' USING ERRCODE='23514';
  END IF;
  IF NEW.state='FINALIZED' AND OLD.state='DRAFT' THEN
    SELECT roster_locked_at INTO lock_at FROM project_reviews WHERE id=NEW.review_id FOR UPDATE;
    IF lock_at IS NULL THEN RAISE EXCEPTION 'review roster must be locked first' USING ERRCODE='23514'; END IF;
    SELECT count(*) INTO roster_count FROM review_roster_members WHERE review_id=NEW.review_id;
    IF roster_count=0 THEN RAISE EXCEPTION 'cannot finalize review without roster' USING ERRCODE='23514'; END IF;
    SELECT count(*) INTO expected_team FROM mode_criteria
      WHERE scheme_mode_id=NEW.scheme_mode_id AND score_scope='TEAM';
    SELECT count(*) INTO expected_student FROM mode_criteria
      WHERE scheme_mode_id=NEW.scheme_mode_id AND score_scope='STUDENT';
    SELECT count(*) INTO actual_team FROM team_criterion_scores WHERE assessment_id=NEW.id;
    SELECT count(*) INTO actual_student FROM student_criterion_scores WHERE assessment_id=NEW.id;
    IF actual_team<>expected_team OR actual_student<>(expected_student*roster_count) THEN
      RAISE EXCEPTION 'assessment scores incomplete' USING ERRCODE='23514';
    END IF;
    IF NEW.finalized_at IS NULL THEN NEW.finalized_at:=now(); END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER validate_assessment_finalization BEFORE UPDATE ON assessments
  FOR EACH ROW EXECUTE FUNCTION smartpro_finalize_assessment();

-- Prevent modifying roster, scheme mode, or rubric after assessment work has started.
CREATE FUNCTION smartpro_guard_review_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='INSERT' THEN
    IF NEW.review_state <> 'SCHEDULED' OR NEW.roster_locked_at IS NOT NULL THEN
      RAISE EXCEPTION 'new reviews must begin scheduled with an unlocked roster' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  IF OLD.scheme_version_id IS DISTINCT FROM NEW.scheme_version_id OR
     OLD.scheme_mode_id IS DISTINCT FROM NEW.scheme_mode_id OR
     OLD.review_definition_id IS DISTINCT FROM NEW.review_definition_id THEN
    IF EXISTS(SELECT 1 FROM assessments WHERE review_id=OLD.id) OR OLD.roster_locked_at IS NOT NULL THEN
      RAISE EXCEPTION 'review configuration locked after assessment begins' USING ERRCODE='23514';
    END IF;
  END IF;
  IF OLD.roster_locked_at IS NULL AND NEW.roster_locked_at IS NOT NULL AND
     NOT EXISTS(SELECT 1 FROM review_roster_members WHERE review_id=OLD.id) THEN
    RAISE EXCEPTION 'cannot lock an empty review roster' USING ERRCODE='23514';
  END IF;
  IF NEW.review_state IN ('OPEN','FINALIZED','RELEASED') THEN
    PERFORM 1 FROM scheme_versions WHERE id=NEW.scheme_version_id AND state IN ('ACTIVE','RETIRED');
    IF NOT FOUND THEN RAISE EXCEPTION 'review requires an activated scheme' USING ERRCODE='23514'; END IF;
  END IF;
  IF OLD.roster_locked_at IS NOT NULL AND NEW.roster_locked_at IS DISTINCT FROM OLD.roster_locked_at THEN
    RAISE EXCEPTION 'review roster lock cannot be removed or changed' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER guard_review_configuration BEFORE INSERT OR UPDATE ON project_reviews
  FOR EACH ROW EXECUTE FUNCTION smartpro_guard_review_change();
COMMIT;
