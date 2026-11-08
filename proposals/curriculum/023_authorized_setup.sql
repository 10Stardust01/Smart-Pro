-- Additive setup operations. HOD approves exact values; Admin applies them.
BEGIN;
DO $$ BEGIN IF to_regprocedure('public.smartpro_register_proposal(uuid,uuid,uuid,text,text)') IS NULL THEN RAISE EXCEPTION 'Reviewed 022 required'; END IF; END $$;
ALTER TABLE public.department_setup_requests DROP CONSTRAINT IF EXISTS department_setup_requests_kind_check;
ALTER TABLE public.department_setup_requests ADD CONSTRAINT department_setup_requests_kind_check CHECK(kind IN ('CYCLE','TYPE','DOCUMENT_NOT_REQUIRED','PROJECT_POLICY','TEAM_POLICY','REVIEW_BLUEPRINT','STUDENT_PROFILE','FACULTY_ACCESS'));
ALTER TABLE public.team_membership_policy_versions ADD COLUMN IF NOT EXISTS label text;
CREATE OR REPLACE FUNCTION public.smartpro_setup_current(actor uuid,dept uuid,action text,input jsonb,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE kind text; cfg jsonb; r public.department_setup_requests%ROWTYPE; a public.department_setup_approvals%ROWTYPE; role_id uuid; auth jsonb; old public.document_command_receipts%ROWTYPE;
 result jsonb; rid uuid; policy public.project_policy_versions%ROWTYPE; version integer; definition uuid; scheme uuid; sv uuid; mode uuid; criterion uuid; stage jsonb; item jsonb; ordinal integer; stage_no integer; criteria_total numeric;
BEGIN
 IF action='REQUEST' THEN kind:=input->>'kind';cfg:=input->'configuration';
 ELSE SELECT * INTO r FROM public.department_setup_requests WHERE id=(input->>'requestId')::uuid AND department_id=dept;kind:=r.kind;cfg:=r.configuration; END IF;
 IF kind IN ('CYCLE','TYPE','DOCUMENT_NOT_REQUIRED') THEN RETURN public.smartpro_department_setup(actor,dept,action,input,key); END IF;
 IF kind IS NULL OR kind NOT IN ('PROJECT_POLICY','TEAM_POLICY','REVIEW_BLUEPRINT','STUDENT_PROFILE','FACULTY_ACCESS') THEN RAISE EXCEPTION 'supported setup request required' USING ERRCODE='22023'; END IF;
 IF NOT EXISTS(SELECT FROM public.academic_governance_settings WHERE department_id=dept AND enabled) OR NOT EXISTS(SELECT FROM public.staff_department_controls WHERE department_id=dept AND enabled) THEN RAISE EXCEPTION 'department setup disabled' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.users WHERE id=actor AND account_status='ACTIVE' FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'active actor required' USING ERRCODE='42501'; END IF;
 IF action='REQUEST' THEN
  SELECT id INTO role_id FROM public.department_role_assignments WHERE user_id=actor AND department_id=dept AND role_code='ACADEMIC_ADMIN' AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until) ORDER BY id LIMIT 1 FOR SHARE;
  IF role_id IS NULL THEN RAISE EXCEPTION 'operational Admin required' USING ERRCODE='42501'; END IF;
 ELSIF action='APPROVE' THEN
  auth:=public.smartpro_academic_authority(actor,dept,true);
  IF kind='REVIEW_BLUEPRINT' AND public.smartpro_academic_grant(actor,dept,'APPROVE_SCHEME') IS NULL THEN RAISE EXCEPTION 'explicit scheme approval mandate required' USING ERRCODE='42501'; END IF;
 ELSE
  PERFORM 1 FROM public.department_role_assignments WHERE id=r.role_id AND user_id=actor AND role_code='ACADEMIC_ADMIN' AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until) FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'original Admin required' USING ERRCODE='42501'; END IF;
  SELECT * INTO a FROM public.department_setup_approvals WHERE request_id=r.id;
  PERFORM 1 FROM public.academic_hod_mandates WHERE id=a.mandate_id AND enabled FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'HOD authorization required' USING ERRCODE='42501'; END IF;
  PERFORM public.smartpro_academic_authority(a.approved_by,dept,true);
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(actor::text||key,0));
 SELECT * INTO old FROM public.document_command_receipts WHERE actor_id=actor AND request_key=key;
 IF FOUND THEN IF old.action<>'SETUP_'||action OR old.input<>jsonb_build_object('departmentId',dept,'payload',input) THEN RAISE EXCEPTION 'request changed' USING ERRCODE='23514'; END IF; RETURN old.output; END IF;
 IF action='REQUEST' THEN
  IF kind='PROJECT_POLICY' THEN
   IF NOT cfg ?& ARRAY['label','projectType','allowStudentRegistration'] OR (SELECT count(*) FROM jsonb_object_keys(cfg))<>3
      OR cfg->>'projectType' NOT IN ('MINI','MAJOR') OR jsonb_typeof(cfg->'allowStudentRegistration')<>'boolean' OR length(btrim(cfg->>'label')) NOT BETWEEN 1 AND 120 THEN RAISE EXCEPTION 'explicit project policy fields required' USING ERRCODE='22023'; END IF;
  ELSIF kind='TEAM_POLICY' THEN
   IF NOT cfg ?& ARRAY['label','allowJoin','allowLeave','allowTransfer','minimumMembers','maximumMembers','sizeMode'] OR (SELECT count(*) FROM jsonb_object_keys(cfg))<>7
     OR cfg->>'sizeMode' NOT IN ('ADVISORY','ENFORCED') OR length(btrim(cfg->>'label')) NOT BETWEEN 1 AND 120
     OR jsonb_typeof(cfg->'allowJoin')<>'boolean' OR jsonb_typeof(cfg->'allowLeave')<>'boolean' OR jsonb_typeof(cfg->'allowTransfer')<>'boolean'
     OR (cfg->>'minimumMembers')::integer<0 OR (cfg->>'maximumMembers')::integer<1 OR (cfg->>'minimumMembers')::integer>(cfg->>'maximumMembers')::integer THEN RAISE EXCEPTION 'explicit supported team policy required' USING ERRCODE='22023'; END IF;
  ELSIF kind='REVIEW_BLUEPRINT' THEN
   IF NOT cfg ?& ARRAY['policyVersionId','cycleId','label','stages'] OR (SELECT count(*) FROM jsonb_object_keys(cfg))<>4 OR jsonb_typeof(cfg->'stages')<>'array' OR jsonb_array_length(cfg->'stages') NOT BETWEEN 1 AND 10 THEN RAISE EXCEPTION 'complete review blueprint required' USING ERRCODE='22023'; END IF;
   SELECT * INTO policy FROM public.project_policy_versions WHERE id=(cfg->>'policyVersionId')::uuid AND department_id=dept AND policy_status='APPROVED';
   IF NOT FOUND OR NOT EXISTS(SELECT FROM public.academic_cycles WHERE id=(cfg->>'cycleId')::uuid AND department_id=dept) THEN RAISE EXCEPTION 'approved scoped policy and cycle required' USING ERRCODE='42501'; END IF;
   FOR stage IN SELECT value FROM jsonb_array_elements(cfg->'stages') LOOP
    IF stage->>'mode' NOT IN ('TEAM','INDIVIDUAL','COMBINED') OR jsonb_array_length(stage->'criteria') NOT BETWEEN 1 AND 30 THEN RAISE EXCEPTION 'supported stage mode and criteria required' USING ERRCODE='22023'; END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(stage->'criteria') LOOP
     IF item->>'scope' NOT IN ('TEAM','STUDENT') OR (stage->>'mode'='TEAM' AND item->>'scope'<>'TEAM') OR (stage->>'mode'='INDIVIDUAL' AND item->>'scope'<>'STUDENT')
       OR (item->>'maximum')::numeric<=0 OR (item->>'maximum')::numeric::text='NaN' OR length(btrim(item->>'label')) NOT BETWEEN 1 AND 120 THEN RAISE EXCEPTION 'valid explicit criterion required' USING ERRCODE='22023'; END IF;
    END LOOP;
   END LOOP;
  ELSE
   IF NOT EXISTS(SELECT FROM public.department_role_assignments dr JOIN public.users u ON u.id=dr.user_id WHERE dr.department_id=dept AND dr.user_id=(cfg->>'userId')::uuid AND u.account_status='ACTIVE') THEN RAISE EXCEPTION 'existing trusted department account required' USING ERRCODE='42501'; END IF;
   IF kind='STUDENT_PROFILE' AND (NOT cfg ?& ARRAY['userId','usn','section','semester'] OR (SELECT count(*) FROM jsonb_object_keys(cfg))<>4 OR NOT public.smartpro_has_role((cfg->>'userId')::uuid,dept,'STUDENT',clock_timestamp())) THEN RAISE EXCEPTION 'trusted student appointment and complete profile required' USING ERRCODE='42501'; END IF;
   IF kind='FACULTY_ACCESS' AND (NOT cfg ?& ARRAY['userId','validUntil'] OR (SELECT count(*) FROM jsonb_object_keys(cfg))<>2 OR (cfg->>'validUntil')::timestamptz<=clock_timestamp()) THEN RAISE EXCEPTION 'finite faculty appointment required' USING ERRCODE='22023'; END IF;
  END IF;
  INSERT INTO public.department_setup_requests(department_id,requested_by,role_id,kind,configuration,reason) VALUES(dept,actor,role_id,kind,cfg,input->>'reason') RETURNING id INTO rid;
  result:=jsonb_build_object('id',rid,'status','Awaiting authorization');
 ELSIF action='APPROVE' THEN
  INSERT INTO public.department_setup_approvals VALUES(r.id,actor,(auth->>'hodMandateId')::uuid,clock_timestamp());result:=jsonb_build_object('id',r.id,'status','Authorized');
 ELSIF action='APPLY' THEN
  PERFORM 1 FROM public.department_setup_requests WHERE id=r.id FOR UPDATE;
  IF EXISTS(SELECT FROM public.department_setup_executions WHERE request_id=r.id) THEN RAISE EXCEPTION 'already configured' USING ERRCODE='23514'; END IF;
  -- Serialize new versions across different approved Admin requests.
  PERFORM 1 FROM public.departments WHERE id=dept FOR UPDATE;
  -- Applying a queued authorization must recheck current target eligibility.
  IF kind IN ('STUDENT_PROFILE','FACULTY_ACCESS') THEN
   PERFORM 1 FROM public.users WHERE id=(cfg->>'userId')::uuid AND account_status='ACTIVE' FOR SHARE;
   IF NOT FOUND THEN RAISE EXCEPTION 'active target account required' USING ERRCODE='42501'; END IF;
   PERFORM 1 FROM public.department_role_assignments WHERE user_id=(cfg->>'userId')::uuid AND department_id=dept AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until) FOR SHARE;
   IF NOT FOUND OR (kind='STUDENT_PROFILE' AND NOT public.smartpro_has_role((cfg->>'userId')::uuid,dept,'STUDENT',clock_timestamp())) THEN RAISE EXCEPTION 'current scoped appointment required' USING ERRCODE='42501'; END IF;
   IF kind='FACULTY_ACCESS' AND (cfg->>'validUntil')::timestamptz<=clock_timestamp() THEN RAISE EXCEPTION 'faculty authorization expired' USING ERRCODE='23514'; END IF;
  END IF;
  IF kind='PROJECT_POLICY' THEN
   SELECT coalesce(max(version_no),0)+1 INTO version FROM public.project_policy_versions WHERE department_id=dept AND project_type=cfg->>'projectType';
   INSERT INTO public.project_policy_versions(department_id,project_type,version_no,policy_status,policy_data)
    VALUES(dept,cfg->>'projectType',version,'APPROVED',jsonb_build_object('label',cfg->>'label','studentRegistration',jsonb_build_object('enabled',(cfg->>'allowStudentRegistration')::boolean))) RETURNING id INTO rid;
  ELSIF kind='TEAM_POLICY' THEN
   SELECT coalesce(max(version_no),0)+1 INTO version FROM public.team_membership_policy_versions WHERE department_id=dept;
   INSERT INTO public.team_membership_policy_versions(department_id,version_no,allow_join,allow_leave,allow_transfer,minimum_members,maximum_members,size_mode,label)
    VALUES(dept,version,(cfg->>'allowJoin')::boolean,(cfg->>'allowLeave')::boolean,(cfg->>'allowTransfer')::boolean,(cfg->>'minimumMembers')::integer,(cfg->>'maximumMembers')::integer,cfg->>'sizeMode',cfg->>'label') RETURNING id INTO rid;
  ELSIF kind='REVIEW_BLUEPRINT' THEN
   SELECT * INTO policy FROM public.project_policy_versions WHERE id=(cfg->>'policyVersionId')::uuid AND department_id=dept AND policy_status='APPROVED' FOR SHARE;
   IF NOT FOUND THEN RAISE EXCEPTION 'source policy no longer approved' USING ERRCODE='23514'; END IF;
   SELECT coalesce(max(version_no),0)+1 INTO version FROM public.project_policy_versions WHERE department_id=dept AND project_type=policy.project_type;
   INSERT INTO public.project_policy_versions(department_id,project_type,version_no,policy_status,policy_data)
    VALUES(dept,policy.project_type,version,'APPROVED',policy.policy_data||jsonb_build_object('label',cfg->>'label','supersedesPolicyId',policy.id)) RETURNING id INTO rid;
   stage_no:=0;
   FOR stage IN SELECT value FROM jsonb_array_elements(cfg->'stages') LOOP
    stage_no:=stage_no+1;
    INSERT INTO public.review_definitions(policy_version_id,department_id,project_type,review_code,ordinal,label) VALUES(rid,dept,policy.project_type,stage->>'code',stage_no,stage->>'label') RETURNING id INTO definition;
    INSERT INTO public.evaluation_schemes(department_id,cycle_id,review_definition_id,label) VALUES(dept,(cfg->>'cycleId')::uuid,definition,stage->>'label') RETURNING id INTO scheme;
    INSERT INTO public.scheme_versions(scheme_id,cycle_id,review_definition_id,version_no) VALUES(scheme,(cfg->>'cycleId')::uuid,definition,1) RETURNING id INTO sv;
    INSERT INTO public.scheme_modes(scheme_version_id,mode_code) VALUES(sv,stage->>'mode') RETURNING id INTO mode;
    ordinal:=0;
    FOR item IN SELECT value FROM jsonb_array_elements(stage->'criteria') LOOP
     ordinal:=ordinal+1;
     INSERT INTO public.rubric_criteria(scheme_version_id,code,label,maximum,sort_order) VALUES(sv,'C'||ordinal,item->>'label',(item->>'maximum')::numeric,ordinal) RETURNING id INTO criterion;
     INSERT INTO public.mode_criteria(scheme_version_id,scheme_mode_id,criterion_id,score_scope) VALUES(sv,mode,criterion,item->>'scope');
    END LOOP;
    UPDATE public.scheme_versions SET state='APPROVED',approved_by=a.approved_by,approved_at=a.approved_at WHERE id=sv;
    UPDATE public.scheme_versions SET state='ACTIVE' WHERE id=sv;
   END LOOP;
  ELSIF kind='STUDENT_PROFILE' THEN
   INSERT INTO public.student_profiles(user_id,department_id,usn,section,semester_key) VALUES((cfg->>'userId')::uuid,dept,upper(btrim(cfg->>'usn')),cfg->>'section',cfg->>'semester')
    ON CONFLICT(user_id) DO UPDATE SET usn=excluded.usn,section=excluded.section,semester_key=excluded.semester_key WHERE student_profiles.department_id=dept RETURNING user_id INTO rid;
   IF rid IS NULL THEN RAISE EXCEPTION 'student department mismatch' USING ERRCODE='42501'; END IF;
  ELSE
   IF EXISTS(SELECT FROM public.department_role_assignments WHERE user_id=(cfg->>'userId')::uuid AND department_id=dept AND role_code='FACULTY' AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until)) THEN RAISE EXCEPTION 'retain existing faculty appointment; no duplicate' USING ERRCODE='23514'; END IF;
   INSERT INTO public.department_role_assignments(user_id,department_id,role_code,valid_until) VALUES((cfg->>'userId')::uuid,dept,'FACULTY',(cfg->>'validUntil')::timestamptz) RETURNING id INTO rid;
  END IF;
  result:=jsonb_build_object('id',rid,'status','Configured');INSERT INTO public.department_setup_executions VALUES(r.id,actor,result,clock_timestamp());
 ELSE RAISE EXCEPTION 'unsupported action' USING ERRCODE='22023'; END IF;
 IF action='APPLY' THEN
  PERFORM 1 FROM public.department_role_assignments WHERE id=r.role_id AND user_id=actor AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until);
  IF NOT FOUND THEN RAISE EXCEPTION 'Admin appointment expired while applying' USING ERRCODE='42501'; END IF;
  PERFORM public.smartpro_academic_authority(a.approved_by,dept,true);
 END IF;
 INSERT INTO public.document_command_receipts VALUES(actor,key,'SETUP_'||action,jsonb_build_object('departmentId',dept,'payload',input),result);
 INSERT INTO public.audit_events(actor_id,action,target_type,target_id,metadata) VALUES(actor,'DEPARTMENT_SETUP_'||action,'SETUP_REQUEST',coalesce(r.id,rid),jsonb_build_object('departmentId',dept,'kind',kind,'input',input,'output',result));
 RETURN result;
END $$;
CREATE OR REPLACE FUNCTION public.smartpro_setup_options(actor uuid,dept uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 PERFORM public.smartpro_department_setup_read(actor,dept);
 RETURN jsonb_build_object('schemeApproval',public.smartpro_academic_grant(actor,dept,'APPROVE_SCHEME') IS NOT NULL,'cycles',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM(SELECT id,code FROM public.academic_cycles WHERE department_id=dept ORDER BY starts_on DESC LIMIT 50)x),
 'policies',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM(SELECT id,project_type,version_no,coalesce(policy_data->>'label','Approved '||lower(project_type)||' project policy') AS label FROM public.project_policy_versions WHERE department_id=dept AND policy_status='APPROVED' ORDER BY version_no DESC LIMIT 50)x),
 'people',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM(SELECT DISTINCT u.id,u.display_name FROM public.users u JOIN public.department_role_assignments r ON r.user_id=u.id WHERE r.department_id=dept AND u.account_status='ACTIVE' AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until) ORDER BY u.display_name LIMIT 100)x));
END $$;
REVOKE ALL ON FUNCTION public.smartpro_setup_current(uuid,uuid,text,jsonb,text),public.smartpro_setup_options(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_setup_current(uuid,uuid,text,jsonb,text),public.smartpro_setup_options(uuid,uuid) TO smartpro_runtime;
COMMIT;
