-- Reuse existing policies, cases, documents, assets and decisions for named requirements.
BEGIN;
DO $$ BEGIN IF to_regprocedure('public.smartpro_manage_assignment(uuid,uuid,text,jsonb,text)') IS NULL THEN RAISE EXCEPTION 'Reviewed 031 required'; END IF; END $$;
ALTER TABLE public.submission_requirement_policies DROP CONSTRAINT IF EXISTS submission_requirement_policies_requirement_key_check;
ALTER TABLE public.submission_requirement_policies ADD COLUMN IF NOT EXISTS document_name text;
ALTER TABLE public.submission_requirement_policies ADD COLUMN IF NOT EXISTS is_required boolean NOT NULL DEFAULT true;
ALTER TABLE public.submission_requirement_policies ADD COLUMN IF NOT EXISTS revisions_enabled boolean NOT NULL DEFAULT true;
ALTER TABLE public.submission_requirement_policies ADD COLUMN IF NOT EXISTS changes_enabled boolean NOT NULL DEFAULT true;
ALTER TABLE public.submission_requirement_policies ADD COLUMN IF NOT EXISTS reviewer_ids jsonb;
ALTER TABLE public.submission_requirement_policies ADD COLUMN IF NOT EXISTS authority jsonb;
ALTER TABLE public.submission_requirement_policies ADD COLUMN IF NOT EXISTS configured_by uuid REFERENCES users(id);
ALTER TABLE public.submission_requirement_policies ADD COLUMN IF NOT EXISTS configured_at timestamptz;
ALTER TABLE public.submission_offering_requirements ADD COLUMN IF NOT EXISTS requirement_key text NOT NULL DEFAULT 'SYNOPSIS';
ALTER TABLE public.submission_offering_requirements DROP CONSTRAINT submission_offering_requirements_pkey;
ALTER TABLE public.submission_offering_requirements ADD PRIMARY KEY(offering_id,requirement_key);
ALTER TABLE public.submission_requirement_policies ADD CONSTRAINT nonblank_requirement_key CHECK(btrim(requirement_key)<>'');
ALTER TABLE public.submission_requirement_policies ADD CONSTRAINT keyed_requirement_identity UNIQUE(id,offering_id,requirement_key);
ALTER TABLE public.submission_offering_requirements ADD CONSTRAINT consistent_requirement_head FOREIGN KEY(policy_id,offering_id,requirement_key) REFERENCES submission_requirement_policies(id,offering_id,requirement_key);
ALTER TABLE public.faculty_assignments ADD COLUMN IF NOT EXISTS requirement_key text;
ALTER TABLE public.approval_decisions DROP CONSTRAINT IF EXISTS approval_decisions_decision_check;
ALTER TABLE public.approval_decisions ADD CHECK(decision IN ('APPROVE','REQUEST_CHANGES','REJECT','COMMENT'));
ALTER TABLE public.approval_decisions DROP CONSTRAINT IF EXISTS approval_decisions_attempt_id_reviewer_user_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS one_formal_reviewer_decision ON public.approval_decisions(attempt_id,reviewer_user_id) WHERE decision<>'COMMENT';

CREATE OR REPLACE FUNCTION public.smartpro_configure_requirement(actor uuid,dept uuid,action text,input jsonb,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE auth jsonb; prior public.document_command_receipts%ROWTYPE; oid uuid; req text; current_policy uuid; rid uuid; instruction uuid; uid uuid; result jsonb;
BEGIN
 auth:=public.smartpro_operational_authority(actor,dept,input->'authority');
 IF action<>'CONFIGURE' OR key IS NULL OR key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' THEN RAISE EXCEPTION 'Configuration command required' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(actor::text||':requirement:'||key,0));
 SELECT * INTO prior FROM public.document_command_receipts WHERE actor_id=actor AND request_key=key;
 IF FOUND THEN IF prior.action<>'CONFIGURE_REQUIREMENT' OR prior.input<>jsonb_build_object('departmentId',dept,'payload',input) THEN RAISE EXCEPTION 'Retry changed' USING ERRCODE='23514'; END IF;RETURN prior.output; END IF;
 oid:=(input->>'offeringId')::uuid;
 PERFORM 1 FROM public.curriculum_offerings WHERE id=oid AND department_id=dept FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Department offering required' USING ERRCODE='42501'; END IF;
 req:=coalesce(input->>'requirementKey','DOCUMENT-'||encode(sha256(convert_to(actor::text||key,'UTF8')),'hex'));
 IF length(req) NOT BETWEEN 1 AND 100 OR length(btrim(input->>'name')) NOT BETWEEN 1 AND 120 OR (input->>'opensAt')::timestamptz >= (input->>'closesAt')::timestamptz OR (input->>'maxBytes')::integer NOT BETWEEN 1 AND 2097152
  OR jsonb_typeof(input->'reviewerIds')<>'array' OR jsonb_array_length(input->'reviewerIds')>50 THEN RAISE EXCEPTION 'Complete approved document settings required' USING ERRCODE='22023'; END IF;
 FOREACH uid IN ARRAY ARRAY(SELECT value::uuid FROM jsonb_array_elements_text(input->'reviewerIds')) LOOP
  IF NOT public.smartpro_has_role(uid,dept,'FACULTY',clock_timestamp()) THEN RAISE EXCEPTION 'Active departmental reviewers required' USING ERRCODE='42501'; END IF;
 END LOOP;
 IF ((input->>'allowApproval')::boolean OR (input->>'allowChanges')::boolean) AND jsonb_array_length(input->'reviewerIds')=0 THEN RAISE EXCEPTION 'Assign authorized reviewers before permitting decisions' USING ERRCODE='22023'; END IF;
 SELECT policy_id INTO current_policy FROM public.submission_offering_requirements WHERE offering_id=oid AND requirement_key=req FOR UPDATE;
 IF current_policy IS DISTINCT FROM (input->>'expectedPolicyId')::uuid THEN RAISE EXCEPTION 'Requirement changed; refresh' USING ERRCODE='23514'; END IF;
 SELECT i.id INTO instruction FROM public.offering_instruction_executions e JOIN public.offering_operational_instructions i ON i.id=e.instruction_id WHERE e.offering_id=oid ORDER BY e.configured_at DESC LIMIT 1;
 IF instruction IS NULL THEN RAISE EXCEPTION 'Configure the offering before its document requirements' USING ERRCODE='23514'; END IF;
 INSERT INTO public.submission_requirement_policies(offering_id,instruction_id,requirement_key,opens_at,closes_at,max_bytes,faculty_approval_enabled,document_name,is_required,revisions_enabled,changes_enabled,reviewer_ids,authority,configured_by,configured_at)
 VALUES(oid,instruction,req,(input->>'opensAt')::timestamptz,(input->>'closesAt')::timestamptz,(input->>'maxBytes')::integer,(input->>'allowApproval')::boolean,btrim(input->>'name'),(input->>'required')::boolean,(input->>'allowRevisions')::boolean,(input->>'allowChanges')::boolean,input->'reviewerIds',input->'authority',actor,clock_timestamp()) RETURNING id INTO rid;
 INSERT INTO public.submission_offering_requirements VALUES(oid,rid,req) ON CONFLICT(offering_id,requirement_key) DO UPDATE SET policy_id=excluded.policy_id;
 -- Reviewer responsibilities are live temporal assignments, separate from the
 -- immutable submission rules pinned to a case. Reassignment retains decisions.
 PERFORM p.id FROM public.projects p JOIN public.teams t ON t.id=p.team_id WHERE t.curriculum_offering_id=oid ORDER BY p.id FOR UPDATE OF p;
 UPDATE public.faculty_assignments f SET valid_until=clock_timestamp() FROM public.projects p JOIN public.teams t ON t.id=p.team_id
  WHERE f.project_id=p.id AND t.curriculum_offering_id=oid AND f.assignment_type='REVIEWER'
   AND (f.requirement_key=req OR (req='SYNOPSIS' AND f.requirement_key IS NULL))
   AND f.valid_from<=clock_timestamp() AND (f.valid_until IS NULL OR clock_timestamp()<f.valid_until)
   AND NOT input->'reviewerIds' ? f.faculty_user_id::text;
 -- Explicit configured reviewers receive only this requirement's project assignment.
 INSERT INTO public.faculty_assignments(project_id,faculty_user_id,assignment_type,requirement_key)
  SELECT p.id,u.value::uuid,'REVIEWER',req FROM public.projects p JOIN public.teams t ON t.id=p.team_id CROSS JOIN jsonb_array_elements_text(input->'reviewerIds') u WHERE t.curriculum_offering_id=oid
   AND NOT EXISTS(SELECT FROM public.faculty_assignments f WHERE f.project_id=p.id AND f.faculty_user_id=u.value::uuid AND f.assignment_type='REVIEWER' AND f.requirement_key=req AND f.valid_from<=clock_timestamp() AND (f.valid_until IS NULL OR clock_timestamp()<f.valid_until));
 PERFORM public.smartpro_operational_authority(actor,dept,input->'authority');
 result:=jsonb_build_object('id',rid,'requirementKey',req,'offeringId',oid);
 INSERT INTO public.document_command_receipts VALUES(actor,key,'CONFIGURE_REQUIREMENT',jsonb_build_object('departmentId',dept,'payload',input),result);
 INSERT INTO public.audit_events(actor_id,action,target_type,target_id,metadata) VALUES(actor,'DOCUMENT_REQUIREMENT_CONFIGURED','REQUIREMENT_POLICY',rid,jsonb_build_object('departmentId',dept,'previousPolicyId',current_policy,'configuration',input,'result',result,'authority',auth));
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION public.smartpro_requirement_access(actor uuid,pid uuid,req text,acting_role text,for_decision boolean DEFAULT false) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE dept uuid; policy public.submission_requirement_policies%ROWTYPE;
BEGIN
 IF NOT public.smartpro_role_choices(actor) ? acting_role THEN RETURN false; END IF;
 SELECT department_id INTO dept FROM public.projects WHERE id=pid;
 SELECT q.* INTO policy FROM public.submission_requirement_policies q WHERE q.id=coalesce(
  (SELECT b.policy_id FROM public.submission_requirement_bindings b JOIN public.submission_cases c ON c.id=b.case_id WHERE c.project_id=pid AND c.requirement_key=req),
  (SELECT h.policy_id FROM public.submission_offering_requirements h JOIN public.teams t ON t.curriculum_offering_id=h.offering_id JOIN public.projects p ON p.team_id=t.id WHERE p.id=pid AND h.requirement_key=req));
 IF NOT FOUND THEN RETURN false; END IF;
 IF acting_role='Student' THEN RETURN NOT for_decision AND public.smartpro_document_scope(actor,pid,'student'); END IF;
 IF acting_role IN ('HOD','Coordinator') THEN RETURN NOT for_decision AND public.smartpro_document_scope(actor,pid,'read'); END IF;
 IF acting_role<>'Faculty' OR NOT public.smartpro_has_role(actor,dept,'FACULTY',clock_timestamp()) THEN RETURN false; END IF;
 IF NOT for_decision AND (EXISTS(SELECT FROM public.faculty_assignments f WHERE f.project_id=pid AND f.faculty_user_id=actor AND f.assignment_type='GUIDE' AND f.valid_from<=clock_timestamp() AND (f.valid_until IS NULL OR clock_timestamp()<f.valid_until)) OR EXISTS(SELECT FROM public.evaluator_assignments e JOIN public.project_reviews r ON r.id=e.review_id WHERE r.project_id=pid AND e.faculty_user_id=actor)) THEN RETURN true; END IF;
 RETURN EXISTS(SELECT FROM public.faculty_assignments f WHERE f.project_id=pid AND f.faculty_user_id=actor AND f.assignment_type='REVIEWER' AND (f.requirement_key=req OR (f.requirement_key IS NULL AND req='SYNOPSIS')) AND f.valid_from<=clock_timestamp() AND (f.valid_until IS NULL OR clock_timestamp()<f.valid_until));
END $$;
CREATE OR REPLACE FUNCTION public.smartpro_requirement_case(cid uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT jsonb_build_object('id',c.id,'state',c.state,'version',c.row_version,
  'versions',(SELECT coalesce(jsonb_agg(jsonb_build_object('id',v.id,'version',v.version_no,'createdAt',v.created_at,'uploadedBy',u.display_name,'bytes',f.size_bytes) ORDER BY v.version_no),'[]') FROM public.submission_requirement_bindings b JOIN public.document_versions v ON v.document_id=b.document_id JOIN public.file_assets f ON f.id=v.file_asset_id JOIN public.users u ON u.id=v.uploaded_by WHERE b.case_id=c.id),
  'attempts',(SELECT coalesce(jsonb_agg(jsonb_build_object('id',a.id,'number',a.attempt_no,'state',a.attempt_state,'submittedAt',a.submitted_at,'versionId',(SELECT document_version_id FROM public.submission_items WHERE attempt_id=a.id LIMIT 1),
   'feedback',(SELECT coalesce(jsonb_agg(jsonb_build_object('comment',d.comment,'decision',d.decision,'by',u.display_name,'at',d.decided_at) ORDER BY d.decided_at),'[]') FROM public.approval_decisions d JOIN public.users u ON u.id=d.reviewer_user_id WHERE d.attempt_id=a.id)) ORDER BY a.attempt_no),'[]') FROM public.submission_attempts a WHERE a.case_id=c.id)) FROM public.submission_cases c WHERE c.id=cid;
$$;
CREATE OR REPLACE FUNCTION public.smartpro_configured_document_workspace(actor uuid,dept uuid,acting_role text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE w jsonb; projects jsonb:='[]'; project jsonb; requirements jsonb; req record;
BEGIN
 w:=public.smartpro_role_documents(actor,dept,acting_role);
 FOR project IN SELECT value FROM jsonb_array_elements(w->'projects') LOOP
  requirements:='[]';
  FOR req IN SELECT DISTINCT ON(q.requirement_key) q.*,c.id AS case_id FROM public.submission_requirement_policies q
   LEFT JOIN public.submission_requirement_bindings b ON b.policy_id=q.id LEFT JOIN public.submission_cases c ON c.id=b.case_id AND c.project_id=(project->>'id')::uuid
   WHERE q.offering_id=(project->>'offeringId')::uuid AND (c.id IS NOT NULL OR EXISTS(SELECT FROM public.submission_offering_requirements h WHERE h.policy_id=q.id)) ORDER BY q.requirement_key,(c.id IS NOT NULL) DESC,q.configured_at DESC NULLS LAST LOOP
   IF public.smartpro_requirement_access(actor,(project->>'id')::uuid,req.requirement_key,acting_role,false) THEN
    requirements:=requirements||jsonb_build_array(jsonb_build_object('key',req.requirement_key,'policyId',req.id,'name',coalesce(req.document_name,'Synopsis'),'required',req.is_required,'opensAt',req.opens_at,'closesAt',req.closes_at,'maxBytes',req.max_bytes,'allowApproval',req.faculty_approval_enabled,'allowChanges',req.changes_enabled,'allowRevisions',req.revisions_enabled,'canReview',public.smartpro_requirement_access(actor,(project->>'id')::uuid,req.requirement_key,acting_role,true),'case',public.smartpro_requirement_case(req.case_id)));
   END IF;
  END LOOP;
  project:=project||jsonb_build_object('canReview',public.smartpro_requirement_access(actor,(project->>'id')::uuid,'SYNOPSIS',acting_role,true));
  IF acting_role='Faculty' AND NOT public.smartpro_requirement_access(actor,(project->>'id')::uuid,'SYNOPSIS',acting_role,false) THEN project:=project||jsonb_build_object('case',NULL,'requirement',NULL,'canReview',false); END IF;
  projects:=projects||jsonb_build_array(project||jsonb_build_object('requirements',requirements));
 END LOOP;
 RETURN jsonb_set(w,'{projects}',projects);
END $$;

CREATE OR REPLACE FUNCTION public.smartpro_document_requirement_management(actor uuid,dept uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 PERFORM public.smartpro_department_setup_read(actor,dept);
 RETURN jsonb_build_object('requirements',(SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.configured_at DESC NULLS LAST),'[]') FROM (SELECT q.*,coalesce(q.document_name,'Synopsis') AS name,EXISTS(SELECT FROM public.submission_offering_requirements h WHERE h.policy_id=q.id) AS current FROM public.submission_requirement_policies q JOIN public.curriculum_offerings o ON o.id=q.offering_id WHERE o.department_id=dept ORDER BY q.configured_at DESC NULLS LAST,q.id LIMIT 200)x));
END $$;

-- Keep the established synopsis facade while routing explicit keys through the
-- very same transactional upload/submission/review implementation.
DO $$ DECLARE def text; sig text; BEGIN
 def:=pg_get_functiondef('public.smartpro_document_command(uuid,uuid,text,jsonb,text)'::regprocedure);
 def:=replace(def,'INSERT INTO public.submission_offering_requirements VALUES(oid,rid) ON CONFLICT(offering_id)','INSERT INTO public.submission_offering_requirements VALUES(oid,rid,''SYNOPSIS'') ON CONFLICT(offering_id,requirement_key)');
 def:=replace(def,'WHERE t.id=p.team_id;','WHERE t.id=p.team_id AND h.requirement_key=coalesce(input->>''requirementKey'',''SYNOPSIS'');');
 def:=replace(def,'requirement_key=''SYNOPSIS'' FOR UPDATE','requirement_key=coalesce(input->>''requirementKey'',''SYNOPSIS'') FOR UPDATE');
 def:=replace(def,'VALUES(p.id,''SYNOPSIS'',''SYNOPSIS'')','VALUES(p.id,rule.requirement_key,CASE WHEN rule.requirement_key=''SYNOPSIS'' THEN ''SYNOPSIS'' ELSE ''OTHER'' END)');
 def:=replace(def,'VALUES(p.id,''SYNOPSIS'',''Project synopsis'')','VALUES(p.id,CASE WHEN rule.requirement_key=''SYNOPSIS'' THEN ''SYNOPSIS'' ELSE ''OTHER'' END,coalesce(rule.document_name,''Project synopsis''))');
 def:=replace(def,'IF action=''PREPARE'' AND c.id IS NULL THEN',E'IF action=''PREPARE'' AND c.id IS NULL THEN\n   INSERT INTO public.faculty_assignments(project_id,faculty_user_id,assignment_type,requirement_key) SELECT p.id,x.value::uuid,''REVIEWER'',rule.requirement_key FROM jsonb_array_elements_text(coalesce(rule.reviewer_ids,''[]'')) x WHERE public.smartpro_has_role(x.value::text::uuid,dept,''FACULTY'',clock_timestamp()) AND NOT EXISTS(SELECT FROM public.faculty_assignments f WHERE f.project_id=p.id AND f.faculty_user_id=x.value::text::uuid AND f.requirement_key=rule.requirement_key AND f.assignment_type=''REVIEWER'' AND f.valid_from<=clock_timestamp() AND (f.valid_until IS NULL OR clock_timestamp()<f.valid_until));');
 def:=replace(def,'OR input->>''decision'' NOT IN (''REQUEST_CHANGES'',''APPROVE'')','OR input->>''decision'' NOT IN (''COMMENT'',''REQUEST_CHANGES'',''APPROVE'') OR (input->>''decision''=''REQUEST_CHANGES'' AND NOT rule.changes_enabled)');
 def:=replace(def,'UPDATE public.submission_attempts SET attempt_state=CASE WHEN input->>''decision''=''APPROVE''', 'IF input->>''decision''<>''COMMENT'' THEN UPDATE public.submission_attempts SET attempt_state=CASE WHEN input->>''decision''=''APPROVE''');
 def:=replace(def,'result:=jsonb_build_object(''status'',CASE WHEN input->>''decision''', 'END IF; IF input->>''decision''=''COMMENT'' THEN UPDATE public.submission_cases SET row_version=row_version+1 WHERE id=c.id; END IF; result:=jsonb_build_object(''status'',CASE WHEN input->>''decision''');
 def:=replace(def,'CASE WHEN input->>''decision''=''APPROVE'' THEN ''APPROVED'' ELSE ''CHANGES_REQUESTED'' END);','CASE WHEN input->>''decision''=''COMMENT'' THEN ''AWAITING_REVIEW'' WHEN input->>''decision''=''APPROVE'' THEN ''APPROVED'' ELSE ''CHANGES_REQUESTED'' END);');
 def:=replace(def,'IF action IN (''START_UPLOAD'',''COMPLETE_UPLOAD'',''SUBMIT'') AND c.state NOT IN', 'IF action IN (''START_UPLOAD'',''COMPLETE_UPLOAD'',''SUBMIT'') AND c.state=''CHANGES_REQUESTED'' AND NOT rule.revisions_enabled THEN RAISE EXCEPTION ''Revisions are not enabled by the pinned requirement'' USING ERRCODE=''23514''; END IF; IF action IN (''START_UPLOAD'',''COMPLETE_UPLOAD'',''SUBMIT'') AND c.state NOT IN');
 def:=replace(def,'IF action=''DECIDE'' THEN','IF action=''DECIDE'' THEN');
 def:=replace(def,'SELECT * INTO a FROM public.submission_attempts WHERE id=',E'IF NOT public.smartpro_requirement_access(actor,p.id,rule.requirement_key,''Faculty'',true) THEN RAISE EXCEPTION ''Assigned requirement reviewer required'' USING ERRCODE=''42501''; END IF; SELECT * INTO a FROM public.submission_attempts WHERE id=');
 EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_proposal_offering(uuid,uuid)'::regprocedure);
 def:=replace(def,'WHERE h.offering_id=offering;','WHERE h.offering_id=offering AND h.requirement_key=''SYNOPSIS'';');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_document_workspace(uuid,uuid)'::regprocedure);
 def:=replace(def,'WHERE offering_id=t.curriculum_offering_id)','WHERE offering_id=t.curriculum_offering_id AND requirement_key=''SYNOPSIS'')');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_role_file(uuid,uuid,text)'::regprocedure);
 def:=replace(def,' RETURN public.smartpro_document_file(actor,version_id);',E' IF NOT public.smartpro_requirement_access(actor,pid,(SELECT c.requirement_key FROM public.submission_cases c JOIN public.submission_requirement_bindings b ON b.case_id=c.id JOIN public.document_versions v ON v.document_id=b.document_id WHERE v.id=version_id),role,false) THEN RAISE EXCEPTION ''Assigned requirement document required'' USING ERRCODE=''42501''; END IF; RETURN public.smartpro_document_file(actor,version_id);');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_role_case_access(uuid,uuid,text)'::regprocedure);
 def:=replace(def,'FROM public.submission_cases c WHERE', 'FROM public.submission_cases c WHERE (NOT EXISTS(SELECT FROM public.submission_requirement_bindings b WHERE b.case_id=c.id) OR public.smartpro_requirement_access(actor,c.project_id,c.requirement_key,role,false)) AND');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_decision_authority()'::regprocedure);
 def:=replace(def,'AND assignment_type IN (''GUIDE'',''REVIEWER'') AND valid_from', 'AND assignment_type IN (''GUIDE'',''REVIEWER'') AND (NOT EXISTS(SELECT FROM public.submission_requirement_bindings b WHERE b.case_id=c.id) OR (assignment_type=''REVIEWER'' AND (requirement_key=c.requirement_key OR (requirement_key IS NULL AND c.requirement_key=''SYNOPSIS'')))) AND valid_from');EXECUTE def;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_requirement_access(uuid,uuid,text,text,boolean),public.smartpro_requirement_case(uuid),public.smartpro_configured_document_workspace(uuid,uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_configured_document_workspace(uuid,uuid,text) TO smartpro_runtime;
REVOKE ALL ON FUNCTION public.smartpro_document_requirement_management(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_document_requirement_management(uuid,uuid) TO smartpro_runtime;
REVOKE ALL ON FUNCTION public.smartpro_configure_requirement(uuid,uuid,text,jsonb,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_configure_requirement(uuid,uuid,text,jsonb,text) TO smartpro_runtime;
COMMIT;
