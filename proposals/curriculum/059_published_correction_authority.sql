-- Candidate 059: align exceptional, already-published result correction authority.
-- Forward-only; install once after 058 on a tested, backed-up copy first.
-- This does NOT alter ordinary pre-publication authorization rules, source
-- assessments, existing releases, provenance, or any published result.
BEGIN;
DO $migration$
DECLARE definition text; old text; replacement text;
BEGIN
 IF to_regclass('public.course_correction_requests') IS NULL
    OR NOT EXISTS(SELECT 1 FROM information_schema.columns
       WHERE table_schema='public' AND table_name='course_correction_requests'
         AND column_name='exceptional_result_id')
    OR to_regprocedure('public.smartpro_course_final_revision(uuid,uuid,text,jsonb,text)') IS NULL THEN
  RAISE EXCEPTION 'Candidate 059 requires installed published-result correction contracts through 058';
 END IF;
 definition:=pg_get_functiondef('public.smartpro_course_command(uuid,uuid,text,jsonb,text)'::regprocedure);
 old:=$old$IF role<>'Coordinator' OR request.requester_id=actor OR (coalesce((framework.configuration->>'outsidePanelAuthorizer')::boolean,true) AND EXISTS(SELECT FROM public.evaluator_assignments WHERE review_id=request.review_id AND faculty_user_id=actor)) THEN RAISE EXCEPTION 'Independent appointed coordinator required; self-authorization forbidden' USING ERRCODE='42501'; END IF;$old$;
 replacement:=$new$IF role<>'Coordinator' OR
     (request.exceptional_result_id IS NULL AND
       (request.requester_id=actor OR
        (coalesce((framework.configuration->>'outsidePanelAuthorizer')::boolean,true) AND
         EXISTS(SELECT FROM public.evaluator_assignments WHERE review_id=request.review_id AND faculty_user_id=actor))))
   THEN RAISE EXCEPTION 'Current coordinator required; ordinary corrections keep their pinned authorizer restrictions' USING ERRCODE='42501'; END IF;$new$;
 IF (length(definition)-length(replace(definition,old,'')))<>length(old) THEN
  RAISE EXCEPTION 'Reviewed stage correction authorization definition changed; stop for review';
 END IF;
 EXECUTE replace(definition,old,replacement);
 definition:=pg_get_functiondef('public.smartpro_course_final_revision(uuid,uuid,text,jsonb,text)'::regprocedure);
 old:=$old$IF input->>'_actingRole'<>'Coordinator' OR request.requester_id=actor OR ((cfg->>'outsidePanelAuthorizer')::boolean AND EXISTS(SELECT FROM public.evaluator_assignments e JOIN public.project_reviews r ON r.id=e.review_id WHERE r.project_id=pid AND e.faculty_user_id=actor AND public.smartpro_evaluator_active(e.id))) THEN RAISE EXCEPTION 'Independent appointed course coordinator required' USING ERRCODE='42501'; END IF;$old$;
 replacement:=$new$IF input->>'_actingRole'<>'Coordinator' THEN RAISE EXCEPTION 'Responsible offering coordinator required for exceptional overall authorization' USING ERRCODE='42501'; END IF;$new$;
 IF (length(definition)-length(replace(definition,old,'')))<>length(old) THEN
  RAISE EXCEPTION 'Reviewed overall revision authorization definition changed; stop for review';
 END IF;
 definition:=replace(definition,old,replacement);
 -- The assigned, currently effective project Guide may request an already
 -- calculated exact revision. Scores still come only from approved stage evidence.
 old:=$old$permission:=CASE WHEN action='AUTHORIZE_FINAL_REVISION' THEN 'CORRECTIONS' ELSE 'RESULTS' END;
 PERFORM public.smartpro_course_authority(actor,oid,permission,input->>'_actingRole');$old$;
 replacement:=$new$permission:=CASE WHEN action='AUTHORIZE_FINAL_REVISION' THEN 'CORRECTIONS' ELSE 'RESULTS' END;
 IF action='REQUEST_FINAL_REVISION' AND input->>'_actingRole'='Faculty' THEN
  IF NOT public.smartpro_role_choices(actor) ? 'Faculty'
     OR NOT EXISTS(
       SELECT 1 FROM public.faculty_assignments g
       JOIN public.curriculum_offerings o ON o.id=oid
       WHERE g.project_id=(input->>'projectId')::uuid
         AND public.smartpro_course_project_offering(g.project_id)=oid
         AND g.faculty_user_id=actor AND g.assignment_type='GUIDE'
         AND g.valid_from<=clock_timestamp()
         AND (g.valid_until IS NULL OR clock_timestamp()<g.valid_until)
         AND public.smartpro_has_role(actor,o.department_id,'FACULTY',clock_timestamp())) THEN
    RAISE EXCEPTION 'Current assigned project Guide required' USING ERRCODE='42501';
  END IF;
 ELSE
  PERFORM public.smartpro_course_authority(actor,oid,permission,input->>'_actingRole');
 END IF;$new$;
 IF (length(definition)-length(replace(definition,old,'')))<>length(old) THEN
  RAISE EXCEPTION 'Reviewed final revision role guard changed; stop for review';
 END IF;
 definition:=replace(definition,old,replacement);
 old:=$old$IF NOT cfg->'publicationRoles' ? (input->>'_actingRole') OR result_row.version IS DISTINCT FROM (input->>'expectedVersion')::integer THEN RAISE EXCEPTION 'Current authorized overall result revision required' USING ERRCODE='23514'; END IF;$old$;
 replacement:=$new$IF (input->>'_actingRole'<>'Faculty' AND NOT (cfg->'publicationRoles' ? (input->>'_actingRole')))
     OR result_row.version IS DISTINCT FROM (input->>'expectedVersion')::integer THEN
    RAISE EXCEPTION 'Current authorized overall result revision required' USING ERRCODE='23514';
   END IF;$new$;
 IF (length(definition)-length(replace(definition,old,'')))<>length(old) THEN
  RAISE EXCEPTION 'Reviewed final revision request guard changed; stop for review';
 END IF;
 definition:=replace(definition,old,replacement);
 -- The approving Coordinator may apply an exact, previously approved request
 -- even if the Guide submitted it. Publishing still requires RESULTS authority
 -- and the approved publication role; no HOD or extra approval is inserted.
 old:=$old$IF actor<>request.requester_id OR NOT cfg->'publicationRoles' ? (input->>'_actingRole') OR result_row.version<>request.expected_version OR NOT EXISTS(SELECT FROM public.course_final_revision_authorizations WHERE request_id=request.id AND approved) OR EXISTS(SELECT FROM public.course_final_revision_applications WHERE request_id=request.id) THEN RAISE EXCEPTION 'Specific unused authorization and original requester required' USING ERRCODE='42501'; END IF;$old$;
 replacement:=$new$IF (actor<>request.requester_id AND NOT EXISTS(
       SELECT FROM public.course_final_revision_authorizations a
       WHERE a.request_id=request.id AND a.actor_id=actor AND a.approved))
     OR NOT (cfg->'publicationRoles' ? (input->>'_actingRole'))
     OR result_row.version<>request.expected_version
     OR NOT EXISTS(SELECT FROM public.course_final_revision_authorizations WHERE request_id=request.id AND approved)
     OR EXISTS(SELECT FROM public.course_final_revision_applications WHERE request_id=request.id)
   THEN RAISE EXCEPTION 'Current published-result version and exact approved request required' USING ERRCODE='42501'; END IF;$new$;
 IF (length(definition)-length(replace(definition,old,'')))<>length(old) THEN
  RAISE EXCEPTION 'Reviewed final revision application guard changed; stop for review';
 END IF;
 EXECUTE replace(definition,old,replacement);
END $migration$;
COMMIT;
