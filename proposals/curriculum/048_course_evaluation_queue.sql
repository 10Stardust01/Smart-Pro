-- Owner-run candidate: scoped evaluation queue and publication preflight.
BEGIN;

CREATE FUNCTION public.smartpro_course_evaluation_queue(actor uuid, oid uuid, role text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE project record; plan record; stage record; review record; policy record;
        stages jsonb; projects jsonb := '[]'; sources jsonb; roster uuid; blocker text;
        overall text; published integer; assigned integer; release_version integer;
        can_publish boolean; can_authorize boolean; outside_panel boolean; own_assessment uuid; faculty jsonb; overflow boolean:=false;
BEGIN
 IF role IS DISTINCT FROM 'Coordinator' OR NOT public.smartpro_course_access(actor,oid,'READ',role) THEN
   RAISE EXCEPTION 'Current offering appointment required' USING ERRCODE='42501';
 END IF;
 can_publish:=public.smartpro_course_access(actor,oid,'RESULTS',role);
 can_authorize:=public.smartpro_course_access(actor,oid,'CORRECTIONS',role);
 SELECT coalesce((f.configuration->>'outsidePanelAuthorizer')::boolean,true) INTO outside_panel
 FROM public.course_plan_versions cp JOIN public.course_framework_versions f ON f.id=cp.framework_id
 WHERE cp.offering_id=oid ORDER BY cp.version DESC LIMIT 1;
 FOR project IN SELECT p.id,p.title,t.name AS team FROM public.projects p JOIN public.teams t ON t.id=p.team_id
   WHERE t.curriculum_offering_id=oid ORDER BY p.title,p.id LIMIT 101
 LOOP
   IF jsonb_array_length(projects)=100 THEN overflow:=true; EXIT; END IF;
   SELECT cp.id,cp.version,cp.schedules,f.configuration,f.version AS framework_version
     INTO plan FROM public.course_plan_versions cp JOIN public.course_framework_versions f ON f.id=cp.framework_id
     WHERE cp.offering_id=oid AND cp.id=coalesce(
       (SELECT plan_id FROM public.course_project_plans WHERE project_id=project.id),
       (SELECT id FROM public.course_plan_versions WHERE offering_id=oid ORDER BY version DESC LIMIT 1));
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
     SELECT count(*) INTO assigned FROM public.evaluator_assignments e WHERE e.review_id=review.id AND public.smartpro_evaluator_active(e.id);
     SELECT id INTO roster FROM public.academic_roster_versions WHERE review_id=review.id ORDER BY version_no DESC LIMIT 1;
     sources:=CASE WHEN roster IS NOT NULL THEN public.smartpro_academic_sources(review.id,roster) END;
     SELECT coalesce(jsonb_agg(jsonb_build_object('name',u.display_name,'state',a.state) ORDER BY u.display_name),'[]'),
       (array_agg(a.id) FILTER (WHERE e.faculty_user_id=actor))[1]
       INTO faculty,own_assessment
       FROM public.evaluator_assignments e JOIN public.users u ON u.id=e.faculty_user_id
       LEFT JOIN public.assessments a ON a.evaluator_assignment_id=e.id AND a.review_id=e.review_id
       WHERE e.review_id=review.id AND public.smartpro_evaluator_active(e.id);
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
       'canAuthorizeCorrection',can_authorize AND release_version IS NULL AND
         (NOT coalesce(outside_panel,true) OR NOT EXISTS(SELECT FROM public.evaluator_assignments
           WHERE review_id=review.id AND faculty_user_id=actor)),
       'finalized',jsonb_array_length(sources),
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
     'id',project.id,'title',project.title,'team',project.team,'planVersion',plan.version,
     'frameworkVersion',plan.framework_version,'stages',stages,'overallBlocker',overall,'overallVersion',release_version));
 END LOOP;
 RETURN jsonb_build_object('projects',projects,'truncated',overflow);
END $$;

REVOKE ALL ON FUNCTION public.smartpro_course_evaluation_queue(uuid,uuid,text) FROM PUBLIC,smartpro_runtime;
GRANT EXECUTE ON FUNCTION public.smartpro_course_evaluation_queue(uuid,uuid,text) TO smartpro_runtime;
COMMIT;
