-- Additional gaps reproduced by edge-probes.xml before adding these guards.
BEGIN;
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE team_memberships ADD CONSTRAINT same_team_membership_no_overlap
  EXCLUDE USING gist(team_id WITH =,user_id WITH =,tstzrange(joined_at,left_at,'[)') WITH &&);
-- This does NOT ban membership in different teams or multiple faculty guides.
ALTER TABLE submission_attempts ADD COLUMN submitted_membership_id uuid REFERENCES team_memberships(id);
ALTER TABLE submission_attempts DISABLE TRIGGER freeze_attempt_identity;
UPDATE submission_attempts a SET submitted_membership_id=m.id
  FROM projects p,team_memberships m WHERE p.id=a.project_id AND m.team_id=p.team_id
    AND m.user_id=a.submitted_by AND m.joined_at<=a.submitted_at
    AND (m.left_at IS NULL OR a.submitted_at<m.left_at);
-- Validate queued historical-attempt checks before changing trigger DDL.
-- PostgreSQL rejects ALTER TABLE while deferred row events remain pending.
SET CONSTRAINTS complete_attempt IMMEDIATE;
ALTER TABLE submission_attempts ENABLE TRIGGER freeze_attempt_identity;
SET CONSTRAINTS complete_attempt DEFERRED;

CREATE FUNCTION smartpro_submitter_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE kind text; dept uuid;
BEGIN
  NEW.submitted_at:=statement_timestamp();
  SELECT c.submission_type,p.department_id INTO kind,dept FROM submission_cases c JOIN projects p ON p.id=c.project_id
    WHERE c.id=NEW.case_id AND c.project_id=NEW.project_id;
  SELECT m.id INTO NEW.submitted_membership_id FROM projects p JOIN team_memberships m ON m.team_id=p.team_id
    WHERE p.id=NEW.project_id AND m.user_id=NEW.submitted_by AND m.joined_at<=NEW.submitted_at
      AND (m.left_at IS NULL OR NEW.submitted_at<m.left_at) FOR SHARE OF m;
  IF kind='SYNOPSIS' AND (NEW.submitted_membership_id IS NULL OR NOT smartpro_has_role(NEW.submitted_by,dept,'STUDENT',NEW.submitted_at)) THEN
    RAISE EXCEPTION 'synopsis submitter requires effective project membership and student role' USING ERRCODE='42501'; END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER snapshot_submitter BEFORE INSERT ON submission_attempts
  FOR EACH ROW EXECUTE FUNCTION smartpro_submitter_snapshot();
ALTER FUNCTION smartpro_submitter_snapshot() SECURITY DEFINER;
ALTER FUNCTION smartpro_submitter_snapshot() SET search_path=pg_catalog,public,pg_temp;

CREATE OR REPLACE FUNCTION smartpro_membership_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS(SELECT 1 FROM review_roster_members WHERE membership_id=OLD.id)
    OR EXISTS(SELECT 1 FROM submission_attempts WHERE submitted_membership_id=OLD.id) THEN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'membership is historical academic evidence' USING ERRCODE='23514'; END IF;
    IF (NEW.id,NEW.team_id,NEW.user_id,NEW.joined_at) IS DISTINCT FROM (OLD.id,OLD.team_id,OLD.user_id,OLD.joined_at)
      OR EXISTS(SELECT 1 FROM review_roster_members rm JOIN project_reviews r ON r.id=rm.review_id
        WHERE rm.membership_id=OLD.id AND r.roster_locked_at IS NOT NULL AND NEW.left_at IS NOT NULL AND NEW.left_at<=r.roster_locked_at)
      OR EXISTS(SELECT 1 FROM submission_attempts a WHERE a.submitted_membership_id=OLD.id AND NEW.left_at IS NOT NULL AND NEW.left_at<=a.submitted_at) THEN
      RAISE EXCEPTION 'membership edit would falsify historical eligibility' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION smartpro_review_terminal_state() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.review_state IN ('FINALIZED','RELEASED') AND
    (to_jsonb(NEW)-'review_state'-'row_version') IS DISTINCT FROM (to_jsonb(OLD)-'review_state'-'row_version') THEN
    RAISE EXCEPTION 'finalized review configuration is historical' USING ERRCODE='23514'; END IF;
  IF NEW.review_state IS DISTINCT FROM OLD.review_state AND NOT (
    (OLD.review_state='SCHEDULED' AND NEW.review_state IN ('OPEN','CANCELLED')) OR
    (OLD.review_state='OPEN' AND NEW.review_state IN ('FINALIZED','CANCELLED')) OR
    (OLD.review_state='FINALIZED' AND NEW.review_state='RELEASED')) THEN
    RAISE EXCEPTION 'invalid review state transition' USING ERRCODE='23514'; END IF;
  IF NEW.review_state='FINALIZED' AND OLD.review_state<>'FINALIZED' THEN
    IF NOT EXISTS(SELECT 1 FROM assessments WHERE review_id=OLD.id)
      OR EXISTS(SELECT 1 FROM assessments WHERE review_id=OLD.id AND state<>'FINALIZED') THEN
      RAISE EXCEPTION 'review finalization requires complete finalized assessments' USING ERRCODE='23514'; END IF;
  END IF;
  IF NEW.review_state='RELEASED' AND NOT EXISTS(SELECT 1 FROM result_releases WHERE review_id=OLD.id AND sealed_at IS NOT NULL) THEN
    RAISE EXCEPTION 'released review requires a sealed result version' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER validate_review_terminal_state BEFORE UPDATE ON project_reviews
  FOR EACH ROW EXECUTE FUNCTION smartpro_review_terminal_state();

CREATE FUNCTION smartpro_document_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS(SELECT 1 FROM document_versions WHERE document_id=OLD.id) AND
    (NEW.id,NEW.project_id,NEW.document_type,NEW.created_at) IS DISTINCT FROM (OLD.id,OLD.project_id,OLD.document_type,OLD.created_at) THEN
    RAISE EXCEPTION 'versioned document identity is historical' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER freeze_document_identity BEFORE UPDATE ON documents
  FOR EACH ROW EXECUTE FUNCTION smartpro_document_identity();

CREATE FUNCTION smartpro_review_definition_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS(SELECT 1 FROM project_reviews WHERE review_definition_id=OLD.id)
     OR EXISTS(SELECT 1 FROM scheme_versions WHERE review_definition_id=OLD.id AND state<>'DRAFT') THEN
    RAISE EXCEPTION 'used review definition is historical configuration' USING ERRCODE='23514'; END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER freeze_review_definition BEFORE UPDATE OR DELETE ON review_definitions
  FOR EACH ROW EXECUTE FUNCTION smartpro_review_definition_history();
COMMIT;
