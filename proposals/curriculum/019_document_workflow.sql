-- Owner-run forward candidate after 018. No production activation or bootstrap.
BEGIN;
DO $$ BEGIN
 IF to_regprocedure('public.smartpro_initial_evaluation(uuid,uuid,text,jsonb,text)') IS NULL THEN
   RAISE EXCEPTION 'Reviewed 018 required'; END IF;
END $$;
CREATE TABLE public.offering_operational_instructions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), department_id uuid NOT NULL REFERENCES departments(id),
 hod_mandate_id uuid NOT NULL REFERENCES academic_hod_mandates(id),
 admin_role_id uuid NOT NULL REFERENCES department_role_assignments(id),
 approved_by uuid NOT NULL REFERENCES users(id), approved_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 configuration jsonb NOT NULL, reason text NOT NULL CHECK(btrim(reason)<>''));
CREATE TABLE public.offering_instruction_executions (
 instruction_id uuid PRIMARY KEY REFERENCES offering_operational_instructions(id),
 offering_id uuid NOT NULL REFERENCES curriculum_offerings(id),
 configured_by uuid NOT NULL REFERENCES users(id), configured_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE public.submission_requirement_policies (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), offering_id uuid NOT NULL REFERENCES curriculum_offerings(id),
 instruction_id uuid NOT NULL REFERENCES offering_operational_instructions(id),
 requirement_key text NOT NULL DEFAULT 'SYNOPSIS' CHECK(requirement_key='SYNOPSIS'),
 opens_at timestamptz NOT NULL, closes_at timestamptz NOT NULL,
 max_bytes integer NOT NULL CHECK(max_bytes BETWEEN 1 AND 2097152),
 faculty_approval_enabled boolean NOT NULL DEFAULT false,
 CHECK(opens_at<closes_at), UNIQUE(id,offering_id));
CREATE TABLE public.submission_offering_requirements (
 offering_id uuid PRIMARY KEY REFERENCES curriculum_offerings(id), policy_id uuid NOT NULL,
 FOREIGN KEY(policy_id,offering_id) REFERENCES submission_requirement_policies(id,offering_id));
CREATE TABLE public.submission_requirement_bindings (
 case_id uuid PRIMARY KEY REFERENCES submission_cases(id),
 policy_id uuid NOT NULL REFERENCES submission_requirement_policies(id),
 document_id uuid NOT NULL UNIQUE REFERENCES documents(id));
CREATE TABLE public.document_command_receipts (
 actor_id uuid NOT NULL REFERENCES users(id), request_key text NOT NULL,
 action text NOT NULL, input jsonb NOT NULL, output jsonb NOT NULL,
 PRIMARY KEY(actor_id,request_key));
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['offering_operational_instructions','offering_instruction_executions','submission_requirement_policies','submission_requirement_bindings','document_command_receipts'] LOOP
  EXECUTE format('CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation()',t);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,smartpro_runtime',t);
 END LOOP;
END $$;
REVOKE ALL ON public.submission_offering_requirements FROM PUBLIC,smartpro_runtime;

CREATE FUNCTION public.smartpro_document_scope(actor uuid,pid uuid,mode text) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.projects%ROWTYPE; o public.curriculum_offerings%ROWTYPE; profile public.student_profiles%ROWTYPE;
BEGIN
 SELECT * INTO p FROM public.projects WHERE id=pid;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM public.users WHERE id=actor AND account_status='ACTIVE' FOR SHARE;
 IF NOT FOUND OR NOT EXISTS(SELECT FROM public.academic_governance_settings WHERE department_id=p.department_id AND enabled)
   OR NOT EXISTS(SELECT FROM public.staff_department_controls WHERE department_id=p.department_id AND enabled) THEN RETURN false; END IF;
 IF mode IN ('student','read') AND public.smartpro_project_permission(pid,actor,'student') THEN
  SELECT x.* INTO o FROM public.curriculum_offerings x JOIN public.teams t ON t.curriculum_offering_id=x.id WHERE t.id=p.team_id;
  SELECT * INTO profile FROM public.student_profiles WHERE user_id=actor FOR SHARE;
  IF profile.department_id=o.department_id AND profile.semester_key=o.semester_key AND o.cycle_id=p.cycle_id
    AND EXISTS(SELECT FROM public.academic_cycles WHERE id=o.cycle_id AND starts_on<=current_date AND current_date<=ends_on) THEN RETURN true; END IF;
 END IF;
 IF mode IN ('reviewer','read') AND public.smartpro_project_permission(pid,actor,'reviewer') THEN RETURN true; END IF;
 IF mode='read' THEN
  BEGIN PERFORM public.smartpro_academic_authority(actor,p.department_id); RETURN true;
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 END IF;
 RETURN false;
END $$;

CREATE FUNCTION public.smartpro_document_command(actor uuid,dept uuid,action text,input jsonb,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE authority jsonb; result jsonb; old public.document_command_receipts%ROWTYPE;
 instruction public.offering_operational_instructions%ROWTYPE; config jsonb;
 p public.projects%ROWTYPE; rule public.submission_requirement_policies%ROWTYPE;
 c public.submission_cases%ROWTYPE; up public.upload_sessions%ROWTYPE; a public.submission_attempts%ROWTYPE;
 role public.department_role_assignments%ROWTYPE; d uuid; oid uuid; rid uuid; vid uuid; fid uuid; aid uuid; n integer;
BEGIN
 IF length(key) NOT BETWEEN 1 AND 128 OR key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$' THEN RAISE EXCEPTION 'request key required' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(actor::text||':documents:'||key,0));
 PERFORM 1 FROM public.users WHERE id=actor AND account_status='ACTIVE' FOR SHARE;
 IF NOT FOUND OR NOT EXISTS(SELECT FROM public.academic_governance_settings WHERE department_id=dept AND enabled)
   OR NOT EXISTS(SELECT FROM public.staff_department_controls WHERE department_id=dept AND enabled) THEN RAISE EXCEPTION 'enabled active department required' USING ERRCODE='42501'; END IF;
 IF action IN ('AUTHORIZE','ASSIGN_REVIEWER') THEN
  authority:=public.smartpro_academic_authority(actor,dept,action='AUTHORIZE');
 ELSIF action='CONFIGURE' THEN
  SELECT * INTO instruction FROM public.offering_operational_instructions WHERE id=(input->>'instructionId')::uuid AND department_id=dept FOR UPDATE;
  SELECT * INTO role FROM public.department_role_assignments WHERE id=instruction.admin_role_id AND user_id=actor AND department_id=dept
    AND role_code='ACADEMIC_ADMIN' AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until) FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'named operational admin required' USING ERRCODE='42501'; END IF;
  PERFORM 1 FROM public.academic_hod_mandates WHERE id=instruction.hod_mandate_id AND enabled FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'original HOD mandate required' USING ERRCODE='42501'; END IF;
  PERFORM public.smartpro_academic_authority(instruction.approved_by,dept,true);
 ELSE
  SELECT * INTO p FROM public.projects WHERE id=(input->>'projectId')::uuid AND department_id=dept FOR SHARE;
  IF NOT FOUND OR NOT public.smartpro_document_scope(actor,p.id,CASE WHEN action='DECIDE' THEN 'reviewer' ELSE 'student' END) THEN
    RAISE EXCEPTION 'current project scope required' USING ERRCODE='42501'; END IF;
 END IF;
 SELECT * INTO old FROM public.document_command_receipts WHERE actor_id=actor AND request_key=key;
 IF FOUND THEN
  IF old.action<>action OR old.input<>input THEN RAISE EXCEPTION 'request key reused' USING ERRCODE='23514'; END IF;
  RETURN old.output;
 END IF;
 IF action='AUTHORIZE' THEN
  config:=input->'configuration';
  IF (SELECT count(*) FROM jsonb_object_keys(config))<>13 OR NOT config ?& ARRAY['curriculumTypeId','cycleId','semester','projectPolicyId','teamPolicyId','visibleFrom','visibleUntil','submissionOpensAt','submissionClosesAt','maxBytes','adminRoleId','facultyApprovalEnabled','teamCreationEnabled']
    OR length(btrim(config->>'semester')) NOT BETWEEN 1 AND 80 OR btrim(input->>'reason')='' THEN RAISE EXCEPTION 'exact approved configuration required' USING ERRCODE='22023'; END IF;
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
  INSERT INTO public.offering_operational_instructions(department_id,hod_mandate_id,admin_role_id,approved_by,configuration,reason)
    VALUES(dept,(authority->>'hodMandateId')::uuid,(config->>'adminRoleId')::uuid,actor,config,input->>'reason') RETURNING id INTO rid;
  result:=jsonb_build_object('instructionId',rid,'status','AUTHORIZED');
 ELSIF action='CONFIGURE' THEN
  IF EXISTS(SELECT FROM public.offering_instruction_executions WHERE instruction_id=instruction.id) THEN RAISE EXCEPTION 'instruction already configured' USING ERRCODE='23514'; END IF;
  config:=instruction.configuration;
  INSERT INTO public.curriculum_offerings(curriculum_type_id,department_id,cycle_id,semester_key,student_team_creation_enabled)
   VALUES((config->>'curriculumTypeId')::uuid,dept,(config->>'cycleId')::uuid,config->>'semester',(config->>'teamCreationEnabled')::boolean)
   ON CONFLICT(department_id,cycle_id,semester_key,curriculum_type_id) DO NOTHING RETURNING id INTO oid;
  IF oid IS NULL THEN
   SELECT id INTO oid FROM public.curriculum_offerings WHERE department_id=dept AND cycle_id=(config->>'cycleId')::uuid
    AND semester_key=config->>'semester' AND curriculum_type_id=(config->>'curriculumTypeId')::uuid FOR UPDATE;
   IF EXISTS(SELECT FROM public.submission_offering_requirements head
      JOIN public.submission_requirement_policies q ON q.id=head.policy_id
      JOIN public.offering_operational_instructions i ON i.id=q.instruction_id
      WHERE head.offering_id=oid AND i.approved_at>instruction.approved_at) THEN
    RAISE EXCEPTION 'newer offering instruction already configured' USING ERRCODE='23514'; END IF;
   UPDATE public.curriculum_offerings SET student_team_creation_enabled=(config->>'teamCreationEnabled')::boolean WHERE id=oid;
  END IF;
  INSERT INTO public.student_offering_windows VALUES(oid,(config->>'visibleFrom')::timestamptz,(config->>'visibleUntil')::timestamptz)
   ON CONFLICT(offering_id) DO UPDATE SET visible_from=excluded.visible_from,visible_until=excluded.visible_until;
  INSERT INTO public.offering_membership_policies VALUES(oid,(config->>'cycleId')::uuid,dept,(config->>'teamPolicyId')::uuid)
   ON CONFLICT(offering_id) DO UPDATE SET policy_version_id=excluded.policy_version_id;
  INSERT INTO public.project_registration_policy_versions(offering_id,cycle_id,department_id,project_type,policy_version_id,version_no,opens_at,closes_at)
    SELECT oid,(config->>'cycleId')::uuid,dept,project_type,id,(SELECT coalesce(max(version_no),0)+1 FROM public.project_registration_policy_versions WHERE offering_id=oid AND project_type=q.project_type),(config->>'visibleFrom')::timestamptz,(config->>'visibleUntil')::timestamptz
    FROM public.project_policy_versions q WHERE id=(config->>'projectPolicyId')::uuid RETURNING id INTO rid;
  INSERT INTO public.offering_project_registration_policies SELECT oid,project_type,rid FROM public.project_policy_versions WHERE id=(config->>'projectPolicyId')::uuid
    ON CONFLICT(offering_id,project_type) DO UPDATE SET registration_policy_version_id=excluded.registration_policy_version_id;
  INSERT INTO public.submission_requirement_policies(offering_id,instruction_id,opens_at,closes_at,max_bytes,faculty_approval_enabled)
    VALUES(oid,instruction.id,(config->>'submissionOpensAt')::timestamptz,(config->>'submissionClosesAt')::timestamptz,(config->>'maxBytes')::integer,(config->>'facultyApprovalEnabled')::boolean) RETURNING id INTO rid;
  INSERT INTO public.submission_offering_requirements VALUES(oid,rid) ON CONFLICT(offering_id) DO UPDATE SET policy_id=excluded.policy_id;
  INSERT INTO public.offering_instruction_executions VALUES(instruction.id,oid,actor,clock_timestamp());
  result:=jsonb_build_object('offeringId',oid,'status','CONFIGURED');
 ELSIF action='ASSIGN_REVIEWER' THEN
  SELECT * INTO p FROM public.projects WHERE id=(input->>'projectId')::uuid AND department_id=dept FOR UPDATE;
  IF NOT FOUND OR NOT public.smartpro_has_role((input->>'facultyId')::uuid,dept,'FACULTY',clock_timestamp()) THEN RAISE EXCEPTION 'scoped project and faculty required' USING ERRCODE='42501'; END IF;
  INSERT INTO public.faculty_assignments(project_id,faculty_user_id,assignment_type) VALUES(p.id,(input->>'facultyId')::uuid,'REVIEWER') RETURNING id INTO rid;
  result:=jsonb_build_object('assignmentId',rid);
 ELSE
  SELECT x.* INTO rule FROM public.submission_requirement_policies x JOIN public.submission_offering_requirements h ON h.policy_id=x.id JOIN public.teams t ON t.curriculum_offering_id=h.offering_id WHERE t.id=p.team_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'approved synopsis requirement missing' USING ERRCODE='23514'; END IF;
  -- Serializes case creation, uploads, submission and review for this project.
  PERFORM pg_advisory_xact_lock(hashtextextended(p.id::text||':synopsis',0));
  SELECT * INTO c FROM public.submission_cases WHERE project_id=p.id AND requirement_key='SYNOPSIS' FOR UPDATE;
  IF c.id IS NOT NULL THEN SELECT q.* INTO rule FROM public.submission_requirement_policies q JOIN public.submission_requirement_bindings b ON b.policy_id=q.id WHERE b.case_id=c.id; END IF;
  IF action='PREPARE' AND c.id IS NULL THEN
   INSERT INTO public.submission_cases(project_id,requirement_key,submission_type) VALUES(p.id,'SYNOPSIS','SYNOPSIS') RETURNING * INTO c;
   INSERT INTO public.documents(project_id,document_type,label) VALUES(p.id,'SYNOPSIS','Project synopsis') RETURNING id INTO d;
   INSERT INTO public.submission_requirement_bindings VALUES(c.id,rule.id,d);
  END IF;
  SELECT document_id INTO d FROM public.submission_requirement_bindings WHERE case_id=c.id AND policy_id=rule.id;
  IF d IS NULL THEN RAISE EXCEPTION 'pinned requirement binding required' USING ERRCODE='23514'; END IF;
  IF action IN ('SUBMIT','DECIDE') AND (input->>'expectedCaseVersion') IS NULL THEN RAISE EXCEPTION 'case revision required' USING ERRCODE='22023'; END IF;
  IF action NOT IN ('PREPARE','DECIDE') AND NOT (rule.opens_at<=clock_timestamp() AND clock_timestamp()<rule.closes_at) THEN RAISE EXCEPTION 'submission window closed' USING ERRCODE='23514'; END IF;
  IF action IN ('START_UPLOAD','COMPLETE_UPLOAD','SUBMIT') AND c.state NOT IN ('DRAFT','CHANGES_REQUESTED') THEN RAISE EXCEPTION 'case not accepting revisions' USING ERRCODE='23514'; END IF;
  IF action='PREPARE' THEN result:=jsonb_build_object('caseId',c.id,'documentId',d);
  ELSIF action='START_UPLOAD' THEN
   rid:=gen_random_uuid(); INSERT INTO public.upload_sessions(id,document_id,user_id,storage_key) VALUES(rid,d,actor,rid::text||'.pdf');
   result:=jsonb_build_object('uploadId',rid,'maxBytes',rule.max_bytes);
  ELSIF action='COMPLETE_UPLOAD' THEN
   SELECT * INTO up FROM public.upload_sessions WHERE id=(input->>'uploadId')::uuid AND document_id=d AND user_id=actor FOR UPDATE;
   IF NOT FOUND OR up.status<>'PENDING' OR (input->>'size')::integer NOT BETWEEN 1 AND rule.max_bytes THEN RAISE EXCEPTION 'valid pending owned upload required' USING ERRCODE='23514'; END IF;
   UPDATE public.upload_sessions SET status='UPLOADED',sha256=input->>'sha256',size_bytes=(input->>'size')::integer WHERE id=up.id;
   PERFORM 1 FROM public.documents WHERE id=d FOR UPDATE;
   SELECT coalesce(max(version_no),0)+1 INTO n FROM public.document_versions WHERE document_id=d;
   INSERT INTO public.file_assets(storage_key,sha256,size_bytes,mime_type,upload_status,uploaded_by,verified_at)
    VALUES(up.storage_key,input->>'sha256',(input->>'size')::integer,'application/pdf','READY',actor,clock_timestamp()) RETURNING id INTO fid;
   INSERT INTO public.document_versions(project_id,document_id,version_no,file_asset_id,uploaded_by) VALUES(p.id,d,n,fid,actor) RETURNING id INTO vid;
   UPDATE public.upload_sessions SET status='COMPLETE',document_version_id=vid,completed_at=clock_timestamp() WHERE id=up.id;
   result:=jsonb_build_object('documentVersionId',vid,'versionNumber',n,'status','READY');
  ELSIF action='SUBMIT' THEN
   IF c.row_version<>(input->>'expectedCaseVersion')::integer THEN RAISE EXCEPTION 'stale case' USING ERRCODE='23514'; END IF;
   SELECT v.id INTO vid FROM public.document_versions v JOIN public.file_assets f ON f.id=v.file_asset_id WHERE v.id=(input->>'documentVersionId')::uuid AND v.document_id=d AND v.uploaded_by=actor AND f.upload_status='READY' FOR SHARE OF f;
   IF vid IS NULL THEN RAISE EXCEPTION 'owned ready version required' USING ERRCODE='42501'; END IF;
   IF EXISTS(SELECT FROM public.submission_items WHERE document_version_id=vid) THEN RAISE EXCEPTION 'submit a new revision' USING ERRCODE='23514'; END IF;
   SELECT coalesce(max(attempt_no),0)+1 INTO n FROM public.submission_attempts WHERE case_id=c.id;
   INSERT INTO public.submission_attempts(case_id,project_id,attempt_no,submitted_by) VALUES(c.id,p.id,n,actor) RETURNING id INTO aid;
   INSERT INTO public.submission_items VALUES(aid,p.id,d,vid);
   UPDATE public.submission_attempts SET sealed_at=clock_timestamp() WHERE id=aid;
   UPDATE public.submission_cases SET state='AWAITING_REVIEW',row_version=row_version+1 WHERE id=c.id;
   result:=jsonb_build_object('attemptId',aid,'status','AWAITING_REVIEW');
  ELSIF action='DECIDE' THEN
   SELECT * INTO a FROM public.submission_attempts WHERE id=(input->>'attemptId')::uuid AND case_id=c.id FOR UPDATE;
   IF NOT FOUND OR c.row_version<>(input->>'expectedCaseVersion')::integer OR c.state<>'AWAITING_REVIEW' OR a.attempt_state<>'SUBMITTED'
    OR input->>'decision' NOT IN ('REQUEST_CHANGES','APPROVE') OR (input->>'decision'='APPROVE' AND NOT rule.faculty_approval_enabled)
    OR length(btrim(input->>'comment')) NOT BETWEEN 1 AND 4000 THEN RAISE EXCEPTION 'pending latest attempt and configured decision with feedback required' USING ERRCODE='23514'; END IF;
   INSERT INTO public.approval_decisions(attempt_id,project_id,reviewer_user_id,decision,comment) VALUES(a.id,p.id,actor,input->>'decision',input->>'comment');
   UPDATE public.submission_attempts SET attempt_state=CASE WHEN input->>'decision'='APPROVE' THEN 'APPROVED' ELSE 'CHANGES_REQUESTED' END WHERE id=a.id;
   UPDATE public.submission_cases SET state=CASE WHEN input->>'decision'='APPROVE' THEN 'APPROVED' ELSE 'CHANGES_REQUESTED' END,row_version=row_version+1 WHERE id=c.id;
   result:=jsonb_build_object('status',CASE WHEN input->>'decision'='APPROVE' THEN 'APPROVED' ELSE 'CHANGES_REQUESTED' END);
  ELSE RAISE EXCEPTION 'unknown document action' USING ERRCODE='22023'; END IF;
 END IF;
 INSERT INTO public.document_command_receipts VALUES(actor,key,action,input,result);
 INSERT INTO public.audit_events(actor_id,project_id,action,target_type,target_id,metadata)
  VALUES(actor,p.id,'DOCUMENT_'||action,'DOCUMENT_WORKFLOW',coalesce(c.id,rid,oid),jsonb_build_object('departmentId',dept,'request',input,'result',result,'authority',authority));
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_document_scope(uuid,uuid,text),public.smartpro_document_command(uuid,uuid,text,jsonb,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_document_command(uuid,uuid,text,jsonb,text) TO smartpro_runtime;
COMMIT;
