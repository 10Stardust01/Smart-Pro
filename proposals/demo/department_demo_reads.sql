-- Demo-only discovery/intake bridge; never install into production.
BEGIN;
CREATE OR REPLACE FUNCTION public.smartpro_demo_guard() RETURNS void LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
  IF current_database() NOT LIKE 'smartpro_test_demo_%' OR to_regclass('public.demo_catalog') IS NULL THEN
    RAISE EXCEPTION 'isolated departmental demo required' USING ERRCODE='42501'; END IF;
END $$;
CREATE OR REPLACE FUNCTION public.smartpro_demo_enroll(actor uuid) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE admission public.demo_admissions%ROWTYPE; inserted uuid;
BEGIN
  PERFORM public.smartpro_demo_guard();
  SELECT a.* INTO admission FROM public.demo_admissions a JOIN public.users u ON u.id=a.user_id
    WHERE a.user_id=actor AND u.account_status='ACTIVE' FOR UPDATE OF a FOR SHARE OF u;
  IF NOT FOUND THEN RAISE EXCEPTION 'trusted synthetic admission required' USING ERRCODE='42501'; END IF;
  PERFORM 1 FROM public.department_role_assignments r WHERE r.user_id=actor AND r.department_id=admission.department_id AND r.role_code='STUDENT'
    AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until) FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'approved admission role required' USING ERRCODE='42501'; END IF;
  INSERT INTO public.student_profiles(user_id,usn,section,semester_key,department_id)
    VALUES(actor,admission.usn,admission.section,admission.semester,admission.department_id) ON CONFLICT(user_id) DO NOTHING RETURNING user_id INTO inserted;
  IF NOT EXISTS(SELECT FROM public.student_profiles WHERE user_id=actor AND department_id=admission.department_id AND usn=admission.usn
      AND semester_key=admission.semester AND section=admission.section) THEN
    RAISE EXCEPTION 'profile conflicts with trusted admission' USING ERRCODE='23514'; END IF;
  IF inserted IS NOT NULL THEN
    INSERT INTO public.audit_events(actor_id,action,target_type,target_id,metadata) VALUES(actor,'DEMO_ENROLLMENT_CONFIRMED','STUDENT_PROFILE',actor,
      jsonb_build_object('departmentId',admission.department_id,'source','SYNTHETIC_TRUSTED_ADMISSION'));
  END IF;
  RETURN public.smartpro_student_profile(actor);
END $$;
CREATE OR REPLACE FUNCTION public.smartpro_demo_workspace(actor uuid) RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE dept uuid; roles jsonb; administrator boolean:=false; faculty boolean:=false; student boolean:=false;
        person jsonb; catalog jsonb; reviews jsonb; projects jsonb; people jsonb; history jsonb;
BEGIN
  PERFORM public.smartpro_demo_guard();
  SELECT jsonb_build_object('id',u.id,'name',u.display_name) INTO person FROM public.users u WHERE u.id=actor AND u.account_status='ACTIVE';
  IF NOT FOUND THEN RAISE EXCEPTION 'active demo identity required' USING ERRCODE='42501'; END IF;
  SELECT r.department_id INTO dept FROM public.department_role_assignments r WHERE r.user_id=actor
    AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)
    AND (r.role_code<>'STUDENT' OR r.department_id=coalesce(
      (SELECT department_id FROM public.student_profiles WHERE user_id=actor),
      (SELECT department_id FROM public.demo_admissions WHERE user_id=actor)))
    ORDER BY CASE r.role_code WHEN 'HOD' THEN 0 WHEN 'COORDINATOR' THEN 1 WHEN 'STUDENT' THEN 2 WHEN 'FACULTY' THEN 3 ELSE 4 END,r.id LIMIT 1;
  SELECT coalesce(jsonb_agg(role_code),'[]') INTO roles FROM public.department_role_assignments WHERE user_id=actor AND department_id=dept
    AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until);
  student:=roles ? 'STUDENT'; faculty:=roles ? 'FACULTY';
  BEGIN PERFORM public.smartpro_academic_authority(actor,dept); administrator:=true;
  EXCEPTION WHEN insufficient_privilege THEN administrator:=false; END;
  administrator:=administrator AND EXISTS(SELECT FROM public.academic_governance_settings WHERE department_id=dept AND enabled);
  IF NOT administrator AND NOT student AND NOT faculty AND NOT roles ? 'ACADEMIC_ADMIN' THEN
    RETURN jsonb_build_object('actor',person,'roles',roles,'access',jsonb_build_object('student',false,'faculty',false,'admin',false),'reviews','[]'::jsonb,'audit','[]'::jsonb);
  END IF;
  SELECT jsonb_build_object('id',d.id,'code',d.code,'name',d.name,'offeringId',c.offering_id,'registrationPolicyId',c.policy_id,
      'schemeVersionId',c.scheme_id,'schemeModeId',c.mode_id) INTO catalog FROM public.demo_catalog c JOIN public.departments d ON d.id=c.department_id WHERE c.department_id=dept;
  SELECT coalesce(jsonb_agg(x.item ORDER BY x.event_time DESC),'[]') INTO reviews FROM (
    SELECT r.roster_locked_at AS event_time,jsonb_build_object('id',r.id,'projectId',p.id,'projectTitle',p.title,'projectCode',p.project_code,'label',d.label,
      'state',CASE WHEN EXISTS(SELECT FROM public.academic_result_versions WHERE review_id=r.id) THEN 'PUBLISHED' ELSE r.review_state END,
      'revision',b.revision,'policyId',b.policy_id,'rosterVersionId',rv.id,
      'roster',CASE WHEN administrator OR (faculty AND EXISTS(SELECT FROM public.evaluator_assignments WHERE review_id=r.id AND faculty_user_id=actor)) THEN (SELECT coalesce(jsonb_agg(jsonb_build_object('id',m.student_user_id,'name',u.display_name) ORDER BY u.display_name),'[]')
        FROM public.academic_roster_members m JOIN public.users u ON u.id=m.student_user_id WHERE m.roster_version_id=rv.id) ELSE '[]'::jsonb END,
      'criteria',CASE WHEN administrator OR (faculty AND EXISTS(SELECT FROM public.evaluator_assignments WHERE review_id=r.id AND faculty_user_id=actor)) THEN (SELECT jsonb_agg(jsonb_build_object('id',mc.id,'label',rc.label,'scope',mc.score_scope,'maximum',rc.maximum::text) ORDER BY rc.sort_order)
        FROM public.mode_criteria mc JOIN public.rubric_criteria rc ON rc.id=mc.criterion_id WHERE mc.scheme_mode_id=r.scheme_mode_id) ELSE '[]'::jsonb END,
      'assessments',CASE WHEN administrator OR faculty THEN (SELECT coalesce(jsonb_agg(jsonb_build_object('id',a.id,'version',a.row_version,'state',a.state,
        'facultyId',e.faculty_user_id,'facultyName',u.display_name,'scores',CASE WHEN e.faculty_user_id=actor THEN coalesce(
          (SELECT v.scores FROM public.academic_evaluation_versions v WHERE v.assessment_id=a.id ORDER BY version_no DESC LIMIT 1),public.smartpro_academic_base_scores(a.id)) ELSE '[]'::jsonb END)),'[]')
        FROM public.assessments a JOIN public.evaluator_assignments e ON e.id=a.evaluator_assignment_id JOIN public.users u ON u.id=e.faculty_user_id
        WHERE a.review_id=r.id AND (administrator OR e.faculty_user_id=actor)) ELSE '[]'::jsonb END) AS item
    FROM public.project_reviews r JOIN public.projects p ON p.id=r.project_id JOIN public.teams t ON t.id=p.team_id
      JOIN public.demo_catalog c ON c.offering_id=t.curriculum_offering_id JOIN public.review_definitions d ON d.id=r.review_definition_id
      LEFT JOIN public.academic_review_bindings b ON b.review_id=r.id
      LEFT JOIN LATERAL(SELECT id FROM public.academic_roster_versions WHERE review_id=r.id ORDER BY version_no DESC LIMIT 1) rv ON true
    WHERE p.department_id=dept AND EXISTS(SELECT FROM public.academic_governance_settings WHERE department_id=dept AND enabled)
      AND (administrator OR (faculty AND EXISTS(SELECT FROM public.evaluator_assignments WHERE review_id=r.id AND faculty_user_id=actor))
      OR (student AND EXISTS(SELECT FROM public.academic_roster_members m JOIN public.academic_roster_versions v ON v.id=m.roster_version_id WHERE v.review_id=r.id AND m.student_user_id=actor)))
    ORDER BY r.roster_locked_at DESC LIMIT 50
  ) x;
  SELECT coalesce(jsonb_agg(jsonb_build_object('id',p.id,'title',p.title,'projectCode',p.project_code,'teamId',p.team_id,'projectType',p.project_type)),'[]') INTO projects
    FROM public.projects p WHERE p.id IN (SELECT (r->>'projectId')::uuid FROM jsonb_array_elements(reviews) r);
  IF administrator THEN
    SELECT coalesce(jsonb_agg(jsonb_build_object('id',x.id,'name',x.display_name)),'[]') INTO people FROM
      (SELECT DISTINCT u.id,u.display_name FROM public.users u JOIN public.department_role_assignments r ON r.user_id=u.id
       WHERE r.department_id=dept AND r.role_code='FACULTY' AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)
         AND u.account_status='ACTIVE' ORDER BY u.display_name LIMIT 50) x;
  END IF;
  SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.occurred_at DESC),'[]') INTO history FROM (
    SELECT a.id,a.action,a.target_id,a.actor_id,a.occurred_at,a.metadata FROM public.audit_events a
    WHERE ((administrator AND (a.metadata->>'departmentId'=dept::text OR a.target_id IN (SELECT (r->>'id')::uuid FROM jsonb_array_elements(reviews) r)))
      OR (a.actor_id=actor AND NOT administrator AND
        (a.action NOT LIKE 'ACADEMIC_%' OR EXISTS(SELECT FROM public.academic_governance_settings WHERE department_id=dept AND enabled)))) ORDER BY a.occurred_at DESC LIMIT 25
  ) x;
  RETURN jsonb_build_object('actor',person,'roles',roles,'access',jsonb_build_object('student',student,'faculty',faculty,'admin',administrator,'operations',roles ? 'ACADEMIC_ADMIN'),
    'demoProjectIds',CASE WHEN administrator THEN (SELECT coalesce(jsonb_agg(p.id),'[]') FROM public.projects p JOIN public.teams t ON t.id=p.team_id
      JOIN public.demo_catalog c ON c.offering_id=t.curriculum_offering_id WHERE p.department_id=dept) ELSE '[]'::jsonb END,
    'department',catalog,'enrolled',EXISTS(SELECT FROM public.student_profiles WHERE user_id=actor),
    'admission',(SELECT jsonb_build_object('usn',a.usn,'section',a.section,'semester',a.semester) FROM public.demo_admissions a WHERE a.user_id=actor),
    'reviews',reviews,'assignedProjects',projects,'faculty',coalesce(people,'[]'),'audit',history);
END $$;
REVOKE ALL ON FUNCTION public.smartpro_demo_guard(),public.smartpro_demo_enroll(uuid),public.smartpro_demo_workspace(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_demo_enroll(uuid),public.smartpro_demo_workspace(uuid) TO smartpro_runtime;
COMMIT;
