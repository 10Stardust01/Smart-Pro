-- Owner-run after 021. Technical references are not institutional numbering rules.
BEGIN;
DO $$ BEGIN IF to_regprocedure('public.smartpro_application_workspace(uuid)') IS NULL THEN RAISE EXCEPTION 'Reviewed 021 required'; END IF; END $$;
CREATE OR REPLACE FUNCTION public.smartpro_proposal_offering(actor uuid,offering uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE profile jsonb; o public.curriculum_offerings%ROWTYPE; classes text[]; classification text; rule public.submission_requirement_policies%ROWTYPE;
BEGIN
 profile:=public.smartpro_student_profile(actor);
 IF NOT EXISTS(SELECT FROM public.academic_governance_settings WHERE department_id=(profile->'department'->>'id')::uuid AND enabled)
   OR NOT EXISTS(SELECT FROM public.staff_department_controls WHERE department_id=(profile->'department'->>'id')::uuid AND enabled) THEN RAISE EXCEPTION 'department proposal workflow disabled' USING ERRCODE='42501'; END IF;
 SELECT x.* INTO o FROM public.curriculum_offerings x JOIN public.academic_cycles c ON c.id=x.cycle_id
  JOIN public.student_offering_windows w ON w.offering_id=x.id
  WHERE x.id=offering AND x.department_id=(profile->'department'->>'id')::uuid AND x.semester_key=profile->>'semester'
   AND c.starts_on<=current_date AND current_date<=c.ends_on AND w.visible_from<=clock_timestamp() AND clock_timestamp()<w.visible_until FOR SHARE OF x,w,c;
 IF NOT FOUND THEN RAISE EXCEPTION 'eligible offering required' USING ERRCODE='42501'; END IF;
 SELECT array_agg(r.project_type ORDER BY r.project_type) INTO classes FROM public.offering_project_registration_policies h
  JOIN public.project_registration_policy_versions r ON r.id=h.registration_policy_version_id JOIN public.project_policy_versions p ON p.id=r.policy_version_id
  WHERE h.offering_id=offering AND r.opens_at<=clock_timestamp() AND clock_timestamp()<r.closes_at AND p.policy_status='APPROVED'
    AND p.policy_data->'studentRegistration'='{"enabled":true}'::jsonb;
 IF cardinality(classes)=1 THEN classification:=classes[1];
 ELSE
  SELECT p.project_type INTO classification FROM public.offering_instruction_executions e
   JOIN public.offering_operational_instructions i ON i.id=e.instruction_id JOIN public.project_policy_versions p ON p.id=(i.configuration->>'projectPolicyId')::uuid
   WHERE e.offering_id=offering AND p.project_type=ANY(classes) ORDER BY e.configured_at DESC LIMIT 1;
 END IF;
 IF classification IS NULL THEN RAISE EXCEPTION 'offering project class is not configured' USING ERRCODE='23514'; END IF;
 SELECT q.* INTO rule FROM public.submission_offering_requirements h JOIN public.submission_requirement_policies q ON q.id=h.policy_id WHERE h.offering_id=offering;
 IF rule.id IS NULL AND NOT EXISTS(SELECT FROM public.offering_document_dispositions WHERE offering_id=offering AND disposition='NOT_REQUIRED') THEN
  RETURN jsonb_build_object('classification',classification,'submissionState','NOT_CONFIGURED','requiresSynopsis',NULL); END IF;
 RETURN jsonb_build_object('classification',classification,'requiresSynopsis',rule.id IS NOT NULL,'maxBytes',rule.max_bytes,
  'opensAt',rule.opens_at,'closesAt',rule.closes_at,'submissionState',CASE WHEN rule.id IS NULL THEN 'NOT_REQUIRED'
    WHEN clock_timestamp()<rule.opens_at THEN 'NOT_YET_OPEN' WHEN clock_timestamp()>=rule.closes_at THEN 'CLOSED' ELSE 'OPEN' END);
END $$;
CREATE OR REPLACE FUNCTION public.smartpro_register_proposal(actor uuid,offering uuid,confirmed_team uuid,title text,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE config jsonb; member public.team_memberships%ROWTYPE; reference text; digest text; previous public.student_project_registrations%ROWTYPE; result jsonb;
BEGIN
 UPDATE public.student_profiles SET membership_scope_revision=gen_random_uuid() WHERE user_id=actor;
 IF NOT FOUND THEN RAISE EXCEPTION 'trusted student record required' USING ERRCODE='42501'; END IF;
 IF NOT EXISTS(SELECT FROM public.student_profiles s JOIN public.academic_governance_settings g ON g.department_id=s.department_id
   JOIN public.staff_department_controls c ON c.department_id=s.department_id WHERE s.user_id=actor AND g.enabled AND c.enabled) THEN RAISE EXCEPTION 'department proposal workflow disabled' USING ERRCODE='42501'; END IF;
 reference:='P-'||encode(sha256(convert_to(actor::text||':proposal:'||key,'UTF8')),'hex');
 digest:=encode(sha256(convert_to(jsonb_build_object('offering',offering,'team',confirmed_team,'title',btrim(title))::text,'UTF8')),'hex');
 SELECT * INTO previous FROM public.student_project_registrations WHERE actor_id=actor AND request_key=key;
 IF FOUND THEN
  IF previous.offering_id<>offering OR previous.team_id<>confirmed_team THEN RAISE EXCEPTION 'retry context changed' USING ERRCODE='23514'; END IF;
  RETURN public.smartpro_register_student_project(actor,confirmed_team,previous.response_body->>'projectType',reference,btrim(title),key,digest);
 END IF;
 config:=public.smartpro_proposal_offering(actor,offering);
 IF config->>'submissionState' NOT IN ('OPEN','NOT_REQUIRED') THEN RAISE EXCEPTION 'offering not accepting proposals' USING ERRCODE='23514'; END IF;
 SELECT * INTO member FROM public.team_memberships WHERE user_id=actor AND curriculum_offering_id=offering
  AND joined_at<=clock_timestamp() AND (left_at IS NULL OR clock_timestamp()<left_at) ORDER BY id LIMIT 1;
 IF NOT FOUND OR member.team_id<>confirmed_team THEN RAISE EXCEPTION 'confirm current team' USING ERRCODE='42501'; END IF;
 reference:='P-'||encode(sha256(convert_to(actor::text||':proposal:'||key,'UTF8')),'hex');
 digest:=encode(sha256(convert_to(jsonb_build_object('offering',offering,'team',confirmed_team,'title',btrim(title))::text,'UTF8')),'hex');
 result:=public.smartpro_register_student_project(actor,member.team_id,config->>'classification',reference,btrim(title),key,digest);
 INSERT INTO public.audit_events(actor_id,project_id,action,target_type,target_id,metadata)
  VALUES(actor,(result->'project'->>'id')::uuid,'PROJECT_PROPOSAL_CREATED','PROJECT',(result->'project'->>'id')::uuid,jsonb_build_object('offeringId',offering,'referenceManaged',true));
 RETURN result;
END $$;
CREATE OR REPLACE FUNCTION public.smartpro_role_choices(actor uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE w jsonb; choices jsonb:='[]'; dept uuid; authority jsonb;
BEGIN
 w:=public.smartpro_application_workspace(actor);dept:=(w->'department'->>'id')::uuid;
 IF w->'roles' ? 'STUDENT' OR EXISTS(SELECT FROM public.department_role_assignments r JOIN public.users u ON u.id=r.user_id WHERE r.user_id=actor AND r.role_code='STUDENT' AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until) AND u.account_status='ACTIVE') THEN choices:=choices||'"Student"'::jsonb; END IF;
 IF w->'roles' ? 'FACULTY' THEN choices:=choices||'"Faculty"'::jsonb; END IF;
 IF w->'roles' ? 'ACADEMIC_ADMIN' THEN choices:=choices||'"Admin"'::jsonb; END IF;
 BEGIN authority:=public.smartpro_academic_authority(actor,dept,true);choices:=choices||'"HOD"'::jsonb; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 IF EXISTS(SELECT FROM public.academic_coordinator_mandates m JOIN public.department_role_assignments r ON r.id=m.role_assignment_id
   JOIN public.academic_hod_mandates h ON h.id=m.hod_mandate_id
   JOIN public.department_role_assignments hr ON hr.id=h.role_assignment_id JOIN public.users hu ON hu.id=h.user_id
   WHERE m.user_id=actor AND m.department_id=dept AND NOT m.revoked AND h.enabled AND hu.account_status='ACTIVE'
    AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)
    AND hr.valid_from<=clock_timestamp() AND (hr.valid_until IS NULL OR clock_timestamp()<hr.valid_until)) THEN choices:=choices||'"Coordinator"'::jsonb; END IF;
 RETURN choices;
END $$;
CREATE OR REPLACE FUNCTION public.smartpro_role_workspace(actor uuid,chosen text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE w jsonb; choices jsonb; reviews jsonb; scoped jsonb;
BEGIN
 choices:=public.smartpro_role_choices(actor);w:=public.smartpro_application_workspace(actor);
 IF w->'department' IS NULL AND choices ? 'Student' AND current_database() LIKE 'smartpro_test_demo_%' AND to_regprocedure('public.smartpro_demo_workspace(uuid)') IS NOT NULL THEN w:=public.smartpro_demo_workspace(actor); END IF;
 IF chosen IS NULL AND jsonb_array_length(choices)=1 THEN chosen:=choices->>0; END IF;
 IF chosen IS NULL AND jsonb_array_length(choices)>1 THEN RETURN jsonb_build_object('actor',w->'actor','roleChoices',choices,'chooseRole',true); END IF;
 IF chosen IS NOT NULL AND NOT choices ? chosen THEN RAISE EXCEPTION 'effective role required' USING ERRCODE='42501'; END IF;
 w:=w||jsonb_build_object('roleChoices',choices,'activeRole',chosen);
 SELECT coalesce(jsonb_agg(r||jsonb_build_object('rowVersion',pr.row_version,'scheduledAt',pr.scheduled_at)),'[]') INTO scoped FROM jsonb_array_elements(w->'reviews') r JOIN public.project_reviews pr ON pr.id=(r->>'id')::uuid;
 w:=jsonb_set(w,'{reviews}',scoped);
 w:=jsonb_set(w,'{access}',jsonb_build_object('student',chosen='Student','faculty',chosen='Faculty','admin',chosen IN ('HOD','Coordinator'),'operations',chosen='Admin'));
 IF chosen IN ('Student','Faculty','Admin') THEN
  SELECT coalesce(jsonb_agg(r),'[]') INTO reviews FROM jsonb_array_elements(w->'reviews') r WHERE
   (chosen='Student' AND EXISTS(SELECT FROM public.academic_roster_members m JOIN public.academic_roster_versions v ON v.id=m.roster_version_id WHERE v.review_id=(r->>'id')::uuid AND m.student_user_id=actor))
   OR (chosen='Faculty' AND EXISTS(SELECT FROM public.evaluator_assignments e WHERE e.review_id=(r->>'id')::uuid AND e.faculty_user_id=actor));
  IF chosen='Student' THEN
   SELECT coalesce(jsonb_agg(r||jsonb_build_object('roster','[]'::jsonb,'criteria','[]'::jsonb,'assessments','[]'::jsonb)),'[]') INTO reviews FROM jsonb_array_elements(reviews) r;
  ELSIF chosen='Faculty' THEN
   SELECT coalesce(jsonb_agg(jsonb_set(r,'{assessments}',(SELECT coalesce(jsonb_agg(a),'[]') FROM jsonb_array_elements(r->'assessments') a WHERE a->>'facultyId'=actor::text))),'[]') INTO reviews FROM jsonb_array_elements(reviews) r;
  END IF;
  w:=jsonb_set(w,'{reviews}',reviews);w:=jsonb_set(w,'{faculty}','[]');
  SELECT coalesce(jsonb_agg(p),'[]') INTO scoped FROM jsonb_array_elements(w->'assignedProjects') p WHERE EXISTS(SELECT FROM jsonb_array_elements(reviews) r WHERE r->>'projectId'=p->>'id');
  w:=jsonb_set(w,'{assignedProjects}',scoped);
  SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.occurred_at DESC),'[]') INTO scoped FROM (
   SELECT a.id,a.action,a.target_id,a.actor_id,a.occurred_at,a.metadata FROM public.audit_events a
   WHERE a.actor_id=actor AND (
    (chosen='Student' AND (a.action LIKE 'PROJECT_%' OR a.action LIKE 'MEMBERSHIP_%' OR a.action IN ('DOCUMENT_PREPARE','DOCUMENT_START_UPLOAD','DOCUMENT_COMPLETE_UPLOAD','DOCUMENT_SUBMIT')) AND public.smartpro_document_scope(actor,a.project_id,'student'))
    OR (chosen='Faculty' AND a.action IN ('ACADEMIC_SAVE_DRAFT','ACADEMIC_FINALIZE_DRAFT','ACADEMIC_EVALUATE','DOCUMENT_DECIDE','DOCUMENT_ACCESSED') AND
      (EXISTS(SELECT FROM jsonb_array_elements(reviews) r WHERE r->>'projectId'=a.project_id::text) OR public.smartpro_document_scope(actor,a.project_id,'reviewer')))
    OR (chosen='Admin' AND (a.action LIKE 'DEPARTMENT_SETUP_%' OR a.action='DOCUMENT_CONFIGURE') AND a.metadata->>'departmentId'=w->'department'->>'id'))
   ORDER BY a.occurred_at DESC LIMIT 25) x;
  w:=jsonb_set(w,'{audit}',scoped);
 END IF;
 IF chosen IN ('HOD','Coordinator') THEN
  SELECT coalesce(jsonb_agg(f||jsonb_build_object('alsoStudent',public.smartpro_has_role((f->>'id')::uuid,(w->'department'->>'id')::uuid,'STUDENT',clock_timestamp()))),'[]') INTO scoped FROM jsonb_array_elements(w->'faculty') f;
  w:=jsonb_set(w,'{faculty}',scoped);
 END IF;
 RETURN w;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_proposal_offering(uuid,uuid),public.smartpro_register_proposal(uuid,uuid,uuid,text,text),public.smartpro_role_choices(uuid),public.smartpro_role_workspace(uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_proposal_offering(uuid,uuid),public.smartpro_register_proposal(uuid,uuid,uuid,text,text),public.smartpro_role_choices(uuid),public.smartpro_role_workspace(uuid,text) TO smartpro_runtime;
CREATE OR REPLACE FUNCTION public.smartpro_role_documents(actor uuid,dept uuid,role text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE w jsonb; projects jsonb; instructions jsonb; person jsonb;
BEGIN
 IF NOT public.smartpro_role_choices(actor) ? role THEN RAISE EXCEPTION 'effective role required' USING ERRCODE='42501'; END IF;
 w:=public.smartpro_document_disposition(actor,dept);
 IF role IN ('Student','Faculty','Admin') THEN
  SELECT coalesce(jsonb_agg(p),'[]') INTO projects FROM jsonb_array_elements(w->'projects') p
   WHERE (role='Student' AND (p->>'canSubmit')::boolean) OR (role='Faculty' AND (p->>'canReview')::boolean);
  w:=jsonb_set(w,'{projects}',projects);
 END IF;
 IF role='Admin' THEN
  SELECT coalesce(jsonb_agg(i),'[]') INTO instructions FROM jsonb_array_elements(w->'instructions') i WHERE EXISTS(
   SELECT FROM public.department_role_assignments r WHERE r.id=(i->'configuration'->>'adminRoleId')::uuid AND r.user_id=actor AND r.role_code='ACADEMIC_ADMIN'
   AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until));
  w:=jsonb_set(w,'{instructions}',instructions);
 ELSIF role IN ('Student','Faculty') THEN w:=jsonb_set(w,'{instructions}','[]');w:=jsonb_set(w,'{options}','{}'); END IF;
 IF role IN ('HOD','Coordinator') THEN
  w:=jsonb_set(w,'{options,projectPolicies}',(SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'project_type',project_type,'version_no',version_no,'label',coalesce(policy_data->>'label','Approved '||lower(project_type)||' project policy')) ORDER BY version_no DESC),'[]') FROM public.project_policy_versions WHERE department_id=dept AND policy_status='APPROVED' AND policy_data->'studentRegistration'='{"enabled":true}'::jsonb));
  w:=jsonb_set(w,'{options,teamPolicies}',(SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'version_no',version_no,'size_mode',size_mode,'label',coalesce(to_jsonb(team_membership_policy_versions)->>'label','Approved team formation policy'),'minimum',minimum_members,'maximum',maximum_members) ORDER BY version_no DESC),'[]') FROM public.team_membership_policy_versions WHERE department_id=dept));
 END IF;
 SELECT coalesce(jsonb_agg(i||jsonb_build_object('offeringLabel',(SELECT label FROM public.curriculum_types WHERE id=(i->'configuration'->>'curriculumTypeId')::uuid),
  'cycleLabel',(SELECT code FROM public.academic_cycles WHERE id=(i->'configuration'->>'cycleId')::uuid))),'[]') INTO instructions FROM jsonb_array_elements(w->'instructions') i;
 w:=jsonb_set(w,'{instructions}',instructions);
 SELECT coalesce(jsonb_agg(p||jsonb_build_object('managedProposal',EXISTS(SELECT FROM public.audit_events WHERE project_id=(p->>'id')::uuid AND action='PROJECT_PROPOSAL_CREATED'),
   'guide',(SELECT jsonb_build_object('id',f.id,'facultyId',f.faculty_user_id,'name',u.display_name,'since',f.valid_from) FROM public.faculty_assignments f JOIN public.users u ON u.id=f.faculty_user_id JOIN public.projects pr ON pr.id=f.project_id
    WHERE f.project_id=(p->>'id')::uuid AND f.assignment_type='GUIDE' AND f.valid_from<=clock_timestamp() AND (f.valid_until IS NULL OR clock_timestamp()<f.valid_until)
      AND public.smartpro_has_role(f.faculty_user_id,pr.department_id,'FACULTY',clock_timestamp()) ORDER BY f.valid_from DESC LIMIT 1))),'[]') INTO projects FROM jsonb_array_elements(w->'projects') p;
 w:=jsonb_set(w,'{projects}',projects);
 w:=w||jsonb_build_object('hod',role='HOD','manager',role IN ('HOD','Coordinator'),'operationalAdmin',role='Admin');
 RETURN w;
END $$;
CREATE OR REPLACE FUNCTION public.smartpro_role_file(actor uuid,version_id uuid,role text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE pid uuid;
BEGIN
 IF NOT public.smartpro_role_choices(actor) ? role OR role='Admin' THEN RAISE EXCEPTION 'academic document responsibility required' USING ERRCODE='42501'; END IF;
 SELECT project_id INTO pid FROM public.document_versions WHERE id=version_id;
 IF pid IS NULL OR NOT public.smartpro_document_scope(actor,pid,CASE role WHEN 'Student' THEN 'student' WHEN 'Faculty' THEN 'reviewer' ELSE 'read' END) THEN RAISE EXCEPTION 'assigned document required' USING ERRCODE='42501'; END IF;
 RETURN public.smartpro_document_file(actor,version_id);
END $$;
CREATE OR REPLACE FUNCTION public.smartpro_role_review_access(actor uuid,review uuid,role text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT CASE role WHEN 'Student' THEN EXISTS(SELECT FROM public.academic_roster_members m JOIN public.academic_roster_versions v ON v.id=m.roster_version_id WHERE v.review_id=review AND m.student_user_id=actor)
 WHEN 'Faculty' THEN EXISTS(SELECT FROM public.evaluator_assignments WHERE review_id=review AND faculty_user_id=actor) ELSE false END
$$;
CREATE OR REPLACE FUNCTION public.smartpro_role_case_access(actor uuid,case_id uuid,role text) RETURNS boolean
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT public.smartpro_role_choices(actor) ? role AND role IN ('Student','Faculty','Coordinator','HOD')
   AND public.smartpro_document_scope(actor,c.project_id,CASE role WHEN 'Student' THEN 'student' WHEN 'Faculty' THEN 'reviewer' ELSE 'read' END)
 FROM public.submission_cases c WHERE c.id=case_id
$$;
REVOKE ALL ON FUNCTION public.smartpro_role_case_access(uuid,uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_role_case_access(uuid,uuid,text) TO smartpro_runtime;
REVOKE ALL ON FUNCTION public.smartpro_role_documents(uuid,uuid,text),public.smartpro_role_file(uuid,uuid,text),public.smartpro_role_review_access(uuid,uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_role_documents(uuid,uuid,text),public.smartpro_role_file(uuid,uuid,text),public.smartpro_role_review_access(uuid,uuid,text) TO smartpro_runtime;
CREATE OR REPLACE FUNCTION public.smartpro_demo_persona_labels(ids uuid[]) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF current_database() NOT LIKE 'smartpro_test_demo_%' OR cardinality(ids)>100 THEN RAISE EXCEPTION 'explicit synthetic environment required' USING ERRCODE='42501'; END IF;
 RETURN (SELECT coalesce(jsonb_object_agg(id::text,display_name),'{}') FROM public.users WHERE id=ANY(ids));
END $$;
REVOKE ALL ON FUNCTION public.smartpro_demo_persona_labels(uuid[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_demo_persona_labels(uuid[]) TO smartpro_runtime;
COMMIT;
