-- Read existing departmental records only. No synthetic defaults or activation.
BEGIN;
DO $$ BEGIN IF to_regprocedure('public.smartpro_document_disposition(uuid,uuid)') IS NULL OR to_regprocedure('public.smartpro_student_profile(uuid)') IS NULL THEN RAISE EXCEPTION 'Install reviewed 019-020 before application reads'; END IF; END $$;
CREATE OR REPLACE FUNCTION public.smartpro_application_workspace(actor uuid) RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE dept uuid; roles jsonb; administrator boolean:=false; faculty boolean:=false; student boolean:=false;
        person jsonb; catalog jsonb; reviews jsonb; projects jsonb; people jsonb; history jsonb;
BEGIN

  SELECT jsonb_build_object('id',u.id,'name',u.display_name) INTO person FROM public.users u WHERE u.id=actor AND u.account_status='ACTIVE';
  IF NOT FOUND THEN RAISE EXCEPTION 'active demo identity required' USING ERRCODE='42501'; END IF;
  SELECT r.department_id INTO dept FROM public.department_role_assignments r WHERE r.user_id=actor
    AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)
    AND (r.role_code<>'STUDENT' OR r.department_id=coalesce(
      (SELECT department_id FROM public.student_profiles WHERE user_id=actor)))
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
  SELECT jsonb_build_object('id',d.id,'code',d.code,'name',d.name,'offeringId',(SELECT id FROM public.curriculum_offerings WHERE department_id=dept ORDER BY id LIMIT 1),'registrationPolicyId',(SELECT r.policy_version_id FROM public.offering_project_registration_policies h JOIN public.project_registration_policy_versions r ON r.id=h.registration_policy_version_id WHERE h.offering_id=(SELECT id FROM public.curriculum_offerings WHERE department_id=dept ORDER BY id LIMIT 1) ORDER BY h.project_type LIMIT 1)) INTO catalog FROM public.departments d WHERE d.id=dept;
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
      JOIN public.review_definitions d ON d.id=r.review_definition_id
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
      WHERE p.department_id=dept) ELSE '[]'::jsonb END,
    'department',catalog,'enrolled',EXISTS(SELECT FROM public.student_profiles WHERE user_id=actor),
    'admission',NULL,
    'reviews',reviews,'assignedProjects',projects,'faculty',coalesce(people,'[]'),'audit',history);
END $$;
REVOKE ALL ON FUNCTION public.smartpro_application_workspace(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_application_workspace(uuid) TO smartpro_runtime;
CREATE OR REPLACE FUNCTION public.smartpro_student_projects_for_offering(p_actor_id uuid,offering_id uuid,after_id uuid DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE profile jsonb; page jsonb; next_cursor uuid;
BEGIN
  profile:=public.smartpro_student_profile(p_actor_id);
  WITH candidates AS (
    SELECT p.*,t.curriculum_offering_id,r.registration_policy_version_id FROM public.projects p
      JOIN public.teams t ON t.id=p.team_id JOIN public.curriculum_offerings o ON o.id=t.curriculum_offering_id
      LEFT JOIN public.student_project_registrations r ON r.project_id=p.id
    WHERE o.department_id=(profile->'department'->>'id')::uuid AND o.semester_key=profile->>'semester'
      AND EXISTS(SELECT FROM public.team_memberships m WHERE m.user_id=p_actor_id AND m.team_id=t.id
        AND m.joined_at<=statement_timestamp() AND (m.left_at IS NULL OR statement_timestamp()<m.left_at))
      AND t.curriculum_offering_id=smartpro_student_projects_for_offering.offering_id AND (after_id IS NULL OR p.id>after_id) ORDER BY p.id LIMIT 51
  ), numbered AS (SELECT *,row_number() OVER(ORDER BY id) AS position FROM candidates)
  SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'teamId',team_id,'offeringId',curriculum_offering_id,
    'cycleId',cycle_id,'projectType',project_type,'projectCode',project_code,'title',title,
    'policyVersionId',policy_version_id,'registrationPolicyVersionId',registration_policy_version_id,
    'createdAt',created_at) ORDER BY id) FILTER(WHERE position<=50),'[]'::jsonb),
    CASE WHEN count(*)>50 THEN (array_agg(id ORDER BY id) FILTER(WHERE position=50))[1] END
  INTO page,next_cursor FROM numbered;
  RETURN jsonb_build_object('results',page,'nextCursor',next_cursor);
END $$;

REVOKE ALL ON FUNCTION public.smartpro_student_projects_for_offering(uuid,uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_student_projects_for_offering(uuid,uuid,uuid) TO smartpro_runtime;
CREATE OR REPLACE FUNCTION public.smartpro_project_review_choices(actor uuid,dept uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 PERFORM public.smartpro_academic_authority(actor,dept);
 RETURN (SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM (
  SELECT p.id AS "projectId",v.id AS "schemeVersionId",m.id AS "schemeModeId",d.label,m.mode_code AS mode
  FROM public.projects p JOIN public.review_definitions d ON d.policy_version_id=p.policy_version_id
  JOIN public.evaluation_schemes e ON e.review_definition_id=d.id AND e.cycle_id=p.cycle_id
  JOIN public.scheme_versions v ON v.scheme_id=e.id AND v.state='ACTIVE'
  JOIN public.scheme_modes m ON m.scheme_version_id=v.id
  WHERE p.department_id=dept ORDER BY p.id,d.ordinal,v.version_no DESC LIMIT 100) x);
END $$;
REVOKE ALL ON FUNCTION public.smartpro_project_review_choices(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_project_review_choices(uuid,uuid) TO smartpro_runtime;
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
   AND c.starts_on<=current_date AND current_date<=c.ends_on AND w.visible_from<=now() AND now()<w.visible_until AND (after_id IS NULL OR o.id>after_id) ORDER BY o.id LIMIT 51
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
