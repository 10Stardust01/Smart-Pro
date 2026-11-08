-- Owner-run forward correction for inherited PUBLIC execution on six functions.
BEGIN;

REVOKE EXECUTE ON FUNCTION
  public.smartpro_initial_evaluation(uuid,uuid,text,jsonb,text),
  public.smartpro_role_documents(uuid,uuid,text),
  public.smartpro_role_workspace(uuid,text)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  public.smartpro_initial_evaluation(uuid,uuid,text,jsonb,text),
  public.smartpro_role_documents(uuid,uuid,text),
  public.smartpro_role_workspace(uuid,text)
TO smartpro_runtime;

-- Trigger execution continues through existing triggers.
REVOKE EXECUTE ON FUNCTION
  public.smartpro_decision_authority(),
  public.smartpro_guard_submitted_file(),
  public.smartpro_submitter_snapshot()
FROM PUBLIC, smartpro_runtime;

COMMIT;
