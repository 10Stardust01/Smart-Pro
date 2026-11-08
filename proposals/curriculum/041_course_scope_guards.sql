-- Close older departmental entry points around current offering authority.
BEGIN;
DO $$ BEGIN IF to_regprocedure('public.smartpro_course_details(uuid,uuid,text)') IS NULL THEN RAISE EXCEPTION 'Reviewed 040 required'; END IF; END $$;
CREATE FUNCTION public.smartpro_course_review_scope(actor uuid,rid uuid,role text) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF role IN('HOD','Coordinator') THEN PERFORM public.smartpro_course_authority(actor,public.smartpro_course_project_offering((SELECT project_id FROM public.project_reviews WHERE id=rid)),'READ',role);
 ELSIF role IN('Faculty','Student') AND NOT public.smartpro_role_review_access(actor,rid,role) THEN RAISE EXCEPTION 'Assigned review required' USING ERRCODE='42501'; END IF;
END $$;
DO $$ DECLARE def text; BEGIN
 -- New offerings are configured paused. An appointed coordinator is a prerequisite
 -- for the existing explicit Admin activation command; legacy records are retained.
 def:=pg_get_functiondef('public.smartpro_document_command(uuid,uuid,text,jsonb,text)'::regprocedure);
 def:=replace(def,'result:=jsonb_build_object(''offeringId'',oid,''status'',''CONFIGURED'');',E'IF NOT EXISTS(SELECT FROM public.smartpro_course_coordinators(oid)) THEN UPDATE public.curriculum_offerings SET availability=''PAUSED'' WHERE id=oid;DELETE FROM public.student_offering_windows WHERE offering_id=oid; END IF;\n  result:=jsonb_build_object(''offeringId'',oid,''status'',''CONFIGURED'');');
 def:=replace(def,'  -- Serializes case creation',E'  IF NOT EXISTS(SELECT FROM public.smartpro_course_coordinators(public.smartpro_course_project_offering(p.id))) OR NOT EXISTS(SELECT FROM public.curriculum_offerings WHERE id=public.smartpro_course_project_offering(p.id) AND availability=''ACTIVE'') THEN RAISE EXCEPTION ''An active offering with an appointed coordinator is required'' USING ERRCODE=''42501''; END IF;\n  -- Serializes case creation');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_student_eligible_teams(uuid,uuid,uuid)'::regprocedure);def:=replace(def,'o.id=p_offering_id','o.id=p_offering_id AND EXISTS(SELECT FROM public.smartpro_course_coordinators(o.id))');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_student_membership(uuid,text,uuid,uuid,text,text,text)'::regprocedure);
 def:=replace(def,'IF NOT FOUND THEN RAISE EXCEPTION ''offering outside student scope'' USING ERRCODE=''42501''; END IF;',E'IF NOT FOUND THEN RAISE EXCEPTION ''offering outside student scope'' USING ERRCODE=''42501''; END IF;\n IF p_action IN(''JOIN'',''TRANSFER'') AND NOT EXISTS(SELECT FROM public.smartpro_course_coordinators(offering)) THEN RAISE EXCEPTION ''An appointed offering coordinator is required'' USING ERRCODE=''42501''; END IF;');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_requirement_access(uuid,uuid,text,text,boolean)'::regprocedure);
 def:=replace(def,'RETURN NOT for_decision AND public.smartpro_document_scope(actor,pid,''read'');','RETURN NOT for_decision AND public.smartpro_course_access(actor,public.smartpro_course_project_offering(pid),''READ'',acting_role) AND public.smartpro_document_scope(actor,pid,''read'');');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_academic_review_command(uuid,uuid,text,jsonb,text)'::regprocedure);
 def:=replace(def,'  IF action_name=''EVALUATE'' THEN',E'  IF action_name IN(''PUBLISH'',''ROSTER'',''BIND'') AND EXISTS(SELECT FROM public.course_final_results WHERE project_id=review.project_id) THEN RAISE EXCEPTION ''Overall final publication closes ordinary stage and roster changes'' USING ERRCODE=''42501''; END IF;\n  IF action_name=''EVALUATE'' THEN');EXECUTE def;
 -- No department-wide read/correction grant may widen the Coordinator workspace.
 def:=pg_get_functiondef('public.smartpro_academic_results(uuid,uuid,uuid,integer)'::regprocedure);
 def:=replace(def,'BEGIN',E'BEGIN\n IF NOT public.smartpro_course_access(actor,public.smartpro_course_project_offering((SELECT project_id FROM public.project_reviews WHERE id=review)),''READ'',''HOD'') AND NOT public.smartpro_course_access(actor,public.smartpro_course_project_offering((SELECT project_id FROM public.project_reviews WHERE id=review)),''READ'',''Coordinator'') AND NOT public.smartpro_role_review_access(actor,review,''Faculty'') AND NOT public.smartpro_role_review_access(actor,review,''Student'') THEN RAISE EXCEPTION ''Authorized offering review required'' USING ERRCODE=''42501''; END IF;');EXECUTE def;
END $$;
CREATE FUNCTION public.smartpro_course_staff_read(actor uuid,dept uuid,projects boolean,after_id uuid,role text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE page jsonb; cursor_id uuid;
BEGIN
 IF role IS NULL OR NOT public.smartpro_role_choices(actor) ? role THEN RAISE EXCEPTION 'Current staff responsibility required' USING ERRCODE='42501'; END IF;
 IF role<>'Coordinator' THEN
  IF projects THEN RETURN public.smartpro_staff_projects(actor,dept,after_id); ELSE RETURN public.smartpro_staff_policies(actor,dept,after_id); END IF;
 END IF;
 IF projects THEN
  WITH candidates AS(SELECT p.*,row_number() OVER(ORDER BY p.id) pos FROM public.projects p JOIN public.teams t ON t.id=p.team_id WHERE p.department_id=dept AND (after_id IS NULL OR p.id>after_id) AND public.smartpro_course_access(actor,t.curriculum_offering_id,'READ',role) ORDER BY p.id LIMIT 51)
  SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'title',title,'projectCode',project_code,'projectType',project_type,'teamId',team_id,'cycleId',cycle_id,'rowVersion',row_version,'hasAcademicEvidence',public.smartpro_project_has_academic_evidence(id)) ORDER BY id) FILTER(WHERE pos<=50),'[]'),(array_agg(id ORDER BY id) FILTER(WHERE pos=50 AND EXISTS(SELECT FROM candidates WHERE pos=51)))[1] INTO page,cursor_id FROM candidates;
 ELSE
  WITH candidates AS(SELECT o.id,row_number() OVER(ORDER BY o.id) pos FROM public.curriculum_offerings o WHERE o.department_id=dept AND (after_id IS NULL OR o.id>after_id) AND public.smartpro_course_access(actor,o.id,'READ',role) ORDER BY o.id LIMIT 51)
  SELECT coalesce(jsonb_agg(public.smartpro_staff_offering_state(id) ORDER BY id) FILTER(WHERE pos<=50),'[]'),(array_agg(id ORDER BY id) FILTER(WHERE pos=50 AND EXISTS(SELECT FROM candidates WHERE pos=51)))[1] INTO page,cursor_id FROM candidates;
 END IF;
 RETURN jsonb_build_object('departmentId',dept,'revision',(SELECT revision FROM public.staff_department_controls WHERE department_id=dept),'results',page,'nextCursor',cursor_id);
END $$;
REVOKE ALL ON FUNCTION public.smartpro_course_staff_read(uuid,uuid,boolean,uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_course_staff_read(uuid,uuid,boolean,uuid,text) TO smartpro_runtime;
DO $$ DECLARE def text; BEGIN
 def:=pg_get_functiondef('public.smartpro_assignment_management(uuid,uuid,text)'::regprocedure);
 def:=replace(def,'WHERE p.department_id=dept ORDER BY f.valid_from','WHERE p.department_id=dept AND public.smartpro_course_access(actor,public.smartpro_course_project_offering(p.id),''READ'',acting_role) ORDER BY f.valid_from');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_role_case_access(uuid,uuid,text)'::regprocedure);
 def:=replace(def,'AND public.smartpro_document_scope(actor,c.project_id,','AND (role<>''Coordinator'' OR public.smartpro_course_access(actor,public.smartpro_course_project_offering(c.project_id),''READ'',role)) AND public.smartpro_document_scope(actor,c.project_id,');EXECUTE def;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_course_review_scope(uuid,uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_course_review_scope(uuid,uuid,text) TO smartpro_runtime;
COMMIT;
