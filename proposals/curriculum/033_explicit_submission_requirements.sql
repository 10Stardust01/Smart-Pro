-- An offering does not implicitly establish mandatory academic documents.
BEGIN;
DO $$ BEGIN IF to_regprocedure('public.smartpro_configure_requirement(uuid,uuid,text,jsonb,text)') IS NULL THEN RAISE EXCEPTION 'Reviewed 032 required'; END IF; END $$;
ALTER TABLE public.curriculum_offerings ADD COLUMN IF NOT EXISTS synopsis_required boolean;
DO $$ DECLARE def text; marker text; closing text; BEGIN
 def:=pg_get_functiondef('public.smartpro_record_instruction(uuid,uuid,text,jsonb,text)'::regprocedure);
 def:=replace(def,'jsonb_object_keys(config))<>13','jsonb_object_keys(config))<>(13+CASE WHEN config ? ''requiresSynopsis'' THEN 1 ELSE 0 END)');
 EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_document_command(uuid,uuid,text,jsonb,text)'::regprocedure);
 marker:='  INSERT INTO public.submission_requirement_policies(offering_id,instruction_id,opens_at,closes_at,max_bytes,faculty_approval_enabled)';
 def:=replace(def,marker,E'  UPDATE public.curriculum_offerings SET synopsis_required=coalesce((config->>''requiresSynopsis'')::boolean,true) WHERE id=oid;\n  IF coalesce((config->>''requiresSynopsis'')::boolean,true) THEN\n'||marker);
 closing:='  INSERT INTO public.submission_offering_requirements VALUES(oid,rid,''SYNOPSIS'') ON CONFLICT(offering_id,requirement_key) DO UPDATE SET policy_id=excluded.policy_id;';
 def:=replace(def,closing,closing||E'\n  ELSE DELETE FROM public.submission_offering_requirements WHERE offering_id=oid AND requirement_key=''SYNOPSIS'';rid:=oid; END IF;');
 EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_proposal_offering(uuid,uuid)'::regprocedure);
 def:=replace(def,'''requiresSynopsis'',rule.id IS NOT NULL','''requiresSynopsis'',rule.id IS NOT NULL AND rule.is_required');
 def:=replace(def,'CASE WHEN rule.id IS NULL THEN ''NOT_REQUIRED''','CASE WHEN rule.id IS NULL OR NOT rule.is_required THEN ''NOT_REQUIRED''');
 def:=replace(def,'IF rule.id IS NULL AND NOT EXISTS','IF rule.id IS NULL AND coalesce(o.synopsis_required,true) AND NOT EXISTS');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_configured_document_workspace(uuid,uuid,text)'::regprocedure);
 def:=replace(def,'  projects:=projects||',E'  IF project->''case''=''null''::jsonb AND EXISTS(SELECT FROM public.curriculum_offerings WHERE id=(project->>''offeringId'')::uuid AND synopsis_required=false) THEN project:=project||jsonb_build_object(''requirementDisposition'',''NOT_REQUIRED''); END IF;\n  projects:=projects||');EXECUTE def;
END $$;
COMMIT;
