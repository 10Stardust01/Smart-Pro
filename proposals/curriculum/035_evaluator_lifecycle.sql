BEGIN;
DO $$ BEGIN IF to_regclass('public.project_proposal_revisions') IS NULL THEN RAISE EXCEPTION 'Reviewed 034 required'; END IF; END $$;
CREATE TABLE public.evaluator_assignment_events(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),assignment_id uuid NOT NULL REFERENCES evaluator_assignments(id),
 version integer NOT NULL,active boolean NOT NULL,actor_id uuid NOT NULL REFERENCES users(id),created_at timestamptz NOT NULL DEFAULT clock_timestamp(),UNIQUE(assignment_id,version));
REVOKE ALL ON public.evaluator_assignment_events FROM PUBLIC,smartpro_runtime;
CREATE TRIGGER retain_evaluator_assignment_event BEFORE UPDATE OR DELETE ON public.evaluator_assignment_events FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation();
CREATE FUNCTION public.smartpro_evaluator_active(assignment uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT coalesce((SELECT active FROM public.evaluator_assignment_events WHERE assignment_id=assignment ORDER BY version DESC LIMIT 1),true);
$$;
CREATE FUNCTION public.smartpro_review_management(actor uuid,dept uuid,rid uuid,acting_role text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE review public.project_reviews%ROWTYPE; roster uuid;
BEGIN
 IF acting_role IS NULL OR acting_role NOT IN ('HOD','Coordinator') OR NOT public.smartpro_role_choices(actor) ? acting_role THEN RAISE EXCEPTION 'Academic management responsibility required' USING ERRCODE='42501'; END IF;
 PERFORM public.smartpro_academic_authority(actor,dept,acting_role='HOD');
 SELECT r.* INTO review FROM public.project_reviews r JOIN public.projects p ON p.id=r.project_id WHERE r.id=rid AND p.department_id=dept;
 IF NOT FOUND THEN RAISE EXCEPTION 'Department review required' USING ERRCODE='42501'; END IF;
 SELECT id INTO roster FROM public.academic_roster_versions WHERE review_id=rid ORDER BY version_no DESC LIMIT 1;
 RETURN jsonb_build_object('assignments',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM (SELECT e.id,e.faculty_user_id,u.display_name,a.id AS assessment_id,a.state,public.smartpro_evaluator_active(e.id) AS active FROM public.evaluator_assignments e JOIN public.assessments a ON a.evaluator_assignment_id=e.id JOIN public.users u ON u.id=e.faculty_user_id WHERE e.review_id=rid)x),
 'history',(SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY created_at),'[]') FROM (SELECT h.*,u.display_name FROM public.evaluator_assignment_events h JOIN public.evaluator_assignments e ON e.id=h.assignment_id JOIN public.users u ON u.id=e.faculty_user_id WHERE e.review_id=rid)x),
 'rosterCandidates',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM (SELECT m.id,m.user_id,u.display_name,EXISTS(SELECT FROM public.academic_roster_members WHERE roster_version_id=roster AND membership_id=m.id) AS selected FROM public.team_memberships m JOIN public.projects p ON p.team_id=m.team_id JOIN public.users u ON u.id=m.user_id WHERE p.id=review.project_id AND m.joined_at<=review.roster_locked_at AND (m.left_at IS NULL OR review.roster_locked_at<m.left_at) AND EXISTS(SELECT FROM public.department_role_assignments r WHERE r.user_id=m.user_id AND r.department_id=dept AND r.role_code='STUDENT' AND r.valid_from<=review.roster_locked_at AND (r.valid_until IS NULL OR review.roster_locked_at<r.valid_until)) ORDER BY u.display_name)x),
 'rosterHistory',(SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY version_no),'[]') FROM (SELECT v.*,(SELECT coalesce(jsonb_agg(u.display_name ORDER BY u.display_name),'[]') FROM public.academic_roster_members m JOIN public.users u ON u.id=m.student_user_id WHERE m.roster_version_id=v.id) AS members FROM public.academic_roster_versions v WHERE v.review_id=rid)x));
END $$;
CREATE FUNCTION public.smartpro_revise_evaluators(actor uuid,dept uuid,action text,input jsonb,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE review public.project_reviews%ROWTYPE; binding public.academic_review_bindings%ROWTYPE; policy public.academic_evaluation_policies%ROWTYPE; prior public.academic_command_receipts%ROWTYPE; auth jsonb; uid uuid; assignment uuid; a record; desired boolean; result jsonb;
BEGIN
 PERFORM 1 FROM public.academic_governance_settings WHERE department_id=dept AND enabled FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Academic management disabled' USING ERRCODE='42501'; END IF;
 IF input->>'_actingRole' IS NULL OR input->>'_actingRole' NOT IN ('HOD','Coordinator') OR NOT public.smartpro_role_choices(actor) ? (input->>'_actingRole') THEN RAISE EXCEPTION 'Academic management responsibility required' USING ERRCODE='42501'; END IF;
 auth:=public.smartpro_academic_authority(actor,dept,input->>'_actingRole'='HOD');
 IF action<>'EVALUATORS' OR key IS NULL OR key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' THEN RAISE EXCEPTION 'Evaluation assignment command required' USING ERRCODE='22023'; END IF;
 SELECT * INTO prior FROM public.academic_command_receipts WHERE actor_id=actor AND request_key=key;
 IF FOUND THEN IF prior.action<>'REVISE_EVALUATORS' OR prior.input<>input OR prior.department_id<>dept THEN RAISE EXCEPTION 'Retry changed' USING ERRCODE='23514'; END IF;RETURN prior.output; END IF;
 SELECT r.* INTO review FROM public.project_reviews r JOIN public.projects p ON p.id=r.project_id WHERE r.id=(input->>'reviewId')::uuid AND p.department_id=dept FOR UPDATE OF r;
 IF NOT FOUND THEN RAISE EXCEPTION 'Department review required' USING ERRCODE='42501'; END IF;
 SELECT * INTO binding FROM public.academic_review_bindings WHERE review_id=review.id FOR UPDATE;
 IF binding.revision IS DISTINCT FROM (input->>'expectedReviewRevision')::integer OR review.review_state<>'OPEN' OR EXISTS(SELECT FROM public.academic_result_versions WHERE review_id=review.id) THEN RAISE EXCEPTION 'Opened unsubmitted evaluation configuration required; use a new review round for finalized evidence' USING ERRCODE='23514'; END IF;
 SELECT * INTO policy FROM public.academic_evaluation_policies WHERE id=binding.policy_id;
 IF jsonb_typeof(input->'facultyIds')<>'array' OR jsonb_array_length(input->'facultyIds')<policy.evaluator_quorum OR jsonb_array_length(input->'facultyIds')<>(SELECT count(DISTINCT value) FROM jsonb_array_elements_text(input->'facultyIds')) THEN RAISE EXCEPTION 'Distinct eligible evaluators meeting quorum required' USING ERRCODE='22023'; END IF;
 IF policy.aggregation='WEIGHTED_MEAN' AND (SELECT jsonb_object_agg(value,true) FROM jsonb_array_elements_text(input->'facultyIds')) IS DISTINCT FROM (SELECT jsonb_object_agg(w.key,true) FROM jsonb_each(policy.evaluator_weights) w) THEN RAISE EXCEPTION 'Assignments must preserve the pinned evaluator weights; create a new review round for a different policy' USING ERRCODE='23514'; END IF;
 FOR uid IN SELECT value::uuid FROM jsonb_array_elements_text(input->'facultyIds') ORDER BY value LOOP
  PERFORM 1 FROM public.department_role_assignments r JOIN public.users u ON u.id=r.user_id WHERE r.user_id=uid AND r.department_id=dept AND r.role_code='FACULTY' AND u.account_status='ACTIVE' AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until) FOR SHARE OF r,u;
  IF NOT FOUND OR NOT public.smartpro_has_role(uid,dept,'FACULTY',clock_timestamp()) THEN RAISE EXCEPTION 'Current departmental faculty required' USING ERRCODE='42501'; END IF;
 END LOOP;
 FOR a IN SELECT e.*,s.id AS assessment_id,s.state FROM public.evaluator_assignments e JOIN public.assessments s ON s.evaluator_assignment_id=e.id WHERE e.review_id=review.id ORDER BY e.id FOR UPDATE OF e,s LOOP
  desired:=(input->'facultyIds') ? a.faculty_user_id::text;
  IF desired IS DISTINCT FROM public.smartpro_evaluator_active(a.id) THEN
   IF a.state='FINALIZED' THEN RAISE EXCEPTION 'Finalized evaluator contribution must remain; create a new review round' USING ERRCODE='23514'; END IF;
   INSERT INTO public.evaluator_assignment_events(assignment_id,version,active,actor_id) SELECT a.id,coalesce(max(version),0)+1,desired,actor FROM public.evaluator_assignment_events WHERE assignment_id=a.id;
   UPDATE public.assessments SET row_version=row_version+1 WHERE id=a.assessment_id;
  END IF;
 END LOOP;
 FOR uid IN SELECT value::uuid FROM jsonb_array_elements_text(input->'facultyIds') ORDER BY value LOOP
  IF NOT EXISTS(SELECT FROM public.evaluator_assignments WHERE review_id=review.id AND faculty_user_id=uid) THEN
   INSERT INTO public.evaluator_assignments(review_id,faculty_user_id) VALUES(review.id,uid) RETURNING id INTO assignment;
   INSERT INTO public.assessments(review_id,scheme_mode_id,evaluator_assignment_id) VALUES(review.id,review.scheme_mode_id,assignment);
   INSERT INTO public.evaluator_assignment_events(assignment_id,version,active,actor_id) VALUES(assignment,1,true,actor);
  END IF;
 END LOOP;
 UPDATE public.academic_review_bindings SET revision=revision+1 WHERE review_id=review.id;
 UPDATE public.project_reviews SET row_version=row_version+1 WHERE id=review.id;
 FOR uid IN SELECT value::uuid FROM jsonb_array_elements_text(input->'facultyIds') LOOP
  IF NOT public.smartpro_has_role(uid,dept,'FACULTY',clock_timestamp()) THEN RAISE EXCEPTION 'Evaluator role expired during assignment' USING ERRCODE='42501'; END IF;
 END LOOP;
 auth:=public.smartpro_academic_authority(actor,dept,input->>'_actingRole'='HOD');
 result:=jsonb_build_object('reviewId',review.id,'revision',binding.revision+1);
 INSERT INTO public.academic_command_receipts(actor_id,request_key,department_id,action,target_id,input,output,authority,occurred_at) VALUES(actor,key,dept,'REVISE_EVALUATORS',review.id,input,result,auth,clock_timestamp());
 INSERT INTO public.audit_events(actor_id,project_id,action,target_type,target_id,metadata) VALUES(actor,review.project_id,'EVALUATORS_REVISED','PROJECT_REVIEW',review.id,jsonb_build_object('departmentId',dept,'facultyIds',input->'facultyIds','authority',auth));
 RETURN result;
END $$;
CREATE FUNCTION public.smartpro_evaluator_write_guard() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE data jsonb; assignment uuid;
BEGIN
 data:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 IF TG_TABLE_NAME='assessments' THEN
  assignment:=(data->>'evaluator_assignment_id')::uuid;
  IF TG_OP='UPDATE' THEN IF (to_jsonb(NEW)-'row_version')=(to_jsonb(OLD)-'row_version') THEN RETURN NEW; END IF; END IF;
 ELSE SELECT evaluator_assignment_id INTO assignment FROM public.assessments WHERE id=(data->>'assessment_id')::uuid; END IF;
 IF NOT public.smartpro_evaluator_active(assignment) THEN RAISE EXCEPTION 'Withdrawn evaluator contribution is read-only' USING ERRCODE='42501'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;RETURN NEW;
END $$;
CREATE TRIGGER evaluator_assignment_write_boundary BEFORE INSERT OR UPDATE OR DELETE ON public.assessments FOR EACH ROW EXECUTE FUNCTION public.smartpro_evaluator_write_guard();
CREATE TRIGGER evaluator_assignment_write_boundary BEFORE INSERT OR UPDATE OR DELETE ON public.team_criterion_scores FOR EACH ROW EXECUTE FUNCTION public.smartpro_evaluator_write_guard();
CREATE TRIGGER evaluator_assignment_write_boundary BEFORE INSERT OR UPDATE OR DELETE ON public.student_criterion_scores FOR EACH ROW EXECUTE FUNCTION public.smartpro_evaluator_write_guard();
REVOKE ALL ON FUNCTION public.smartpro_evaluator_write_guard() FROM PUBLIC;
DO $$ DECLARE def text; BEGIN
 def:=pg_get_functiondef('public.smartpro_initial_evaluation(uuid,uuid,text,jsonb,text)'::regprocedure);
 def:=replace(def,'AND e.faculty_user_id=actor AND p.department_id=dept','AND e.faculty_user_id=actor AND public.smartpro_evaluator_active(e.id) AND p.department_id=dept');
 def:=replace(def,'WHERE review_id=rid AND state<>''FINALIZED''','WHERE review_id=rid AND state<>''FINALIZED'' AND public.smartpro_evaluator_active(evaluator_assignment_id)');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_review_terminal_state()'::regprocedure);
 def:=replace(def,'WHERE review_id=OLD.id AND state<>''FINALIZED''','WHERE review_id=OLD.id AND state<>''FINALIZED'' AND public.smartpro_evaluator_active(evaluator_assignment_id)');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_application_workspace(uuid)'::regprocedure);
 def:=replace(def,'''label'',d.label,','''label'',d.label,''round'',r.round_no,');
 def:=replace(def,'WHERE a.review_id=r.id AND (administrator','WHERE public.smartpro_evaluator_active(e.id) AND a.review_id=r.id AND (administrator');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_role_review_access(uuid,uuid,text)'::regprocedure);
 def:=replace(def,'WHERE review_id=review AND faculty_user_id=actor','WHERE review_id=review AND faculty_user_id=actor AND public.smartpro_evaluator_active(id)');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_role_workspace(uuid,text)'::regprocedure);
 def:=replace(def,'WHERE e.review_id=(r->>''id'')::uuid AND e.faculty_user_id=actor','WHERE public.smartpro_evaluator_active(e.id) AND e.review_id=(r->>''id'')::uuid AND e.faculty_user_id=actor');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_requirement_access(uuid,uuid,text,text,boolean)'::regprocedure);
 def:=replace(def,'WHERE r.project_id=pid AND e.faculty_user_id=actor','WHERE public.smartpro_evaluator_active(e.id) AND r.project_id=pid AND e.faculty_user_id=actor');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_document_scope(uuid,uuid,text)'::regprocedure);
 def:=replace(def,'WHERE r.project_id=pid AND e.faculty_user_id=actor','WHERE public.smartpro_evaluator_active(e.id) AND r.project_id=pid AND e.faculty_user_id=actor');EXECUTE def;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_evaluator_active(uuid),public.smartpro_review_management(uuid,uuid,uuid,text),public.smartpro_revise_evaluators(uuid,uuid,text,jsonb,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_evaluator_active(uuid),public.smartpro_review_management(uuid,uuid,uuid,text),public.smartpro_revise_evaluators(uuid,uuid,text,jsonb,text) TO smartpro_runtime;
COMMIT;
