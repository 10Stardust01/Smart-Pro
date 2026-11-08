-- Part of candidate 019, after its command schema.
BEGIN;
DO $$ BEGIN IF to_regprocedure('public.smartpro_document_command(uuid,uuid,text,jsonb,text)') IS NULL THEN
 RAISE EXCEPTION 'Install document workflow commands before reads'; END IF; END $$;
CREATE FUNCTION public.smartpro_document_workspace(actor uuid,dept uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE manager boolean:=false; hod boolean:=false; operational boolean:=false; projects jsonb; instructions jsonb; options jsonb:='{}';
BEGIN
 PERFORM 1 FROM public.users WHERE id=actor AND account_status='ACTIVE' FOR SHARE;
 IF NOT FOUND OR NOT EXISTS(SELECT FROM public.academic_governance_settings WHERE department_id=dept AND enabled)
  OR NOT EXISTS(SELECT FROM public.staff_department_controls WHERE department_id=dept AND enabled) THEN RAISE EXCEPTION 'active enabled department required' USING ERRCODE='42501'; END IF;
 BEGIN PERFORM public.smartpro_academic_authority(actor,dept); manager:=true;
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN PERFORM public.smartpro_academic_authority(actor,dept,true); hod:=true;
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 operational:=public.smartpro_has_role(actor,dept,'ACADEMIC_ADMIN',clock_timestamp());
 IF NOT manager AND NOT operational AND NOT public.smartpro_has_role(actor,dept,'STUDENT',clock_timestamp()) AND NOT public.smartpro_has_role(actor,dept,'FACULTY',clock_timestamp()) THEN
   RAISE EXCEPTION 'department role required' USING ERRCODE='42501'; END IF;
 SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.approved_at DESC),'[]') INTO instructions FROM (
  SELECT i.id,i.configuration,i.approved_at,i.reason,e.offering_id,e.configured_at FROM public.offering_operational_instructions i
   LEFT JOIN public.offering_instruction_executions e ON e.instruction_id=i.id
   JOIN public.academic_hod_mandates h ON h.id=i.hod_mandate_id AND h.enabled
   JOIN public.department_role_assignments hr ON hr.id=h.role_assignment_id
  WHERE i.department_id=dept AND hr.valid_from<=clock_timestamp() AND (hr.valid_until IS NULL OR clock_timestamp()<hr.valid_until)
   AND (manager OR i.admin_role_id IN(SELECT id FROM public.department_role_assignments WHERE user_id=actor AND role_code='ACADEMIC_ADMIN'
     AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until))) ORDER BY i.approved_at DESC LIMIT 50) x;
 IF manager THEN
  options:=jsonb_build_object(
   'types',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM (SELECT id,label FROM public.curriculum_types ORDER BY label LIMIT 50) x),
   'cycles',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM (SELECT id,code FROM public.academic_cycles WHERE department_id=dept ORDER BY starts_on DESC LIMIT 50) x),
   'projectPolicies',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM (SELECT id,project_type,version_no FROM public.project_policy_versions WHERE department_id=dept AND policy_status='APPROVED' AND policy_data->'studentRegistration'='{"enabled":true}'::jsonb ORDER BY version_no DESC LIMIT 50) x),
   'teamPolicies',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM (SELECT id,version_no,size_mode FROM public.team_membership_policy_versions WHERE department_id=dept ORDER BY version_no DESC LIMIT 50) x),
   'admins',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM (SELECT r.id,u.display_name FROM public.department_role_assignments r JOIN public.users u ON u.id=r.user_id WHERE r.department_id=dept AND r.role_code='ACADEMIC_ADMIN' AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until) AND u.account_status='ACTIVE' ORDER BY u.display_name LIMIT 50) x),
   'faculty',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM (SELECT DISTINCT u.id,u.display_name FROM public.department_role_assignments r JOIN public.users u ON u.id=r.user_id WHERE r.department_id=dept AND r.role_code='FACULTY' AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until) AND u.account_status='ACTIVE' ORDER BY u.display_name LIMIT 50) x));
 END IF;
 SELECT coalesce(jsonb_agg(x.item ORDER BY x.created_at DESC),'[]') INTO projects FROM (
  SELECT p.created_at,jsonb_build_object('id',p.id,'title',p.title,'projectCode',p.project_code,'offeringId',t.curriculum_offering_id,
   'canSubmit',public.smartpro_document_scope(actor,p.id,'student'),'canReview',public.smartpro_document_scope(actor,p.id,'reviewer'),
   'requirement',(SELECT jsonb_build_object('maxBytes',q.max_bytes,'opensAt',q.opens_at,'closesAt',q.closes_at,'facultyApprovalEnabled',q.faculty_approval_enabled) FROM public.submission_requirement_policies q
     WHERE q.id=coalesce((SELECT b.policy_id FROM public.submission_requirement_bindings b JOIN public.submission_cases c ON c.id=b.case_id WHERE c.project_id=p.id AND c.requirement_key='SYNOPSIS'),
       (SELECT policy_id FROM public.submission_offering_requirements WHERE offering_id=t.curriculum_offering_id))),
   'case',(SELECT jsonb_build_object('id',c.id,'state',c.state,'version',c.row_version,
    'versions',(SELECT coalesce(jsonb_agg(jsonb_build_object('id',v.id,'version',v.version_no,'createdAt',v.created_at,'uploadedBy',u.display_name,'bytes',f.size_bytes) ORDER BY v.version_no),'[]')
      FROM public.submission_requirement_bindings b JOIN public.document_versions v ON v.document_id=b.document_id JOIN public.file_assets f ON f.id=v.file_asset_id JOIN public.users u ON u.id=v.uploaded_by WHERE b.case_id=c.id),
    'attempts',(SELECT coalesce(jsonb_agg(jsonb_build_object('id',a.id,'number',a.attempt_no,'state',a.attempt_state,'submittedAt',a.submitted_at,
      'versionId',(SELECT document_version_id FROM public.submission_items WHERE attempt_id=a.id LIMIT 1),
      'feedback',(SELECT coalesce(jsonb_agg(jsonb_build_object('comment',d.comment,'decision',d.decision,'by',u.display_name,'at',d.decided_at) ORDER BY d.decided_at),'[]') FROM public.approval_decisions d JOIN public.users u ON u.id=d.reviewer_user_id WHERE d.attempt_id=a.id)) ORDER BY a.attempt_no),'[]') FROM public.submission_attempts a WHERE a.case_id=c.id))
     FROM public.submission_cases c JOIN public.submission_requirement_bindings b ON b.case_id=c.id WHERE c.project_id=p.id AND c.requirement_key='SYNOPSIS')) AS item
  FROM public.projects p JOIN public.teams t ON t.id=p.team_id WHERE p.department_id=dept AND public.smartpro_document_scope(actor,p.id,'read') ORDER BY p.created_at DESC LIMIT 50) x;
 RETURN jsonb_build_object('hod',hod,'manager',manager,'operationalAdmin',operational,'instructions',instructions,'options',options,'projects',projects);
END $$;
CREATE FUNCTION public.smartpro_document_file(actor uuid,version_id uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE v public.document_versions%ROWTYPE; f public.file_assets%ROWTYPE;
BEGIN
 SELECT * INTO v FROM public.document_versions WHERE id=version_id;
 IF NOT FOUND OR NOT EXISTS(SELECT FROM public.submission_requirement_bindings WHERE document_id=v.document_id)
   OR NOT public.smartpro_document_scope(actor,v.project_id,'read') THEN RAISE EXCEPTION 'authorized document required' USING ERRCODE='42501'; END IF;
 SELECT * INTO f FROM public.file_assets WHERE id=v.file_asset_id AND upload_status='READY' FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'ready file required' USING ERRCODE='23514'; END IF;
 INSERT INTO public.audit_events(actor_id,project_id,action,target_type,target_id,metadata)
  VALUES(actor,v.project_id,'DOCUMENT_ACCESSED','DOCUMENT_VERSION',v.id,jsonb_build_object('departmentId',(SELECT department_id FROM public.projects WHERE id=v.project_id)));
 RETURN jsonb_build_object('key',f.storage_key,'sha256',btrim(f.sha256),'bytes',f.size_bytes,'version',v.version_no);
END $$;
REVOKE ALL ON FUNCTION public.smartpro_document_workspace(uuid,uuid),public.smartpro_document_file(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_document_workspace(uuid,uuid),public.smartpro_document_file(uuid,uuid) TO smartpro_runtime;
-- Add current configured classifications to the existing eligible-offering API.
CREATE OR REPLACE FUNCTION public.smartpro_student_offerings(actor_id uuid, after_id uuid DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE profile jsonb; page jsonb; next_cursor uuid;
BEGIN
 profile:=public.smartpro_student_profile(actor_id);
 WITH eligible AS (
  SELECT o.id,o.semester_key,o.student_team_creation_enabled,c.id AS cycle_id,c.code AS cycle_code,t.code,t.label
  FROM public.curriculum_offerings o JOIN public.student_offering_windows w ON w.offering_id=o.id
   JOIN public.academic_cycles c ON c.id=o.cycle_id JOIN public.curriculum_types t ON t.id=o.curriculum_type_id
  WHERE o.department_id=(profile->'department'->>'id')::uuid AND o.semester_key=profile->>'semester'
   AND w.visible_from<=now() AND now()<w.visible_until AND (after_id IS NULL OR o.id>after_id) ORDER BY o.id LIMIT 51
 ), numbered AS (SELECT *,row_number() OVER(ORDER BY id) AS position FROM eligible)
 SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'semester',semester_key,'code',code,'label',label,
  'cycle',jsonb_build_object('id',cycle_id,'code',cycle_code),'studentTeamCreationEnabled',student_team_creation_enabled,
  'projectTypes',(SELECT coalesce(jsonb_agg(r.project_type ORDER BY r.project_type),'[]') FROM public.offering_project_registration_policies h
    JOIN public.project_registration_policy_versions r ON r.id=h.registration_policy_version_id
    JOIN public.project_policy_versions p ON p.id=r.policy_version_id WHERE h.offering_id=numbered.id
     AND r.opens_at<=now() AND now()<r.closes_at AND p.policy_status='APPROVED' AND p.policy_data->'studentRegistration'='{"enabled":true}'::jsonb)
  ) ORDER BY id) FILTER(WHERE position<=50),'[]'),
  CASE WHEN count(*)>50 THEN (array_agg(id ORDER BY id) FILTER(WHERE position=50))[1] END
 INTO page,next_cursor FROM numbered;
 RETURN jsonb_build_object('results',page,'nextCursor',next_cursor);
END $$;
COMMIT;
