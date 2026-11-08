-- Explicit approved deadline rules and deterministic in-app scheduling.
BEGIN;
DO $$ BEGIN IF to_regclass('public.course_final_results') IS NULL THEN RAISE EXCEPTION 'Reviewed 038 required'; END IF; END $$;
CREATE TABLE public.course_deadline_versions(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),offering_id uuid NOT NULL REFERENCES curriculum_offerings(id),deadline_key text NOT NULL,version integer NOT NULL,project_id uuid REFERENCES projects(id),kind text NOT NULL CHECK(kind IN('DOCUMENT','REVISION','REVIEW','EVALUATION','MILESTONE','FINAL_SUBMISSION')),target text NOT NULL,name text NOT NULL,due_at timestamptz NOT NULL,reminder_hours integer[] NOT NULL,notify_roles text[] NOT NULL,active boolean NOT NULL,actor_id uuid NOT NULL REFERENCES users(id),created_at timestamptz NOT NULL DEFAULT clock_timestamp(),UNIQUE(offering_id,deadline_key,version),CHECK(notify_roles<@ARRAY['Student','Faculty','Coordinator','HOD']::text[]));
CREATE TABLE public.course_task_completions(deadline_id uuid NOT NULL REFERENCES course_deadline_versions(id),project_id uuid NOT NULL REFERENCES projects(id),actor_id uuid NOT NULL REFERENCES users(id),created_at timestamptz NOT NULL DEFAULT clock_timestamp(),PRIMARY KEY(deadline_id,project_id,actor_id));
CREATE TABLE public.course_notifications(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),deadline_id uuid NOT NULL REFERENCES course_deadline_versions(id),project_id uuid NOT NULL REFERENCES projects(id),recipient_id uuid NOT NULL REFERENCES users(id),recipient_role text NOT NULL,bucket text NOT NULL,status text NOT NULL CHECK(status IN('ACTIVE','COMPLETED','SUPERSEDED')),created_at timestamptz NOT NULL DEFAULT clock_timestamp(),UNIQUE(deadline_id,project_id,recipient_id,recipient_role,bucket));
CREATE TABLE public.course_notification_history(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),notification_id uuid NOT NULL REFERENCES course_notifications(id),state text NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp());
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['course_deadline_versions','course_task_completions','course_notification_history'] LOOP EXECUTE format('CREATE TRIGGER retain_deadline_history BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation()',t); END LOOP;
 FOREACH t IN ARRAY ARRAY['course_deadline_versions','course_task_completions','course_notifications','course_notification_history'] LOOP EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,smartpro_runtime',t); END LOOP; END $$;
CREATE FUNCTION public.smartpro_course_deadline_effective(pid uuid,kind text,target text,baseline timestamptz) RETURNS timestamptz
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT coalesce((SELECT d.due_at FROM(SELECT DISTINCT ON(deadline_key) * FROM public.course_deadline_versions WHERE offering_id=public.smartpro_course_project_offering(pid) ORDER BY deadline_key,version DESC)d WHERE d.active AND (d.project_id IS NULL OR d.project_id=pid) AND d.kind=smartpro_course_deadline_effective.kind AND d.target=smartpro_course_deadline_effective.target ORDER BY (d.project_id IS NOT NULL) DESC,d.created_at DESC LIMIT 1),baseline);
$$;
CREATE FUNCTION public.smartpro_course_document_close(pid uuid,req text,baseline timestamptz) RETURNS timestamptz
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT public.smartpro_course_deadline_effective(pid,CASE WHEN EXISTS(SELECT FROM public.submission_cases WHERE project_id=pid AND requirement_key=req AND state='CHANGES_REQUESTED') THEN 'REVISION' ELSE 'DOCUMENT' END,req,public.smartpro_course_deadline_effective(pid,'DOCUMENT',req,baseline));
$$;
CREATE FUNCTION public.smartpro_course_deadline_command(actor uuid,oid uuid,action text,input jsonb,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE framework jsonb; rules jsonb; prior public.document_command_receipts%ROWTYPE; old public.course_deadline_versions%ROWTYPE; result jsonb; target_id uuid; due timestamptz; baseline timestamptz; dept uuid;
BEGIN
 PERFORM public.smartpro_course_authority(actor,oid,'DEADLINES',input->>'_actingRole');
 SELECT department_id INTO dept FROM public.curriculum_offerings WHERE id=oid;
 SELECT f.configuration INTO framework FROM public.course_plan_versions p JOIN public.course_framework_versions f ON f.id=p.framework_id WHERE p.offering_id=oid ORDER BY p.version DESC LIMIT 1;
 rules:=framework->'deadlineRules';
 IF action<>'DEADLINE' OR rules IS NULL OR NOT rules->'kinds' ? (input->>'kind') THEN RAISE EXCEPTION 'Explicit approved deadline framework required' USING ERRCODE='42501'; END IF;
 IF key IS NULL OR key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' THEN RAISE EXCEPTION 'Request key required' USING ERRCODE='22023'; END IF;
 SELECT * INTO prior FROM public.document_command_receipts WHERE actor_id=actor AND request_key=key;
 IF FOUND THEN IF prior.action<>'COURSE_DEADLINE' OR prior.input<>jsonb_build_object('offeringId',oid,'payload',input) THEN RAISE EXCEPTION 'Retry changed' USING ERRCODE='23514'; END IF; RETURN prior.output; END IF;
 SELECT * INTO old FROM public.course_deadline_versions WHERE offering_id=oid AND deadline_key=input->>'deadlineKey' ORDER BY version DESC LIMIT 1;
 IF coalesce(old.version,0) IS DISTINCT FROM (input->>'expectedVersion')::integer THEN RAISE EXCEPTION 'Deadline changed; refresh' USING ERRCODE='23514'; END IF;
 due:=(input->>'dueAt')::timestamptz;
 IF length(btrim(input->>'deadlineKey')) NOT BETWEEN 1 AND 80 OR length(btrim(input->>'name')) NOT BETWEEN 1 AND 120 OR jsonb_typeof(input->'reminderHours') IS DISTINCT FROM 'array' OR jsonb_array_length(input->'reminderHours')>20 OR due IS NULL OR due<(rules->>'earliestAt')::timestamptz OR due>(rules->>'latestAt')::timestamptz OR EXISTS(SELECT FROM jsonb_array_elements_text(input->'reminderHours') x WHERE x::integer<0 OR x::integer>(rules->>'maxReminderHours')::integer) THEN RAISE EXCEPTION 'Approved deadline bounds and reminder timing required' USING ERRCODE='22023'; END IF;
 IF input->>'projectId' IS NOT NULL AND public.smartpro_course_project_offering((input->>'projectId')::uuid) IS DISTINCT FROM oid THEN RAISE EXCEPTION 'Offering project required' USING ERRCODE='42501'; END IF;
 IF input->>'kind' IN('DOCUMENT','REVISION') THEN
  SELECT min(q.closes_at) INTO baseline FROM public.submission_requirement_policies q WHERE q.offering_id=oid AND q.requirement_key=input->>'target' AND (EXISTS(SELECT FROM public.submission_offering_requirements h WHERE h.policy_id=q.id) OR EXISTS(SELECT FROM public.submission_requirement_bindings b JOIN public.submission_cases c ON c.id=b.case_id WHERE b.policy_id=q.id AND (input->>'projectId' IS NULL OR c.project_id=(input->>'projectId')::uuid)));
  IF baseline IS NULL OR due>baseline+make_interval(days=>(framework->>'maxExtensionDays')::integer) THEN RAISE EXCEPTION 'Configured document and permitted extension required' USING ERRCODE='23514'; END IF;
 ELSIF input->>'kind' IN('REVIEW','EVALUATION') AND NOT EXISTS(SELECT FROM jsonb_array_elements(framework->'stages') s WHERE s->>'key'=input->>'target' AND due<=(s->>'deadline')::timestamptz+make_interval(days=>(framework->>'maxExtensionDays')::integer)) THEN RAISE EXCEPTION 'Configured stage and permitted extension required' USING ERRCODE='23514'; END IF;
 INSERT INTO public.course_deadline_versions(offering_id,deadline_key,version,project_id,kind,target,name,due_at,reminder_hours,notify_roles,active,actor_id) VALUES(oid,input->>'deadlineKey',coalesce(old.version,0)+1,(input->>'projectId')::uuid,input->>'kind',input->>'target',btrim(input->>'name'),due,ARRAY(SELECT value::integer FROM jsonb_array_elements_text(input->'reminderHours')),ARRAY(SELECT value FROM jsonb_array_elements_text(input->'notifyRoles')),(input->>'active')::boolean,actor) RETURNING id INTO target_id;
 PERFORM public.smartpro_course_authority(actor,oid,'DEADLINES',input->>'_actingRole');
 result:=jsonb_build_object('id',target_id,'version',coalesce(old.version,0)+1);
 INSERT INTO public.document_command_receipts VALUES(actor,key,'COURSE_DEADLINE',jsonb_build_object('offeringId',oid,'payload',input),result);
 INSERT INTO public.audit_events(actor_id,action,target_type,target_id,metadata) VALUES(actor,'COURSE_DEADLINE_CHANGED','OFFERING',oid,jsonb_build_object('before',to_jsonb(old),'input',input,'result',result));
 RETURN result;
END $$;
CREATE FUNCTION public.smartpro_course_task_complete(did uuid,pid uuid,recipient uuid,role text) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE d public.course_deadline_versions%ROWTYPE; state text;
BEGIN
 SELECT * INTO d FROM public.course_deadline_versions WHERE id=did;
 IF EXISTS(SELECT FROM public.course_final_results WHERE project_id=pid) THEN RETURN true; END IF;
 IF d.kind IN('DOCUMENT','REVISION') THEN
  SELECT c.state INTO state FROM public.submission_cases c WHERE c.project_id=pid AND c.requirement_key=d.target;
  RETURN CASE WHEN role='Student' THEN coalesce(state IN('AWAITING_REVIEW','APPROVED'),false) WHEN role='Faculty' THEN state IS DISTINCT FROM 'AWAITING_REVIEW' ELSE coalesce(state='APPROVED',false) END;
 ELSIF d.kind='EVALUATION' THEN
  RETURN EXISTS(SELECT FROM public.course_review_bindings b JOIN public.project_reviews r ON r.id=b.review_id WHERE r.project_id=pid AND b.stage_key=d.target) AND NOT EXISTS(SELECT FROM public.course_review_bindings b JOIN public.project_reviews r ON r.id=b.review_id JOIN public.assessments a ON a.review_id=r.id JOIN public.evaluator_assignments e ON e.id=a.evaluator_assignment_id WHERE r.project_id=pid AND b.stage_key=d.target AND public.smartpro_evaluator_active(e.id) AND a.state<>'FINALIZED' AND (role<>'Faculty' OR e.faculty_user_id=recipient));
 ELSIF d.kind='REVIEW' THEN RETURN EXISTS(SELECT FROM public.course_review_bindings b JOIN public.project_reviews r ON r.id=b.review_id WHERE r.project_id=pid AND b.stage_key=d.target AND r.review_state IN('FINALIZED','RELEASED'));
 ELSIF d.kind='MILESTONE' THEN RETURN EXISTS(SELECT FROM public.course_task_completions c JOIN public.course_deadline_versions v ON v.id=c.deadline_id WHERE v.offering_id=d.offering_id AND v.deadline_key=d.deadline_key AND c.project_id=pid AND (role IN('Coordinator','HOD') OR c.actor_id=recipient)); END IF;
 RETURN false;
END $$;
CREATE FUNCTION public.smartpro_course_obligations() RETURNS TABLE(deadline_id uuid,project_id uuid,recipient_id uuid,recipient_role text,due_at timestamptz,bucket text,completed boolean)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 WITH current_deadlines AS(SELECT DISTINCT ON(offering_id,deadline_key) * FROM public.course_deadline_versions ORDER BY offering_id,deadline_key,version DESC), scopes AS(
 SELECT d.*,p.id AS pid FROM current_deadlines d JOIN public.teams t ON t.curriculum_offering_id=d.offering_id JOIN public.projects p ON p.team_id=t.id WHERE d.active AND (d.project_id IS NULL OR d.project_id=p.id) AND EXISTS(SELECT FROM public.smartpro_course_coordinators(d.offering_id)))
 SELECT d.id,d.pid,u.user_id,u.role,d.due_at,CASE WHEN d.due_at<=clock_timestamp() THEN 'OVERDUE' ELSE 'DUE:'||(SELECT min(h) FROM unnest(d.reminder_hours) h WHERE d.due_at<=clock_timestamp()+make_interval(hours=>h))::text END,
 public.smartpro_course_task_complete(d.id,d.pid,u.user_id,u.role)
 FROM scopes d CROSS JOIN LATERAL(
 SELECT m.user_id,'Student'::text AS role FROM public.team_memberships m JOIN public.projects p ON p.team_id=m.team_id WHERE p.id=d.pid AND m.joined_at<=clock_timestamp() AND (m.left_at IS NULL OR clock_timestamp()<m.left_at) AND public.smartpro_has_role(m.user_id,p.department_id,'STUDENT',clock_timestamp()) AND public.smartpro_document_scope(m.user_id,p.id,'student')
 UNION SELECT f.faculty_user_id,'Faculty' FROM public.faculty_assignments f JOIN public.projects p ON p.id=f.project_id WHERE f.project_id=d.pid AND f.valid_from<=clock_timestamp() AND (f.valid_until IS NULL OR clock_timestamp()<f.valid_until) AND public.smartpro_has_role(f.faculty_user_id,p.department_id,'FACULTY',clock_timestamp())
 UNION SELECT e.faculty_user_id,'Faculty' FROM public.evaluator_assignments e JOIN public.project_reviews r ON r.id=e.review_id JOIN public.projects p ON p.id=r.project_id WHERE r.project_id=d.pid AND public.smartpro_evaluator_active(e.id) AND public.smartpro_has_role(e.faculty_user_id,p.department_id,'FACULTY',clock_timestamp())
 UNION SELECT c.user_id,'Coordinator' FROM public.smartpro_course_coordinators(d.offering_id) c
 UNION SELECT h.user_id,'HOD' FROM public.academic_hod_mandates h JOIN public.curriculum_offerings o ON o.department_id=h.department_id WHERE o.id=d.offering_id AND h.enabled AND public.smartpro_has_role(h.user_id,h.department_id,'HOD',clock_timestamp())
 )u WHERE u.role=ANY(d.notify_roles) ORDER BY d.id,d.pid,u.user_id LIMIT 2000;
$$;
CREATE FUNCTION public.smartpro_dispatch_course_notifications() RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE generated integer:=0; resolved integer:=0;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('smartpro:course-notifications',0));
 WITH obligations AS MATERIALIZED(SELECT * FROM public.smartpro_course_obligations()),changed AS(
 UPDATE public.course_notifications n SET status=CASE WHEN EXISTS(SELECT FROM obligations o WHERE o.deadline_id=n.deadline_id AND o.project_id=n.project_id AND o.recipient_id=n.recipient_id AND o.recipient_role=n.recipient_role AND o.completed) THEN 'COMPLETED' ELSE 'SUPERSEDED' END
 WHERE n.status='ACTIVE' AND NOT EXISTS(SELECT FROM obligations o WHERE o.deadline_id=n.deadline_id AND o.project_id=n.project_id AND o.recipient_id=n.recipient_id AND o.recipient_role=n.recipient_role AND NOT o.completed AND o.bucket=n.bucket) RETURNING id,status)
 INSERT INTO public.course_notification_history(notification_id,state) SELECT id,status FROM changed;
 GET DIAGNOSTICS resolved=ROW_COUNT;
 WITH pending AS(SELECT * FROM public.smartpro_course_obligations() WHERE NOT completed AND bucket IS NOT NULL),generated AS(
 INSERT INTO public.course_notifications(deadline_id,project_id,recipient_id,recipient_role,bucket,status) SELECT deadline_id,project_id,recipient_id,recipient_role,bucket,'ACTIVE' FROM pending
 ON CONFLICT(deadline_id,project_id,recipient_id,recipient_role,bucket) DO UPDATE SET status='ACTIVE' WHERE course_notifications.status<>'ACTIVE' RETURNING id)
 INSERT INTO public.course_notification_history(notification_id,state) SELECT id,'GENERATED_IN_APP' FROM generated;
 GET DIAGNOSTICS generated=ROW_COUNT;
 RETURN jsonb_build_object('generatedInApp',generated,'resolved',resolved);
END $$;
CREATE FUNCTION public.smartpro_course_notifications(actor uuid,role text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF NOT public.smartpro_role_choices(actor) ? role THEN RAISE EXCEPTION 'Current responsibility required' USING ERRCODE='42501'; END IF;
 RETURN jsonb_build_object('alerts',(SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY due_at),'[]') FROM(SELECT n.id,n.bucket,n.status,d.name,d.kind,d.due_at,p.id AS project_id,p.title FROM public.course_notifications n JOIN public.course_deadline_versions d ON d.id=n.deadline_id JOIN public.projects p ON p.id=n.project_id WHERE n.recipient_id=actor AND n.recipient_role=role AND n.status='ACTIVE' AND EXISTS(SELECT FROM public.smartpro_course_obligations() o WHERE o.deadline_id=d.id AND o.project_id=p.id AND o.recipient_id=actor AND o.recipient_role=role AND NOT o.completed) ORDER BY d.due_at LIMIT 100)x));
END $$;
-- Effective deadlines are authorized overlays; pinned policies remain immutable.
DO $$ DECLARE def text; BEGIN
 def:=pg_get_functiondef('public.smartpro_document_command(uuid,uuid,text,jsonb,text)'::regprocedure);
 def:=replace(def,'clock_timestamp()<rule.closes_at','clock_timestamp()<public.smartpro_course_document_close(p.id,rule.requirement_key,rule.closes_at)');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_course_command(uuid,uuid,text,jsonb,text)'::regprocedure);
 def:=replace(def,'clock_timestamp()>=rule.closes_at','clock_timestamp()>=public.smartpro_course_document_close(pid,rule.requirement_key,rule.closes_at)');EXECUTE def;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_course_deadline_effective(uuid,text,text,timestamptz),public.smartpro_course_document_close(uuid,text,timestamptz),public.smartpro_course_deadline_command(uuid,uuid,text,jsonb,text),public.smartpro_course_task_complete(uuid,uuid,uuid,text),public.smartpro_course_obligations(),public.smartpro_dispatch_course_notifications(),public.smartpro_course_notifications(uuid,text) FROM PUBLIC,smartpro_runtime;
GRANT EXECUTE ON FUNCTION public.smartpro_course_deadline_command(uuid,uuid,text,jsonb,text),public.smartpro_dispatch_course_notifications(),public.smartpro_course_notifications(uuid,text) TO smartpro_runtime;
COMMIT;
