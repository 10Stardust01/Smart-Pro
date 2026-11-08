-- A coordinator can correct their own finalized contribution before overall release.
BEGIN;

ALTER TABLE public.course_correction_requests
  ADD COLUMN direct_coordinator_version_id uuid REFERENCES public.course_coordinator_versions(id);

DO $migration$
DECLARE definition text;
BEGIN
  definition := pg_get_functiondef('public.smartpro_course_correction_guard(uuid,uuid,jsonb)'::regprocedure);
  definition := replace(definition,
    'JOIN public.course_correction_authorizations a ON a.request_id=q.id AND a.approved',
    'LEFT JOIN public.course_correction_authorizations a ON a.request_id=q.id AND a.approved');
  definition := replace(definition, ' WHERE q.review_id=rid',
    ' WHERE (a.request_id IS NOT NULL OR (q.direct_coordinator_version_id IS NOT NULL
      AND NOT EXISTS(SELECT FROM public.course_final_results f JOIN public.project_reviews r ON r.project_id=f.project_id WHERE r.id=rid)
      AND EXISTS(SELECT FROM public.smartpro_course_coordinators(q.offering_id) v
        WHERE v.id=q.direct_coordinator_version_id AND v.user_id=actor AND ''CORRECTIONS''=ANY(v.responsibilities))))
      AND q.review_id=rid');
  definition := replace(definition, 'ORDER BY q.created_at LIMIT 1',
    'ORDER BY (q.direct_coordinator_version_id IS NOT NULL) DESC,q.created_at LIMIT 1');
  EXECUTE definition;

  definition := pg_get_functiondef('public.smartpro_course_command(uuid,uuid,text,jsonb,text)'::regprocedure);
  IF strpos(definition,'  INSERT INTO public.course_correction_requests(offering_id')=0 THEN
    RAISE EXCEPTION 'Reviewed course correction command required';
  END IF;
  definition := replace(definition, '  INSERT INTO public.course_correction_requests(offering_id', $command$
  SELECT project_id INTO pid FROM public.project_reviews WHERE id=rid;
  SELECT id INTO assignment FROM public.smartpro_course_coordinators(oid)
    WHERE user_id=actor AND 'CORRECTIONS'=ANY(responsibilities)
      AND NOT EXISTS(SELECT FROM public.course_final_results WHERE project_id=pid);
  IF assignment IS NOT NULL THEN
    PERFORM public.smartpro_course_authority(actor,oid,'CORRECTIONS','Coordinator');
  END IF;
  INSERT INTO public.course_correction_requests(offering_id$command$);
  definition := replace(definition,
    $old$expected_revision,scores,note) VALUES(oid,rid,(input->>'assessmentId')::uuid,actor,(input->>'expectedReviewRevision')::integer,input->'scores',nullif(input->>'reason','')) RETURNING id INTO target;$old$,
    $new$expected_revision,scores,note,direct_coordinator_version_id)
  VALUES(oid,rid,(input->>'assessmentId')::uuid,actor,(input->>'expectedReviewRevision')::integer,input->'scores',nullif(input->>'reason',''),assignment) RETURNING id INTO target;
  IF assignment IS NOT NULL THEN
    result:=public.smartpro_academic_review_command(actor,o.department_id,'EVALUATE',
      jsonb_build_object('reviewId',rid,'assessmentId',input->>'assessmentId','expectedReviewRevision',input->'expectedReviewRevision','scores',input->'scores','reason',coalesce(input->>'reason','')),
      'course-correct:'||target::text)||jsonb_build_object('appliedImmediately',true);
  END IF;$new$);
  IF strpos(definition,'''appliedImmediately''')=0 THEN
    RAISE EXCEPTION 'Reviewed correction insert required';
  END IF;
  EXECUTE definition;
END
$migration$;

COMMIT;
