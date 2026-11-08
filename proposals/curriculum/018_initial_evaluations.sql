-- Owner-run candidate after 017. Tested on synthetic databases only.
BEGIN;
DO $$ BEGIN
  IF to_regprocedure('public.smartpro_academic_review_command(uuid,uuid,text,jsonb,text)') IS NULL THEN
    RAISE EXCEPTION 'Install academic result versions 017 first'; END IF;
END $$;
CREATE OR REPLACE FUNCTION public.smartpro_initial_evaluation(actor uuid,dept uuid,action_name text,input jsonb,request_key text)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE prior public.academic_command_receipts%ROWTYPE; auth jsonb; project public.projects%ROWTYPE;
        review public.project_reviews%ROWTYPE; assessment public.assessments%ROWTYPE;
        scheme public.scheme_versions%ROWTYPE; academic_policy public.academic_evaluation_policies%ROWTYPE;
        role_id uuid; faculty uuid; assignment uuid; rid uuid; member record; criterion record; score jsonb;
        stamp timestamptz; n integer; before_scores jsonb; output jsonb; binding jsonb;
BEGIN
  IF request_key IS NULL OR request_key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
    OR jsonb_typeof(input) IS DISTINCT FROM 'object' OR length(btrim(coalesce(input->>'reason',''))) NOT BETWEEN 1 AND 500 THEN
    RAISE EXCEPTION 'valid key, command and reason required' USING ERRCODE='22023'; END IF;
  PERFORM 1 FROM public.academic_governance_settings WHERE department_id=dept AND enabled FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'academic service disabled' USING ERRCODE='42501'; END IF;
  IF action_name='CREATE_REVIEW' THEN
    auth:=public.smartpro_academic_authority(actor,dept);
  ELSIF action_name IN ('SAVE_DRAFT','FINALIZE_DRAFT') THEN
    SELECT a.* INTO assessment FROM public.assessments a JOIN public.evaluator_assignments e ON e.id=a.evaluator_assignment_id
      JOIN public.project_reviews r ON r.id=a.review_id JOIN public.projects p ON p.id=r.project_id
      WHERE a.id=(input->>'assessmentId')::uuid AND e.faculty_user_id=actor AND p.department_id=dept FOR UPDATE OF a,r;
    IF NOT FOUND THEN RAISE EXCEPTION 'own assigned assessment required' USING ERRCODE='42501'; END IF;
    SELECT r.id INTO role_id FROM public.department_role_assignments r JOIN public.users u ON u.id=r.user_id
      WHERE r.user_id=actor AND r.department_id=dept AND r.role_code='FACULTY' AND u.account_status='ACTIVE'
        AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)
      ORDER BY r.id LIMIT 1 FOR UPDATE OF r FOR SHARE OF u;
    IF NOT FOUND THEN RAISE EXCEPTION 'active assigned faculty required' USING ERRCODE='42501'; END IF;
    auth:=jsonb_build_object('facultyRoleId',role_id,'originalEvaluatorId',actor);
  ELSE RAISE EXCEPTION 'unsupported evaluation command' USING ERRCODE='22023';
  END IF;
  SELECT r.* INTO prior FROM public.academic_command_receipts r WHERE r.actor_id=actor AND r.request_key=smartpro_initial_evaluation.request_key;
  IF FOUND THEN
    IF (prior.department_id,prior.action,prior.input) IS DISTINCT FROM (dept,action_name,input) THEN
      RAISE EXCEPTION 'idempotency conflict' USING ERRCODE='23505'; END IF;
    RETURN prior.output;
  END IF;
  IF action_name='CREATE_REVIEW' THEN
    SELECT p.* INTO project FROM public.projects p WHERE p.id=(input->>'projectId')::uuid AND p.department_id=dept FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'project outside department' USING ERRCODE='42501'; END IF;
    SELECT s.* INTO scheme FROM public.scheme_versions s JOIN public.evaluation_schemes es ON es.id=s.scheme_id
      JOIN public.review_definitions d ON d.id=s.review_definition_id
      WHERE s.id=(input->>'schemeVersionId')::uuid AND s.state='ACTIVE' AND es.department_id=dept
        AND s.cycle_id=project.cycle_id AND d.policy_version_id=project.policy_version_id FOR SHARE OF s,es,d;
    IF NOT FOUND OR NOT EXISTS(SELECT FROM public.scheme_modes WHERE id=(input->>'schemeModeId')::uuid AND scheme_version_id=scheme.id) THEN
      RAISE EXCEPTION 'applicable active rubric and mode required' USING ERRCODE='23514'; END IF;
    SELECT p.* INTO academic_policy FROM public.academic_evaluation_policies p WHERE p.id=(input->>'policyId')::uuid AND p.department_id=dept;
    IF NOT FOUND OR jsonb_typeof(input->'facultyIds') IS DISTINCT FROM 'array' OR jsonb_array_length(input->'facultyIds')<academic_policy.evaluator_quorum
      OR jsonb_array_length(input->'facultyIds')<>(SELECT count(DISTINCT value::uuid) FROM jsonb_array_elements_text(input->'facultyIds')) THEN
      RAISE EXCEPTION 'distinct evaluators satisfying configured quorum required' USING ERRCODE='23514'; END IF;
    IF academic_policy.aggregation='WEIGHTED_MEAN' AND
      (SELECT jsonb_object_agg(value::uuid::text,true) FROM jsonb_array_elements_text(input->'facultyIds')) IS DISTINCT FROM
      (SELECT jsonb_object_agg(key,true) FROM jsonb_each(academic_policy.evaluator_weights)) THEN
      RAISE EXCEPTION 'configured evaluator weights must match assignments' USING ERRCODE='23514'; END IF;
    PERFORM 1 FROM public.teams WHERE id=project.team_id FOR SHARE;
    stamp:=clock_timestamp();
    INSERT INTO public.project_reviews(project_id,cycle_id,policy_version_id,review_definition_id,round_no,scheme_version_id,scheme_mode_id)
      SELECT project.id,project.cycle_id,project.policy_version_id,scheme.review_definition_id,coalesce(max(round_no),0)+1,scheme.id,(input->>'schemeModeId')::uuid
        FROM public.project_reviews WHERE project_id=project.id AND review_definition_id=scheme.review_definition_id RETURNING id INTO rid;
    FOR member IN SELECT m.* FROM public.team_memberships m JOIN public.users u ON u.id=m.user_id
      WHERE m.team_id=project.team_id AND m.joined_at<=stamp AND (m.left_at IS NULL OR stamp<m.left_at)
      ORDER BY m.id FOR SHARE OF m,u LOOP
      IF NOT EXISTS(SELECT FROM public.users WHERE id=member.user_id AND account_status='ACTIVE') THEN
        RAISE EXCEPTION 'verify disabled team member eligibility before freezing a review' USING ERRCODE='23514'; END IF;
      PERFORM 1 FROM public.department_role_assignments r WHERE r.user_id=member.user_id AND r.department_id=dept AND r.role_code='STUDENT'
        AND r.valid_from<=stamp AND (r.valid_until IS NULL OR stamp<r.valid_until) FOR SHARE;
      IF NOT FOUND THEN RAISE EXCEPTION 'current student role required for complete team roster' USING ERRCODE='23514'; END IF;
      INSERT INTO public.review_roster_members(review_id,project_id,team_id,membership_id,student_user_id,created_at)
        VALUES(rid,project.id,project.team_id,member.id,member.user_id,stamp);
    END LOOP;
    UPDATE public.project_reviews SET review_state='OPEN',roster_locked_at=stamp,row_version=row_version+1 WHERE id=rid;
    FOR faculty IN SELECT value::uuid FROM jsonb_array_elements_text(input->'facultyIds') ORDER BY value::uuid LOOP
      PERFORM 1 FROM public.department_role_assignments r JOIN public.users u ON u.id=r.user_id
        WHERE r.user_id=faculty AND r.department_id=dept AND r.role_code='FACULTY' AND u.account_status='ACTIVE'
          AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until) FOR SHARE OF r,u;
      IF NOT FOUND THEN RAISE EXCEPTION 'effective departmental faculty required' USING ERRCODE='42501'; END IF;
      INSERT INTO public.evaluator_assignments(review_id,faculty_user_id) VALUES(rid,faculty) RETURNING id INTO assignment;
      INSERT INTO public.assessments(review_id,scheme_mode_id,evaluator_assignment_id) VALUES(rid,(input->>'schemeModeId')::uuid,assignment);
    END LOOP;
    binding:=public.smartpro_academic_review_command(actor,dept,'BIND',jsonb_build_object('reviewId',rid,'policyId',academic_policy.id,
      'expectedReviewRevision',0,'reason',input->>'reason'),'initial-bind:'||rid::text);
    output:=jsonb_build_object('reviewId',rid,'revision',binding->'revision');
  ELSE
    IF assessment.state<>'DRAFT' OR coalesce(input->>'expectedAssessmentVersion','') !~ '^[1-9][0-9]*$'
      OR assessment.row_version<>(input->>'expectedAssessmentVersion')::integer THEN
      RAISE EXCEPTION 'stale or finalized assessment' USING ERRCODE='23514'; END IF;
    rid:=assessment.review_id;
    before_scores:=public.smartpro_academic_base_scores(assessment.id);
    IF action_name='SAVE_DRAFT' THEN
      SELECT coalesce(sum(CASE WHEN score_scope='TEAM' THEN 1 ELSE (SELECT count(*) FROM public.review_roster_members WHERE review_id=rid) END),0)
        INTO n FROM public.mode_criteria WHERE scheme_mode_id=assessment.scheme_mode_id;
      IF jsonb_typeof(input->'scores') IS DISTINCT FROM 'array' OR jsonb_array_length(input->'scores')<>n OR n=0
        OR (SELECT count(DISTINCT (x->>'criterionId',x->>'studentId')) FROM jsonb_array_elements(input->'scores') x)<>n THEN
        RAISE EXCEPTION 'complete distinct criterion scores required' USING ERRCODE='23514'; END IF;
      FOR score IN SELECT value FROM jsonb_array_elements(input->'scores') LOOP
        IF jsonb_typeof(score) IS DISTINCT FROM 'object' OR score-ARRAY['criterionId','studentId','marks']<>'{}'
          OR NOT score ?& ARRAY['criterionId','studentId','marks'] OR coalesce(score->>'marks','') !~ '^[0-9]+(\.[0-9]{1,2})?$' THEN
          RAISE EXCEPTION 'exact criterion, student and decimal marks required' USING ERRCODE='22023'; END IF;
        SELECT mc.score_scope,rc.maximum INTO criterion FROM public.mode_criteria mc JOIN public.rubric_criteria rc ON rc.id=mc.criterion_id
          WHERE mc.id=(score->>'criterionId')::uuid AND mc.scheme_mode_id=assessment.scheme_mode_id;
        IF NOT FOUND OR (score->>'marks')::numeric>criterion.maximum THEN RAISE EXCEPTION 'marks outside rubric' USING ERRCODE='23514'; END IF;
        IF criterion.score_scope='TEAM' THEN
          IF score->>'studentId' IS NOT NULL THEN RAISE EXCEPTION 'team criterion cannot target student' USING ERRCODE='23514'; END IF;
          INSERT INTO public.team_criterion_scores VALUES(assessment.id,assessment.scheme_mode_id,(score->>'criterionId')::uuid,'TEAM',(score->>'marks')::numeric)
            ON CONFLICT(assessment_id,mode_criterion_id) DO UPDATE SET marks=excluded.marks;
        ELSE
          SELECT * INTO member FROM public.review_roster_members WHERE review_id=rid AND student_user_id::text=score->>'studentId';
          IF NOT FOUND THEN RAISE EXCEPTION 'student outside frozen roster' USING ERRCODE='23514'; END IF;
          INSERT INTO public.student_criterion_scores VALUES(assessment.id,rid,assessment.scheme_mode_id,member.id,(score->>'criterionId')::uuid,'STUDENT',(score->>'marks')::numeric)
            ON CONFLICT(assessment_id,roster_member_id,mode_criterion_id) DO UPDATE SET marks=excluded.marks;
        END IF;
      END LOOP;
      UPDATE public.assessments SET row_version=row_version+1 WHERE id=assessment.id RETURNING * INTO assessment;
    ELSE
      UPDATE public.assessments SET state='FINALIZED',row_version=row_version+1 WHERE id=assessment.id RETURNING * INTO assessment;
      IF NOT EXISTS(SELECT FROM public.assessments WHERE review_id=rid AND state<>'FINALIZED') THEN
        UPDATE public.project_reviews SET review_state='FINALIZED',row_version=row_version+1 WHERE id=rid AND review_state='OPEN';
      END IF;
    END IF;
    output:=jsonb_build_object('reviewId',rid,'assessmentId',assessment.id,'assessmentVersion',assessment.row_version,'state',assessment.state);
  END IF;
  IF role_id IS NOT NULL THEN
    UPDATE public.department_role_assignments SET staff_authority_revision=gen_random_uuid() WHERE id=role_id;
    IF NOT EXISTS(SELECT FROM public.department_role_assignments WHERE id=role_id AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until)) THEN
      RAISE EXCEPTION 'evaluator authority expired' USING ERRCODE='42501'; END IF;
    auth:=auth||jsonb_build_object('authorizedAt',clock_timestamp());
  ELSE auth:=public.smartpro_academic_authority(actor,dept);
  END IF;
  INSERT INTO public.audit_events(actor_id,action,target_type,target_id,metadata) VALUES(actor,'ACADEMIC_'||action_name,'PROJECT_REVIEW',rid,
    jsonb_build_object('departmentId',dept,'authority',auth,'oldScores',before_scores,'new',input,'result',output,'reason',input->>'reason'));
  INSERT INTO public.academic_command_receipts(actor_id,request_key,department_id,action,target_id,input,output,authority,occurred_at)
    VALUES(actor,request_key,dept,action_name,rid,input,output,auth,(auth->>'authorizedAt')::timestamptz);
  RETURN output;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_initial_evaluation(uuid,uuid,text,jsonb,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_initial_evaluation(uuid,uuid,text,jsonb,text) TO smartpro_runtime;
COMMIT;
