-- Admin records and implements departmental instructions received outside the app.
-- No impersonation, manufactured HOD click, extra authority grant, or policy default.
BEGIN;
DO $$ BEGIN IF to_regprocedure('public.smartpro_project_operation(uuid,uuid,text,jsonb,text)') IS NULL OR strpos(coalesce(pg_get_functiondef(to_regprocedure('public.smartpro_project_operation(uuid,uuid,text,jsonb,text)')),''),'-- Optional user note (025)')=0 THEN RAISE EXCEPTION 'Reviewed 024-025 required'; END IF; END $$;
ALTER TABLE public.department_setup_approvals ADD COLUMN IF NOT EXISTS approval_source text NOT NULL DEFAULT 'IN_APP' CHECK(approval_source IN ('IN_APP','EXTERNAL_INSTRUCTION'));
ALTER TABLE public.department_setup_approvals ADD COLUMN IF NOT EXISTS recorded_by uuid REFERENCES users(id);
ALTER TABLE public.department_setup_approvals ADD COLUMN IF NOT EXISTS instruction_reference text;
ALTER TABLE public.offering_operational_instructions ADD COLUMN IF NOT EXISTS approval_source text NOT NULL DEFAULT 'IN_APP' CHECK(approval_source IN ('IN_APP','EXTERNAL_INSTRUCTION'));
ALTER TABLE public.offering_operational_instructions ADD COLUMN IF NOT EXISTS recorded_by uuid REFERENCES users(id);
ALTER TABLE public.offering_operational_instructions ADD COLUMN IF NOT EXISTS instruction_reference text;
-- Legacy explicit approval INSERTs need column lists after adding provenance.
DO $$ DECLARE sig text; def text; BEGIN
 FOREACH sig IN ARRAY ARRAY['public.smartpro_department_setup(uuid,uuid,text,jsonb,text)','public.smartpro_setup_current(uuid,uuid,text,jsonb,text)'] LOOP
  def:=pg_get_functiondef(to_regprocedure(sig));
  def:=replace(def,'INSERT INTO public.department_setup_approvals VALUES','INSERT INTO public.department_setup_approvals(request_id,approved_by,mandate_id,approved_at) VALUES');
  EXECUTE def;
 END LOOP;
END $$;
DO $$ DECLARE def text; BEGIN
 def:=pg_get_functiondef('public.smartpro_document_workspace(uuid,uuid)'::regprocedure);
 def:=replace(def,'IF manager THEN','IF manager OR operational THEN');
 def:=replace(def,'i.id,i.configuration,i.approved_at,i.reason,','i.id,i.configuration,i.approved_at,i.reason,i.approval_source,i.recorded_by,i.instruction_reference,');
 EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_role_documents(uuid,uuid,text)'::regprocedure);
 def:=replace(def,'IF role IN (''HOD'',''Coordinator'') THEN','IF role IN (''HOD'',''Coordinator'',''Admin'') THEN');
 EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_department_setup_read(uuid,uuid)'::regprocedure);
 def:=replace(def,'r.*,a.approved_at,e.configured_at','r.*,a.approved_at,a.approval_source,a.recorded_by,a.instruction_reference,e.configured_at');
 EXECUTE def;
END $$;
CREATE OR REPLACE FUNCTION public.smartpro_record_instruction(actor uuid,dept uuid,action text,input jsonb,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE role_id uuid; mandate public.academic_hod_mandates%ROWTYPE; prior public.document_command_receipts%ROWTYPE;
 config jsonb; rid uuid; requested jsonb; result jsonb; internal_key text;
BEGIN
 IF action IS DISTINCT FROM 'RECORD' OR jsonb_typeof(input) IS DISTINCT FROM 'object' OR NOT input ?& ARRAY['kind','configuration','authority'] OR jsonb_typeof(input->'authority') IS DISTINCT FROM 'object'
  OR input->'authority'->>'source' IS DISTINCT FROM 'EXTERNAL_INSTRUCTION' OR input->'authority'->'confirmed' IS DISTINCT FROM 'true'::jsonb
  OR length(coalesce(input->'authority'->>'reference',''))>500 OR length(coalesce(input->>'reason',''))>500
  OR key IS NULL OR length(key) NOT BETWEEN 1 AND 128 OR key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$' THEN
  RAISE EXCEPTION 'Record the authorized external instruction and its source' USING ERRCODE='22023'; END IF;
 IF NOT EXISTS(SELECT FROM public.academic_governance_settings WHERE department_id=dept AND enabled) OR NOT EXISTS(SELECT FROM public.staff_department_controls WHERE department_id=dept AND enabled) THEN RAISE EXCEPTION 'department configuration disabled' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.users WHERE id=actor AND account_status='ACTIVE' FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'active Admin required' USING ERRCODE='42501'; END IF;
 SELECT id INTO role_id FROM public.department_role_assignments WHERE user_id=actor AND department_id=dept AND role_code='ACADEMIC_ADMIN' AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until) ORDER BY id LIMIT 1 FOR SHARE;
 IF role_id IS NULL THEN RAISE EXCEPTION 'departmental Admin required' USING ERRCODE='42501'; END IF;
 SELECT * INTO mandate FROM public.academic_hod_mandates WHERE id=(input->'authority'->>'hodMandateId')::uuid AND department_id=dept AND enabled FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'current departmental HOD instruction required' USING ERRCODE='42501'; END IF;
 PERFORM public.smartpro_academic_authority(mandate.user_id,dept,true);
 IF input->>'kind'='REVIEW_BLUEPRINT' AND public.smartpro_academic_grant(mandate.user_id,dept,'APPROVE_SCHEME') IS NULL THEN RAISE EXCEPTION 'HOD scheme authority required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(actor::text||':instruction:'||key,0));
 SELECT * INTO prior FROM public.document_command_receipts WHERE actor_id=actor AND request_key=key;
 IF FOUND THEN IF prior.action<>'RECORD_INSTRUCTION' OR prior.input<>jsonb_build_object('departmentId',dept,'payload',input) THEN RAISE EXCEPTION 'instruction request changed' USING ERRCODE='23514'; END IF;RETURN prior.output; END IF;
 internal_key:='instruction:'||encode(sha256(convert_to(actor::text||key,'UTF8')),'hex');
 IF input->>'kind'='OFFERING' THEN
  config:=input->'configuration';
  IF config->>'adminRoleId' IS DISTINCT FROM role_id::text THEN RAISE EXCEPTION 'configure as the authenticated Admin' USING ERRCODE='42501'; END IF;
  IF (SELECT count(*) FROM jsonb_object_keys(config))<>13 OR NOT config ?& ARRAY['curriculumTypeId','cycleId','semester','projectPolicyId','teamPolicyId','visibleFrom','visibleUntil','submissionOpensAt','submissionClosesAt','maxBytes','adminRoleId','facultyApprovalEnabled','teamCreationEnabled']
    OR length(btrim(config->>'semester')) NOT BETWEEN 1 AND 80 THEN RAISE EXCEPTION 'exact approved configuration required' USING ERRCODE='22023'; END IF;
  PERFORM 1 FROM public.academic_cycles WHERE id=(config->>'cycleId')::uuid AND department_id=dept FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'department cycle required' USING ERRCODE='42501'; END IF;
  PERFORM 1 FROM public.curriculum_types WHERE id=(config->>'curriculumTypeId')::uuid;
  IF NOT FOUND THEN RAISE EXCEPTION 'existing curriculum type required' USING ERRCODE='23514'; END IF;
  PERFORM 1 FROM public.project_policy_versions WHERE id=(config->>'projectPolicyId')::uuid AND department_id=dept AND policy_status='APPROVED'
    AND policy_data->'studentRegistration'='{"enabled":true}'::jsonb FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'approved registration policy required' USING ERRCODE='23514'; END IF;
  PERFORM 1 FROM public.team_membership_policy_versions WHERE id=(config->>'teamPolicyId')::uuid AND department_id=dept;
  IF NOT FOUND THEN RAISE EXCEPTION 'department team policy required' USING ERRCODE='23514'; END IF;
  PERFORM 1 FROM public.department_role_assignments r JOIN public.users u ON u.id=r.user_id WHERE r.id=(config->>'adminRoleId')::uuid
    AND r.department_id=dept AND r.role_code='ACADEMIC_ADMIN' AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until) AND u.account_status='ACTIVE' FOR SHARE OF r,u;
  IF NOT FOUND THEN RAISE EXCEPTION 'active named academic admin required' USING ERRCODE='42501'; END IF;
  IF (config->>'visibleFrom')::timestamptz >= (config->>'visibleUntil')::timestamptz
    OR (config->>'submissionOpensAt')::timestamptz >= (config->>'submissionClosesAt')::timestamptz
    OR (config->>'maxBytes')::integer NOT BETWEEN 1 AND 2097152 THEN RAISE EXCEPTION 'invalid windows or size' USING ERRCODE='22023'; END IF;
  INSERT INTO public.offering_operational_instructions(department_id,hod_mandate_id,admin_role_id,approved_by,configuration,reason,approval_source,recorded_by,instruction_reference)
    VALUES(dept,mandate.id,(config->>'adminRoleId')::uuid,mandate.user_id,config,input->>'reason','EXTERNAL_INSTRUCTION',actor,input->'authority'->>'reference') RETURNING id INTO rid;

  result:=public.smartpro_document_command(actor,dept,'CONFIGURE',jsonb_build_object('instructionId',rid),internal_key);
 ELSE
  requested:=public.smartpro_setup_current(actor,dept,'REQUEST',jsonb_build_object('kind',input->>'kind','configuration',input->'configuration','reason',coalesce(input->>'reason','')),internal_key||':request');
  rid:=(requested->>'id')::uuid;
  INSERT INTO public.department_setup_approvals(request_id,approved_by,mandate_id,approved_at,approval_source,recorded_by,instruction_reference)
   VALUES(rid,mandate.user_id,mandate.id,clock_timestamp(),'EXTERNAL_INSTRUCTION',actor,input->'authority'->>'reference');
  result:=public.smartpro_setup_current(actor,dept,'APPLY',jsonb_build_object('requestId',rid),internal_key||':apply');
 END IF;
 PERFORM public.smartpro_academic_authority(mandate.user_id,dept,true);
 IF NOT public.smartpro_has_role(actor,dept,'ACADEMIC_ADMIN',clock_timestamp()) THEN RAISE EXCEPTION 'Admin role expired' USING ERRCODE='42501'; END IF;
 INSERT INTO public.document_command_receipts VALUES(actor,key,'RECORD_INSTRUCTION',jsonb_build_object('departmentId',dept,'payload',input),result);
 INSERT INTO public.audit_events(actor_id,action,target_type,target_id,metadata) VALUES(actor,'DEPARTMENT_INSTRUCTION_RECORDED','CONFIGURATION',rid,jsonb_build_object('departmentId',dept,'authority',input->'authority','configuration',input->'configuration','kind',input->>'kind','result',result,'recordedBy',actor,'academicAuthority',mandate.user_id));
 RETURN result;
END $$;
CREATE OR REPLACE FUNCTION public.smartpro_instruction_sources(actor uuid,dept uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 PERFORM public.smartpro_department_setup_read(actor,dept);
 RETURN jsonb_build_object('hods',(SELECT coalesce(jsonb_agg(jsonb_build_object('id',m.id,'name',u.display_name)),'[]') FROM public.academic_hod_mandates m JOIN public.users u ON u.id=m.user_id JOIN public.department_role_assignments r ON r.id=m.role_assignment_id WHERE m.department_id=dept AND m.enabled AND u.account_status='ACTIVE' AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)),
 'adminRoleId',(SELECT id FROM public.department_role_assignments WHERE user_id=actor AND department_id=dept AND role_code='ACADEMIC_ADMIN' AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until) ORDER BY id LIMIT 1));
END $$;
REVOKE ALL ON FUNCTION public.smartpro_record_instruction(uuid,uuid,text,jsonb,text),public.smartpro_instruction_sources(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_record_instruction(uuid,uuid,text,jsonb,text),public.smartpro_instruction_sources(uuid,uuid) TO smartpro_runtime;
COMMIT;
