-- Initial proposal details are immutable evidence, alongside existing documents.
BEGIN;
DO $$ BEGIN IF to_regprocedure('public.smartpro_record_instruction(uuid,uuid,text,jsonb,text)') IS NULL THEN RAISE EXCEPTION 'Reviewed 026 required'; END IF; END $$;
CREATE TABLE IF NOT EXISTS public.project_proposal_details (
 project_id uuid PRIMARY KEY REFERENCES public.projects(id),
 description text NOT NULL CHECK(length(description)<=10000),
 submitted_by uuid NOT NULL REFERENCES public.users(id),created_at timestamptz NOT NULL DEFAULT clock_timestamp());
REVOKE ALL ON public.project_proposal_details FROM PUBLIC,smartpro_runtime;
DO $$ BEGIN IF NOT EXISTS(SELECT FROM pg_trigger WHERE tgrelid='public.project_proposal_details'::regclass AND tgname='preserve_proposal_details') THEN
 CREATE TRIGGER preserve_proposal_details BEFORE UPDATE OR DELETE ON public.project_proposal_details FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation();
END IF; END $$;
CREATE OR REPLACE FUNCTION public.smartpro_register_proposal(actor uuid,offering uuid,confirmed_team uuid,title text,description text,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE result jsonb; previous public.project_proposal_details%ROWTYPE; pid uuid;
BEGIN
 IF description IS NULL OR length(description)>10000 THEN RAISE EXCEPTION 'Valid proposal description required' USING ERRCODE='22023'; END IF;
 result:=public.smartpro_register_proposal(actor,offering,confirmed_team,title,key);
 pid:=(result->'project'->>'id')::uuid;
 SELECT * INTO previous FROM public.project_proposal_details WHERE project_id=pid;
 IF FOUND THEN
  IF previous.description<>btrim(description) THEN RAISE EXCEPTION 'Retry details changed' USING ERRCODE='23514'; END IF;
 ELSIF (result->>'replayed')::boolean THEN
  IF btrim(description)<>'' THEN RAISE EXCEPTION 'Historical proposal cannot be rewritten' USING ERRCODE='23514'; END IF;
 ELSE
  INSERT INTO public.project_proposal_details(project_id,description,submitted_by) VALUES(pid,btrim(description),actor);
  INSERT INTO public.audit_events(actor_id,project_id,action,target_type,target_id,metadata)
   VALUES(actor,pid,'PROPOSAL_DETAILS_RECORDED','PROJECT',pid,jsonb_build_object('description',btrim(description)));
 END IF;
 RETURN jsonb_set(result,'{project,description}',to_jsonb(btrim(description)));
END $$;
-- Enrich already-authorized, scoped document results; no new public read surface.
DO $$ DECLARE def text; BEGIN
 def:=pg_get_functiondef('public.smartpro_application_workspace(uuid)'::regprocedure);
 def:=replace(def,'(SELECT department_id FROM public.student_profiles WHERE user_id=actor)))','(SELECT department_id FROM public.student_profiles WHERE user_id=actor),r.department_id))');
 EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_role_documents(uuid,uuid,text)'::regprocedure);
 IF strpos(def,'''description'',(SELECT description FROM public.project_proposal_details')=0 THEN
  def:=replace(def,'''managedProposal'',EXISTS(','''description'',(SELECT description FROM public.project_proposal_details WHERE project_id=(p->>''id'')::uuid),''managedProposal'',EXISTS(');
  EXECUTE def;
 END IF;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_register_proposal(uuid,uuid,uuid,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_register_proposal(uuid,uuid,uuid,text,text,text) TO smartpro_runtime;
COMMIT;
