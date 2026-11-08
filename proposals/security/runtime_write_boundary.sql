-- Candidate owner-run write privilege hardening for the synthetic synopsis runtime.
-- Depends on runtime_read_boundary.sql, and must be applied by the DB owner.
-- Does not change ordered baseline migrations 001-009 or existing evidence.
-- This is NOT an automatic change to a production database.
BEGIN;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='smartpro_runtime')
     OR to_regprocedure('public.smartpro_synopsis_idempotency_lookup(uuid,text,text)') IS NULL THEN
    RAISE EXCEPTION 'Runtime role and synopsis read boundary must be installed first';
  END IF;
END;
$$;

-- Document-version allocation must serialize on the parent document row,
-- but SELECT FOR UPDATE requires an UPDATE right. Encapsulate the row lock
-- rather than restoring the legacy UPDATE(label) grant to the app role.
CREATE OR REPLACE FUNCTION public.smartpro_synopsis_lock_document(
  p_document_id uuid, p_actor_id uuid
) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp
AS $$
BEGIN
  -- Lock the exact document row while validating its current project
  -- permission. Avoid authorizing from a project_id captured before a
  -- concurrent document reassignment.
  PERFORM d.id FROM public.documents d
  WHERE d.id=p_document_id
    AND public.smartpro_project_permission(d.project_id,p_actor_id,'student')
  FOR UPDATE OF d;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'document lock requires current project student'
      USING ERRCODE='42501';
  END IF;
  RETURN true;
END;
$$;
-- Keep a submitted synopsis file's READY identity stable for the whole
-- write transaction without granting the application UPDATE on file_assets.
-- Return only fields required by the existing validation service.
CREATE OR REPLACE FUNCTION public.smartpro_synopsis_locked_version(
  p_version_id uuid, p_project_id uuid, p_actor_id uuid
) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp
AS $$
DECLARE
  result jsonb;
BEGIN
  IF NOT public.smartpro_project_permission(p_project_id,p_actor_id,'student') THEN
    RAISE EXCEPTION 'verified file lock requires current project student'
      USING ERRCODE='42501';
  END IF;
  SELECT jsonb_build_object(
    'id',dv.id,
    'document_id',dv.document_id,
    'document_type',d.document_type,
    'storage_key',fa.storage_key,
    'sha256',fa.sha256,
    'upload_status',fa.upload_status
  ) INTO result
  FROM public.document_versions dv
  JOIN public.documents d ON d.id=dv.document_id
  JOIN public.file_assets fa ON fa.id=dv.file_asset_id
  WHERE dv.id=p_version_id AND dv.project_id=p_project_id
  -- The submission-item trigger requires UPDATE. Taking SHARE first allows
  -- concurrent validators to deadlock while both upgrade their shared locks.
  FOR UPDATE OF fa;
  RETURN result;
END;
$$;
REVOKE ALL ON FUNCTION public.smartpro_synopsis_locked_version(uuid,uuid,uuid)
  FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_synopsis_locked_version(uuid,uuid,uuid)
  TO smartpro_runtime;

REVOKE ALL ON FUNCTION public.smartpro_synopsis_lock_document(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_synopsis_lock_document(uuid,uuid)
  TO smartpro_runtime;

-- The baseline submission-item validation trigger locks its associated
-- file asset FOR UPDATE to ensure it is READY. Keep this trigger's required
-- lock privilege with the owner; do not restore UPDATE on file_assets to
-- the application's SQL role. The function has no dynamic SQL or writes.
ALTER FUNCTION public.smartpro_guard_submitted_file() SECURITY DEFINER;
ALTER FUNCTION public.smartpro_guard_submitted_file()
  SET search_path=pg_catalog,public,pg_temp;

-- Remove inherited broad INSERT/UPDATE grants, including document label edits
-- and unused worker/notification writes. No application role may directly
-- DELETE, TRUNCATE, REFERENCES or TRIGGER any legacy academic table.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
  ON ALL TABLES IN SCHEMA public FROM smartpro_runtime;
-- Legacy provisioners also issued a COLUMN-level UPDATE(label) grant.
-- Table-level REVOKE does not remove separately granted column privileges.
REVOKE UPDATE(label) ON public.documents FROM smartpro_runtime;

-- The currently implemented synopsis flow needs these inserts. Team creation
-- uses its independent owner-run SECURITY DEFINER command in candidate 012.
GRANT INSERT ON TABLE
  public.file_assets,
  public.document_versions,
  public.submission_items,
  public.approval_decisions,
  public.audit_events,
  public.outbox_events,
  public.idempotency_records,
  public.upload_sessions,
  public.submission_attempts
TO smartpro_runtime;

-- Bound UPDATE to the exact columns used by current service methods.
GRANT UPDATE(status,sha256,size_bytes,document_version_id,completed_at)
  ON public.upload_sessions TO smartpro_runtime;
GRANT UPDATE(state,row_version)
  ON public.submission_cases TO smartpro_runtime;
GRANT UPDATE(sealed_at,attempt_state)
  ON public.submission_attempts TO smartpro_runtime;

-- Outbox claim/ack/retry and notification-delivery writes are worker operations:
-- they have no live HTTP caller in the current synopsis implementation.
-- Run future workers under a separately reviewed service principal.
COMMIT;
