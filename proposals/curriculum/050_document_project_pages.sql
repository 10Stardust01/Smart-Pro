-- Bounded project discovery and selected academic evidence, after 049.
BEGIN;

CREATE FUNCTION public.smartpro_document_project_page(actor uuid, dept uuid, role text, query text, page integer, offering uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE result jsonb;
BEGIN
 IF role IS NULL OR role NOT IN ('Student','Faculty','Coordinator','HOD')
   OR NOT public.smartpro_role_choices(actor) ? role
   OR NOT EXISTS(SELECT FROM public.academic_governance_settings WHERE department_id=dept AND enabled)
   OR NOT EXISTS(SELECT FROM public.staff_department_controls WHERE department_id=dept AND enabled) THEN
   RAISE EXCEPTION 'Effective document responsibility required' USING ERRCODE='42501';
 END IF;
 IF query IS NULL OR length(query)>120 OR page IS NULL OR page<1 THEN
   RAISE EXCEPTION 'Invalid document page' USING ERRCODE='22023';
 END IF;
 WITH assigned AS MATERIALIZED (
   SELECT f.project_id FROM public.faculty_assignments f WHERE role='Faculty' AND f.faculty_user_id=actor
     AND f.assignment_type IN ('GUIDE','REVIEWER')
   UNION
   SELECT r.project_id FROM public.evaluator_assignments e JOIN public.project_reviews r ON r.id=e.review_id
     WHERE role='Faculty' AND e.faculty_user_id=actor
 ), eligible_offerings AS MATERIALIZED (
   SELECT o.id,o.cycle_id FROM public.curriculum_offerings o WHERE o.department_id=dept AND (offering IS NULL OR o.id=offering)
     AND CASE
       WHEN role IN ('Coordinator','HOD') THEN public.smartpro_course_access(actor,o.id,'READ',role)
       WHEN role='Student' THEN public.smartpro_has_role(actor,dept,'STUDENT',statement_timestamp())
         AND EXISTS(SELECT FROM public.student_profiles s JOIN public.academic_cycles c ON c.id=o.cycle_id
           WHERE s.user_id=actor AND s.department_id=dept AND s.semester_key=o.semester_key
             AND current_date BETWEEN c.starts_on AND c.ends_on)
       ELSE true END
 ), candidates AS MATERIALIZED (
   SELECT p.id,p.title,t.name AS team,t.curriculum_offering_id AS "offeringId"
   FROM public.projects p JOIN public.teams t ON t.id=p.team_id
   JOIN eligible_offerings o ON o.id=t.curriculum_offering_id
   WHERE p.department_id=dept AND (query='' OR strpos(lower(p.title),lower(query))>0 OR strpos(lower(t.name),lower(query))>0)
     AND CASE role
       WHEN 'Student' THEN EXISTS(SELECT FROM public.team_memberships m WHERE m.team_id=t.id AND m.user_id=actor AND m.joined_at<=statement_timestamp()
         AND (m.left_at IS NULL OR statement_timestamp()<m.left_at) AND p.cycle_id=o.cycle_id)
       WHEN 'Faculty' THEN EXISTS(SELECT FROM assigned a WHERE a.project_id=p.id)
       ELSE true END
 ), matches AS MATERIALIZED (
   SELECT * FROM candidates WHERE CASE role
     WHEN 'Faculty' THEN public.smartpro_document_scope(actor,id,'faculty_read')
     ELSE true END
 ), bounds AS (
   SELECT count(*) AS total,least(page,greatest(1,(count(*)+24)/25))::integer AS current_page FROM matches
 )
 SELECT jsonb_build_object('total',total,'page',current_page,'pageSize',25,'projects',coalesce((
   SELECT jsonb_agg(to_jsonb(x) ORDER BY x.title,x.id) FROM (
     SELECT m.*,c.state AS "submissionStatus",g.display_name AS guide
     FROM (SELECT * FROM matches ORDER BY title,id LIMIT 25 OFFSET ((bounds.current_page-1)::bigint*25)) m
     LEFT JOIN public.submission_cases c ON c.project_id=m.id AND c.requirement_key='SYNOPSIS'
     LEFT JOIN LATERAL (SELECT u.display_name FROM public.faculty_assignments f JOIN public.users u ON u.id=f.faculty_user_id
       WHERE f.project_id=m.id AND f.assignment_type='GUIDE' AND f.valid_from<=clock_timestamp()
         AND (f.valid_until IS NULL OR clock_timestamp()<f.valid_until)
       ORDER BY f.valid_from DESC,f.id LIMIT 1) g ON true
   ) x),'[]')) INTO result FROM bounds;
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION public.smartpro_course_project_documents(actor uuid,dept uuid,pid uuid,role text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE scope text:=current_setting('smartpro.document_project',true); result jsonb;
BEGIN
 IF role IS NULL OR NOT public.smartpro_role_choices(actor) ? role
   OR NOT EXISTS(SELECT FROM public.projects p WHERE p.id=pid AND p.department_id=dept)
   OR NOT (CASE role
      WHEN 'Student' THEN public.smartpro_document_scope(actor,pid,'student')
      WHEN 'Faculty' THEN public.smartpro_document_scope(actor,pid,'faculty_read')
      WHEN 'Coordinator' THEN public.smartpro_course_access(actor,public.smartpro_course_project_offering(pid),'READ',role)
      WHEN 'HOD' THEN public.smartpro_course_access(actor,public.smartpro_course_project_offering(pid),'READ',role)
      ELSE false END) THEN
   RAISE EXCEPTION 'Current authorized project required' USING ERRCODE='42501';
 END IF;
 PERFORM set_config('smartpro.document_project',pid::text,true);
 result:=public.smartpro_configured_document_workspace(actor,dept,role);
 PERFORM set_config('smartpro.document_project',coalesce(scope,''),true);
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_document_project_page(uuid,uuid,text,text,integer,uuid) FROM PUBLIC,smartpro_runtime;
GRANT EXECUTE ON FUNCTION public.smartpro_document_project_page(uuid,uuid,text,text,integer,uuid) TO smartpro_runtime;
COMMIT;
