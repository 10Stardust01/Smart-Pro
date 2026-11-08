-- Offering discovery and Coordinator version history for the existing department workspace.
BEGIN;
CREATE FUNCTION public.smartpro_department_offering_page(
  actor uuid,dept uuid,acting_role text,query_text text,availability_filter text,
  page_number integer,selected uuid,appointment_page integer
) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF acting_role='Admin' THEN
    PERFORM public.smartpro_department_intake_code(actor,dept);
  ELSIF acting_role='HOD' THEN
    PERFORM public.smartpro_academic_authority(actor,dept,true);
  ELSE
    RAISE EXCEPTION 'Department management responsibility required' USING ERRCODE='42501';
  END IF;
  IF query_text IS NULL OR length(query_text)>120
    OR availability_filter IS NULL OR availability_filter NOT IN ('ALL','ACTIVE','PAUSED','ARCHIVED')
    OR page_number IS NULL OR page_number NOT BETWEEN 1 AND 99999999
    OR appointment_page IS NULL OR appointment_page NOT BETWEEN 1 AND 99999999 THEN
    RAISE EXCEPTION 'Invalid offering filters' USING ERRCODE='22023';
  END IF;
  RETURN (
    WITH scoped AS (
      SELECT o.*,t.label,c.code AS cycle_label,w.visible_from,w.visible_until
      FROM public.curriculum_offerings o JOIN public.curriculum_types t ON t.id=o.curriculum_type_id
      JOIN public.academic_cycles c ON c.id=o.cycle_id
      LEFT JOIN public.student_offering_windows w ON w.offering_id=o.id
      WHERE o.department_id=dept
    ), matching AS (
      SELECT * FROM scoped WHERE (availability_filter='ALL' OR availability=availability_filter)
        AND (query_text='' OR strpos(lower(label),lower(query_text))>0
          OR strpos(lower(cycle_label),lower(query_text))>0
          OR strpos(lower(semester_key),lower(query_text))>0)
    ), paged AS (
      SELECT * FROM matching ORDER BY lower(label),id LIMIT 25 OFFSET (page_number::bigint-1)*25
    ), visible AS (
      SELECT * FROM paged
      UNION ALL SELECT * FROM scoped WHERE id=selected AND NOT EXISTS(SELECT FROM paged WHERE id=selected)
    ), annotated AS (
      SELECT v.*, EXISTS(SELECT FROM public.smartpro_course_coordinators(v.id)) AS has_coordinator,
        '[]'::jsonb AS responsibilities,
        (SELECT count(*) FROM public.smartpro_course_coordinators(v.id)) AS effective_count,
        (SELECT count(*) FROM public.teams WHERE curriculum_offering_id=v.id) AS team_count,
        CASE WHEN acting_role='Admin' THEN
          (SELECT i.configuration FROM public.offering_instruction_executions e
           JOIN public.offering_operational_instructions i ON i.id=e.instruction_id
           WHERE e.offering_id=v.id ORDER BY e.configured_at DESC LIMIT 1) END AS configuration,
        CASE WHEN acting_role='Admin' THEN
          (SELECT coalesce(jsonb_agg(to_jsonb(h) ORDER BY h.revision DESC),'[]') FROM public.offering_management_history h WHERE h.offering_id=v.id)
          ELSE '[]'::jsonb END AS history
      FROM visible v
    ), versions AS (
      SELECT a.*,u.display_name AS name,actor_user.display_name AS actor_name,
        NOT EXISTS(SELECT FROM public.course_coordinator_versions newer
          WHERE newer.offering_id=a.offering_id AND newer.user_id=a.user_id AND newer.version>a.version) AS latest,
        a.id IN(SELECT id FROM public.smartpro_course_coordinators(a.offering_id)) AS current
      FROM public.course_coordinator_versions a JOIN public.users u ON u.id=a.user_id
      JOIN public.users actor_user ON actor_user.id=a.actor_id
      WHERE a.offering_id=selected AND EXISTS(SELECT FROM scoped WHERE id=selected)
      ORDER BY a.created_at DESC,a.id DESC LIMIT 25 OFFSET (appointment_page::bigint-1)*25
    )
    SELECT jsonb_build_object(
      'page',page_number,'total',(SELECT count(*) FROM matching),
      'appointmentPage',appointment_page,'appointmentTotal',(SELECT count(*) FROM public.course_coordinator_versions
        WHERE offering_id=selected AND EXISTS(SELECT FROM scoped WHERE id=selected)),
      'offerings',(SELECT coalesce(jsonb_agg(to_jsonb(a)||jsonb_build_object(
        'appointments',CASE WHEN a.id=selected THEN (SELECT coalesce(jsonb_agg(to_jsonb(v) ORDER BY v.created_at DESC,v.id DESC),'[]') FROM versions v)
          ELSE '[]'::jsonb END) ORDER BY lower(a.label),a.id),'[]') FROM annotated a),
      'faculty',CASE WHEN acting_role='Admin' AND selected IS NOT NULL THEN
        (SELECT coalesce(jsonb_agg(to_jsonb(f) ORDER BY f.display_name,f.id),'[]') FROM (
          SELECT DISTINCT u.id,u.display_name FROM public.users u JOIN public.department_role_assignments r ON r.user_id=u.id
          WHERE r.department_id=dept AND r.role_code='FACULTY' AND u.account_status='ACTIVE'
            AND r.valid_from<=statement_timestamp() AND (r.valid_until IS NULL OR statement_timestamp()<r.valid_until)
          ORDER BY u.display_name,u.id LIMIT 200
        ) f) ELSE '[]'::jsonb END,
      'semesters',(SELECT coalesce(jsonb_agg(s ORDER BY s),'[]') FROM
        (SELECT DISTINCT semester_key s FROM public.student_profiles WHERE department_id=dept
         UNION SELECT DISTINCT semester_key FROM scoped) semesters)
    )
  );
END $$;
REVOKE ALL ON FUNCTION public.smartpro_department_offering_page(uuid,uuid,text,text,text,integer,uuid,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_department_offering_page(uuid,uuid,text,text,text,integer,uuid,integer) TO smartpro_runtime;
COMMIT;
