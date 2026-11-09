-- Candidate 061: include both exceptional correction modes in authorized read projections.
-- No academic marks, policy, historical releases, access grants, or assignments are changed.
BEGIN;
DO $guard$
BEGIN
 IF to_regprocedure('public.smartpro_course_final_revision(uuid,uuid,text,jsonb,text)') IS NULL
 OR to_regprocedure('public.smartpro_course_details(uuid,uuid,text)') IS NULL
 OR to_regprocedure('public.smartpro_guide_final_corrections(uuid,text)') IS NULL
 THEN RAISE EXCEPTION 'Installed correction functions 059 and 060 required'; END IF;
 IF strpos(pg_get_functiondef('public.smartpro_course_final_revision(uuid,uuid,text,jsonb,text)'::regprocedure),
           'STAGE_EVIDENCE_OVERALL_CORRECTION')=0
 THEN RAISE EXCEPTION 'Forward migration 060 required first'; END IF;
 IF strpos(pg_get_functiondef('public.smartpro_guide_final_corrections(uuid,text)'::regprocedure),
           'STAGE_EVIDENCE_OVERALL_CORRECTION')>0
 THEN RAISE EXCEPTION '061 already installed or read model differs; investigate before retry'; END IF;
END $guard$;

CREATE OR REPLACE FUNCTION public.smartpro_course_details(actor uuid,oid uuid,role text)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE result jsonb;
BEGIN
 result:=public.smartpro_course_details_pre059(actor,oid,role);
 IF role IN ('Coordinator','HOD') THEN
  result:=jsonb_set(result,'{finalRevisions}',coalesce((
   SELECT jsonb_agg(to_jsonb(x) ORDER BY x.created_at DESC)
   FROM (SELECT q.id,q.project_id,q.expected_version,q.snapshot,q.requester_id,
      q.reason,q.created_at,u.display_name,
      (SELECT display_name FROM public.users WHERE id=(q.snapshot->'changes'->0->>'studentId')::uuid) AS student_name,
      a.approved,a.actor_id AS authorizer_id,
      app.result_id,(app.request_id IS NOT NULL) AS applied
    FROM public.course_final_revision_requests q
    JOIN public.users u ON u.id=q.requester_id
    LEFT JOIN public.course_final_revision_authorizations a ON a.request_id=q.id
    LEFT JOIN public.course_final_revision_applications app ON app.request_id=q.id
    WHERE public.smartpro_course_project_offering(q.project_id)=oid
      AND q.snapshot->>'type' IN ('DIRECT_AUTHORIZED_OVERALL_CORRECTION','STAGE_EVIDENCE_OVERALL_CORRECTION')
    ORDER BY q.created_at DESC LIMIT 100) x
   ),'[]'::jsonb));
 ELSE result:=jsonb_set(result,'{finalRevisions}','[]'::jsonb);
 END IF;
 RETURN result;
END $$;
CREATE OR REPLACE FUNCTION public.smartpro_guide_final_corrections(actor uuid,role text)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF role<>'Faculty' OR NOT public.smartpro_role_choices(actor) ? role THEN
   RAISE EXCEPTION 'Current Faculty role required' USING ERRCODE='42501'; END IF;
 RETURN jsonb_build_object('projects',coalesce((
  SELECT jsonb_agg(to_jsonb(x) ORDER BY x.title) FROM (
   SELECT p.id AS "projectId",p.title,t.curriculum_offering_id AS "offeringId",
      f.version,
      CASE WHEN fw.configuration->>'method'='SINGLE_RAW'
       THEN f.sources->0->>'rubricMaximum' ELSE fw.configuration->>'scale' END AS "maxMarks",
      (fw.configuration->>'decimalPlaces')::integer AS "decimalPlaces",
      (SELECT coalesce(jsonb_agg(jsonb_build_object('studentId',kv.key,
         'name',coalesce(u.display_name,'Student'),'marks',kv.value)
         ORDER BY coalesce(u.display_name,'Student'),kv.key),'[]'::jsonb)
       FROM jsonb_each_text(f.results) kv LEFT JOIN public.users u ON u.id=kv.key::uuid) AS marks,
      (SELECT coalesce(jsonb_agg(jsonb_build_object(
         'id',q.id,'type',q.snapshot->>'type','changes',q.snapshot->'changes','reason',q.reason,
         'approved',a.approved,'applied',app.request_id IS NOT NULL,
         'createdAt',q.created_at) ORDER BY q.created_at DESC),'[]'::jsonb)
       FROM public.course_final_revision_requests q
       LEFT JOIN public.course_final_revision_authorizations a ON a.request_id=q.id
       LEFT JOIN public.course_final_revision_applications app ON app.request_id=q.id
       WHERE q.project_id=p.id AND q.requester_id=actor
          AND q.snapshot->>'type' IN ('DIRECT_AUTHORIZED_OVERALL_CORRECTION','STAGE_EVIDENCE_OVERALL_CORRECTION')) AS requests
   FROM public.projects p JOIN public.teams t ON t.id=p.team_id
   JOIN public.course_final_results f ON f.project_id=p.id
   JOIN public.course_plan_versions cp ON cp.id=f.plan_id
   JOIN public.course_framework_versions fw ON fw.id=cp.framework_id
   WHERE f.id=(SELECT newest.id FROM public.course_final_results newest
       WHERE newest.project_id=p.id ORDER BY newest.version DESC LIMIT 1)
     AND coalesce((fw.configuration->>'allowFinalCorrections')::boolean,false)
     AND public.smartpro_current_project_guide(actor,p.id)
   ORDER BY p.title,p.id LIMIT 100
  ) x
 ),'[]'::jsonb));
END $$;
-- CREATE OR REPLACE retains original owner and EXECUTE grants.
COMMIT;
