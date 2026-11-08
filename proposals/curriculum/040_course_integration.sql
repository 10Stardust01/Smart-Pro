-- Course read projections and live guide/evaluator handover.
BEGIN;
DO $$ BEGIN IF to_regclass('public.course_notification_history') IS NULL THEN RAISE EXCEPTION 'Reviewed 039 required'; END IF; END $$;
ALTER TABLE public.course_guide_evaluators DROP CONSTRAINT course_guide_evaluators_pkey;
ALTER TABLE public.course_guide_evaluators ADD PRIMARY KEY(assignment_id,guide_assignment_id);
CREATE FUNCTION public.smartpro_sync_course_guide_evaluators(actor uuid,pid uuid) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE guide public.faculty_assignments%ROWTYPE; r record; e record; assignment uuid; assessment uuid;
BEGIN
 PERFORM 1 FROM public.projects WHERE id=pid FOR UPDATE;
 SELECT * INTO guide FROM public.faculty_assignments WHERE project_id=pid AND assignment_type='GUIDE' AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until) FOR UPDATE;
 FOR r IN SELECT pr.*,p.aggregation,p.evaluator_weights FROM public.project_reviews pr JOIN public.course_review_bindings cb ON cb.review_id=pr.id JOIN public.academic_review_bindings b ON b.review_id=pr.id JOIN public.academic_evaluation_policies p ON p.id=b.policy_id WHERE pr.project_id=pid AND pr.review_state='OPEN' ORDER BY pr.id FOR UPDATE OF pr,b LOOP
  IF guide.id IS NOT NULL AND r.aggregation='WEIGHTED_MEAN' AND NOT r.evaluator_weights ? guide.faculty_user_id::text THEN RAISE EXCEPTION 'Guide handover is incompatible with this pinned weighted panel; settle its approved evaluation configuration first' USING ERRCODE='23514'; END IF;
  FOR e IN SELECT ea.id,a.id AS assessment_id,a.state FROM public.evaluator_assignments ea JOIN public.assessments a ON a.evaluator_assignment_id=ea.id WHERE ea.review_id=r.id AND public.smartpro_evaluator_active(ea.id) AND EXISTS(SELECT FROM public.course_guide_evaluators g WHERE g.assignment_id=ea.id AND g.guide_assignment_id IS DISTINCT FROM guide.id) AND ea.faculty_user_id IS DISTINCT FROM guide.faculty_user_id ORDER BY ea.id FOR UPDATE OF ea,a LOOP
   IF e.state='DRAFT' THEN
    INSERT INTO public.evaluator_assignment_events(assignment_id,version,active,actor_id) SELECT e.id,coalesce(max(version),0)+1,false,actor FROM public.evaluator_assignment_events WHERE assignment_id=e.id;
    UPDATE public.assessments SET row_version=row_version+1 WHERE id=e.assessment_id;
   END IF;
  END LOOP;
  IF guide.id IS NOT NULL THEN
   SELECT id INTO assignment FROM public.evaluator_assignments WHERE review_id=r.id AND faculty_user_id=guide.faculty_user_id;
   IF assignment IS NULL THEN
    INSERT INTO public.evaluator_assignments(review_id,faculty_user_id) VALUES(r.id,guide.faculty_user_id) RETURNING id INTO assignment;
    INSERT INTO public.assessments(review_id,scheme_mode_id,evaluator_assignment_id) VALUES(r.id,r.scheme_mode_id,assignment);
    INSERT INTO public.course_guide_evaluators VALUES(assignment,guide.id,clock_timestamp());
    INSERT INTO public.evaluator_assignment_events(assignment_id,version,active,actor_id) VALUES(assignment,1,true,actor);
   ELSIF NOT public.smartpro_evaluator_active(assignment) THEN
    INSERT INTO public.evaluator_assignment_events(assignment_id,version,active,actor_id) SELECT assignment,coalesce(max(version),0)+1,true,actor FROM public.evaluator_assignment_events WHERE assignment_id=assignment;
    INSERT INTO public.course_guide_evaluators VALUES(assignment,guide.id,clock_timestamp()) ON CONFLICT DO NOTHING;
   END IF;
  END IF;
  UPDATE public.academic_review_bindings SET revision=revision+1 WHERE review_id=r.id;
  INSERT INTO public.audit_events(actor_id,project_id,action,target_type,target_id,metadata) VALUES(actor,pid,'COURSE_GUIDE_EVALUATORS_SYNCHRONIZED','PROJECT_REVIEW',r.id,jsonb_build_object('guideAssignmentId',guide.id));
 END LOOP;
END $$;
CREATE FUNCTION public.smartpro_course_evaluation_window(aid uuid) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r record; stage jsonb; due timestamptz;
BEGIN
 SELECT a.review_id,pr.project_id,b.stage_key,f.configuration INTO r FROM public.assessments a JOIN public.project_reviews pr ON pr.id=a.review_id JOIN public.course_review_bindings b ON b.review_id=pr.id JOIN public.course_plan_versions p ON p.id=b.plan_id JOIN public.course_framework_versions f ON f.id=p.framework_id WHERE a.id=aid;
 IF NOT FOUND THEN RETURN; END IF;
 SELECT value INTO stage FROM jsonb_array_elements(r.configuration->'stages') WHERE value->>'key'=r.stage_key;
 due:=public.smartpro_course_deadline_effective(r.project_id,'EVALUATION',r.stage_key,(stage->>'deadline')::timestamptz);
 IF EXISTS(SELECT FROM public.course_final_results WHERE project_id=r.project_id) OR clock_timestamp()<(stage->>'opensAt')::timestamptz OR clock_timestamp()>=due THEN RAISE EXCEPTION 'Configured evaluation window is closed; an authorized extension may be required' USING ERRCODE='42501'; END IF;
END $$;
CREATE FUNCTION public.smartpro_course_details(actor uuid,oid uuid,role text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE dept uuid;
BEGIN
 SELECT department_id INTO dept FROM public.curriculum_offerings WHERE id=oid;
 IF role='Admin' AND public.smartpro_has_role(actor,dept,'ACADEMIC_ADMIN',clock_timestamp()) THEN PERFORM public.smartpro_department_setup_read(actor,dept);
 ELSE PERFORM public.smartpro_course_authority(actor,oid,'READ',role); END IF;
 RETURN jsonb_build_object(
 'projectCount',(SELECT count(*) FROM public.projects p JOIN public.teams t ON t.id=p.team_id WHERE t.curriculum_offering_id=oid),
 'teamCount',(SELECT count(*) FROM public.teams WHERE curriculum_offering_id=oid),
 'studentCount',(SELECT count(DISTINCT m.user_id) FROM public.team_memberships m JOIN public.teams t ON t.id=m.team_id WHERE t.curriculum_offering_id=oid AND m.joined_at<=clock_timestamp() AND (m.left_at IS NULL OR m.left_at>clock_timestamp())),
 'reviewProgress',(SELECT jsonb_build_object('total',count(*),'published',count(*) FILTER(WHERE EXISTS(SELECT FROM public.academic_result_versions v WHERE v.review_id=r.id))) FROM public.project_reviews r JOIN public.projects p ON p.id=r.project_id JOIN public.teams t ON t.id=p.team_id WHERE t.curriculum_offering_id=oid),
 'submissionProgress',(SELECT jsonb_build_object('awaitingReview',count(*) FILTER(WHERE c.state='AWAITING_REVIEW'),'awaitingRevision',count(*) FILTER(WHERE c.state='CHANGES_REQUESTED')) FROM public.submission_cases c JOIN public.projects p ON p.id=c.project_id JOIN public.teams t ON t.id=p.team_id WHERE t.curriculum_offering_id=oid AND NOT EXISTS(SELECT FROM public.course_final_results f WHERE f.project_id=p.id)),
 'requirements',(SELECT coalesce(jsonb_agg(to_jsonb(q)),'[]') FROM public.submission_offering_requirements h JOIN public.submission_requirement_policies q ON q.id=h.policy_id WHERE h.offering_id=oid),
 'requirementVersions',(SELECT coalesce(jsonb_agg(to_jsonb(q) ORDER BY q.configured_at DESC),'[]') FROM public.submission_requirement_policies q WHERE q.offering_id=oid),
 'frameworks',(SELECT coalesce(jsonb_agg(to_jsonb(f) ORDER BY f.version DESC),'[]') FROM public.course_framework_versions f WHERE offering_id=oid),
 'plans',(SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY p.version DESC),'[]') FROM public.course_plan_versions p WHERE offering_id=oid),
 'deadlines',(SELECT coalesce(jsonb_agg(to_jsonb(d) ORDER BY d.created_at DESC),'[]') FROM public.course_deadline_versions d WHERE offering_id=oid),
 'rubrics',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM(SELECT v.id AS scheme_version_id,m.id AS scheme_mode_id,d.label,m.mode_code,v.version_no,(SELECT sum(rc.maximum) FROM public.mode_criteria mc JOIN public.rubric_criteria rc ON rc.id=mc.criterion_id WHERE mc.scheme_mode_id=m.id) AS maximum FROM public.scheme_versions v JOIN public.review_definitions d ON d.id=v.review_definition_id JOIN public.scheme_modes m ON m.scheme_version_id=v.id JOIN public.curriculum_offerings o ON o.cycle_id=v.cycle_id WHERE o.id=oid AND v.state='ACTIVE' AND d.department_id=dept AND d.policy_version_id IN(SELECT r.policy_version_id FROM public.offering_project_registration_policies h JOIN public.project_registration_policy_versions r ON r.id=h.registration_policy_version_id WHERE h.offering_id=oid) ORDER BY d.ordinal,v.version_no DESC LIMIT 100)x),
 'evaluationPolicies',(SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY p.version_no DESC),'[]') FROM public.academic_evaluation_policies p WHERE department_id=dept),
 'corrections',CASE WHEN role='Admin' THEN '[]'::jsonb ELSE (SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY created_at DESC),'[]') FROM(SELECT q.*,u.display_name,a.approved,a.actor_id AS authorizer_id,EXISTS(SELECT FROM public.course_correction_applications WHERE request_id=q.id) AS applied FROM public.course_correction_requests q JOIN public.users u ON u.id=q.requester_id LEFT JOIN public.course_correction_authorizations a ON a.request_id=q.id WHERE q.offering_id=oid LIMIT 100)x) END,
 'overallResults',CASE WHEN role='Admin' THEN '[]'::jsonb ELSE (SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.created_at),'[]') FROM public.course_final_results r JOIN public.projects p ON p.id=r.project_id JOIN public.teams t ON t.id=p.team_id WHERE t.curriculum_offering_id=oid) END,
 'notificationSummary',(SELECT jsonb_build_object('activeInApp',count(*) FILTER(WHERE n.status='ACTIVE'),'retainedHistory',count(*),'emailDelivery','Not configured') FROM public.course_notifications n JOIN public.course_deadline_versions d ON d.id=n.deadline_id WHERE d.offering_id=oid),
 'history',(SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY occurred_at DESC),'[]') FROM(SELECT a.id,a.action,a.occurred_at FROM public.audit_events a WHERE a.metadata->>'offeringId'=oid::text OR (a.target_type='OFFERING' AND a.target_id=oid) OR EXISTS(SELECT FROM public.projects p JOIN public.teams t ON t.id=p.team_id WHERE p.id=a.project_id AND t.curriculum_offering_id=oid) ORDER BY occurred_at DESC LIMIT 200)x));
END $$;
ALTER FUNCTION public.smartpro_configured_document_workspace(uuid,uuid,text) RENAME TO smartpro_configured_document_workspace_pre040;
REVOKE ALL ON FUNCTION public.smartpro_configured_document_workspace_pre040(uuid,uuid,text) FROM PUBLIC,smartpro_runtime;
CREATE FUNCTION public.smartpro_configured_document_workspace(actor uuid,dept uuid,role text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE w jsonb; projects jsonb:='[]'; p jsonb; req jsonb; requirements jsonb; closed boolean; can_reopen boolean; final_results jsonb;
BEGIN
 w:=public.smartpro_configured_document_workspace_pre040(actor,dept,role);
 FOR p IN SELECT value FROM jsonb_array_elements(w->'projects') LOOP
  closed:=EXISTS(SELECT FROM public.course_final_results WHERE project_id=(p->>'id')::uuid);
  can_reopen:=NOT closed AND role='Faculty' AND p->'case'->>'state'='APPROVED' AND EXISTS(SELECT FROM public.faculty_assignments g WHERE g.project_id=(p->>'id')::uuid AND g.faculty_user_id=actor AND g.assignment_type='GUIDE' AND g.valid_from<=clock_timestamp() AND (g.valid_until IS NULL OR clock_timestamp()<g.valid_until)) AND public.smartpro_requirement_access(actor,(p->>'id')::uuid,'SYNOPSIS','Faculty',true) AND EXISTS(SELECT FROM public.submission_requirement_bindings b JOIN public.submission_requirement_policies q ON q.id=b.policy_id WHERE b.case_id=(p->'case'->>'id')::uuid AND q.revisions_enabled AND q.changes_enabled AND q.opens_at<=clock_timestamp() AND clock_timestamp()<public.smartpro_course_document_close((p->>'id')::uuid,'SYNOPSIS',q.closes_at));
  requirements:='[]';
  FOR req IN SELECT value FROM jsonb_array_elements(p->'requirements') LOOP
   req:=req||jsonb_build_object('closesAt',public.smartpro_course_document_close((p->>'id')::uuid,req->>'key',(req->>'closesAt')::timestamptz),'canReview',NOT closed AND (req->>'canReview')::boolean);requirements:=requirements||jsonb_build_array(req);
  END LOOP;
  IF p->'requirement'<>'null'::jsonb THEN p:=jsonb_set(p,'{requirement,closesAt}',to_jsonb(public.smartpro_course_document_close((p->>'id')::uuid,'SYNOPSIS',(p->'requirement'->>'closesAt')::timestamptz))); END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object('version',r.version,'createdAt',r.created_at,'results',CASE WHEN role='Student' THEN jsonb_build_object(actor::text,r.results->actor::text) ELSE r.results END) ORDER BY r.version),'[]') INTO final_results FROM public.course_final_results r WHERE r.project_id=(p->>'id')::uuid;
  p:=p||jsonb_build_object('requirements',requirements,'overallFinalPublished',closed,'overallResults',final_results,'canReopenSynopsis',coalesce(can_reopen,false),'canSubmit',NOT closed AND (p->>'canSubmit')::boolean,'canReview',NOT closed AND (p->>'canReview')::boolean,'canReviseProposal',NOT closed AND (p->>'canReviseProposal')::boolean);
  projects:=projects||jsonb_build_array(p);
 END LOOP;
 RETURN w||jsonb_build_object('projects',projects);
END $$;
DO $$ DECLARE def text; BEGIN
 def:=pg_get_functiondef('public.smartpro_course_notifications(uuid,text)'::regprocedure);
 def:=replace(def,' RETURN jsonb_build_object(''alerts'',',' RETURN jsonb_build_object(''corrections'',(SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY created_at DESC),''[]'') FROM(SELECT q.*,a.approved,EXISTS(SELECT FROM public.course_correction_applications WHERE request_id=q.id) AS applied FROM public.course_correction_requests q LEFT JOIN public.course_correction_authorizations a ON a.request_id=q.id WHERE q.requester_id=actor AND role=''Faculty'' ORDER BY q.created_at DESC LIMIT 100)x),''alerts'',');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_project_operation(uuid,uuid,text,jsonb,text)'::regprocedure);def:=replace(def,'PERFORM public.smartpro_sync_guide_synopsis(actor,p.id);','PERFORM public.smartpro_sync_guide_synopsis(actor,p.id);PERFORM public.smartpro_sync_course_guide_evaluators(actor,p.id);');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_manage_assignment(uuid,uuid,text,jsonb,text)'::regprocedure);def:=replace(def,'PERFORM public.smartpro_sync_guide_synopsis(actor,assignment.project_id);','PERFORM public.smartpro_sync_guide_synopsis(actor,assignment.project_id);PERFORM public.smartpro_sync_course_guide_evaluators(actor,assignment.project_id);');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_initial_evaluation(uuid,uuid,text,jsonb,text)'::regprocedure);def:=replace(def,' RETURN public.smartpro_initial_evaluation_pre038',E' PERFORM public.smartpro_course_evaluation_window((input->>''assessmentId'')::uuid);\n RETURN public.smartpro_initial_evaluation_pre038');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_review_management(uuid,uuid,uuid,text)'::regprocedure);def:=replace(def,' PERFORM public.smartpro_academic_authority(actor,dept,acting_role=''HOD'');',' PERFORM public.smartpro_course_authority(actor,public.smartpro_course_project_offering((SELECT project_id FROM public.project_reviews WHERE id=rid)),''READ'',acting_role);');EXECUTE def;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_sync_course_guide_evaluators(uuid,uuid),public.smartpro_course_evaluation_window(uuid),public.smartpro_course_details(uuid,uuid,text),public.smartpro_configured_document_workspace(uuid,uuid,text) FROM PUBLIC,smartpro_runtime;
GRANT EXECUTE ON FUNCTION public.smartpro_course_details(uuid,uuid,text),public.smartpro_configured_document_workspace(uuid,uuid,text) TO smartpro_runtime;
COMMIT;
