BEGIN;
DO $$ BEGIN IF to_regprocedure('public.smartpro_configured_document_workspace(uuid,uuid,text)') IS NULL THEN RAISE EXCEPTION 'Reviewed 032-033 required'; END IF; END $$;
CREATE TABLE public.project_proposal_revisions(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),project_id uuid NOT NULL REFERENCES projects(id),version integer NOT NULL,
 before_state jsonb NOT NULL,after_state jsonb NOT NULL,submitted_by uuid NOT NULL REFERENCES users(id),created_at timestamptz NOT NULL DEFAULT clock_timestamp(),UNIQUE(project_id,version));
REVOKE ALL ON public.project_proposal_revisions FROM PUBLIC,smartpro_runtime;
CREATE TRIGGER retain_proposal_revision BEFORE UPDATE OR DELETE ON public.project_proposal_revisions FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation();
CREATE FUNCTION public.smartpro_revise_proposal(actor uuid,pid uuid,action text,input jsonb,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.projects%ROWTYPE; tid uuid; offering uuid; prior public.document_command_receipts%ROWTYPE; result jsonb; previous jsonb;
BEGIN
 IF action<>'REVISE' OR key IS NULL OR key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' OR length(btrim(input->>'title')) NOT BETWEEN 1 AND 500 OR length(coalesce(input->>'description',''))>10000 THEN RAISE EXCEPTION 'Complete proposal details required' USING ERRCODE='22023'; END IF;
 UPDATE public.student_profiles SET membership_scope_revision=gen_random_uuid() WHERE user_id=actor;
 IF NOT FOUND THEN RAISE EXCEPTION 'Trusted student record required' USING ERRCODE='42501'; END IF;
 SELECT team_id INTO tid FROM public.projects WHERE id=pid;
 PERFORM 1 FROM public.teams WHERE id=tid FOR UPDATE;
 SELECT * INTO p FROM public.projects WHERE id=pid FOR UPDATE;
 SELECT curriculum_offering_id INTO offering FROM public.teams WHERE id=p.team_id;
 PERFORM public.smartpro_proposal_offering(actor,offering);
 IF NOT EXISTS(SELECT FROM public.team_memberships WHERE user_id=actor AND team_id=p.team_id AND joined_at<=clock_timestamp() AND (left_at IS NULL OR clock_timestamp()<left_at)) THEN RAISE EXCEPTION 'Current project team membership required' USING ERRCODE='42501'; END IF;
 SELECT * INTO prior FROM public.document_command_receipts WHERE actor_id=actor AND request_key=key;
 IF FOUND THEN IF prior.action<>'REVISE_PROPOSAL' OR prior.input<>jsonb_build_object('projectId',pid,'payload',input) THEN RAISE EXCEPTION 'Retry changed' USING ERRCODE='23514'; END IF;RETURN prior.output; END IF;
 IF p.row_version IS DISTINCT FROM (input->>'expectedRevision')::integer OR EXISTS(SELECT FROM public.submission_attempts WHERE project_id=pid) OR EXISTS(SELECT FROM public.project_reviews WHERE project_id=pid) THEN RAISE EXCEPTION 'Submitted academic details are preserved; revise the permitted document instead' USING ERRCODE='23514'; END IF;
 previous:=jsonb_build_object('title',p.title,'description',coalesce((SELECT after_state->>'description' FROM public.project_proposal_revisions WHERE project_id=pid ORDER BY version DESC LIMIT 1),(SELECT description FROM public.project_proposal_details WHERE project_id=pid),''));
 UPDATE public.projects SET title=btrim(input->>'title'),row_version=row_version+1 WHERE id=pid;
 result:=jsonb_build_object('projectId',pid,'revision',p.row_version+1,'title',btrim(input->>'title'),'description',btrim(input->>'description'));
 INSERT INTO public.project_proposal_revisions(project_id,version,before_state,after_state,submitted_by) VALUES(pid,p.row_version+1,previous,result,actor);
 PERFORM public.smartpro_proposal_offering(actor,offering);
 INSERT INTO public.document_command_receipts VALUES(actor,key,'REVISE_PROPOSAL',jsonb_build_object('projectId',pid,'payload',input),result);
 INSERT INTO public.audit_events(actor_id,project_id,action,target_type,target_id,metadata) VALUES(actor,pid,'PROJECT_DRAFT_REVISED','PROJECT',pid,jsonb_build_object('before',previous,'after',result));
 RETURN result;
END $$;
DO $$ DECLARE def text; BEGIN
 def:=pg_get_functiondef('public.smartpro_configured_document_workspace(uuid,uuid,text)'::regprocedure);
 def:=replace(def,'  projects:=projects||',E'  project:=project||jsonb_build_object(''proposalRevision'',(SELECT row_version FROM public.projects WHERE id=(project->>''id'')::uuid),''description'',coalesce((SELECT after_state->>''description'' FROM public.project_proposal_revisions WHERE project_id=(project->>''id'')::uuid ORDER BY version DESC LIMIT 1),project->>''description''),''canReviseProposal'',acting_role=''Student'' AND NOT EXISTS(SELECT FROM public.submission_attempts WHERE project_id=(project->>''id'')::uuid) AND NOT EXISTS(SELECT FROM public.project_reviews WHERE project_id=(project->>''id'')::uuid) AND EXISTS(SELECT FROM public.student_offering_windows WHERE offering_id=(project->>''offeringId'')::uuid AND visible_from<=clock_timestamp() AND clock_timestamp()<visible_until),''proposalHistory'',(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY version),''[]'') FROM public.project_proposal_revisions r WHERE project_id=(project->>''id'')::uuid));\n  projects:=projects||');EXECUTE def;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_revise_proposal(uuid,uuid,text,jsonb,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_revise_proposal(uuid,uuid,text,jsonb,text) TO smartpro_runtime;
COMMIT;
