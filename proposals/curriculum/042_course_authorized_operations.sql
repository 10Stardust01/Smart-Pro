-- Specific exceptional result revisions, reusable approved requirements and milestones.
BEGIN;
DO $$ BEGIN IF to_regprocedure('public.smartpro_course_staff_read(uuid,uuid,boolean,uuid,text)') IS NULL THEN RAISE EXCEPTION 'Reviewed 041 required'; END IF; END $$;
ALTER TABLE public.course_correction_authorizations ADD COLUMN appointment_id uuid REFERENCES course_coordinator_versions(id);
ALTER TABLE public.course_deadline_versions ADD COLUMN completion_role text CHECK(completion_role IN('Student','Faculty','Coordinator','HOD'));
ALTER TABLE public.course_deadline_versions ADD COLUMN completion_scope text CHECK(completion_scope IN('PROJECT','INDIVIDUAL'));
CREATE TABLE public.course_final_revision_requests(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),project_id uuid NOT NULL REFERENCES projects(id),expected_version integer NOT NULL,snapshot jsonb NOT NULL,requester_id uuid NOT NULL REFERENCES users(id),created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE public.course_final_revision_authorizations(request_id uuid PRIMARY KEY REFERENCES course_final_revision_requests(id),actor_id uuid NOT NULL REFERENCES users(id),appointment_id uuid NOT NULL REFERENCES course_coordinator_versions(id),approved boolean NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE public.course_final_revision_applications(request_id uuid PRIMARY KEY REFERENCES course_final_revision_requests(id),result_id uuid NOT NULL UNIQUE REFERENCES course_final_results(id),actor_id uuid NOT NULL REFERENCES users(id),created_at timestamptz NOT NULL DEFAULT clock_timestamp());
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['course_final_revision_requests','course_final_revision_authorizations','course_final_revision_applications'] LOOP EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,smartpro_runtime',t);EXECUTE format('CREATE TRIGGER retain_final_correction_history BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation()',t); END LOOP; END $$;
CREATE FUNCTION public.smartpro_course_calculate(pid uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE plan public.course_plan_versions%ROWTYPE; framework public.course_framework_versions%ROWTYPE; stage jsonb; source public.academic_result_versions%ROWTYPE; sources jsonb:='[]'; totals jsonb:='{}'; roster text[]; member text; total numeric; maximum numeric;
BEGIN
 SELECT p.* INTO plan FROM public.course_project_plans b JOIN public.course_plan_versions p ON p.id=b.plan_id WHERE b.project_id=pid;
 SELECT * INTO framework FROM public.course_framework_versions WHERE id=plan.framework_id;
 IF framework.id IS NULL THEN RAISE EXCEPTION 'Pinned approved course plan required' USING ERRCODE='23514'; END IF;
  FOR stage IN SELECT value FROM jsonb_array_elements(framework.configuration->'stages') LOOP
   SELECT r.* INTO source FROM public.academic_result_versions r JOIN public.course_review_bindings b ON b.review_id=r.review_id JOIN public.project_reviews pr ON pr.id=r.review_id WHERE pr.project_id=pid AND b.plan_id=plan.id AND b.stage_key=stage->>'key' ORDER BY r.version_no DESC LIMIT 1;
   IF source.id IS NULL AND ((stage->>'required')::boolean OR (stage->>'weight')::numeric>0) THEN RAISE EXCEPTION 'Every required/contributing stage must be completely published under this pinned plan' USING ERRCODE='23514'; END IF;
   IF source.id IS NULL THEN CONTINUE; END IF;
   SELECT sum(rc.maximum) INTO maximum FROM public.project_reviews r JOIN public.mode_criteria mc ON mc.scheme_mode_id=r.scheme_mode_id JOIN public.rubric_criteria rc ON rc.id=mc.criterion_id WHERE r.id=source.review_id;
   IF maximum IS NULL OR maximum<=0 THEN RAISE EXCEPTION 'Explicit nonzero rubric maximum required' USING ERRCODE='23514'; END IF;
   IF roster IS NULL THEN SELECT array_agg(k ORDER BY k) INTO roster FROM jsonb_object_keys(source.results) k;
   ELSIF roster IS DISTINCT FROM (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(source.results) k) THEN RAISE EXCEPTION 'Stage rosters differ; correct historical evidence without awarding missing marks' USING ERRCODE='23514'; END IF;
   FOREACH member IN ARRAY roster LOOP
    total:=coalesce((totals->>member)::numeric,0)+CASE WHEN framework.configuration->>'method'='SINGLE_RAW' THEN (source.results->>member)::numeric ELSE (source.results->>member)::numeric/maximum*(stage->>'weight')::numeric/100*(framework.configuration->>'scale')::numeric END;
    totals:=jsonb_set(totals,ARRAY[member],to_jsonb(total));
   END LOOP;
   sources:=sources||jsonb_build_array(jsonb_build_object('stageKey',stage->>'key','resultVersionId',source.id,'weight',stage->'weight','rubricMaximum',maximum));
  END LOOP;
  IF totals='{}' THEN RAISE EXCEPTION 'Complete published academic evidence required' USING ERRCODE='23514'; END IF;
  SELECT jsonb_object_agg(k,round(v::numeric,(framework.configuration->>'decimalPlaces')::integer)::text) INTO totals FROM jsonb_each_text(totals) x(k,v);

 RETURN jsonb_build_object('planId',plan.id,'sources',sources,'results',totals);
END $$;
CREATE FUNCTION public.smartpro_course_final_revision(actor uuid,oid uuid,action text,input jsonb,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE request public.course_final_revision_requests%ROWTYPE; result_row public.course_final_results%ROWTYPE; cfg jsonb; snapshot jsonb; pid uuid; target uuid; appointment uuid; prior public.document_command_receipts%ROWTYPE; result jsonb; permission text;
BEGIN
 permission:=CASE WHEN action='AUTHORIZE_FINAL_REVISION' THEN 'CORRECTIONS' ELSE 'RESULTS' END;
 PERFORM public.smartpro_course_authority(actor,oid,permission,input->>'_actingRole');
 IF key IS NULL OR key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' THEN RAISE EXCEPTION 'Request key required' USING ERRCODE='22023'; END IF;
 SELECT * INTO prior FROM public.document_command_receipts WHERE actor_id=actor AND request_key=key;
 IF FOUND THEN IF prior.action<>action OR prior.input<>jsonb_build_object('offeringId',oid,'payload',input) THEN RAISE EXCEPTION 'Retry changed' USING ERRCODE='23514'; END IF; RETURN prior.output; END IF;
 IF action='REQUEST_FINAL_REVISION' THEN pid:=(input->>'projectId')::uuid;
 ELSE SELECT * INTO request FROM public.course_final_revision_requests WHERE id=(input->>'requestId')::uuid FOR UPDATE;pid:=request.project_id; END IF;
 PERFORM 1 FROM public.projects WHERE id=pid AND public.smartpro_course_project_offering(id)=oid FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Offering project required' USING ERRCODE='42501'; END IF;
 SELECT * INTO result_row FROM public.course_final_results WHERE project_id=pid ORDER BY version DESC LIMIT 1;
 SELECT f.configuration INTO cfg FROM public.course_plan_versions p JOIN public.course_framework_versions f ON f.id=p.framework_id WHERE p.id=result_row.plan_id;
 IF result_row.id IS NULL OR coalesce((cfg->>'allowFinalCorrections')::boolean,false)=false THEN RAISE EXCEPTION 'Pinned policy permitting exceptional final corrections required' USING ERRCODE='42501'; END IF;
 IF action='REQUEST_FINAL_REVISION' THEN
  IF NOT cfg->'publicationRoles' ? (input->>'_actingRole') OR result_row.version IS DISTINCT FROM (input->>'expectedVersion')::integer THEN RAISE EXCEPTION 'Current authorized overall result revision required' USING ERRCODE='23514'; END IF;
  snapshot:=public.smartpro_course_calculate(pid);
  IF snapshot->'sources'=result_row.sources AND snapshot->'results'=result_row.results THEN RAISE EXCEPTION 'No revised academic evidence to publish' USING ERRCODE='23514'; END IF;
  INSERT INTO public.course_final_revision_requests(project_id,expected_version,snapshot,requester_id) VALUES(pid,result_row.version,snapshot,actor) RETURNING id INTO target;
 ELSIF action='AUTHORIZE_FINAL_REVISION' THEN
  IF input->>'_actingRole'<>'Coordinator' OR request.requester_id=actor OR ((cfg->>'outsidePanelAuthorizer')::boolean AND EXISTS(SELECT FROM public.evaluator_assignments e JOIN public.project_reviews r ON r.id=e.review_id WHERE r.project_id=pid AND e.faculty_user_id=actor AND public.smartpro_evaluator_active(e.id))) THEN RAISE EXCEPTION 'Independent appointed course coordinator required' USING ERRCODE='42501'; END IF;
  SELECT id INTO appointment FROM public.smartpro_course_coordinators(oid) WHERE user_id=actor AND 'CORRECTIONS'=ANY(responsibilities);
  INSERT INTO public.course_final_revision_authorizations VALUES(request.id,actor,appointment,(input->>'approved')::boolean,clock_timestamp());target:=request.id;
 ELSIF action='APPLY_FINAL_REVISION' THEN
  IF actor<>request.requester_id OR NOT cfg->'publicationRoles' ? (input->>'_actingRole') OR result_row.version<>request.expected_version OR NOT EXISTS(SELECT FROM public.course_final_revision_authorizations WHERE request_id=request.id AND approved) OR EXISTS(SELECT FROM public.course_final_revision_applications WHERE request_id=request.id) THEN RAISE EXCEPTION 'Specific unused authorization and original requester required' USING ERRCODE='42501'; END IF;
  snapshot:=public.smartpro_course_calculate(pid);
  IF snapshot<>request.snapshot THEN RAISE EXCEPTION 'Academic evidence changed after authorization; request a fresh exact revision' USING ERRCODE='23514'; END IF;
  INSERT INTO public.course_final_results(project_id,plan_id,version,supersedes_id,sources,results,actor_id) VALUES(pid,result_row.plan_id,result_row.version+1,result_row.id,snapshot->'sources',snapshot->'results',actor) RETURNING id INTO target;
  INSERT INTO public.course_final_revision_applications VALUES(request.id,target,actor,clock_timestamp());
 ELSE RAISE EXCEPTION 'Supported exceptional-result command required' USING ERRCODE='22023'; END IF;
 PERFORM public.smartpro_course_authority(actor,oid,permission,input->>'_actingRole');
 result:=jsonb_build_object('id',target,'projectId',pid);
 INSERT INTO public.document_command_receipts VALUES(actor,key,action,jsonb_build_object('offeringId',oid,'payload',input),result);
 INSERT INTO public.audit_events(actor_id,project_id,action,target_type,target_id,metadata) VALUES(actor,pid,'COURSE_'||action,'FINAL_RESULT_REVISION',target,jsonb_build_object('offeringId',oid,'input',input,'snapshot',snapshot,'appointmentId',appointment));
 RETURN result;
END $$;
CREATE FUNCTION public.smartpro_course_auxiliary(actor uuid,oid uuid,action text,input jsonb,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE q public.submission_requirement_policies%ROWTYPE; d public.course_deadline_versions%ROWTYPE; cfg jsonb; pid uuid; prior public.document_command_receipts%ROWTYPE; result jsonb; role text;
BEGIN
 role:=input->>'_actingRole';
 IF role IS NULL OR NOT public.smartpro_role_choices(actor) ? role OR key IS NULL OR key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' THEN RAISE EXCEPTION 'Current responsibility and request key required' USING ERRCODE='42501'; END IF;
 IF action='APPLY_REQUIREMENT' THEN PERFORM public.smartpro_course_authority(actor,oid,'REQUIREMENTS',role);
 ELSIF action='COMPLETE_MILESTONE' THEN
  pid:=(input->>'projectId')::uuid;
  IF public.smartpro_course_project_offering(pid) IS DISTINCT FROM oid THEN RAISE EXCEPTION 'Offering project required' USING ERRCODE='42501'; END IF;
  IF role IN('HOD','Coordinator') THEN PERFORM public.smartpro_course_authority(actor,oid,'DEADLINES',role);
  ELSIF role IN('Student','Faculty') THEN
   PERFORM 1 FROM public.curriculum_offerings WHERE id=oid FOR SHARE;
   IF NOT public.smartpro_document_scope(actor,pid,CASE WHEN role='Student' THEN 'student' ELSE 'faculty_read' END) THEN RAISE EXCEPTION 'Assigned academic work required' USING ERRCODE='42501'; END IF;
  ELSE RAISE EXCEPTION 'Assigned academic work required' USING ERRCODE='42501'; END IF;
  PERFORM 1 FROM public.projects WHERE id=pid FOR UPDATE;
 ELSE RAISE EXCEPTION 'Supported course operation required' USING ERRCODE='22023'; END IF;
 SELECT * INTO prior FROM public.document_command_receipts WHERE actor_id=actor AND request_key=key;
 IF FOUND THEN IF prior.action<>action OR prior.input<>jsonb_build_object('offeringId',oid,'payload',input) THEN RAISE EXCEPTION 'Retry changed' USING ERRCODE='23514'; END IF; RETURN prior.output; END IF;
 IF action='APPLY_REQUIREMENT' THEN
  SELECT f.configuration INTO cfg FROM public.course_plan_versions p JOIN public.course_framework_versions f ON f.id=p.framework_id WHERE p.offering_id=oid ORDER BY p.version DESC LIMIT 1;
  SELECT * INTO q FROM public.submission_requirement_policies WHERE id=(input->>'policyId')::uuid AND offering_id=oid;
  IF q.id IS NULL OR NOT coalesce(cfg->'requirementPolicyIds','[]') ? q.id::text THEN RAISE EXCEPTION 'This exact requirement version must be permitted by the approved course framework' USING ERRCODE='42501'; END IF;
  IF (SELECT policy_id FROM public.submission_offering_requirements WHERE offering_id=oid AND requirement_key=q.requirement_key) IS DISTINCT FROM (input->>'expectedPolicyId')::uuid THEN RAISE EXCEPTION 'Requirement changed; refresh' USING ERRCODE='23514'; END IF;
  INSERT INTO public.submission_offering_requirements VALUES(oid,q.id,q.requirement_key) ON CONFLICT(offering_id,requirement_key) DO UPDATE SET policy_id=excluded.policy_id;
  -- Do not revoke guide-linked or independent historical rights. The approved
  -- new requirement's reviewer list is realized by the existing PREPARE service.
  result:=jsonb_build_object('id',q.id,'requirementKey',q.requirement_key);
 ELSE
  SELECT * INTO d FROM public.course_deadline_versions WHERE id=(input->>'deadlineId')::uuid AND offering_id=oid;
  IF d.id IS NULL OR NOT d.active OR d.kind<>'MILESTONE' OR d.completion_role IS DISTINCT FROM role OR (d.project_id IS NOT NULL AND d.project_id<>pid) OR EXISTS(SELECT FROM public.course_deadline_versions WHERE offering_id=oid AND deadline_key=d.deadline_key AND version>d.version) OR EXISTS(SELECT FROM public.course_final_results WHERE project_id=pid) THEN RAISE EXCEPTION 'Current explicitly assigned unfinished milestone required' USING ERRCODE='42501'; END IF;
  INSERT INTO public.course_task_completions VALUES(d.id,pid,actor,clock_timestamp()) ON CONFLICT DO NOTHING;
  result:=jsonb_build_object('id',d.id,'projectId',pid,'status','COMPLETED');
 END IF;
 INSERT INTO public.document_command_receipts VALUES(actor,key,action,jsonb_build_object('offeringId',oid,'payload',input),result);
 INSERT INTO public.audit_events(actor_id,project_id,action,target_type,target_id,metadata) VALUES(actor,pid,'COURSE_'||action,'COURSE_TASK',coalesce(q.id,d.id),jsonb_build_object('offeringId',oid,'input',input,'result',result));
 RETURN result;
END $$;
DO $$ DECLARE def text; BEGIN
 def:=pg_get_functiondef('public.smartpro_course_deadline_command(uuid,uuid,text,jsonb,text)'::regprocedure);
 def:=replace(def,' INSERT INTO public.course_deadline_versions(',E' IF input->>''kind''=''MILESTONE'' AND (NOT coalesce(rules->''completionRoles'',''[]'') ? (input->>''completionRole'') OR input->>''completionRole'' IS NULL OR input->>''completionScope'' IS NULL OR input->>''completionScope'' NOT IN(''PROJECT'',''INDIVIDUAL'')) THEN RAISE EXCEPTION ''Explicit approved milestone completion responsibility and scope required'' USING ERRCODE=''42501''; END IF;\n INSERT INTO public.course_deadline_versions(');
 def:=replace(def,'notify_roles,active,actor_id)','notify_roles,active,actor_id,completion_role,completion_scope)');
 def:=replace(def,'(input->>''active'')::boolean,actor)','(input->>''active'')::boolean,actor,input->>''completionRole'',input->>''completionScope'')');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_course_command(uuid,uuid,text,jsonb,text)'::regprocedure);
 def:=replace(def,'INSERT INTO public.course_correction_authorizations VALUES(request.id,actor,(input->>''approved'')::boolean,clock_timestamp());','INSERT INTO public.course_correction_authorizations VALUES(request.id,actor,(input->>''approved'')::boolean,clock_timestamp(),(SELECT id FROM public.smartpro_course_coordinators(oid) WHERE user_id=actor AND ''CORRECTIONS''=ANY(responsibilities)));');EXECUTE def;
END $$;
CREATE FUNCTION public.smartpro_course_task_people(pid uuid)
RETURNS TABLE(user_id uuid, role text)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT m.user_id,'Student' FROM public.team_memberships m JOIN public.projects p ON p.team_id=m.team_id
 WHERE p.id=pid AND m.joined_at<=clock_timestamp() AND (m.left_at IS NULL OR clock_timestamp()<m.left_at)
 AND public.smartpro_document_scope(m.user_id,p.id,'student')
 UNION SELECT f.faculty_user_id,'Faculty' FROM public.faculty_assignments f JOIN public.projects p ON p.id=f.project_id
 WHERE p.id=pid AND f.valid_from<=clock_timestamp() AND (f.valid_until IS NULL OR clock_timestamp()<f.valid_until)
 AND public.smartpro_has_role(f.faculty_user_id,p.department_id,'FACULTY',clock_timestamp())
 UNION SELECT e.faculty_user_id,'Faculty' FROM public.evaluator_assignments e JOIN public.project_reviews r ON r.id=e.review_id JOIN public.projects p ON p.id=r.project_id
 WHERE p.id=pid AND public.smartpro_evaluator_active(e.id) AND public.smartpro_has_role(e.faculty_user_id,p.department_id,'FACULTY',clock_timestamp())
 UNION SELECT c.user_id,'Coordinator' FROM public.smartpro_course_coordinators(public.smartpro_course_project_offering(pid)) c
 UNION SELECT h.user_id,'HOD' FROM public.academic_hod_mandates h JOIN public.projects p ON p.department_id=h.department_id
 WHERE p.id=pid AND h.enabled AND public.smartpro_has_role(h.user_id,h.department_id,'HOD',clock_timestamp());
$$;
CREATE FUNCTION public.smartpro_course_milestone_complete(d public.course_deadline_versions,pid uuid,recipient uuid,acting_role text)
RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 WITH completions AS (
  SELECT c.actor_id FROM public.course_task_completions c JOIN public.course_deadline_versions v ON v.id=c.deadline_id
  WHERE v.offering_id=d.offering_id AND v.deadline_key=d.deadline_key AND v.completion_role=d.completion_role
   AND v.completion_scope=d.completion_scope AND c.project_id=pid
 ), expected AS (
  SELECT user_id FROM public.smartpro_course_task_people(pid) WHERE role=d.completion_role
 )
 SELECT CASE d.completion_scope
  WHEN 'PROJECT' THEN EXISTS(SELECT FROM completions)
  WHEN 'INDIVIDUAL' THEN CASE WHEN acting_role=d.completion_role THEN EXISTS(SELECT FROM completions WHERE actor_id=recipient)
    ELSE EXISTS(SELECT FROM expected) AND NOT EXISTS(SELECT user_id FROM expected EXCEPT SELECT actor_id FROM completions) END
  ELSE false END;
$$;
DO $$ DECLARE def text; first_at integer; last_at integer; BEGIN
 def:=pg_get_functiondef('public.smartpro_course_obligations()'::regprocedure);
 first_at:=strpos(def,' FROM scopes d CROSS JOIN LATERAL(');
 last_at:=strpos(def,' ORDER BY d.id,d.pid,u.user_id');
 IF first_at=0 OR last_at<=first_at THEN RAISE EXCEPTION 'Reviewed obligation projection required'; END IF;
 EXECUTE left(def,first_at-1)||' FROM scopes d CROSS JOIN LATERAL public.smartpro_course_task_people(d.pid) u WHERE u.role=ANY(d.notify_roles) OR u.role=d.completion_role'||replace(substr(def,last_at),' ORDER BY d.id,d.pid,u.user_id LIMIT 2000','');
 def:=pg_get_functiondef('public.smartpro_course_task_complete(uuid,uuid,uuid,text)'::regprocedure);
 first_at:=strpos(def,' ELSIF d.kind=''MILESTONE'' THEN');
 last_at:=strpos(def,' RETURN false;');
 IF first_at=0 OR last_at<=first_at THEN RAISE EXCEPTION 'Reviewed completion rules required'; END IF;
 EXECUTE left(def,first_at-1)||E' ELSIF d.kind=''MILESTONE'' THEN RETURN public.smartpro_course_milestone_complete(d,pid,recipient,role); END IF;\n'||substr(def,last_at);
 def:=pg_get_functiondef('public.smartpro_dispatch_course_notifications()'::regprocedure);
 EXECUTE replace(def,'SELECT * FROM public.smartpro_course_obligations() WHERE NOT completed AND bucket IS NOT NULL','SELECT o.* FROM public.smartpro_course_obligations() o JOIN public.course_deadline_versions d ON d.id=o.deadline_id WHERE NOT o.completed AND o.bucket IS NOT NULL AND o.recipient_role=ANY(d.notify_roles)');
 def:=pg_get_functiondef('public.smartpro_course_notifications(uuid,text)'::regprocedure);
 def:=replace(def,'SELECT n.id,n.bucket','SELECT n.id,n.deadline_id,n.bucket');
 EXECUTE replace(def,'''alerts'',','''tasks'',(SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY due_at),''[]'') FROM(SELECT d.id AS deadline_id,d.offering_id,d.name,d.kind,o.due_at,p.id AS project_id,p.title,(d.kind=''MILESTONE'' AND d.completion_role=role) AS can_complete FROM public.smartpro_course_obligations() o JOIN public.course_deadline_versions d ON d.id=o.deadline_id JOIN public.projects p ON p.id=o.project_id WHERE o.recipient_id=actor AND o.recipient_role=role AND NOT o.completed ORDER BY o.due_at LIMIT 100)x),''alerts'',');
 def:=pg_get_functiondef('public.smartpro_course_details(uuid,uuid,text)'::regprocedure);
 EXECUTE replace(def,'''overallResults'',','''finalRevisions'',CASE WHEN role=''Admin'' THEN ''[]''::jsonb ELSE (SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY created_at DESC),''[]'') FROM(SELECT q.*,a.approved,u.display_name,EXISTS(SELECT FROM public.course_final_revision_applications WHERE request_id=q.id) AS applied FROM public.course_final_revision_requests q JOIN public.users u ON u.id=q.requester_id LEFT JOIN public.course_final_revision_authorizations a ON a.request_id=q.id WHERE public.smartpro_course_project_offering(q.project_id)=oid ORDER BY q.created_at DESC LIMIT 100)x) END,''overallResults'',');
 def:=pg_get_functiondef('public.smartpro_course_command(uuid,uuid,text,jsonb,text)'::regprocedure);
 first_at:=strpos(def,' ELSIF action=''PUBLISH_FINAL'' THEN');
 last_at:=strpos(def,'  INSERT INTO public.course_final_results');
 IF first_at=0 OR last_at<=first_at OR strpos(substr(def,first_at),'  FOR stage IN SELECT')=0 THEN RAISE EXCEPTION 'Reviewed overall calculation required'; END IF;
 first_at:=first_at+strpos(substr(def,first_at),'  FOR stage IN SELECT')-1;
 EXECUTE left(def,first_at-1)||E'  cfg:=public.smartpro_course_calculate(pid);\n  totals:=cfg->''results''; sources:=cfg->''sources'';\n'||substr(def,last_at);
END $$;
DO $$ DECLARE def text; BEGIN
 def:=pg_get_functiondef('public.smartpro_role_workspace(uuid,text)'::regprocedure);
 IF strpos(def,' RETURN w;')=0 THEN RAISE EXCEPTION 'Reviewed workspace projection required'; END IF;
 EXECUTE replace(def,' RETURN w;', $projection$
 IF jsonb_typeof(w->'reviews')='array' THEN
  w:=jsonb_set(w,'{reviews}',(
   SELECT coalesce(jsonb_agg(
    CASE WHEN stage.value IS NULL THEN item.review ELSE item.review||jsonb_build_object('label',stage.value->>'name') END
    ORDER BY item.position),'[]'::jsonb)
   FROM jsonb_array_elements(w->'reviews') WITH ORDINALITY AS item(review,position)
   LEFT JOIN public.course_review_bindings b ON b.review_id=(item.review->>'id')::uuid
   LEFT JOIN public.course_plan_versions p ON p.id=b.plan_id
   LEFT JOIN public.course_framework_versions f ON f.id=p.framework_id
   LEFT JOIN LATERAL jsonb_array_elements(f.configuration->'stages') stage(value) ON stage.value->>'key'=b.stage_key
  ));
 END IF;
 RETURN w;$projection$);
END $$;
REVOKE ALL ON FUNCTION public.smartpro_course_task_people(uuid),public.smartpro_course_milestone_complete(public.course_deadline_versions,uuid,uuid,text) FROM PUBLIC,smartpro_runtime;
REVOKE ALL ON FUNCTION public.smartpro_course_calculate(uuid),public.smartpro_course_final_revision(uuid,uuid,text,jsonb,text),public.smartpro_course_auxiliary(uuid,uuid,text,jsonb,text) FROM PUBLIC,smartpro_runtime;
GRANT EXECUTE ON FUNCTION public.smartpro_course_final_revision(uuid,uuid,text,jsonb,text),public.smartpro_course_auxiliary(uuid,uuid,text,jsonb,text) TO smartpro_runtime;
COMMIT;
