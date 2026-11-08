-- Owner-run candidate after 048: bounded project pages and ordinary correction closure.
BEGIN;
ALTER TABLE public.course_correction_requests ADD COLUMN exceptional_result_id uuid
  REFERENCES public.course_final_results(id);


CREATE FUNCTION public.smartpro_course_evaluation_queue(actor uuid, oid uuid, role text, search text, status_filter text, requested_page integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE project record; plan record; stage record; review record; policy record;
        stages jsonb; projects jsonb := '[]'; sources jsonb; roster uuid; blocker text;
        overall text; published integer; assigned integer; release_version integer;
        can_publish boolean; can_authorize boolean; outside_panel boolean; own_assessment uuid; faculty jsonb; guide text; page_rows jsonb; total bigint; page_number integer;
BEGIN
 IF role IS DISTINCT FROM 'Coordinator' OR NOT public.smartpro_course_access(actor,oid,'READ',role) THEN
   RAISE EXCEPTION 'Current offering appointment required' USING ERRCODE='42501';
 END IF;
 can_publish:=public.smartpro_course_access(actor,oid,'RESULTS',role);
 can_authorize:=public.smartpro_course_access(actor,oid,'CORRECTIONS',role);
 SELECT coalesce((f.configuration->>'outsidePanelAuthorizer')::boolean,true) INTO outside_panel
 FROM public.course_plan_versions cp JOIN public.course_framework_versions f ON f.id=cp.framework_id
 WHERE cp.offering_id=oid ORDER BY cp.version DESC LIMIT 1;
 IF search IS NULL OR length(search)>120 OR status_filter IS NULL OR status_filter NOT IN ('all','unassigned','in-progress','published')
   OR requested_page IS NULL OR requested_page<1 THEN
   RAISE EXCEPTION 'Invalid queue filters' USING ERRCODE='22023';
 END IF;
 WITH matched AS MATERIALIZED (
   SELECT p.id,p.title,t.name AS team
   FROM public.projects p JOIN public.teams t ON t.id=p.team_id
   WHERE t.curriculum_offering_id=oid
     AND (search='' OR p.id::text=search OR strpos(lower(p.title),lower(search))>0 OR strpos(lower(t.name),lower(search))>0)
     AND CASE status_filter
       WHEN 'all' THEN true
       WHEN 'published' THEN EXISTS(SELECT FROM public.course_final_results f WHERE f.project_id=p.id)
       ELSE NOT EXISTS(SELECT FROM public.course_final_results f WHERE f.project_id=p.id) AND
         (status_filter='in-progress')=EXISTS(SELECT FROM public.project_reviews r
           JOIN public.course_review_bindings b ON b.review_id=r.id WHERE r.project_id=p.id)
     END
 ), bounds AS (
   SELECT count(*) AS n,least(requested_page,greatest(1,(count(*)+24)/25))::integer AS page FROM matched
 )
 SELECT n,page,coalesce((SELECT jsonb_agg(to_jsonb(x) ORDER BY x.title,x.id)
   FROM (SELECT * FROM matched ORDER BY title,id LIMIT 25 OFFSET ((bounds.page-1)::bigint*25)) x),'[]')
 INTO total,page_number,page_rows FROM bounds;
 FOR project IN SELECT * FROM jsonb_to_recordset(page_rows) AS x(id uuid,title text,team text)
 LOOP
   SELECT cp.id,cp.version,cp.schedules,f.configuration,f.version AS framework_version
     INTO plan FROM public.course_plan_versions cp JOIN public.course_framework_versions f ON f.id=cp.framework_id
     WHERE cp.offering_id=oid AND cp.id=coalesce(
       (SELECT plan_id FROM public.course_project_plans WHERE project_id=project.id),
       (SELECT id FROM public.course_plan_versions WHERE offering_id=oid ORDER BY version DESC LIMIT 1));
   SELECT u.display_name INTO guide FROM public.faculty_assignments a JOIN public.users u ON u.id=a.faculty_user_id
   JOIN public.projects pr ON pr.id=a.project_id
   WHERE a.project_id=project.id AND a.assignment_type='GUIDE' AND a.valid_from<=clock_timestamp()
     AND (a.valid_until IS NULL OR clock_timestamp()<a.valid_until)
     AND public.smartpro_has_role(a.faculty_user_id,pr.department_id,'FACULTY',clock_timestamp())
   ORDER BY a.valid_from DESC,a.id LIMIT 1;
   SELECT max(version) INTO release_version FROM public.course_final_results WHERE project_id=project.id;
   stages:='[]';
   FOR stage IN SELECT value AS cfg FROM jsonb_array_elements(plan.configuration->'stages') LOOP
     SELECT r.id,r.review_state,r.roster_locked_at,r.scheduled_at
       INTO review FROM public.course_review_bindings b JOIN public.project_reviews r ON r.id=b.review_id
       WHERE b.plan_id=plan.id AND r.project_id=project.id AND b.stage_key=stage.cfg->>'key'
       ORDER BY r.round_no DESC,r.id LIMIT 1;
     SELECT evaluator_quorum,version_no,aggregation,evaluator_weights INTO policy
       FROM public.academic_evaluation_policies WHERE id=(stage.cfg->>'policyId')::uuid;
     SELECT max(version_no) INTO published FROM public.academic_result_versions WHERE review_id=review.id;

     SELECT id INTO roster FROM public.academic_roster_versions WHERE review_id=review.id ORDER BY version_no DESC LIMIT 1;
     sources:=CASE WHEN roster IS NOT NULL AND published IS NULL AND release_version IS NULL THEN public.smartpro_academic_sources(review.id,roster) END;
     SELECT coalesce(jsonb_agg(jsonb_build_object('name',u.display_name,'state',a.state) ORDER BY u.display_name),'[]'),
       (array_agg(a.id) FILTER (WHERE e.faculty_user_id=actor))[1]
       INTO faculty,own_assessment
       FROM public.evaluator_assignments e JOIN public.users u ON u.id=e.faculty_user_id
       LEFT JOIN public.assessments a ON a.evaluator_assignment_id=e.id AND a.review_id=e.review_id
       WHERE e.review_id=review.id AND public.smartpro_evaluator_active(e.id);
     assigned:=jsonb_array_length(faculty);
     blocker:=CASE WHEN release_version IS NOT NULL THEN 'Overall result published. Use the exceptional revision process.'
       WHEN published IS NOT NULL THEN 'Stage results already published.'
       WHEN review.id IS NULL THEN 'Assign evaluators and create this assessment stage.'
       WHEN review.review_state='CANCELLED' OR review.roster_locked_at IS NULL OR roster IS NULL THEN 'An active assessment with a frozen roster is required.'
       WHEN NOT can_publish THEN 'Your appointment does not delegate result publication.'
       WHEN assigned<policy.evaluator_quorum THEN format('Only %s active evaluators assigned; quorum requires %s.',assigned,policy.evaluator_quorum)
       WHEN sources IS NULL THEN 'Finalized marks do not match the current frozen roster.'
       WHEN jsonb_array_length(sources)<policy.evaluator_quorum THEN format('%s of %s required evaluator contributions finalized.',jsonb_array_length(sources),policy.evaluator_quorum)
       WHEN policy.aggregation='WEIGHTED_MEAN' AND
         (SELECT coalesce(jsonb_object_agg(s->>'evaluatorId',true),'{}') FROM jsonb_array_elements(sources) s)
         IS DISTINCT FROM (SELECT coalesce(jsonb_object_agg(key,true),'{}') FROM jsonb_each(policy.evaluator_weights))
         THEN 'Finalized evaluators do not match the pinned aggregation weights.' END;
     stages:=stages||jsonb_build_array(jsonb_build_object(
       'key',stage.cfg->>'key','name',stage.cfg->>'name','reviewId',review.id,
       'scheduledAt',coalesce(to_jsonb(review.scheduled_at),plan.schedules->(stage.cfg->>'key')),
       'deadline',CASE WHEN review.id IS NOT NULL THEN
         public.smartpro_course_deadline_effective(project.id,'EVALUATION',stage.cfg->>'key',(stage.cfg->>'deadline')::timestamptz)
         ELSE (stage.cfg->>'deadline')::timestamptz END,
       'policyVersion',policy.version_no,'mode',(SELECT mode_code FROM public.scheme_modes WHERE id=(stage.cfg->>'schemeModeId')::uuid),
       'evaluators',faculty,'ownAssessmentId',own_assessment,
       'canAuthorizeCorrection',can_authorize AND
         (NOT coalesce(outside_panel,true) OR NOT EXISTS(SELECT FROM public.evaluator_assignments
           WHERE review_id=review.id AND faculty_user_id=actor)),
       'finalized',CASE WHEN published IS NOT NULL THEN (SELECT jsonb_array_length(v.sources) FROM public.academic_result_versions v WHERE v.review_id=review.id AND v.version_no=published) ELSE jsonb_array_length(sources) END,
       'exceptionalAllowed',release_version IS NOT NULL AND coalesce((plan.configuration->>'allowFinalCorrections')::boolean,false),
       'quorum',policy.evaluator_quorum,'publishedVersion',published,'blocker',blocker));
   END LOOP;
   overall:=CASE WHEN release_version IS NOT NULL THEN 'Overall result published. Use the exceptional revision process.'
     WHEN plan.id IS NULL THEN 'Apply an approved course plan.'
     WHEN NOT can_publish OR NOT plan.configuration->'publicationRoles' ? role THEN 'Your appointment or pinned policy does not authorize overall publication.' END;
   IF overall IS NULL THEN
     BEGIN
       PERFORM public.smartpro_course_calculate(project.id);
     EXCEPTION WHEN check_violation THEN
       overall:=SQLERRM;
     END;
   END IF;
   projects:=projects||jsonb_build_array(jsonb_build_object(
     'id',project.id,'title',project.title,'team',project.team,'guide',guide,'planVersion',plan.version,
     'frameworkVersion',plan.framework_version,'stages',stages,'overallBlocker',overall,'overallVersion',release_version));
 END LOOP;
 RETURN jsonb_build_object('projects',projects,'total',total,'page',page_number,'pageSize',25);
END $$;

REVOKE ALL ON FUNCTION public.smartpro_course_evaluation_queue(uuid,uuid,text,text,text,integer) FROM PUBLIC,smartpro_runtime;
GRANT EXECUTE ON FUNCTION public.smartpro_course_evaluation_queue(uuid,uuid,text,text,text,integer) TO smartpro_runtime;
-- Use the same command, receipts and authorization path for explicitly exceptional
-- stage evidence, pinned to the currently published overall result.
DO $patch$
DECLARE definition text; anchor text := '  IF action=''AUTHORIZE_CORRECTION'' THEN';
BEGIN
 definition:=pg_get_functiondef('public.smartpro_course_command(uuid,uuid,text,jsonb,text)'::regprocedure);
 IF strpos(definition,anchor)=0 OR strpos(definition,'  INSERT INTO public.course_correction_requests(offering_id')=0 THEN
   RAISE EXCEPTION 'Reviewed course correction command required';
 END IF;
 definition:=replace(definition,'  INSERT INTO public.course_correction_requests(offering_id',$guard$
  SELECT f.id INTO previous FROM public.course_final_results f WHERE f.project_id=pid ORDER BY f.version DESC LIMIT 1;
  IF (previous IS NOT NULL) IS DISTINCT FROM coalesce((input->>'_exceptional')::boolean,false) THEN
    RAISE EXCEPTION 'Use the correction procedure for the current publication state' USING ERRCODE='42501';
  END IF;
  IF previous IS NOT NULL AND NOT EXISTS (
    SELECT FROM public.course_final_results f JOIN public.course_plan_versions cp ON cp.id=f.plan_id
    JOIN public.course_framework_versions fw ON fw.id=cp.framework_id
    WHERE f.id=previous AND (fw.configuration->>'allowFinalCorrections')::boolean) THEN
    RAISE EXCEPTION 'Pinned policy does not permit exceptional correction evidence' USING ERRCODE='42501';
  END IF;
  INSERT INTO public.course_correction_requests(offering_id$guard$);
 definition:=replace(definition,'note,direct_coordinator_version_id)', 'note,direct_coordinator_version_id,exceptional_result_id)');
 definition:=replace(definition,'assignment) RETURNING id INTO target;', 'assignment,previous) RETURNING id INTO target;');
 definition:=replace(definition,anchor,$guard$
  SELECT f.id INTO previous FROM public.course_final_results f JOIN public.project_reviews r ON r.project_id=f.project_id
    WHERE r.id=request.review_id ORDER BY f.version DESC LIMIT 1;
  IF previous IS DISTINCT FROM request.exceptional_result_id OR
     (previous IS NOT NULL) IS DISTINCT FROM coalesce((input->>'_exceptional')::boolean,false) THEN
    RAISE EXCEPTION 'Use the correction procedure for the current publication state' USING ERRCODE='42501';
  END IF;
  IF action='AUTHORIZE_CORRECTION' THEN$guard$);
 EXECUTE definition;
END $patch$;
-- A direct academic call must never apply an ordinary request after publication.
DO $patch$
DECLARE definition text; anchor text := ' AND q.review_id=rid';
BEGIN
 definition:=pg_get_functiondef('public.smartpro_course_correction_guard(uuid,uuid,jsonb)'::regprocedure);
 IF strpos(definition,anchor)=0 THEN RAISE EXCEPTION 'Reviewed correction guard required'; END IF;
 EXECUTE replace(definition,anchor,$guard$
  AND q.exceptional_result_id IS NOT DISTINCT FROM (
    SELECT f.id FROM public.course_final_results f JOIN public.project_reviews r ON r.project_id=f.project_id
    WHERE r.id=rid ORDER BY f.version DESC LIMIT 1)
  AND q.review_id=rid$guard$);
END $patch$;
DO $patch$
DECLARE definition text; anchor text := '''overallFinalPublished'',closed,''overallResults'',final_results';
BEGIN
 definition:=pg_get_functiondef('public.smartpro_configured_document_workspace(uuid,uuid,text)'::regprocedure);
 IF strpos(definition,anchor)=0 THEN RAISE EXCEPTION 'Reviewed document workspace required'; END IF;
 EXECUTE replace(definition,anchor,$projection$
 'overallFinalPublished',closed,'overallResults',final_results,
 'exceptionalStageCorrectionsAllowed',closed AND EXISTS(
   SELECT FROM public.course_final_results f JOIN public.course_plan_versions cp ON cp.id=f.plan_id
   JOIN public.course_framework_versions fw ON fw.id=cp.framework_id
   WHERE f.project_id=(p->>'id')::uuid AND (fw.configuration->>'allowFinalCorrections')::boolean)
 $projection$);
END $patch$;
-- Narrow the legacy document projection before it chooses its first 50 rows.
-- The transaction-local setting is only a further restriction, never a grant.
DO $patch$
DECLARE definition text; anchor text := 'WHERE p.department_id=dept AND public.smartpro_document_scope';
BEGIN
 definition:=pg_get_functiondef('public.smartpro_document_workspace(uuid,uuid)'::regprocedure);
 IF strpos(definition,anchor)=0 THEN RAISE EXCEPTION 'Reviewed document selector required'; END IF;
 EXECUTE replace(definition,anchor,$filter$
 WHERE p.department_id=dept
   AND (nullif(current_setting('smartpro.document_project',true),'') IS NULL
     OR p.id::text=current_setting('smartpro.document_project',true))
   AND public.smartpro_document_scope$filter$);
END $patch$;
CREATE FUNCTION public.smartpro_course_project_documents(actor uuid,dept uuid,pid uuid,role text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE scope text:=current_setting('smartpro.document_project',true); result jsonb;
BEGIN
 IF role IS DISTINCT FROM 'Coordinator' OR NOT EXISTS(SELECT FROM public.projects p WHERE p.id=pid AND p.department_id=dept)
   OR NOT public.smartpro_course_access(actor,public.smartpro_course_project_offering(pid),'READ',role) THEN
   RAISE EXCEPTION 'Current offering project required' USING ERRCODE='42501';
 END IF;
 PERFORM set_config('smartpro.document_project',pid::text,true);
 result:=public.smartpro_configured_document_workspace(actor,dept,role);
 PERFORM set_config('smartpro.document_project',coalesce(scope,''),true);
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_course_project_documents(uuid,uuid,uuid,text) FROM PUBLIC,smartpro_runtime;
GRANT EXECUTE ON FUNCTION public.smartpro_course_project_documents(uuid,uuid,uuid,text) TO smartpro_runtime;
COMMIT;
