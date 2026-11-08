-- Forward-only runtime read hardening for the existing synopsis demo/service.
-- Owner-applied after ordered baseline migrations and before using the app role.
-- A separate reviewed production rollout must verify existing deployment grants.
-- This script deliberately does NOT modify historical migrations 001-009.
BEGIN;

-- The synopsis service's only required idempotency lookup is a known
-- actor/operation/key triple from trusted server-side authentication. Do not
-- expose raw idempotency rows for all students or other subsystems.
CREATE OR REPLACE FUNCTION public.smartpro_synopsis_idempotency_lookup(
  p_actor_id uuid, p_operation text, p_key text
) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp
AS $$
  SELECT jsonb_build_object(
    'request_sha256',btrim(i.request_sha256),
    'state',i.state,
    'response_body',i.response_body
  )
  FROM public.idempotency_records AS i
  WHERE i.actor_id=p_actor_id
    AND i.operation=p_operation
    AND i.key=p_key
    AND (p_operation LIKE 'SUBMIT_ATTEMPT:%'
         OR p_operation LIKE 'REVIEW_DECISION:%')
$$;
REVOKE ALL ON FUNCTION public.smartpro_synopsis_idempotency_lookup(uuid,text,text)
  FROM PUBLIC;

-- Remove the inherited blanket grant from the original test provisioning.
-- Only tables used by current synopsis service reads / its invoker triggers
-- remain directly readable; project permission is checked by a separate
-- SECURITY DEFINER function and does not require table-wide runtime reads
-- of users, teams, membership, faculty or role registry.
REVOKE SELECT ON ALL TABLES IN SCHEMA public FROM smartpro_runtime;
GRANT SELECT ON TABLE
  public.projects,
  public.documents,
  public.file_assets,
  public.document_versions,
  public.upload_sessions,
  public.submission_cases,
  public.submission_attempts,
  public.submission_items,
  public.approval_decisions
TO smartpro_runtime;

GRANT EXECUTE ON FUNCTION
  public.smartpro_synopsis_idempotency_lookup(uuid,text,text)
TO smartpro_runtime;
COMMIT;
