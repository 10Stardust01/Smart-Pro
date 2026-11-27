-- 066: PRC synopsis entry-gate foundation. Install only after separate acceptance.
-- Historical projects, existing Guide assignments, results and documents are not changed.
BEGIN;
DO $$ BEGIN
 IF to_regprocedure('public.smartpro_document_command(uuid,uuid,text,jsonb,text)') IS NULL
    OR to_regprocedure('public.smartpro_project_operation(uuid,uuid,text,jsonb,text)') IS NULL
    OR to_regprocedure('public.smartpro_course_authority(uuid,uuid,text,text)') IS NULL
 THEN RAISE EXCEPTION 'Install the reviewed SMART-PRO academic lifecycle first'; END IF;
END $$;

CREATE TABLE public.prc_offering_gates(
 offering_id uuid PRIMARY KEY REFERENCES public.curriculum_offerings(id),
 activated_by uuid NOT NULL REFERENCES public.users(id),
 activated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE public.prc_project_members(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 project_id uuid NOT NULL REFERENCES public.projects(id),
 faculty_user_id uuid NOT NULL REFERENCES public.users(id),
 reviewer_assignment_id uuid NOT NULL UNIQUE,
 appointed_by uuid NOT NULL REFERENCES public.users(id),
 appointed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 ended_at timestamptz,
 FOREIGN KEY(reviewer_assignment_id,project_id,faculty_user_id)
   REFERENCES public.faculty_assignments(id,project_id,faculty_user_id),
 CHECK(ended_at IS NULL OR ended_at>=appointed_at)
);
CREATE UNIQUE INDEX prc_one_active_member ON public.prc_project_members(project_id,faculty_user_id)
 WHERE ended_at IS NULL;
CREATE INDEX prc_member_faculty_lookup ON public.prc_project_members(faculty_user_id,project_id)
 WHERE ended_at IS NULL;
CREATE TABLE public.prc_synopsis_decisions(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 project_id uuid NOT NULL REFERENCES public.projects(id),
 attempt_id uuid NOT NULL UNIQUE,
 faculty_user_id uuid NOT NULL REFERENCES public.users(id),
 decision text NOT NULL CHECK(decision IN ('APPROVE','REQUEST_MODIFICATION','REJECT')),
 comment text NOT NULL CHECK(length(btrim(comment)) BETWEEN 1 AND 4000),
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(attempt_id,project_id) REFERENCES public.submission_attempts(id,project_id)
);
CREATE INDEX prc_decision_project_history ON public.prc_synopsis_decisions(project_id,recorded_at);
REVOKE ALL ON public.prc_offering_gates,public.prc_project_members,public.prc_synopsis_decisions
 FROM PUBLIC,smartpro_runtime;
CREATE TRIGGER prc_preserve_activation BEFORE UPDATE OR DELETE ON public.prc_offering_gates
 FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation();
CREATE TRIGGER prc_preserve_decision BEFORE UPDATE OR DELETE ON public.prc_synopsis_decisions
 FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation();

-- Existing historical Guides remain valid; projects without a prior Guide in a
-- PRC-enabled offering cannot receive their first Guide without PRC approval.
CREATE FUNCTION public.smartpro_prc_required(pid uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $f$
 SELECT EXISTS(
  SELECT FROM public.projects p JOIN public.teams t ON t.id=p.team_id
   JOIN public.prc_offering_gates g ON g.offering_id=t.curriculum_offering_id
  WHERE p.id=pid
    AND NOT EXISTS(SELECT FROM public.faculty_assignments f
       WHERE f.project_id=p.id AND f.assignment_type='GUIDE'
         AND f.valid_from<g.activated_at)
 );
$f$;
CREATE FUNCTION public.smartpro_prc_approved(pid uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $f$
 SELECT coalesce((
  SELECT d.decision='APPROVE' AND a.attempt_state='APPROVED' AND c.state='APPROVED'
   FROM public.submission_cases c JOIN public.submission_attempts a ON a.case_id=c.id
   LEFT JOIN public.prc_synopsis_decisions d ON d.attempt_id=a.id
   WHERE c.project_id=pid AND c.requirement_key='SYNOPSIS'
   ORDER BY a.attempt_no DESC LIMIT 1
 ),false);
$f$;
CREATE FUNCTION public.smartpro_prc_guide_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $f$
BEGIN
 IF NEW.assignment_type='GUIDE' AND public.smartpro_prc_required(NEW.project_id)
    AND NOT public.smartpro_prc_approved(NEW.project_id)
 THEN RAISE EXCEPTION 'PRC synopsis approval required before first Guide allocation'
    USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $f$;
CREATE TRIGGER require_prc_before_first_guide BEFORE INSERT ON public.faculty_assignments
 FOR EACH ROW EXECUTE FUNCTION public.smartpro_prc_guide_guard();

-- A generic Faculty document decision must not impersonate an official PRC
-- decision for an offering whose entry gate was explicitly activated.
CREATE FUNCTION public.smartpro_prc_document_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $f$
DECLARE is_synopsis boolean;
BEGIN
 SELECT c.requirement_key='SYNOPSIS' INTO is_synopsis
 FROM public.submission_attempts a JOIN public.submission_cases c ON c.id=a.case_id
 WHERE a.id=NEW.attempt_id AND c.project_id=NEW.project_id;
 IF coalesce(is_synopsis,false) AND public.smartpro_prc_required(NEW.project_id) THEN
  IF current_setting('smartpro.prc_authorized_decision',true) IS DISTINCT FROM 'yes'
     OR NOT EXISTS(
       SELECT FROM public.prc_project_members m JOIN public.faculty_assignments f
       ON f.id=m.reviewer_assignment_id
       WHERE m.project_id=NEW.project_id AND m.faculty_user_id=NEW.reviewer_user_id
         AND m.ended_at IS NULL AND f.valid_from<=clock_timestamp()
         AND (f.valid_until IS NULL OR clock_timestamp()<f.valid_until))
  THEN RAISE EXCEPTION 'Use the authorized PRC synopsis decision workflow'
       USING ERRCODE='42501'; END IF;
 END IF;
 RETURN NEW;
END $f$;
CREATE TRIGGER require_prc_document_decision BEFORE INSERT ON public.approval_decisions
 FOR EACH ROW EXECUTE FUNCTION public.smartpro_prc_document_guard();

-- Coordinator is responsible for assigning PRC members. Individual assigned
-- PRC Faculty may record a committee outcome; no voting/quorum rule is invented.
CREATE FUNCTION public.smartpro_prc_command(
 actor uuid, oid uuid, action text, input jsonb, request_key text
) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $f$
DECLARE pid uuid; dept uuid; reviewer uuid; member public.prc_project_members%ROWTYPE;
        attempt public.submission_attempts%ROWTYPE; c public.submission_cases%ROWTYPE;
        result jsonb; previous_context text; decision text; stamp timestamptz;
BEGIN
 IF request_key IS NULL OR request_key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
 THEN RAISE EXCEPTION 'Valid idempotency key required' USING ERRCODE='22023'; END IF;
 IF jsonb_typeof(input) IS DISTINCT FROM 'object'
 THEN RAISE EXCEPTION 'PRC command object required' USING ERRCODE='22023'; END IF;
 SELECT department_id INTO dept FROM public.curriculum_offerings WHERE id=oid;
 IF NOT FOUND THEN RAISE EXCEPTION 'Scoped course offering required' USING ERRCODE='42501'; END IF;

 IF action IN ('ACTIVATE','ASSIGN','END_MEMBER') THEN
  PERFORM public.smartpro_course_authority(actor,oid,'EVALUATORS','Coordinator');
 ELSIF action='DECIDE' THEN
  IF NOT public.smartpro_role_choices(actor) ? 'Faculty'
     OR NOT public.smartpro_has_role(actor,dept,'FACULTY',clock_timestamp())
  THEN RAISE EXCEPTION 'Current assigned PRC Faculty required' USING ERRCODE='42501'; END IF;
 ELSE RAISE EXCEPTION 'Unsupported PRC operation' USING ERRCODE='22023'; END IF;

 IF action='ACTIVATE' THEN
  -- Make the PRC gate active only after an approved synopsis requirement can
  -- handle approval, modifications and resubmissions. Never rewrite policy.
  PERFORM 1 FROM public.submission_offering_requirements h
  JOIN public.submission_requirement_policies q ON q.id=h.policy_id
  WHERE h.offering_id=oid AND h.requirement_key='SYNOPSIS'
   AND q.faculty_approval_enabled AND q.changes_enabled AND q.revisions_enabled;
  IF NOT FOUND THEN RAISE EXCEPTION
   'Configure an approved synopsis requirement with approval, changes and revisions first'
   USING ERRCODE='23514'; END IF;
  INSERT INTO public.prc_offering_gates(offering_id,activated_by)
   VALUES(oid,actor) ON CONFLICT DO NOTHING;
  INSERT INTO public.audit_events(actor_id,action,target_type,target_id,metadata)
   VALUES(actor,'PRC_GATE_ACTIVATED','CURRICULUM_OFFERING',oid,
     jsonb_build_object('offeringId',oid,'source','explicit coordinator activation'));
  result:=jsonb_build_object('status','PRC_ENABLED','offeringId',oid);

 ELSIF action='ASSIGN' THEN
  pid:=(input->>'projectId')::uuid;
  PERFORM 1 FROM public.projects p JOIN public.teams t ON t.id=p.team_id
   WHERE p.id=pid AND t.curriculum_offering_id=oid FOR UPDATE OF p;
  IF NOT FOUND OR NOT EXISTS(SELECT FROM public.prc_offering_gates WHERE offering_id=oid)
  THEN RAISE EXCEPTION 'Enable PRC for this offering and select one of its projects'
    USING ERRCODE='23514'; END IF;
  IF NOT public.smartpro_has_role((input->>'facultyId')::uuid,dept,'FACULTY',clock_timestamp())
  THEN RAISE EXCEPTION 'Current departmental Faculty required' USING ERRCODE='42501'; END IF;
  SELECT * INTO member FROM public.prc_project_members WHERE project_id=pid
   AND faculty_user_id=(input->>'facultyId')::uuid AND ended_at IS NULL;
  IF member.id IS NULL THEN
   INSERT INTO public.faculty_assignments(project_id,faculty_user_id,assignment_type,requirement_key)
    VALUES(pid,(input->>'facultyId')::uuid,'REVIEWER','SYNOPSIS') RETURNING id INTO reviewer;
   INSERT INTO public.prc_project_members(project_id,faculty_user_id,reviewer_assignment_id,appointed_by)
    VALUES(pid,(input->>'facultyId')::uuid,reviewer,actor) RETURNING * INTO member;
   INSERT INTO public.audit_events(actor_id,project_id,action,target_type,target_id,metadata)
    VALUES(actor,pid,'PRC_MEMBER_ASSIGNED','PRC_MEMBER',member.id,
           jsonb_build_object('facultyId',member.faculty_user_id,'offeringId',oid));
  END IF;
  result:=jsonb_build_object('status','ASSIGNED','memberId',member.id,'projectId',pid);

 ELSIF action='END_MEMBER' THEN
  SELECT p.id INTO pid FROM public.prc_project_members m
   JOIN public.projects p ON p.id=m.project_id JOIN public.teams t ON t.id=p.team_id
   WHERE m.id=(input->>'memberId')::uuid AND t.curriculum_offering_id=oid;
  IF pid IS NULL THEN RAISE EXCEPTION 'Scoped PRC member required' USING ERRCODE='23514'; END IF;
  PERFORM 1 FROM public.projects WHERE id=pid FOR UPDATE;
  SELECT * INTO member FROM public.prc_project_members
   WHERE id=(input->>'memberId')::uuid FOR UPDATE;
  IF member.id IS NULL OR member.ended_at IS NOT NULL
  THEN RAISE EXCEPTION 'Active scoped PRC assignment required' USING ERRCODE='23514'; END IF;
  stamp:=clock_timestamp();
  UPDATE public.prc_project_members SET ended_at=stamp WHERE id=member.id;
  UPDATE public.faculty_assignments SET valid_until=stamp
   WHERE id=member.reviewer_assignment_id AND (valid_until IS NULL OR valid_until>stamp);
  INSERT INTO public.audit_events(actor_id,project_id,action,target_type,target_id,metadata)
   VALUES(actor,pid,'PRC_MEMBER_ENDED','PRC_MEMBER',member.id,
     jsonb_build_object('facultyId',member.faculty_user_id,'reason',coalesce(input->>'reason','')));
  result:=jsonb_build_object('status','ENDED','memberId',member.id);

 ELSE
  pid:=(input->>'projectId')::uuid;
  decision:=input->>'decision';
  IF decision NOT IN ('APPROVE','REQUEST_MODIFICATION','REJECT')
     OR length(btrim(coalesce(input->>'comment',''))) NOT BETWEEN 1 AND 4000
  THEN RAISE EXCEPTION 'Choose a PRC decision and supply its comments' USING ERRCODE='22023'; END IF;
  PERFORM 1 FROM public.projects p JOIN public.teams t ON t.id=p.team_id
   WHERE p.id=pid AND t.curriculum_offering_id=oid FOR UPDATE OF p;
  IF NOT FOUND OR NOT public.smartpro_prc_required(pid)
  THEN RAISE EXCEPTION 'An enabled, unguided PRC project is required' USING ERRCODE='23514'; END IF;
  SELECT * INTO member FROM public.prc_project_members
   WHERE project_id=pid AND faculty_user_id=actor AND ended_at IS NULL
   ORDER BY appointed_at DESC LIMIT 1 FOR UPDATE;
  IF member.id IS NULL OR NOT EXISTS(
   SELECT FROM public.faculty_assignments f WHERE f.id=member.reviewer_assignment_id
    AND f.valid_from<=clock_timestamp() AND (f.valid_until IS NULL OR clock_timestamp()<f.valid_until))
  THEN RAISE EXCEPTION 'Active project PRC assignment required' USING ERRCODE='42501'; END IF;
  SELECT * INTO c FROM public.submission_cases WHERE project_id=pid
    AND requirement_key='SYNOPSIS' FOR UPDATE;
  SELECT * INTO attempt FROM public.submission_attempts
   WHERE id=(input->>'attemptId')::uuid AND case_id=c.id FOR UPDATE;
  IF c.id IS NULL OR attempt.id IS NULL OR c.state<>'AWAITING_REVIEW'
     OR c.row_version IS DISTINCT FROM (input->>'expectedCaseVersion')::integer
     OR EXISTS(SELECT FROM public.prc_synopsis_decisions WHERE attempt_id=attempt.id)
  THEN RAISE EXCEPTION 'Latest undecided synopsis submission required' USING ERRCODE='23514'; END IF;
  previous_context:=current_setting('smartpro.prc_authorized_decision',true);
  PERFORM set_config('smartpro.prc_authorized_decision','yes',true);
  result:=public.smartpro_document_command(actor,dept,'DECIDE',
   jsonb_build_object('projectId',pid,'attemptId',attempt.id,
     'expectedCaseVersion',c.row_version,'decision',
     CASE WHEN decision='APPROVE' THEN 'APPROVE' ELSE 'REQUEST_CHANGES' END,
     'comment',input->>'comment','requirementKey','SYNOPSIS','_actingRole','Faculty'),
   'prc-'||substr(md5(actor::text||':'||request_key),1,30));
  PERFORM set_config('smartpro.prc_authorized_decision',coalesce(previous_context,''),true);
  INSERT INTO public.prc_synopsis_decisions(project_id,attempt_id,faculty_user_id,decision,comment)
   VALUES(pid,attempt.id,actor,decision,input->>'comment') RETURNING id INTO reviewer;
  INSERT INTO public.audit_events(actor_id,project_id,action,target_type,target_id,metadata)
   VALUES(actor,pid,'PRC_'||decision,'PRC_SYNOPSIS_DECISION',reviewer,
    jsonb_build_object('attemptId',attempt.id,'offeringId',oid,'documentStatus',result->'status'));
  result:=jsonb_build_object('status',decision,'projectId',pid,'attemptId',attempt.id);
 END IF;
 -- Recheck after lock waits. An expired appointment rolls back all writes.
 IF action IN ('ACTIVATE','ASSIGN','END_MEMBER') THEN
  PERFORM public.smartpro_course_authority(actor,oid,'EVALUATORS','Coordinator');
 ELSE
  IF NOT public.smartpro_has_role(actor,dept,'FACULTY',clock_timestamp())
  THEN RAISE EXCEPTION 'PRC membership expired while waiting' USING ERRCODE='42501'; END IF;
 END IF;
 RETURN result;
END $f$;

CREATE FUNCTION public.smartpro_prc_overview(actor uuid,oid uuid,acting_role text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $f$
DECLARE department uuid; authorized boolean;
BEGIN
 SELECT department_id INTO department FROM public.curriculum_offerings WHERE id=oid;
 IF department IS NULL OR NOT public.smartpro_role_choices(actor) ? acting_role
 THEN RAISE EXCEPTION 'Scoped course role required' USING ERRCODE='42501'; END IF;
 authorized:=CASE WHEN acting_role='Coordinator' THEN
  public.smartpro_course_access(actor,oid,'READ','Coordinator')
  WHEN acting_role='Faculty' THEN EXISTS(
   SELECT FROM public.prc_project_members m JOIN public.projects p ON p.id=m.project_id
   JOIN public.teams t ON t.id=p.team_id WHERE t.curriculum_offering_id=oid
    AND m.faculty_user_id=actor AND m.ended_at IS NULL)
  ELSE false END;
 IF NOT authorized THEN RAISE EXCEPTION 'PRC workspace access denied' USING ERRCODE='42501'; END IF;
 RETURN jsonb_build_object('activated',
  EXISTS(SELECT FROM public.prc_offering_gates WHERE offering_id=oid),
  'projects',(SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.title),'[]'::jsonb)
   FROM(
     SELECT p.id,p.title,p.project_code AS "projectCode",
       c.state AS "synopsisState",c.row_version AS "caseVersion",
       a.id AS "latestAttemptId",d.decision AS "prcDecision",
       public.smartpro_prc_approved(p.id) AS "prcApproved",
       EXISTS(SELECT FROM public.faculty_assignments g WHERE g.project_id=p.id
         AND g.assignment_type='GUIDE' AND g.valid_from<=clock_timestamp()
         AND (g.valid_until IS NULL OR clock_timestamp()<g.valid_until)) AS "guideAssigned",
       (SELECT coalesce(jsonb_agg(jsonb_build_object(
          'id',m.id,'facultyId',m.faculty_user_id,'name',u.display_name)), '[]'::jsonb)
        FROM public.prc_project_members m JOIN public.users u ON u.id=m.faculty_user_id
        WHERE m.project_id=p.id AND m.ended_at IS NULL) AS "members"
     FROM public.projects p JOIN public.teams t ON t.id=p.team_id
     LEFT JOIN public.submission_cases c ON c.project_id=p.id AND c.requirement_key='SYNOPSIS'
     LEFT JOIN LATERAL(
       SELECT sa.id FROM public.submission_attempts sa WHERE sa.case_id=c.id
       ORDER BY sa.attempt_no DESC LIMIT 1) a ON true
     LEFT JOIN public.prc_synopsis_decisions d ON d.attempt_id=a.id
     WHERE t.curriculum_offering_id=oid AND
      (acting_role='Coordinator' OR EXISTS(
        SELECT FROM public.prc_project_members pm WHERE pm.project_id=p.id
        AND pm.faculty_user_id=actor AND pm.ended_at IS NULL))
     ORDER BY p.title LIMIT 200
   ) x));
END $f$;
-- Student-facing, project-scoped PRC state: never exposes another team's work.
CREATE FUNCTION public.smartpro_prc_student_status(actor uuid,pid uuid,acting_role text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $f$
DECLARE state jsonb;
BEGIN
 IF acting_role<>'Student' OR NOT public.smartpro_role_choices(actor) ? 'Student'
    OR NOT public.smartpro_document_scope(actor,pid,'student')
 THEN RAISE EXCEPTION 'Current project student required' USING ERRCODE='42501'; END IF;
 SELECT jsonb_build_object(
   'enabled',public.smartpro_prc_required(pid),
   'approved',public.smartpro_prc_approved(pid),
   'synopsisState',c.state,
   'latestDecision',(SELECT d.decision FROM public.submission_attempts a
      LEFT JOIN public.prc_synopsis_decisions d ON d.attempt_id=a.id
      WHERE a.case_id=c.id ORDER BY a.attempt_no DESC LIMIT 1),
   'history',(SELECT coalesce(jsonb_agg(jsonb_build_object(
       'attemptNo',a.attempt_no,'decision',d.decision,'comment',d.comment,
       'recordedAt',d.recorded_at) ORDER BY a.attempt_no),'[]'::jsonb)
      FROM public.submission_attempts a JOIN public.prc_synopsis_decisions d ON d.attempt_id=a.id
      WHERE a.case_id=c.id)
 ) INTO state FROM public.projects p
 LEFT JOIN public.submission_cases c ON c.project_id=p.id AND c.requirement_key='SYNOPSIS'
 WHERE p.id=pid;
 RETURN coalesce(state,'{}'::jsonb);
END $f$;
REVOKE ALL ON FUNCTION public.smartpro_prc_student_status(uuid,uuid,text),public.smartpro_prc_required(uuid),public.smartpro_prc_approved(uuid),
 public.smartpro_prc_guide_guard(),public.smartpro_prc_document_guard(),
 public.smartpro_prc_command(uuid,uuid,text,jsonb,text),public.smartpro_prc_overview(uuid,uuid,text)
 FROM PUBLIC,smartpro_runtime;
GRANT EXECUTE ON FUNCTION public.smartpro_prc_command(uuid,uuid,text,jsonb,text),
 public.smartpro_prc_overview(uuid,uuid,text),
 public.smartpro_prc_student_status(uuid,uuid,text) TO smartpro_runtime;
COMMIT;
