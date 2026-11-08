-- Owner-run candidate after 016; never auto-activate on real academic records.
BEGIN;
DO $$ BEGIN
  IF to_regprocedure('public.smartpro_academic_governance(uuid,uuid,text,jsonb,text)') IS NULL THEN
    RAISE EXCEPTION 'Install academic governance 016 first'; END IF;
END $$;
CREATE TABLE public.academic_review_bindings (
  review_id uuid PRIMARY KEY REFERENCES public.project_reviews(id),
  department_id uuid NOT NULL,
  policy_id uuid NOT NULL,
  revision bigint NOT NULL DEFAULT 0,
  FOREIGN KEY(policy_id,department_id) REFERENCES public.academic_evaluation_policies(id,department_id)
);
CREATE TABLE public.academic_roster_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), review_id uuid NOT NULL REFERENCES public.project_reviews(id),
  version_no integer NOT NULL, supersedes_id uuid,
  actor_id uuid NOT NULL REFERENCES public.users(id), reason text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(review_id,version_no), UNIQUE(id,review_id),
  FOREIGN KEY(supersedes_id,review_id) REFERENCES public.academic_roster_versions(id,review_id)
);
CREATE TABLE public.academic_roster_members (
  roster_version_id uuid NOT NULL REFERENCES public.academic_roster_versions(id),
  student_user_id uuid NOT NULL, membership_id uuid NOT NULL,
  eligibility_role_id uuid NOT NULL REFERENCES public.department_role_assignments(id),
  team_id uuid NOT NULL, eligibility_at timestamptz NOT NULL,
  PRIMARY KEY(roster_version_id,student_user_id),
  FOREIGN KEY(membership_id,team_id,student_user_id) REFERENCES public.team_memberships(id,team_id,user_id)
);
CREATE TABLE public.academic_evaluation_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), assessment_id uuid NOT NULL REFERENCES public.assessments(id),
  roster_version_id uuid NOT NULL REFERENCES public.academic_roster_versions(id),
  version_no integer NOT NULL, actor_id uuid NOT NULL REFERENCES public.users(id),
  scores jsonb NOT NULL CHECK(jsonb_typeof(scores)='array'), reason text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(assessment_id,version_no)
);
CREATE TABLE public.academic_result_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), review_id uuid NOT NULL REFERENCES public.project_reviews(id),
  version_no integer NOT NULL, supersedes_id uuid,
  legacy_release_id uuid REFERENCES public.result_releases(id),
  roster_version_id uuid NOT NULL REFERENCES public.academic_roster_versions(id),
  policy_id uuid NOT NULL REFERENCES public.academic_evaluation_policies(id),
  actor_id uuid NOT NULL REFERENCES public.users(id), reason text NOT NULL,
  sources jsonb NOT NULL, results jsonb NOT NULL,
  calculation_version text NOT NULL DEFAULT 'DECIMAL_TOTAL_V1',
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(review_id,version_no), UNIQUE(id,review_id), UNIQUE(supersedes_id),
  FOREIGN KEY(supersedes_id,review_id) REFERENCES public.academic_result_versions(id,review_id)
);
ALTER TABLE public.team_memberships ADD COLUMN academic_evidence_revision uuid NOT NULL DEFAULT gen_random_uuid();
CREATE FUNCTION public.smartpro_academic_membership_history() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF NEW.left_at IS NOT NULL AND EXISTS(SELECT FROM public.academic_roster_members r WHERE r.membership_id=OLD.id AND NEW.left_at<=r.eligibility_at) THEN
    RAISE EXCEPTION 'membership end would falsify academic roster evidence' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER preserve_academic_roster_eligibility BEFORE UPDATE OF left_at ON public.team_memberships
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_academic_membership_history();
CREATE FUNCTION public.smartpro_academic_evaluator_role_history() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF EXISTS(SELECT FROM public.academic_command_receipts r WHERE r.authority->>'facultyRoleId'=OLD.id::text
    AND (NEW.valid_from>r.occurred_at OR (NEW.valid_until IS NOT NULL AND NEW.valid_until<=r.occurred_at)))
    OR EXISTS(SELECT FROM public.academic_roster_members m WHERE m.eligibility_role_id=OLD.id
      AND (NEW.valid_from>m.eligibility_at OR (NEW.valid_until IS NOT NULL AND NEW.valid_until<=m.eligibility_at))) THEN
    RAISE EXCEPTION 'role edit invalidates evaluator history' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER preserve_academic_evaluator_history BEFORE UPDATE OF valid_from,valid_until ON public.department_role_assignments
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_academic_evaluator_role_history();
CREATE INDEX ix_academic_roster_history ON public.academic_roster_members(membership_id,eligibility_at);
CREATE INDEX ix_academic_evaluation_latest ON public.academic_evaluation_versions(assessment_id,version_no DESC);
CREATE FUNCTION public.smartpro_academic_binding_identity() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'retain review policy history' USING ERRCODE='23514'; END IF;
  IF (NEW.review_id,NEW.department_id,NEW.policy_id) IS DISTINCT FROM (OLD.review_id,OLD.department_id,OLD.policy_id) OR NEW.revision<=OLD.revision THEN
    RAISE EXCEPTION 'review policy identity immutable; revision must advance' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER freeze_academic_binding BEFORE UPDATE OR DELETE ON public.academic_review_bindings
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_academic_binding_identity();
CREATE TRIGGER freeze_academic_roster BEFORE UPDATE OR DELETE ON public.academic_roster_versions
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation();
CREATE TRIGGER freeze_academic_roster_member BEFORE UPDATE OR DELETE ON public.academic_roster_members
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation();
CREATE TRIGGER freeze_academic_evaluation BEFORE UPDATE OR DELETE ON public.academic_evaluation_versions
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation();
CREATE TRIGGER freeze_academic_result BEFORE UPDATE OR DELETE ON public.academic_result_versions
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation();

CREATE FUNCTION public.smartpro_academic_base_scores(assessment uuid) RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
  SELECT coalesce(jsonb_agg(x.score ORDER BY x.score::text),'[]'::jsonb) FROM (
    SELECT jsonb_build_object('criterionId',s.mode_criterion_id,'studentId',NULL,'marks',s.marks::text) AS score
      FROM public.team_criterion_scores s WHERE s.assessment_id=assessment
    UNION ALL
    SELECT jsonb_build_object('criterionId',s.mode_criterion_id,'studentId',r.student_user_id,'marks',s.marks::text)
      FROM public.student_criterion_scores s JOIN public.review_roster_members r ON r.id=s.roster_member_id WHERE s.assessment_id=assessment
  ) x
$$;

CREATE FUNCTION public.smartpro_academic_sources(review uuid,roster uuid) RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE a record; v public.academic_evaluation_versions%ROWTYPE; result jsonb:='[]'; scores jsonb; ordinal integer;
BEGIN
  SELECT version_no INTO ordinal FROM public.academic_roster_versions WHERE id=roster;
  FOR a IN SELECT x.id,e.faculty_user_id FROM public.assessments x JOIN public.evaluator_assignments e ON e.id=x.evaluator_assignment_id
    WHERE x.review_id=review AND x.state='FINALIZED' ORDER BY x.id FOR SHARE OF x,e
  LOOP
    SELECT x.* INTO v FROM public.academic_evaluation_versions x WHERE x.assessment_id=a.id ORDER BY x.version_no DESC LIMIT 1;
    IF FOUND THEN
      IF v.roster_version_id<>roster THEN RETURN NULL; END IF;
      scores:=v.scores;
    ELSIF ordinal=1 THEN scores:=public.smartpro_academic_base_scores(a.id);
    ELSE RETURN NULL;
    END IF;
    result:=result||jsonb_build_array(jsonb_build_object('assessmentId',a.id,'evaluatorId',a.faculty_user_id,'evaluationVersionId',v.id,'scores',scores));
  END LOOP;
  RETURN result;
END $$;

CREATE FUNCTION public.smartpro_academic_publish(actor uuid,review uuid,roster uuid,reason text)
RETURNS uuid LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE policy public.academic_evaluation_policies%ROWTYPE; sources jsonb; previous public.academic_result_versions%ROWTYPE;
        member record; source jsonb; total numeric; weights numeric; weighted numeric; marks numeric; low numeric; high numeric;
        result jsonb:='{}'; weight numeric; rid uuid;
BEGIN
  SELECT p.* INTO policy FROM public.academic_review_bindings b JOIN public.academic_evaluation_policies p ON p.id=b.policy_id WHERE b.review_id=review;
  sources:=public.smartpro_academic_sources(review,roster);
  IF sources IS NULL OR jsonb_array_length(sources)<policy.evaluator_quorum THEN RETURN NULL; END IF;
  IF policy.aggregation='WEIGHTED_MEAN' AND
      (SELECT coalesce(jsonb_object_agg(s->>'evaluatorId',true),'{}') FROM jsonb_array_elements(sources) s)
      IS DISTINCT FROM (SELECT coalesce(jsonb_object_agg(key,true),'{}') FROM jsonb_each(policy.evaluator_weights)) THEN
    RAISE EXCEPTION 'weights must cover exactly the finalized evaluators' USING ERRCODE='23514'; END IF;
  FOR member IN SELECT student_user_id FROM public.academic_roster_members WHERE roster_version_id=roster ORDER BY student_user_id LOOP
    weights:=0; weighted:=0; low:=NULL; high:=NULL;
    FOR source IN SELECT value FROM jsonb_array_elements(sources) LOOP
      SELECT coalesce(sum((s->>'marks')::numeric),0) INTO total FROM jsonb_array_elements(source->'scores') s
        WHERE s->>'studentId' IS NULL OR s->>'studentId'=member.student_user_id::text;
      weight:=CASE WHEN policy.aggregation='WEIGHTED_MEAN' THEN (policy.evaluator_weights->>(source->>'evaluatorId'))::numeric ELSE 1 END;
      weights:=weights+weight; weighted:=weighted+total*weight; low:=least(low,total); high:=greatest(high,total);
    END LOOP;
    marks:=CASE policy.aggregation WHEN 'MIN' THEN low WHEN 'MAX' THEN high ELSE weighted/weights END;
    result:=result||jsonb_build_object(member.student_user_id::text,round(marks,2)::text);
  END LOOP;
  SELECT x.* INTO previous FROM public.academic_result_versions x WHERE x.review_id=review ORDER BY x.version_no DESC LIMIT 1;
  INSERT INTO public.academic_result_versions(review_id,version_no,supersedes_id,legacy_release_id,roster_version_id,policy_id,actor_id,reason,sources,results)
    VALUES(review,coalesce(previous.version_no,0)+1,previous.id,
      (SELECT id FROM public.result_releases WHERE review_id=review ORDER BY release_no DESC LIMIT 1),roster,policy.id,actor,reason,sources,result) RETURNING id INTO rid;
  INSERT INTO public.audit_events(actor_id,action,target_type,target_id,metadata)
    VALUES(actor,'ACADEMIC_RESULT_VERSION_PUBLISHED','ACADEMIC_RESULT',rid,
      jsonb_build_object('reviewId',review,'policyId',policy.id,'previousResultId',previous.id,'old',previous.results,'new',result,'reason',reason));
  RETURN rid;
END $$;

CREATE FUNCTION public.smartpro_academic_review_command(actor uuid,dept uuid,action_name text,input jsonb,request_key text)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE review public.project_reviews%ROWTYPE; binding public.academic_review_bindings%ROWTYPE; auth jsonb;
        prior public.academic_command_receipts%ROWTYPE; roster uuid; old_roster uuid; result_id uuid; evaluation uuid;
        version integer; assessment public.assessments%ROWTYPE; faculty_role uuid; element jsonb; criterion record;
        member record; count_expected integer; old_scores jsonb; result jsonb; stamp timestamptz; eligibility_role uuid;
BEGIN
  IF request_key IS NULL OR request_key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' OR jsonb_typeof(input) IS DISTINCT FROM 'object'
    OR coalesce(input->>'expectedReviewRevision','') !~ '^[0-9]+$' OR length(coalesce(input->>'reason',''))>500
    OR (action_name<>'EVALUATE' AND btrim(coalesce(input->>'reason',''))='') THEN
    RAISE EXCEPTION 'invalid academic review command' USING ERRCODE='22023'; END IF;
  PERFORM 1 FROM public.academic_governance_settings WHERE department_id=dept AND enabled FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'academic governance disabled' USING ERRCODE='42501'; END IF;
  SELECT r.* INTO review FROM public.project_reviews r JOIN public.projects p ON p.id=r.project_id
    WHERE r.id=(input->>'reviewId')::uuid AND p.department_id=dept FOR UPDATE OF r;
  IF NOT FOUND OR review.roster_locked_at IS NULL OR review.review_state='CANCELLED' THEN
    RAISE EXCEPTION 'scoped frozen review required' USING ERRCODE='42501'; END IF;
  IF action_name='EVALUATE' THEN
    SELECT a.* INTO assessment FROM public.assessments a JOIN public.evaluator_assignments e ON e.id=a.evaluator_assignment_id
      WHERE a.id=(input->>'assessmentId')::uuid AND a.review_id=review.id AND a.state='FINALIZED' AND e.faculty_user_id=actor FOR UPDATE OF a;
    IF NOT FOUND THEN RAISE EXCEPTION 'original evaluator of finalized assessment required' USING ERRCODE='42501'; END IF;
    SELECT r.id INTO faculty_role FROM public.department_role_assignments r JOIN public.users u ON u.id=r.user_id
      WHERE r.user_id=actor AND r.department_id=dept AND r.role_code='FACULTY' AND u.account_status='ACTIVE'
        AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)
      ORDER BY r.id LIMIT 1 FOR UPDATE OF r FOR SHARE OF u;
    IF NOT FOUND THEN RAISE EXCEPTION 'active original faculty evaluator required' USING ERRCODE='42501'; END IF;
    auth:=jsonb_build_object('originalEvaluatorId',actor,'facultyRoleId',faculty_role);
  ELSE
    auth:=public.smartpro_academic_authority(actor,dept);
    IF action_name='ROSTER' AND auth->>'coordinatorMandateId' IS NULL THEN
      RAISE EXCEPTION 'appointed coordinator required for retrospective correction' USING ERRCODE='42501'; END IF;
  END IF;
  SELECT r.* INTO prior FROM public.academic_command_receipts r WHERE r.actor_id=actor AND r.request_key=smartpro_academic_review_command.request_key;
  IF FOUND THEN
    IF (prior.department_id,prior.action,prior.input) IS DISTINCT FROM (dept,action_name,input) THEN
      RAISE EXCEPTION 'idempotency conflict' USING ERRCODE='23505'; END IF;
    RETURN prior.output;
  END IF;
  SELECT b.* INTO binding FROM public.academic_review_bindings b WHERE b.review_id=review.id FOR UPDATE;
  IF coalesce(binding.revision,0)<>(input->>'expectedReviewRevision')::bigint THEN
    RAISE EXCEPTION 'stale review revision' USING ERRCODE='23514'; END IF;
  IF action_name='BIND' THEN
    IF binding.review_id IS NOT NULL THEN RAISE EXCEPTION 'review policy is already pinned' USING ERRCODE='23514'; END IF;
    IF EXISTS(SELECT FROM public.review_roster_members r WHERE r.review_id=review.id AND NOT EXISTS(
      SELECT FROM public.department_role_assignments x WHERE x.user_id=r.student_user_id AND x.department_id=dept AND x.role_code='STUDENT'
        AND x.valid_from<=r.created_at AND (x.valid_until IS NULL OR r.created_at<x.valid_until))) THEN
      RAISE EXCEPTION 'verify original historical student role before policy adoption' USING ERRCODE='23514'; END IF;
    INSERT INTO public.academic_review_bindings(review_id,department_id,policy_id) VALUES(review.id,dept,(input->>'policyId')::uuid) RETURNING * INTO binding;
    INSERT INTO public.academic_roster_versions(review_id,version_no,actor_id,reason) VALUES(review.id,1,actor,input->>'reason') RETURNING id INTO roster;
    INSERT INTO public.academic_roster_members(roster_version_id,student_user_id,membership_id,eligibility_role_id,team_id,eligibility_at)
      SELECT roster,r.student_user_id,r.membership_id,
        (SELECT x.id FROM public.department_role_assignments x WHERE x.user_id=r.student_user_id AND x.department_id=dept AND x.role_code='STUDENT'
          AND x.valid_from<=r.created_at AND (x.valid_until IS NULL OR r.created_at<x.valid_until) ORDER BY x.id LIMIT 1),
        r.team_id,r.created_at FROM public.review_roster_members r WHERE r.review_id=review.id;
    IF NOT FOUND THEN RAISE EXCEPTION 'nonempty original roster required' USING ERRCODE='23514'; END IF;
  ELSE
    IF binding.review_id IS NULL THEN RAISE EXCEPTION 'explicit review policy required' USING ERRCODE='42501'; END IF;
    SELECT r.id,r.version_no INTO roster,version FROM public.academic_roster_versions r WHERE r.review_id=review.id ORDER BY r.version_no DESC LIMIT 1;
    old_roster:=roster;
    IF action_name='ROSTER' THEN
      IF jsonb_typeof(input->'membershipIds') IS DISTINCT FROM 'array' OR jsonb_array_length(input->'membershipIds')=0
        OR (SELECT count(DISTINCT value) FROM jsonb_array_elements_text(input->'membershipIds'))<>jsonb_array_length(input->'membershipIds') THEN
        RAISE EXCEPTION 'distinct nonempty membership IDs required' USING ERRCODE='22023'; END IF;
      INSERT INTO public.academic_roster_versions(review_id,version_no,supersedes_id,actor_id,reason)
        VALUES(review.id,version+1,roster,actor,input->>'reason') RETURNING id INTO roster;
      FOR member IN SELECT id,team_id,user_id,joined_at,left_at FROM public.team_memberships
        WHERE id IN (SELECT value::uuid FROM jsonb_array_elements_text(input->'membershipIds')) ORDER BY id FOR UPDATE
      LOOP
        IF member.team_id<>(SELECT team_id FROM public.projects WHERE id=review.project_id)
          OR member.joined_at>review.roster_locked_at OR (member.left_at IS NOT NULL AND member.left_at<=review.roster_locked_at) THEN
          RAISE EXCEPTION 'membership does not prove retrospective eligibility' USING ERRCODE='23514'; END IF;
        SELECT x.id INTO eligibility_role FROM public.department_role_assignments x
          WHERE x.user_id=member.user_id AND x.department_id=dept AND x.role_code='STUDENT'
            AND x.valid_from<=review.roster_locked_at AND (x.valid_until IS NULL OR review.roster_locked_at<x.valid_until)
          ORDER BY x.id LIMIT 1 FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'historical student role required' USING ERRCODE='23514'; END IF;
        INSERT INTO public.academic_roster_members VALUES(roster,member.user_id,member.id,eligibility_role,member.team_id,review.roster_locked_at);
        UPDATE public.team_memberships SET academic_evidence_revision=gen_random_uuid() WHERE id=member.id;
      END LOOP;
      IF (SELECT count(*) FROM public.academic_roster_members WHERE roster_version_id=roster)<>jsonb_array_length(input->'membershipIds') THEN
        RAISE EXCEPTION 'unknown or duplicate student membership' USING ERRCODE='23514'; END IF;
    ELSIF action_name='EVALUATE' THEN
      IF jsonb_typeof(input->'scores') IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'criterion scores required' USING ERRCODE='22023'; END IF;
      SELECT coalesce(sum(CASE WHEN mc.score_scope='TEAM' THEN 1 ELSE (SELECT count(*) FROM public.academic_roster_members WHERE roster_version_id=roster) END),0)
        INTO count_expected FROM public.mode_criteria mc WHERE mc.scheme_mode_id=assessment.scheme_mode_id;
      IF jsonb_array_length(input->'scores')<>count_expected OR count_expected=0 THEN
        RAISE EXCEPTION 'complete rubric and roster scores required' USING ERRCODE='23514'; END IF;
      IF (SELECT count(DISTINCT (x->>'criterionId',x->>'studentId')) FROM jsonb_array_elements(input->'scores') x)<>count_expected THEN
        RAISE EXCEPTION 'duplicate criterion scores' USING ERRCODE='23514'; END IF;
      FOR element IN SELECT value FROM jsonb_array_elements(input->'scores') LOOP
        IF jsonb_typeof(element) IS DISTINCT FROM 'object' OR element-ARRAY['criterionId','studentId','marks']<>'{}' OR NOT element ?& ARRAY['criterionId','studentId','marks']
          OR coalesce(element->>'marks','') !~ '^[0-9]+(\.[0-9]{1,2})?$' THEN
          RAISE EXCEPTION 'exact criterion, student and decimal marks required' USING ERRCODE='22023'; END IF;
        SELECT mc.score_scope,rc.maximum INTO criterion FROM public.mode_criteria mc JOIN public.rubric_criteria rc ON rc.id=mc.criterion_id
          WHERE mc.id=(element->>'criterionId')::uuid AND mc.scheme_mode_id=assessment.scheme_mode_id;
        IF NOT FOUND OR (element->>'marks')::numeric>criterion.maximum
          OR (criterion.score_scope='TEAM' AND element->>'studentId' IS NOT NULL)
          OR (criterion.score_scope='STUDENT' AND NOT EXISTS(SELECT FROM public.academic_roster_members r WHERE r.roster_version_id=roster AND r.student_user_id::text=element->>'studentId')) THEN
          RAISE EXCEPTION 'score outside rubric or roster' USING ERRCODE='23514'; END IF;
      END LOOP;
      SELECT v.scores INTO old_scores FROM public.academic_evaluation_versions v WHERE v.assessment_id=assessment.id ORDER BY version_no DESC LIMIT 1;
      old_scores:=coalesce(old_scores,public.smartpro_academic_base_scores(assessment.id));
      INSERT INTO public.academic_evaluation_versions(assessment_id,roster_version_id,version_no,actor_id,scores,reason)
        SELECT assessment.id,roster,coalesce(max(version_no),0)+1,actor,input->'scores',coalesce(input->>'reason','')
          FROM public.academic_evaluation_versions WHERE assessment_id=assessment.id RETURNING id INTO evaluation;
      IF EXISTS(SELECT FROM public.academic_result_versions WHERE review_id=review.id)
        OR EXISTS(SELECT FROM public.result_releases WHERE review_id=review.id) THEN
        result_id:=public.smartpro_academic_publish(actor,review.id,roster,coalesce(input->>'reason',''));
      END IF;
    ELSIF action_name='PUBLISH' THEN
      result_id:=public.smartpro_academic_publish(actor,review.id,roster,input->>'reason');
      IF result_id IS NULL THEN RAISE EXCEPTION 'quorum or current-roster evaluations incomplete' USING ERRCODE='23514'; END IF;
    ELSE RAISE EXCEPTION 'unsupported review command' USING ERRCODE='22023';
    END IF;
  END IF;
  -- Serialize historical eligibility corrections even against older owner snapshots.
  UPDATE public.team_memberships m SET academic_evidence_revision=gen_random_uuid()
    WHERE m.id IN (SELECT membership_id FROM public.academic_roster_members WHERE roster_version_id=roster);
  UPDATE public.department_role_assignments r SET staff_authority_revision=gen_random_uuid()
    WHERE r.id IN (SELECT eligibility_role_id FROM public.academic_roster_members WHERE roster_version_id=roster);
  IF EXISTS(SELECT FROM public.academic_roster_members m JOIN public.department_role_assignments r ON r.id=m.eligibility_role_id
    WHERE m.roster_version_id=roster AND (r.valid_from>m.eligibility_at OR (r.valid_until IS NOT NULL AND r.valid_until<=m.eligibility_at))) THEN
    RAISE EXCEPTION 'historical role evidence changed' USING ERRCODE='23514'; END IF;
  stamp:=clock_timestamp();
  IF faculty_role IS NOT NULL THEN
    UPDATE public.department_role_assignments SET staff_authority_revision=gen_random_uuid() WHERE id=faculty_role;
    IF NOT EXISTS(SELECT FROM public.department_role_assignments r WHERE r.id=faculty_role AND r.valid_from<=stamp AND (r.valid_until IS NULL OR stamp<r.valid_until)) THEN
      RAISE EXCEPTION 'faculty authority expired' USING ERRCODE='42501'; END IF;
    auth:=auth||jsonb_build_object('authorizedAt',stamp);
  ELSE
    UPDATE public.department_role_assignments SET staff_authority_revision=gen_random_uuid() WHERE id IN ((auth->>'hodRoleId')::uuid,(auth->>'coordinatorRoleId')::uuid);
    auth:=public.smartpro_academic_authority(actor,dept);
  END IF;
  UPDATE public.academic_review_bindings SET revision=revision+1 WHERE review_id=review.id RETURNING revision INTO binding.revision;
  result:=jsonb_build_object('reviewId',review.id,'revision',binding.revision,'rosterVersionId',roster,'evaluationVersionId',evaluation,'resultVersionId',result_id);
  INSERT INTO public.audit_events(actor_id,project_id,action,target_type,target_id,metadata)
    VALUES(actor,review.project_id,'ACADEMIC_'||action_name,'PROJECT_REVIEW',review.id,
      jsonb_build_object('departmentId',dept,'authority',auth,'oldRosterVersionId',old_roster,'newRosterVersionId',roster,'oldScores',old_scores,
        'new',input,'resultVersionId',result_id,'reason',coalesce(input->>'reason',''),'correctionKind',CASE WHEN action_name='EVALUATE' THEN 'ORIGINAL_EVALUATOR_DIRECT' ELSE action_name END));
  INSERT INTO public.academic_command_receipts(actor_id,request_key,department_id,action,target_id,input,output,authority,occurred_at)
    VALUES(actor,request_key,dept,action_name,review.id,input,result,auth,(auth->>'authorizedAt')::timestamptz);
  RETURN result;
END $$;

REVOKE ALL ON TABLE public.academic_review_bindings,public.academic_roster_versions,public.academic_roster_members,
  public.academic_evaluation_versions,public.academic_result_versions FROM PUBLIC,smartpro_runtime;
REVOKE ALL ON FUNCTION public.smartpro_academic_membership_history(),public.smartpro_academic_binding_identity(),
  public.smartpro_academic_evaluator_role_history(),
  public.smartpro_academic_base_scores(uuid),public.smartpro_academic_sources(uuid,uuid),public.smartpro_academic_publish(uuid,uuid,uuid,text),
  public.smartpro_academic_review_command(uuid,uuid,text,jsonb,text) FROM PUBLIC,smartpro_runtime;
GRANT EXECUTE ON FUNCTION public.smartpro_academic_review_command(uuid,uuid,text,jsonb,text) TO smartpro_runtime;
CREATE FUNCTION public.smartpro_academic_results(actor uuid,dept uuid,review uuid,after_version integer DEFAULT 0)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE privileged boolean:=false; evaluator boolean; page jsonb; context jsonb; roster uuid;
BEGIN
  IF after_version IS NULL OR after_version<0 THEN RAISE EXCEPTION 'invalid result cursor' USING ERRCODE='22023'; END IF;
  PERFORM 1 FROM public.academic_governance_settings WHERE department_id=dept AND enabled FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'academic governance disabled' USING ERRCODE='42501'; END IF;
  PERFORM 1 FROM public.users WHERE id=actor AND account_status='ACTIVE' FOR SHARE;
  IF NOT FOUND OR NOT EXISTS(SELECT FROM public.project_reviews r JOIN public.projects p ON p.id=r.project_id WHERE r.id=review AND p.department_id=dept) THEN
    RAISE EXCEPTION 'scoped active principal required' USING ERRCODE='42501'; END IF;
  BEGIN PERFORM public.smartpro_academic_authority(actor,dept); privileged:=true;
  EXCEPTION WHEN insufficient_privilege THEN privileged:=false;
  END;
  SELECT EXISTS(SELECT FROM public.evaluator_assignments e JOIN public.department_role_assignments r ON r.user_id=e.faculty_user_id
    WHERE e.review_id=review AND e.faculty_user_id=actor AND r.department_id=dept AND r.role_code='FACULTY'
      AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)) INTO evaluator;
  IF NOT privileged AND NOT evaluator AND NOT (
    EXISTS(SELECT FROM public.department_role_assignments r WHERE r.user_id=actor AND r.department_id=dept AND r.role_code='STUDENT'
      AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until))
    AND (EXISTS(SELECT FROM public.review_roster_members WHERE review_id=review AND student_user_id=actor)
      OR EXISTS(SELECT FROM public.academic_roster_members m JOIN public.academic_roster_versions v ON v.id=m.roster_version_id WHERE v.review_id=review AND m.student_user_id=actor))) THEN
    RAISE EXCEPTION 'review result access denied' USING ERRCODE='42501'; END IF;
  SELECT coalesce(jsonb_agg(x.item ORDER BY x.version_no),'[]'::jsonb) INTO page FROM (
    SELECT v.version_no,jsonb_build_object('id',v.id,'version',v.version_no,'supersedesId',v.supersedes_id,
      'legacyReleaseId',v.legacy_release_id,'rosterVersionId',v.roster_version_id,'policyId',v.policy_id,'actorId',v.actor_id,'createdAt',v.created_at,
      'calculationVersion',v.calculation_version,
      'results',CASE WHEN privileged OR evaluator THEN v.results ELSE jsonb_build_object(actor::text,v.results->actor::text) END,
      'sources',CASE WHEN privileged THEN v.sources WHEN evaluator THEN (SELECT coalesce(jsonb_agg(s),'[]') FROM jsonb_array_elements(v.sources) s WHERE s->>'evaluatorId'=actor::text) ELSE '[]'::jsonb END) AS item
    FROM public.academic_result_versions v WHERE v.review_id=review AND v.version_no>after_version
      AND (privileged OR evaluator OR v.results ? actor::text) ORDER BY v.version_no LIMIT 50
  ) x;
  IF privileged OR evaluator THEN
    SELECT id INTO roster FROM public.academic_roster_versions WHERE review_id=review ORDER BY version_no DESC LIMIT 1;
    SELECT jsonb_build_object('revision',b.revision,'policyId',b.policy_id,'rosterVersionId',roster,
      'studentIds',(SELECT coalesce(jsonb_agg(student_user_id ORDER BY student_user_id),'[]') FROM public.academic_roster_members WHERE roster_version_id=roster),
      'criteria',(SELECT coalesce(jsonb_agg(jsonb_build_object('criterionId',mc.id,'scope',mc.score_scope,'maximum',rc.maximum::text) ORDER BY mc.id),'[]')
        FROM public.project_reviews r JOIN public.mode_criteria mc ON mc.scheme_mode_id=r.scheme_mode_id JOIN public.rubric_criteria rc ON rc.id=mc.criterion_id WHERE r.id=review))
      INTO context FROM public.academic_review_bindings b WHERE b.review_id=review;
  END IF;
  RETURN jsonb_build_object('reviewId',review,'context',context,'results',page,
    'nextAfterVersion',CASE WHEN jsonb_array_length(page)=50 THEN (page->49->>'version')::integer END);
END $$;
REVOKE ALL ON FUNCTION public.smartpro_academic_results(uuid,uuid,uuid,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_academic_results(uuid,uuid,uuid,integer) TO smartpro_runtime;
CREATE FUNCTION public.smartpro_academic_policy_state(actor uuid,dept uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE revision bigint;
BEGIN
  SELECT s.revision INTO revision FROM public.academic_governance_settings s WHERE s.department_id=dept AND s.enabled FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'academic governance disabled' USING ERRCODE='42501'; END IF;
  PERFORM public.smartpro_academic_authority(actor,dept);
  RETURN jsonb_build_object('departmentId',dept,'revision',revision,
    'policies',(SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY version_no DESC),'[]') FROM
      (SELECT * FROM public.academic_evaluation_policies WHERE department_id=dept ORDER BY version_no DESC LIMIT 50) p),
    'appointments',(SELECT coalesce(jsonb_agg(to_jsonb(c)),'[]') FROM
      (SELECT * FROM public.academic_coordinator_mandates WHERE department_id=dept ORDER BY id LIMIT 50) c));
END $$;
REVOKE ALL ON FUNCTION public.smartpro_academic_policy_state(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_academic_policy_state(uuid,uuid) TO smartpro_runtime;
COMMIT;
