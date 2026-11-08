-- Approved course plans extend existing review/rubric/result services.
BEGIN;
DO $$ BEGIN IF to_regclass('public.course_coordinator_versions') IS NULL THEN RAISE EXCEPTION 'Reviewed 037 required'; END IF; END $$;
CREATE TABLE public.course_framework_versions(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),offering_id uuid NOT NULL REFERENCES curriculum_offerings(id),version integer NOT NULL,configuration jsonb NOT NULL,actor_id uuid NOT NULL REFERENCES users(id),authority jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),UNIQUE(offering_id,version));
CREATE TABLE public.course_plan_versions(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),offering_id uuid NOT NULL REFERENCES curriculum_offerings(id),framework_id uuid NOT NULL REFERENCES course_framework_versions(id),version integer NOT NULL,schedules jsonb NOT NULL,actor_id uuid NOT NULL REFERENCES users(id),created_at timestamptz NOT NULL DEFAULT clock_timestamp(),UNIQUE(offering_id,version));
CREATE TABLE public.course_project_plans(project_id uuid PRIMARY KEY REFERENCES projects(id),plan_id uuid NOT NULL REFERENCES course_plan_versions(id));
CREATE TABLE public.course_review_bindings(review_id uuid PRIMARY KEY REFERENCES project_reviews(id),plan_id uuid NOT NULL REFERENCES course_plan_versions(id),stage_key text NOT NULL);
CREATE TABLE public.course_guide_evaluators(assignment_id uuid PRIMARY KEY REFERENCES evaluator_assignments(id),guide_assignment_id uuid NOT NULL REFERENCES faculty_assignments(id),created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE public.course_correction_requests(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),offering_id uuid NOT NULL REFERENCES curriculum_offerings(id),review_id uuid NOT NULL REFERENCES project_reviews(id),assessment_id uuid NOT NULL REFERENCES assessments(id),requester_id uuid NOT NULL REFERENCES users(id),expected_revision integer NOT NULL,scores jsonb NOT NULL,note text,created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE public.course_correction_authorizations(request_id uuid PRIMARY KEY REFERENCES course_correction_requests(id),actor_id uuid NOT NULL REFERENCES users(id),approved boolean NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE public.course_correction_applications(request_id uuid PRIMARY KEY REFERENCES course_correction_requests(id),actor_id uuid NOT NULL REFERENCES users(id),created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE public.course_final_results(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),project_id uuid NOT NULL REFERENCES projects(id),plan_id uuid NOT NULL REFERENCES course_plan_versions(id),version integer NOT NULL,supersedes_id uuid REFERENCES course_final_results(id),sources jsonb NOT NULL,results jsonb NOT NULL,actor_id uuid NOT NULL REFERENCES users(id),created_at timestamptz NOT NULL DEFAULT clock_timestamp(),UNIQUE(project_id,version));
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['course_framework_versions','course_plan_versions','course_project_plans','course_review_bindings','course_guide_evaluators','course_correction_requests','course_correction_authorizations','course_correction_applications','course_final_results'] LOOP
 EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,smartpro_runtime',t);
 EXECUTE format('CREATE TRIGGER retain_course_history BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation()',t);
END LOOP; END $$;
CREATE FUNCTION public.smartpro_course_project_offering(pid uuid) RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$ SELECT t.curriculum_offering_id FROM public.projects p JOIN public.teams t ON t.id=p.team_id WHERE p.id=pid $$;
CREATE FUNCTION public.smartpro_course_correction_guard(actor uuid,rid uuid,input jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE request public.course_correction_requests%ROWTYPE;
BEGIN
 SELECT q.* INTO request FROM public.course_correction_requests q JOIN public.course_correction_authorizations a ON a.request_id=q.id AND a.approved
 WHERE q.review_id=rid AND q.assessment_id=(input->>'assessmentId')::uuid AND q.requester_id=actor AND q.expected_revision=(input->>'expectedReviewRevision')::integer AND q.scores=input->'scores'
 AND NOT EXISTS(SELECT FROM public.course_correction_applications WHERE request_id=q.id) ORDER BY q.created_at LIMIT 1 FOR UPDATE OF q;
 IF NOT FOUND THEN RAISE EXCEPTION 'Specific coordinator-authorized correction required' USING ERRCODE='42501'; END IF;
 IF EXISTS(SELECT FROM public.course_final_results WHERE project_id=(SELECT project_id FROM public.project_reviews WHERE id=rid)) AND NOT coalesce((SELECT (f.configuration->>'allowFinalCorrections')::boolean FROM public.course_review_bindings b JOIN public.course_plan_versions p ON p.id=b.plan_id JOIN public.course_framework_versions f ON f.id=p.framework_id WHERE b.review_id=rid),false) THEN RAISE EXCEPTION 'Exceptional final correction policy required' USING ERRCODE='42501'; END IF;
 INSERT INTO public.course_correction_applications VALUES(request.id,actor,clock_timestamp());
END $$;
CREATE FUNCTION public.smartpro_course_command(actor uuid,oid uuid,action text,input jsonb,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE o public.curriculum_offerings%ROWTYPE; prior public.document_command_receipts%ROWTYPE; auth jsonb; role text; cfg jsonb; stage jsonb; plan public.course_plan_versions%ROWTYPE; framework public.course_framework_versions%ROWTYPE;
 pid uuid; target uuid; rid uuid; uid uuid; guide public.faculty_assignments%ROWTYPE; assignment uuid; policy uuid; result jsonb; request public.course_correction_requests%ROWTYPE; c public.submission_cases%ROWTYPE; rule public.submission_requirement_policies%ROWTYPE; attempt uuid; source public.academic_result_versions%ROWTYPE; sources jsonb:='[]'; totals jsonb:='{}'; roster text[]; member text; total numeric; maximum numeric; version integer; previous uuid;
BEGIN
 SELECT * INTO o FROM public.curriculum_offerings WHERE id=oid;
 IF NOT FOUND OR key IS NULL OR key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' OR jsonb_typeof(input) IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'Scoped course command required' USING ERRCODE='22023'; END IF;
 role:=input->>'_actingRole';
 IF NOT public.smartpro_role_choices(actor) ? role THEN RAISE EXCEPTION 'Current responsibility required' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.academic_governance_settings WHERE department_id=o.department_id AND enabled FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Academic controls disabled' USING ERRCODE='42501'; END IF;
 IF action='FRAMEWORK' THEN
  IF role='HOD' THEN auth:=public.smartpro_academic_authority(actor,o.department_id,true);
  ELSIF role='Admin' THEN auth:=public.smartpro_operational_authority(actor,o.department_id,input->'authority');
  ELSE RAISE EXCEPTION 'HOD framework authority required' USING ERRCODE='42501'; END IF;
 ELSIF action IN('REQUEST_CORRECTION','APPLY_CORRECTION','REOPEN_SYNOPSIS') THEN
  IF role<>'Faculty' OR NOT public.smartpro_has_role(actor,o.department_id,'FACULTY',clock_timestamp()) THEN RAISE EXCEPTION 'Current assigned faculty required' USING ERRCODE='42501'; END IF;
 ELSE
  PERFORM public.smartpro_course_authority(actor,oid,CASE action WHEN 'PLAN' THEN 'PLAN' WHEN 'CREATE_STAGE' THEN 'EVALUATORS' WHEN 'AUTHORIZE_CORRECTION' THEN 'CORRECTIONS' WHEN 'PUBLISH_FINAL' THEN 'RESULTS' ELSE action END,role);
 END IF;
 PERFORM 1 FROM public.curriculum_offerings WHERE id=oid FOR UPDATE;
 PERFORM pg_advisory_xact_lock(hashtextextended(actor::text||':course-command:'||key,0));
 SELECT * INTO prior FROM public.document_command_receipts WHERE actor_id=actor AND request_key=key;
 IF FOUND THEN IF prior.action<>'COURSE_'||action OR prior.input<>jsonb_build_object('offeringId',oid,'payload',input) THEN RAISE EXCEPTION 'Retry changed' USING ERRCODE='23514'; END IF; RETURN prior.output; END IF;
 SELECT * INTO plan FROM public.course_plan_versions WHERE offering_id=oid ORDER BY version DESC LIMIT 1;
 IF plan.id IS NOT NULL THEN SELECT * INTO framework FROM public.course_framework_versions WHERE id=plan.framework_id; END IF;
 IF action IN('CREATE_STAGE','PUBLISH_FINAL') THEN
  SELECT p.* INTO plan FROM public.course_plan_versions p WHERE p.id=coalesce((SELECT plan_id FROM public.course_project_plans WHERE project_id=(input->>'projectId')::uuid),plan.id);
  SELECT * INTO framework FROM public.course_framework_versions WHERE id=plan.framework_id;
 END IF;
 IF action='FRAMEWORK' THEN
  cfg:=input->'configuration';
  IF cfg IS NULL OR NOT cfg ?& ARRAY['stages','method','rounding','decimalPlaces','scale','allowFinalCorrections','outsidePanelAuthorizer','maxExtensionDays','publicationRoles'] OR EXISTS(SELECT FROM jsonb_each(cfg) WHERE value='null'::jsonb) OR jsonb_typeof(cfg->'stages') IS DISTINCT FROM 'array' OR jsonb_array_length(cfg->'stages') NOT BETWEEN 1 AND 10 OR cfg->>'method' NOT IN('SINGLE_RAW','WEIGHTED_NORMALIZED') OR cfg->>'rounding'<>'HALF_UP' OR (cfg->>'decimalPlaces')::integer NOT BETWEEN 0 AND 4 OR (cfg->>'scale')::numeric<=0 OR jsonb_typeof(cfg->'allowFinalCorrections') IS DISTINCT FROM 'boolean' OR jsonb_typeof(cfg->'outsidePanelAuthorizer') IS DISTINCT FROM 'boolean' OR (cfg->>'maxExtensionDays')::integer NOT BETWEEN 0 AND 366 OR jsonb_typeof(cfg->'publicationRoles') IS DISTINCT FROM 'array' OR jsonb_array_length(cfg->'publicationRoles')=0 OR EXISTS(SELECT FROM jsonb_array_elements_text(cfg->'publicationRoles') x WHERE x NOT IN('HOD','Coordinator')) THEN RAISE EXCEPTION 'Explicit complete approved framework required' USING ERRCODE='22023'; END IF;
  IF cfg->>'method'='SINGLE_RAW' AND jsonb_array_length(cfg->'stages')<>1 THEN RAISE EXCEPTION 'Single assessment requires exactly one stage' USING ERRCODE='23514'; END IF;
  IF (SELECT sum((s->>'weight')::numeric) FROM jsonb_array_elements(cfg->'stages') s)<>100 OR (SELECT count(DISTINCT s->>'key') FROM jsonb_array_elements(cfg->'stages') s)<>jsonb_array_length(cfg->'stages') THEN RAISE EXCEPTION 'Distinct stage keys and explicit weights totaling 100 required' USING ERRCODE='23514'; END IF;
  IF cfg ? 'deadlineRules' THEN
   IF jsonb_typeof(cfg->'deadlineRules') IS DISTINCT FROM 'object' OR NOT (cfg->'deadlineRules') ?& ARRAY['kinds','earliestAt','latestAt','maxReminderHours'] OR EXISTS(SELECT FROM jsonb_each(cfg->'deadlineRules') WHERE value='null'::jsonb) OR jsonb_typeof(cfg->'deadlineRules'->'kinds') IS DISTINCT FROM 'array' OR EXISTS(SELECT FROM jsonb_array_elements_text(cfg->'deadlineRules'->'kinds') k WHERE k NOT IN('DOCUMENT','REVISION','REVIEW','EVALUATION','MILESTONE','FINAL_SUBMISSION')) OR (cfg->'deadlineRules'->>'earliestAt')::timestamptz>=(cfg->'deadlineRules'->>'latestAt')::timestamptz OR (cfg->'deadlineRules'->>'maxReminderHours')::integer NOT BETWEEN 0 AND 8784 THEN RAISE EXCEPTION 'Complete explicit deadline authority required' USING ERRCODE='22023'; END IF;
  END IF;
  FOR stage IN SELECT value FROM jsonb_array_elements(cfg->'stages') LOOP
   IF NOT stage ?& ARRAY['key','name','schemeVersionId','schemeModeId','policyId','weight','required','opensAt','deadline'] OR EXISTS(SELECT FROM jsonb_each(stage) WHERE value='null'::jsonb) OR length(btrim(stage->>'name')) NOT BETWEEN 1 AND 120 OR length(btrim(stage->>'key')) NOT BETWEEN 1 AND 80 OR (stage->>'weight')::numeric NOT BETWEEN 0 AND 100 OR jsonb_typeof(stage->'required') IS DISTINCT FROM 'boolean' OR (stage->>'opensAt')::timestamptz>=(stage->>'deadline')::timestamptz THEN RAISE EXCEPTION 'Complete stage configuration required' USING ERRCODE='22023'; END IF;
   PERFORM 1 FROM public.scheme_versions v JOIN public.evaluation_schemes es ON es.id=v.scheme_id JOIN public.review_definitions d ON d.id=v.review_definition_id JOIN public.scheme_modes m ON m.scheme_version_id=v.id
    WHERE v.id=(stage->>'schemeVersionId')::uuid AND m.id=(stage->>'schemeModeId')::uuid AND v.state='ACTIVE' AND es.department_id=o.department_id AND v.cycle_id=o.cycle_id AND d.policy_version_id IN(SELECT r.policy_version_id FROM public.offering_project_registration_policies h JOIN public.project_registration_policy_versions r ON r.id=h.registration_policy_version_id WHERE h.offering_id=oid) FOR SHARE OF v,es,d,m;
   IF NOT FOUND OR NOT EXISTS(SELECT FROM public.academic_evaluation_policies WHERE id=(stage->>'policyId')::uuid AND department_id=o.department_id) THEN RAISE EXCEPTION 'Applicable approved rubric and aggregation policy required' USING ERRCODE='23514'; END IF;
  END LOOP;
  SELECT coalesce(max(v.version),0)+1 INTO version FROM public.course_framework_versions v WHERE offering_id=oid;
  IF version-1 IS DISTINCT FROM (input->>'expectedVersion')::integer THEN RAISE EXCEPTION 'Framework changed; refresh' USING ERRCODE='23514'; END IF;
  INSERT INTO public.course_framework_versions(offering_id,version,configuration,actor_id,authority) VALUES(oid,version,cfg,actor,coalesce(auth,'{}')||jsonb_build_object('recordedRole',role,'instruction',input->'authority')) RETURNING id INTO target;
 ELSIF action='PLAN' THEN
  SELECT * INTO framework FROM public.course_framework_versions WHERE id=(input->>'frameworkId')::uuid AND offering_id=oid;
  IF NOT FOUND OR coalesce(plan.version,0) IS DISTINCT FROM (input->>'expectedVersion')::integer THEN RAISE EXCEPTION 'Approved framework and current plan revision required' USING ERRCODE='23514'; END IF;
  FOR stage IN SELECT value FROM jsonb_array_elements(framework.configuration->'stages') LOOP
   IF input->'schedules'->>(stage->>'key') IS NULL OR (input->'schedules'->>(stage->>'key'))::timestamptz<(stage->>'opensAt')::timestamptz OR (input->'schedules'->>(stage->>'key'))::timestamptz>(stage->>'deadline')::timestamptz THEN RAISE EXCEPTION 'Schedule every approved stage within its authorized bounds' USING ERRCODE='23514'; END IF;
  END LOOP;
  INSERT INTO public.course_plan_versions(offering_id,framework_id,version,schedules,actor_id) VALUES(oid,framework.id,coalesce(plan.version,0)+1,input->'schedules',actor) RETURNING id INTO target;
 ELSIF action='CREATE_STAGE' THEN
  pid:=(input->>'projectId')::uuid;
  IF public.smartpro_course_project_offering(pid) IS DISTINCT FROM oid OR EXISTS(SELECT FROM public.course_final_results WHERE project_id=pid) THEN RAISE EXCEPTION 'Unfinished offering project required' USING ERRCODE='42501'; END IF;
  PERFORM 1 FROM public.projects WHERE id=pid FOR UPDATE;
  IF EXISTS(SELECT FROM public.course_review_bindings b JOIN public.project_reviews r ON r.id=b.review_id WHERE r.project_id=pid AND b.stage_key=input->>'stageKey') THEN RAISE EXCEPTION 'Stage already assigned; preserve its review history' USING ERRCODE='23514'; END IF;
  SELECT value INTO stage FROM jsonb_array_elements(framework.configuration->'stages') WHERE value->>'key'=input->>'stageKey';
  IF stage IS NULL THEN RAISE EXCEPTION 'Apply an approved course plan first' USING ERRCODE='23514'; END IF;
  SELECT * INTO guide FROM public.faculty_assignments WHERE project_id=pid AND assignment_type='GUIDE' AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until) FOR UPDATE;
  IF guide.id IS NULL THEN RAISE EXCEPTION 'Allocate the primary guide before assigning the stage' USING ERRCODE='23514'; END IF;
  SELECT jsonb_agg(DISTINCT f) INTO cfg FROM(SELECT value AS f FROM jsonb_array_elements_text(input->'facultyIds') UNION SELECT guide.faculty_user_id::text) x;
  result:=public.smartpro_initial_evaluation_pre038(actor,o.department_id,'CREATE_REVIEW',jsonb_build_object('projectId',pid,'schemeVersionId',stage->'schemeVersionId','schemeModeId',stage->'schemeModeId','policyId',stage->'policyId','facultyIds',cfg,'reason',coalesce(input->>'reason','')),'course-review:'||encode(sha256(convert_to(actor::text||key,'UTF8')),'hex'));
  rid:=(result->>'reviewId')::uuid;
  INSERT INTO public.course_project_plans VALUES(pid,plan.id) ON CONFLICT(project_id) DO NOTHING;
  INSERT INTO public.course_review_bindings VALUES(rid,plan.id,stage->>'key');
  UPDATE public.project_reviews SET scheduled_at=(plan.schedules->>(stage->>'key'))::timestamptz WHERE id=rid;
  INSERT INTO public.course_guide_evaluators SELECT e.id,guide.id,clock_timestamp() FROM public.evaluator_assignments e WHERE e.review_id=rid AND e.faculty_user_id=guide.faculty_user_id;
  target:=rid;
 ELSIF action='REOPEN_SYNOPSIS' THEN
  pid:=(input->>'projectId')::uuid;
  PERFORM 1 FROM public.projects WHERE id=pid AND public.smartpro_course_project_offering(id)=oid FOR UPDATE;
  IF NOT FOUND OR EXISTS(SELECT FROM public.course_final_results WHERE project_id=pid) THEN RAISE EXCEPTION 'Ordinary revisions are closed after overall final publication' USING ERRCODE='42501'; END IF;
  SELECT * INTO guide FROM public.faculty_assignments WHERE project_id=pid AND faculty_user_id=actor AND assignment_type='GUIDE' AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until) FOR SHARE;
  IF guide.id IS NULL OR NOT public.smartpro_requirement_access(actor,pid,'SYNOPSIS','Faculty',true) THEN RAISE EXCEPTION 'Current authorized primary guide required' USING ERRCODE='42501'; END IF;
  SELECT * INTO c FROM public.submission_cases WHERE project_id=pid AND requirement_key='SYNOPSIS' FOR UPDATE;
  SELECT q.* INTO rule FROM public.submission_requirement_policies q JOIN public.submission_requirement_bindings b ON b.policy_id=q.id WHERE b.case_id=c.id;
  IF c.state<>'APPROVED' OR c.row_version IS DISTINCT FROM (input->>'expectedCaseVersion')::integer OR NOT rule.revisions_enabled OR NOT rule.changes_enabled OR clock_timestamp()<rule.opens_at OR clock_timestamp()>=rule.closes_at THEN RAISE EXCEPTION 'Approved synopsis within configured revision rules/window required' USING ERRCODE='23514'; END IF;
  SELECT id INTO attempt FROM public.submission_attempts WHERE case_id=c.id ORDER BY attempt_no DESC LIMIT 1;
  INSERT INTO public.approval_decisions(attempt_id,project_id,reviewer_user_id,decision,comment) VALUES(attempt,pid,actor,'REQUEST_REVISION',nullif(input->>'comment',''));
  UPDATE public.submission_cases SET state='CHANGES_REQUESTED',row_version=row_version+1 WHERE id=c.id;
  target:=c.id;
 ELSIF action='REQUEST_CORRECTION' THEN
  rid:=(input->>'reviewId')::uuid;
  PERFORM 1 FROM public.assessments a JOIN public.evaluator_assignments e ON e.id=a.evaluator_assignment_id JOIN public.project_reviews r ON r.id=a.review_id WHERE a.id=(input->>'assessmentId')::uuid AND r.id=rid AND public.smartpro_course_project_offering(r.project_id)=oid AND e.faculty_user_id=actor AND a.state='FINALIZED' FOR UPDATE OF a,r;
  IF NOT FOUND OR jsonb_typeof(input->'scores') IS DISTINCT FROM 'array' OR (input->>'expectedReviewRevision')::integer IS DISTINCT FROM (SELECT revision FROM public.academic_review_bindings WHERE review_id=rid) THEN RAISE EXCEPTION 'Own finalized evaluation and current revision required' USING ERRCODE='42501'; END IF;
  INSERT INTO public.course_correction_requests(offering_id,review_id,assessment_id,requester_id,expected_revision,scores,note) VALUES(oid,rid,(input->>'assessmentId')::uuid,actor,(input->>'expectedReviewRevision')::integer,input->'scores',nullif(input->>'reason','')) RETURNING id INTO target;
 ELSIF action IN('AUTHORIZE_CORRECTION','APPLY_CORRECTION') THEN
  SELECT * INTO request FROM public.course_correction_requests WHERE id=(input->>'requestId')::uuid AND offering_id=oid FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Offering correction request required' USING ERRCODE='42501'; END IF;
  IF action='AUTHORIZE_CORRECTION' THEN
   IF role<>'Coordinator' OR request.requester_id=actor OR (coalesce((framework.configuration->>'outsidePanelAuthorizer')::boolean,true) AND EXISTS(SELECT FROM public.evaluator_assignments WHERE review_id=request.review_id AND faculty_user_id=actor)) THEN RAISE EXCEPTION 'Independent appointed coordinator required; self-authorization forbidden' USING ERRCODE='42501'; END IF;
   INSERT INTO public.course_correction_authorizations VALUES(request.id,actor,(input->>'approved')::boolean,clock_timestamp());
  ELSE
   IF request.requester_id<>actor THEN RAISE EXCEPTION 'Original requesting evaluator required' USING ERRCODE='42501'; END IF;
   result:=public.smartpro_academic_review_command(actor,o.department_id,'EVALUATE',jsonb_build_object('reviewId',request.review_id,'assessmentId',request.assessment_id,'expectedReviewRevision',request.expected_revision,'scores',request.scores,'reason',coalesce(request.note,'')),'course-correct:'||request.id::text);
  END IF;
  target:=request.id;
 ELSIF action='PUBLISH_FINAL' THEN
  pid:=(input->>'projectId')::uuid;
  PERFORM 1 FROM public.projects WHERE id=pid AND public.smartpro_course_project_offering(id)=oid FOR UPDATE;
  IF NOT FOUND OR plan.id IS NULL OR NOT framework.configuration->'publicationRoles' ? role THEN RAISE EXCEPTION 'Configured final-publication authority and plan required' USING ERRCODE='42501'; END IF;
  SELECT id,v.version INTO previous,version FROM public.course_final_results v WHERE project_id=pid ORDER BY v.version DESC LIMIT 1;
  IF coalesce(version,0) IS DISTINCT FROM (input->>'expectedVersion')::integer THEN RAISE EXCEPTION 'Final result changed' USING ERRCODE='23514'; END IF;
  IF previous IS NOT NULL THEN RAISE EXCEPTION 'Use the separately authorized exceptional result process; ordinary final publication is closed' USING ERRCODE='42501'; END IF;
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
  INSERT INTO public.course_final_results(project_id,plan_id,version,supersedes_id,sources,results,actor_id) VALUES(pid,plan.id,1,NULL,sources,totals,actor) RETURNING id INTO target;
 ELSE RAISE EXCEPTION 'Supported course command required' USING ERRCODE='22023'; END IF;
 IF role IN('HOD','Coordinator') THEN PERFORM public.smartpro_course_authority(actor,oid,CASE action WHEN 'FRAMEWORK' THEN 'READ' WHEN 'PLAN' THEN 'PLAN' WHEN 'CREATE_STAGE' THEN 'EVALUATORS' WHEN 'AUTHORIZE_CORRECTION' THEN 'CORRECTIONS' ELSE 'RESULTS' END,role);
 ELSIF role='Admin' THEN PERFORM public.smartpro_operational_authority(actor,o.department_id,input->'authority');
 ELSIF NOT public.smartpro_has_role(actor,o.department_id,'FACULTY',clock_timestamp()) THEN RAISE EXCEPTION 'Faculty authority expired' USING ERRCODE='42501'; END IF;
 result:=coalesce(result,'{}')||jsonb_build_object('id',target,'offeringId',oid);
 INSERT INTO public.document_command_receipts VALUES(actor,key,'COURSE_'||action,jsonb_build_object('offeringId',oid,'payload',input),result);
 INSERT INTO public.audit_events(actor_id,project_id,action,target_type,target_id,metadata) VALUES(actor,pid,'COURSE_'||action,'COURSE_OPERATION',target,jsonb_build_object('offeringId',oid,'request',input,'result',result,'authority',auth));
 RETURN result;
END $$;
-- Reopening appends a decision and leaves the earlier approved attempt untouched.
ALTER TABLE public.approval_decisions DROP CONSTRAINT approval_decisions_decision_check;
ALTER TABLE public.approval_decisions ADD CHECK(decision IN('APPROVE','REQUEST_CHANGES','REJECT','COMMENT','REQUEST_REVISION'));
DROP INDEX public.one_formal_reviewer_decision;
CREATE UNIQUE INDEX one_formal_reviewer_decision ON public.approval_decisions(attempt_id,reviewer_user_id) WHERE decision NOT IN('COMMENT','REQUEST_REVISION');
DO $$ DECLARE def text; BEGIN
 def:=pg_get_functiondef('public.smartpro_decision_authority()'::regprocedure);
 def:=replace(def,'BEGIN',E'BEGIN\n IF NEW.decision=''REQUEST_REVISION'' THEN\n  IF current_user<>pg_get_userbyid((SELECT proowner FROM pg_proc WHERE oid=''public.smartpro_course_command(uuid,uuid,text,jsonb,text)''::regprocedure)) OR EXISTS(SELECT FROM public.course_final_results WHERE project_id=NEW.project_id) OR NOT public.smartpro_requirement_access(NEW.reviewer_user_id,NEW.project_id,''SYNOPSIS'',''Faculty'',true) OR NOT EXISTS(SELECT FROM public.submission_attempts pending_attempt JOIN public.submission_cases synopsis_case ON synopsis_case.id=pending_attempt.case_id WHERE pending_attempt.id=NEW.attempt_id AND synopsis_case.project_id=NEW.project_id AND synopsis_case.requirement_key=''SYNOPSIS'' AND synopsis_case.state=''APPROVED'' AND pending_attempt.attempt_state=''APPROVED'') THEN RAISE EXCEPTION ''Authorized pre-final synopsis reopening required'' USING ERRCODE=''42501''; END IF;\n  SELECT f.id INTO NEW.faculty_assignment_id FROM public.faculty_assignments f WHERE f.project_id=NEW.project_id AND f.faculty_user_id=NEW.reviewer_user_id AND f.assignment_type=''REVIEWER'' AND (f.requirement_key IS NULL OR f.requirement_key=''SYNOPSIS'') AND f.valid_from<=clock_timestamp() AND (f.valid_until IS NULL OR clock_timestamp()<f.valid_until) ORDER BY f.id LIMIT 1;\n  NEW.decided_at:=clock_timestamp();RETURN NEW;\n END IF;');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_academic_review_command(uuid,uuid,text,jsonb,text)'::regprocedure);
 def:=replace(def,'ELSIF action_name=''EVALUATE'' THEN',E'ELSIF action_name=''EVALUATE'' THEN\n      PERFORM public.smartpro_course_correction_guard(actor,review.id,input);');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_document_command(uuid,uuid,text,jsonb,text)'::regprocedure);
 def:=replace(def,'  ELSIF action=''START_UPLOAD'' THEN',E'  ELSIF action=''START_UPLOAD'' THEN');
 def:=replace(def,'  -- Serializes case creation',E'  IF EXISTS(SELECT FROM public.course_final_results WHERE project_id=p.id) THEN RAISE EXCEPTION ''Ordinary document changes closed after overall final publication'' USING ERRCODE=''42501''; END IF;\n  -- Serializes case creation');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_revise_proposal(uuid,uuid,text,jsonb,text)'::regprocedure);
 def:=replace(def,'BEGIN',E'BEGIN\n IF EXISTS(SELECT FROM public.course_final_results WHERE project_id=pid) THEN RAISE EXCEPTION ''Overall final result published'' USING ERRCODE=''42501''; END IF;');EXECUTE def;
END $$;
ALTER FUNCTION public.smartpro_initial_evaluation(uuid,uuid,text,jsonb,text) RENAME TO smartpro_initial_evaluation_pre038;
DO $$ DECLARE def text; BEGIN
 def:=pg_get_functiondef('public.smartpro_initial_evaluation_pre038(uuid,uuid,text,jsonb,text)'::regprocedure);
 EXECUTE replace(def,'smartpro_initial_evaluation.request_key','smartpro_initial_evaluation_pre038.request_key');
END $$;
REVOKE ALL ON FUNCTION public.smartpro_initial_evaluation_pre038(uuid,uuid,text,jsonb,text) FROM PUBLIC,smartpro_runtime;
CREATE FUNCTION public.smartpro_initial_evaluation(actor uuid,dept uuid,action_name text,input jsonb,request_key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF action_name='CREATE_REVIEW' THEN RAISE EXCEPTION 'Assign reviews through the approved offering plan' USING ERRCODE='42501'; END IF;
 RETURN public.smartpro_initial_evaluation_pre038(actor,dept,action_name,input,request_key);
END $$;
GRANT EXECUTE ON FUNCTION public.smartpro_initial_evaluation(uuid,uuid,text,jsonb,text) TO smartpro_runtime;
DO $$ DECLARE def text; BEGIN
 def:=pg_get_functiondef('public.smartpro_revise_evaluators(uuid,uuid,text,jsonb,text)'::regprocedure);
 def:=replace(def,' auth:=public.smartpro_academic_authority',E' PERFORM public.smartpro_course_authority(actor,public.smartpro_course_project_offering((SELECT project_id FROM public.project_reviews WHERE id=(input->>''reviewId'')::uuid)),''EVALUATORS'',input->>''_actingRole'');\n auth:=public.smartpro_academic_authority');
 def:=replace(def,' FOR uid IN SELECT value::uuid FROM jsonb_array_elements_text(input->''facultyIds'') ORDER BY value LOOP',E' IF EXISTS(SELECT FROM public.faculty_assignments f WHERE f.project_id=review.project_id AND f.assignment_type=''GUIDE'' AND f.valid_from<=clock_timestamp() AND (f.valid_until IS NULL OR clock_timestamp()<f.valid_until) AND NOT input->''facultyIds'' ? f.faculty_user_id::text) THEN RAISE EXCEPTION ''The active primary guide is an evaluator by default'' USING ERRCODE=''23514''; END IF;\n FOR uid IN SELECT value::uuid FROM jsonb_array_elements_text(input->''facultyIds'') ORDER BY value LOOP');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_academic_review_command(uuid,uuid,text,jsonb,text)'::regprocedure);
 def:=replace(def,'    auth:=public.smartpro_academic_authority(actor,dept);',E'    IF NOT public.smartpro_course_access(actor,public.smartpro_course_project_offering(review.project_id),''READ'',''HOD'') THEN PERFORM public.smartpro_course_authority(actor,public.smartpro_course_project_offering(review.project_id),CASE WHEN action_name=''ROSTER'' THEN ''CORRECTIONS'' WHEN action_name=''PUBLISH'' THEN ''RESULTS'' ELSE ''PLAN'' END,''Coordinator''); END IF;\n    auth:=public.smartpro_academic_authority(actor,dept);');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_academic_governance(uuid,uuid,text,jsonb,text)'::regprocedure);
 def:=replace(def,'  stamp:=clock_timestamp();',E'  IF action_name=''CREATE_POLICY'' THEN PERFORM public.smartpro_academic_authority(actor,dept,true); END IF;\n  IF action_name=''REVOKE_COORDINATOR'' AND EXISTS(SELECT FROM public.course_coordinator_versions v JOIN public.curriculum_offerings o ON o.id=v.offering_id WHERE v.mandate_id=(input->>''mandateId'')::uuid AND o.availability=''ACTIVE'' AND v.id IN(SELECT id FROM public.smartpro_course_coordinators(o.id)) AND (SELECT count(*) FROM public.smartpro_course_coordinators(o.id))=1) THEN RAISE EXCEPTION ''Pause or hand over the active offering before revocation'' USING ERRCODE=''23514''; END IF;\n  stamp:=clock_timestamp();');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_document_command(uuid,uuid,text,jsonb,text)'::regprocedure);
 def:=replace(def,' ELSIF action=''ASSIGN_REVIEWER'' THEN',E' ELSIF action=''ASSIGN_REVIEWER'' THEN\n  IF NOT public.smartpro_course_access(actor,public.smartpro_course_project_offering((input->>''projectId'')::uuid),''READ'',''HOD'') THEN PERFORM public.smartpro_course_authority(actor,public.smartpro_course_project_offering((input->>''projectId'')::uuid),''SUBMISSIONS'',''Coordinator''); END IF;');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_manage_assignment(uuid,uuid,text,jsonb,text)'::regprocedure);
 def:=replace(def,'  PERFORM 1 FROM public.projects WHERE id=assignment.project_id FOR UPDATE;',E'  PERFORM public.smartpro_course_authority(actor,public.smartpro_course_project_offering(assignment.project_id),CASE WHEN assignment.assignment_type=''GUIDE'' THEN ''GUIDE'' ELSE ''SUBMISSIONS'' END,input->>''_actingRole'');\n  PERFORM 1 FROM public.projects WHERE id=assignment.project_id FOR UPDATE;');EXECUTE def;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_course_project_offering(uuid),public.smartpro_course_correction_guard(uuid,uuid,jsonb),public.smartpro_course_command(uuid,uuid,text,jsonb,text) FROM PUBLIC,smartpro_runtime;
GRANT EXECUTE ON FUNCTION public.smartpro_course_command(uuid,uuid,text,jsonb,text) TO smartpro_runtime;
COMMIT;
