-- Candidate 062. Forward-only scoped correction paging; requires completed 061.
-- Only adds read-only functions. Does NOT change marks, histories, grants on
-- existing functions, academic policies, appointments, or published records.
BEGIN;
DO $guard$ BEGIN
 IF to_regprocedure('public.smartpro_course_final_revision(uuid,uuid,text,jsonb,text)') IS NULL
 OR to_regprocedure('public.smartpro_course_details_pre059(uuid,uuid,text)') IS NULL
 OR strpos(pg_get_functiondef('public.smartpro_guide_final_corrections(uuid,text)'::regprocedure),
   'STAGE_EVIDENCE_OVERALL_CORRECTION')=0 THEN
   RAISE EXCEPTION 'Installed candidate 061 is required before 062'; END IF;
 IF to_regprocedure('public.smartpro_guide_final_correction_project(uuid,text,uuid,integer,timestamptz)') IS NOT NULL
 OR to_regprocedure('public.smartpro_course_final_revisions_page(uuid,uuid,text,integer,timestamptz)') IS NOT NULL THEN
   RAISE EXCEPTION 'Candidate 062 already installed; do not reapply'; END IF;
END $guard$;

-- The existing Faculty project-work list is already paginated. Look up one
-- selected project directly, so a Guide's 101st+ project is never excluded.
-- Request history is separately bounded to 25/page with an anchor timestamp
-- stable under newly inserted requests.
CREATE FUNCTION public.smartpro_guide_final_correction_project(
 actor uuid, role text, pid uuid, requested_page integer, requested_anchor timestamptz DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE item jsonb; history jsonb; total bigint; at_time timestamptz;
BEGIN
 IF role<>'Faculty' OR NOT public.smartpro_role_choices(actor) ? role THEN
   RAISE EXCEPTION 'Current Faculty responsibility required' USING ERRCODE='42501'; END IF;
 IF requested_page IS NULL OR requested_page NOT BETWEEN 1 AND 100000000 THEN
   RAISE EXCEPTION 'Valid page required' USING ERRCODE='22023'; END IF;
 at_time:=coalesce(requested_anchor,clock_timestamp());
 SELECT jsonb_build_object('projectId',p.id,'title',p.title,'offeringId',t.curriculum_offering_id,
    'version',f.version,
    'maxMarks',CASE WHEN fw.configuration->>'method'='SINGLE_RAW'
                 THEN f.sources->0->>'rubricMaximum' ELSE fw.configuration->>'scale' END,
    'decimalPlaces',(fw.configuration->>'decimalPlaces')::integer,
    'marks',(SELECT coalesce(jsonb_agg(jsonb_build_object('studentId',kv.key,
       'name',coalesce(u.display_name,'Student'),'marks',kv.value)
       ORDER BY coalesce(u.display_name,'Student'),kv.key),'[]'::jsonb)
       FROM jsonb_each_text(f.results) kv
       LEFT JOIN public.users u ON u.id=kv.key::uuid))
 INTO item
 FROM public.projects p JOIN public.teams t ON t.id=p.team_id
 JOIN public.course_final_results f ON f.project_id=p.id
 JOIN public.course_plan_versions cp ON cp.id=f.plan_id
 JOIN public.course_framework_versions fw ON fw.id=cp.framework_id
 WHERE p.id=pid AND f.id=(SELECT newest.id FROM public.course_final_results newest
     WHERE newest.project_id=p.id ORDER BY newest.version DESC LIMIT 1)
   AND coalesce((fw.configuration->>'allowFinalCorrections')::boolean,false)
   AND public.smartpro_current_project_guide(actor,p.id);
 IF item IS NULL THEN RETURN jsonb_build_object('project',null,'requests','[]'::jsonb,
      'total',0,'page',requested_page,'pageSize',25,'anchor',at_time); END IF;
 SELECT count(*) INTO total FROM public.course_final_revision_requests q
 WHERE q.project_id=pid AND q.requester_id=actor AND q.created_at<=at_time
   AND q.snapshot->>'type' IN
   ('DIRECT_AUTHORIZED_OVERALL_CORRECTION','STAGE_EVIDENCE_OVERALL_CORRECTION');
 SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.created_at DESC,x.id DESC),'[]'::jsonb)
 INTO history FROM (
   SELECT q.id,q.created_at,q.snapshot->>'type' AS type,
      q.snapshot->'changes' AS changes,q.reason,
      a.approved,app.request_id IS NOT NULL AS applied
   FROM public.course_final_revision_requests q
   LEFT JOIN public.course_final_revision_authorizations a ON a.request_id=q.id
   LEFT JOIN public.course_final_revision_applications app ON app.request_id=q.id
   WHERE q.project_id=pid AND q.requester_id=actor AND q.created_at<=at_time
     AND q.snapshot->>'type' IN
     ('DIRECT_AUTHORIZED_OVERALL_CORRECTION','STAGE_EVIDENCE_OVERALL_CORRECTION')
   ORDER BY q.created_at DESC,q.id DESC LIMIT 25
   OFFSET ((requested_page::bigint-1)*25)
 ) x;
 RETURN jsonb_build_object('project',item,'requests',history,'total',total,
    'page',requested_page,'pageSize',25,'anchor',at_time);
END $$;

-- Preserve the Coordinator/HOD read scope from the original offering-details
-- function, then page requests. No extra approver is introduced.
CREATE FUNCTION public.smartpro_course_final_revisions_page(
 actor uuid, oid uuid, role text, requested_page integer, requested_anchor timestamptz DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE history jsonb; total bigint; at_time timestamptz;
BEGIN
 IF role NOT IN ('Coordinator','HOD') OR NOT public.smartpro_role_choices(actor) ? role THEN
   RAISE EXCEPTION 'Assigned course responsibility required' USING ERRCODE='42501'; END IF;
 IF requested_page IS NULL OR requested_page NOT BETWEEN 1 AND 100000000 THEN
   RAISE EXCEPTION 'Valid page required' USING ERRCODE='22023'; END IF;
 PERFORM public.smartpro_course_details_pre059(actor,oid,role);
 at_time:=coalesce(requested_anchor,clock_timestamp());
 SELECT count(*) INTO total FROM public.course_final_revision_requests q
 JOIN public.projects p ON p.id=q.project_id JOIN public.teams t ON t.id=p.team_id
 WHERE t.curriculum_offering_id=oid AND q.created_at<=at_time
   AND q.snapshot->>'type' IN
    ('DIRECT_AUTHORIZED_OVERALL_CORRECTION','STAGE_EVIDENCE_OVERALL_CORRECTION');
 SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.created_at DESC,x.id DESC),'[]'::jsonb)
 INTO history FROM (
   SELECT q.id,q.project_id,q.expected_version,q.snapshot,q.requester_id,q.reason,
     q.created_at,u.display_name,
     (SELECT display_name FROM public.users
       WHERE id=(q.snapshot->'changes'->0->>'studentId')::uuid) AS student_name,
     a.approved,a.actor_id AS authorizer_id,
     app.result_id,(app.request_id IS NOT NULL) AS applied
   FROM public.course_final_revision_requests q
   JOIN public.projects p ON p.id=q.project_id
   JOIN public.teams t ON t.id=p.team_id JOIN public.users u ON u.id=q.requester_id
   LEFT JOIN public.course_final_revision_authorizations a ON a.request_id=q.id
   LEFT JOIN public.course_final_revision_applications app ON app.request_id=q.id
   WHERE t.curriculum_offering_id=oid AND q.created_at<=at_time
     AND q.snapshot->>'type' IN
     ('DIRECT_AUTHORIZED_OVERALL_CORRECTION','STAGE_EVIDENCE_OVERALL_CORRECTION')
   ORDER BY q.created_at DESC,q.id DESC LIMIT 25
   OFFSET ((requested_page::bigint-1)*25)
 ) x;
 RETURN jsonb_build_object('requests',history,'total',total,
   'page',requested_page,'pageSize',25,'anchor',at_time);
END $$;
REVOKE ALL ON FUNCTION public.smartpro_guide_final_correction_project(uuid,text,uuid,integer,timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.smartpro_course_final_revisions_page(uuid,uuid,text,integer,timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_guide_final_correction_project(uuid,text,uuid,integer,timestamptz) TO smartpro_runtime;
GRANT EXECUTE ON FUNCTION public.smartpro_course_final_revisions_page(uuid,uuid,text,integer,timestamptz) TO smartpro_runtime;
COMMIT;
