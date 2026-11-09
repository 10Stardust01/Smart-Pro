-- Candidate 060: forward-only stage-evidence re-release on top of installed 059.
-- This does not reinstall 059, rewrite historic releases, add credentials,
-- change earlier academic/evaluator authorization, or grant broader runtime roles.
-- Owner-run once after reviewing existing 059 and the recovery branches.
BEGIN;
DO $preflight$
DECLARE def text;
BEGIN
 IF to_regprocedure('public.smartpro_course_final_revision(uuid,uuid,text,jsonb,text)') IS NULL
    OR to_regprocedure('public.smartpro_guide_final_corrections(uuid,text)') IS NULL
    OR to_regclass('public.course_final_revision_requests') IS NULL THEN
   RAISE EXCEPTION 'Expected installed 059 direct correction schema required';
 END IF;
 def:=pg_get_functiondef('public.smartpro_course_final_revision(uuid,uuid,text,jsonb,text)'::regprocedure);
 IF strpos(def,'DIRECT_AUTHORIZED_OVERALL_CORRECTION')=0
    OR strpos(def,'STAGE_EVIDENCE_OVERALL_CORRECTION')<>0 THEN
   RAISE EXCEPTION 'Expected original 059 direct-only function required; do not overwrite an unknown revision';
 END IF;
END $preflight$;
CREATE OR REPLACE FUNCTION public.smartpro_course_final_revision(
 actor uuid,oid uuid,action text,input jsonb,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE o public.curriculum_offerings%ROWTYPE;
 prior public.document_command_receipts%ROWTYPE;
 request public.course_final_revision_requests%ROWTYPE;
 released public.course_final_results%ROWTYPE;
 cfg jsonb; proposed jsonb; changes jsonb; reply jsonb;
 pid uuid; uid uuid; target uuid; appointment uuid; published uuid;
 old_marks text; new_marks text; reason text; role text; correction_type text; candidate jsonb; proposed_sources jsonb;
 value numeric; maximum numeric; decimals integer;
BEGIN
 IF action NOT IN ('REQUEST_FINAL_REVISION','AUTHORIZE_FINAL_REVISION')
    OR key IS NULL OR key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
    OR jsonb_typeof(input) IS DISTINCT FROM 'object' THEN
   RAISE EXCEPTION 'Direct published-result request or decision required' USING ERRCODE='22023';
 END IF;
 SELECT * INTO o FROM public.curriculum_offerings WHERE id=oid;
 IF NOT FOUND THEN RAISE EXCEPTION 'Offering required' USING ERRCODE='42501'; END IF;
 role:=input->>'_actingRole';
 IF NOT public.smartpro_role_choices(actor) ? role THEN RAISE EXCEPTION 'Current role required' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.academic_governance_settings WHERE department_id=o.department_id AND enabled FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Academic controls disabled' USING ERRCODE='42501'; END IF;
 IF action='REQUEST_FINAL_REVISION' THEN
   IF NOT public.smartpro_current_project_guide(actor,(input->>'projectId')::uuid) THEN
     RAISE EXCEPTION 'Current assigned Project Guide required' USING ERRCODE='42501';
   END IF;
 ELSE
   IF role<>'Coordinator' THEN RAISE EXCEPTION 'Offering Coordinator required' USING ERRCODE='42501'; END IF;
   PERFORM public.smartpro_course_authority(actor,oid,'CORRECTIONS',role);
 END IF;
 PERFORM 1 FROM public.curriculum_offerings WHERE id=oid FOR UPDATE;
 PERFORM pg_advisory_xact_lock(hashtextextended(actor::text||':direct-result:'||key,0));
 SELECT * INTO prior FROM public.document_command_receipts WHERE actor_id=actor AND request_key=key;
 IF FOUND THEN
   IF prior.action<>'COURSE_'||action OR prior.input<>jsonb_build_object('offeringId',oid,'payload',input) THEN
     RAISE EXCEPTION 'Idempotency replay changed' USING ERRCODE='23514';
   END IF;
   RETURN prior.output;
 END IF;
 IF action='REQUEST_FINAL_REVISION' THEN pid:=(input->>'projectId')::uuid;
 ELSE
   SELECT * INTO request FROM public.course_final_revision_requests
     WHERE id=(input->>'requestId')::uuid FOR UPDATE;
   IF NOT FOUND OR request.snapshot->>'type' NOT IN ('DIRECT_AUTHORIZED_OVERALL_CORRECTION','STAGE_EVIDENCE_OVERALL_CORRECTION') THEN
     RAISE EXCEPTION 'Current direct correction request required' USING ERRCODE='42501';
   END IF;
   pid:=request.project_id;
 END IF;
 PERFORM 1 FROM public.projects p WHERE p.id=pid
   AND public.smartpro_course_project_offering(p.id)=oid FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Project in offering required' USING ERRCODE='42501'; END IF;
 SELECT * INTO released FROM public.course_final_results WHERE project_id=pid ORDER BY version DESC LIMIT 1;
 IF NOT FOUND THEN RAISE EXCEPTION 'Published overall result required' USING ERRCODE='42501'; END IF;
 SELECT f.configuration INTO cfg FROM public.course_plan_versions cp
   JOIN public.course_framework_versions f ON f.id=cp.framework_id WHERE cp.id=released.plan_id;
 IF NOT coalesce((cfg->>'allowFinalCorrections')::boolean,false) THEN
   RAISE EXCEPTION 'Pinned framework disallows final correction' USING ERRCODE='42501';
 END IF;
 IF action='REQUEST_FINAL_REVISION' THEN
   IF released.version IS DISTINCT FROM (input->>'expectedVersion')::integer THEN
     RAISE EXCEPTION 'Published result changed; refresh and propose again' USING ERRCODE='23514';
   END IF;
   reason:=nullif(btrim(input->>'reason'),'');
   IF reason IS NULL OR length(reason)>500 THEN
     RAISE EXCEPTION 'Specific correction reason required' USING ERRCODE='22023';
   END IF;
   IF input->>'mode'='STAGE_EVIDENCE' THEN
     -- Only reuses completed, previously corrected stage publications;
     -- does not change evaluator marks, create an approval or bypass a rubric.
     candidate:=public.smartpro_course_calculate(pid);
     proposed:=candidate->'results';
     proposed_sources:=candidate->'sources';
     IF proposed IS NULL OR proposed_sources IS NULL OR
        proposed_sources=released.sources THEN
       RAISE EXCEPTION 'No updated, complete stage evidence to release' USING ERRCODE='23514';
     END IF;
     correction_type:='STAGE_EVIDENCE_OVERALL_CORRECTION';
     SELECT coalesce(jsonb_agg(jsonb_build_object('studentId',x.student,
       'from',released.results->>x.student,'to',proposed->>x.student)
       ORDER BY x.student),'[]'::jsonb) INTO changes
     FROM (SELECT r.student FROM jsonb_object_keys(released.results) AS r(student)
           UNION SELECT n.student FROM jsonb_object_keys(proposed) AS n(student)) x
     WHERE released.results->>x.student IS DISTINCT FROM proposed->>x.student;
   ELSE
     uid:=(input->>'studentId')::uuid;
     IF NOT released.results ? uid::text
        OR jsonb_typeof(input->'marks') IS DISTINCT FROM 'string'
        OR (input->>'marks') !~ '^[0-9]{1,8}(\.[0-9]{1,4})?$' THEN
       RAISE EXCEPTION 'Current student and numeric overall mark required' USING ERRCODE='22023';
     END IF;
     decimals:=(cfg->>'decimalPlaces')::integer;
     maximum:=CASE WHEN cfg->>'method'='SINGLE_RAW'
       THEN (released.sources->0->>'rubricMaximum')::numeric
       ELSE (cfg->>'scale')::numeric END;
     value:=(input->>'marks')::numeric;
     IF decimals NOT BETWEEN 0 AND 4 OR maximum IS NULL OR maximum<=0
        OR value<0 OR value>maximum OR round(value,decimals)<>value THEN
       RAISE EXCEPTION 'Mark outside approved total or precision' USING ERRCODE='22023';
     END IF;
     new_marks:=to_char(value,'FM999999990'||CASE WHEN decimals>0 THEN '.'||repeat('0',decimals) ELSE '' END);
     old_marks:=released.results->>uid::text;
     IF old_marks::numeric=value THEN RAISE EXCEPTION 'No change proposed' USING ERRCODE='23514'; END IF;
     proposed:=jsonb_set(released.results,ARRAY[uid::text],to_jsonb(new_marks));
     proposed_sources:=released.sources;
     changes:=jsonb_build_array(jsonb_build_object('studentId',uid,'from',old_marks,'to',new_marks));
     correction_type:='DIRECT_AUTHORIZED_OVERALL_CORRECTION';
   END IF;
   INSERT INTO public.course_final_revision_requests(project_id,expected_version,snapshot,requester_id,reason)
   VALUES(pid,released.version,jsonb_build_object('basedOnResultId',released.id,
     'sources',proposed_sources,'results',proposed,'changes',changes,
     'type',correction_type),actor,reason) RETURNING id INTO target;
   reply:=jsonb_build_object('id',target,'projectId',pid,'status','PENDING');
 ELSE
   IF jsonb_typeof(input->'approved') IS DISTINCT FROM 'boolean'
      OR EXISTS(SELECT FROM public.course_final_revision_authorizations WHERE request_id=request.id) THEN
     RAISE EXCEPTION 'Unused request with explicit decision required' USING ERRCODE='23514';
   END IF;
   IF released.version<>request.expected_version
      OR released.id IS DISTINCT FROM (request.snapshot->>'basedOnResultId')::uuid
      OR (request.snapshot->>'type'='DIRECT_AUTHORIZED_OVERALL_CORRECTION'
       AND released.sources IS DISTINCT FROM request.snapshot->'sources') THEN
     RAISE EXCEPTION 'Original result changed; request fresh exact correction' USING ERRCODE='23514';
   END IF;
   IF request.snapshot->>'type'='STAGE_EVIDENCE_OVERALL_CORRECTION' THEN
     candidate:=public.smartpro_course_calculate(pid);
     IF candidate->'sources' IS DISTINCT FROM request.snapshot->'sources'
        OR candidate->'results' IS DISTINCT FROM request.snapshot->'results' THEN
       RAISE EXCEPTION 'Stage evidence changed since request; refresh correction' USING ERRCODE='23514';
     END IF;
   END IF;
   SELECT id INTO appointment FROM public.smartpro_course_coordinators(oid)
    WHERE user_id=actor AND 'CORRECTIONS'=ANY(responsibilities) LIMIT 1;
   IF appointment IS NULL THEN RAISE EXCEPTION 'Current Coordinator correction responsibility required' USING ERRCODE='42501'; END IF;
   INSERT INTO public.course_final_revision_authorizations(request_id,actor_id,appointment_id,approved,created_at)
   VALUES(request.id,actor,appointment,(input->>'approved')::boolean,clock_timestamp());
   target:=request.id;
   IF (input->>'approved')::boolean THEN
     INSERT INTO public.course_final_results(project_id,plan_id,version,supersedes_id,sources,results,actor_id)
     VALUES(pid,released.plan_id,released.version+1,released.id,
       request.snapshot->'sources',request.snapshot->'results',actor) RETURNING id INTO published;
     INSERT INTO public.course_final_revision_applications(request_id,result_id,actor_id,created_at)
     VALUES(request.id,published,actor,clock_timestamp());
   END IF;
   reply:=jsonb_build_object('id',target,'projectId',pid,
     'approved',(input->>'approved')::boolean,'resultId',published,
     'newVersion',CASE WHEN published IS NOT NULL THEN released.version+1 ELSE NULL END);
   PERFORM public.smartpro_course_authority(actor,oid,'CORRECTIONS','Coordinator');
 END IF;
 IF action='REQUEST_FINAL_REVISION' AND NOT public.smartpro_current_project_guide(actor,pid) THEN
   RAISE EXCEPTION 'Guide responsibility expired during request' USING ERRCODE='42501';
 END IF;
 INSERT INTO public.document_command_receipts
 VALUES(actor,key,'COURSE_'||action,jsonb_build_object('offeringId',oid,'payload',input),reply);
 INSERT INTO public.audit_events(actor_id,project_id,action,target_type,target_id,metadata)
 VALUES(actor,pid,'COURSE_'||action,'FINAL_RESULT_CORRECTION',target,
   jsonb_build_object('offeringId',oid,'originalResultId',released.id,
     'originalVersion',released.version,'requestId',
     CASE WHEN action='REQUEST_FINAL_REVISION' THEN target ELSE request.id END,
     'changes',CASE WHEN action='REQUEST_FINAL_REVISION' THEN changes ELSE request.snapshot->'changes' END,
     'reason',CASE WHEN action='REQUEST_FINAL_REVISION' THEN reason ELSE request.reason END,
     'decision',input->'approved','replacementResultId',published,'appointmentId',appointment));
 RETURN reply;
END $$;
-- CREATE OR REPLACE retains existing owner and EXECUTE grants.
COMMIT;
