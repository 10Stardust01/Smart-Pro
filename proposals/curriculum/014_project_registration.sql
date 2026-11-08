-- Owner-run candidate 014, after reviewed 010-013 and runtime boundaries.
-- Not an automatic migration or authorization to activate real academic data.
BEGIN;
DO $$ BEGIN
  IF to_regprocedure('public.smartpro_student_membership(uuid,text,uuid,uuid,text,text,text)') IS NULL THEN
    RAISE EXCEPTION 'Install activated curriculum 010-013 before project registration';
  END IF;
END $$;

-- Reuse existing approved academic policies. Only an explicitly approved simple
-- registration rule is supported; unknown restrictions must never be ignored.
CREATE TABLE public.project_registration_policy_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  offering_id uuid NOT NULL,
  cycle_id uuid NOT NULL,
  department_id uuid NOT NULL,
  project_type text NOT NULL CHECK(project_type IN ('MINI','MAJOR')),
  policy_version_id uuid NOT NULL,
  version_no integer NOT NULL CHECK(version_no>0),
  opens_at timestamptz NOT NULL,
  closes_at timestamptz NOT NULL,
  CHECK(opens_at<closes_at),
  FOREIGN KEY(offering_id,cycle_id,department_id)
    REFERENCES public.curriculum_offerings(id,cycle_id,department_id),
  FOREIGN KEY(policy_version_id,department_id,project_type)
    REFERENCES public.project_policy_versions(id,department_id,project_type),
  UNIQUE(offering_id,project_type,version_no),
  UNIQUE(id,offering_id,project_type),
  UNIQUE(id,offering_id,cycle_id,policy_version_id)
);
CREATE FUNCTION public.smartpro_registration_policy_approval() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  PERFORM 1 FROM public.project_policy_versions p WHERE p.id=NEW.policy_version_id
    AND p.department_id=NEW.department_id AND p.project_type=NEW.project_type
    AND p.policy_status='APPROVED'
    AND p.policy_data->'studentRegistration'='{"enabled":true}'::jsonb FOR SHARE OF p;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'approved supported student registration policy required' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER validate_registration_policy BEFORE INSERT ON public.project_registration_policy_versions
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_registration_policy_approval();
CREATE TRIGGER freeze_registration_policy BEFORE UPDATE OR DELETE ON public.project_registration_policy_versions
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation();
CREATE TABLE public.offering_project_registration_policies (
  offering_id uuid NOT NULL REFERENCES public.curriculum_offerings(id),
  project_type text NOT NULL,
  registration_policy_version_id uuid NOT NULL,
  PRIMARY KEY(offering_id,project_type),
  FOREIGN KEY(registration_policy_version_id,offering_id,project_type)
    REFERENCES public.project_registration_policy_versions(id,offering_id,project_type)
);
CREATE FUNCTION public.smartpro_audit_registration_policy() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  INSERT INTO public.audit_events(action,target_type,target_id,metadata)
    VALUES('PROJECT_REGISTRATION_POLICY_BOUND','CURRICULUM_OFFERING',coalesce(NEW.offering_id,OLD.offering_id),
      jsonb_build_object('old',CASE WHEN TG_OP<>'INSERT' THEN to_jsonb(OLD) END,
                         'new',CASE WHEN TG_OP<>'DELETE' THEN to_jsonb(NEW) END,
                         'databaseActor',session_user));
  RETURN NULL;
END $$;
CREATE TRIGGER audit_registration_policy AFTER INSERT OR UPDATE OR DELETE
  ON public.offering_project_registration_policies FOR EACH ROW
  EXECUTE FUNCTION public.smartpro_audit_registration_policy();

-- Dedicated immutable receipts avoid the legacy runtime INSERT grant on the
-- shared idempotency table. No runtime DML is granted on projects or receipts.
-- Composite FKs pin project/team/cycle/policy and original membership evidence.
CREATE TABLE public.student_project_registrations (
  project_id uuid PRIMARY KEY,
  actor_id uuid NOT NULL,
  request_key text NOT NULL CHECK(length(request_key) BETWEEN 1 AND 128),
  request_sha256 text NOT NULL CHECK(request_sha256 ~ '^[0-9a-f]{64}$'),
  team_id uuid NOT NULL,
  offering_id uuid NOT NULL,
  cycle_id uuid NOT NULL,
  policy_version_id uuid NOT NULL,
  registration_policy_version_id uuid NOT NULL,
  membership_id uuid NOT NULL,
  response_body jsonb NOT NULL CHECK(jsonb_typeof(response_body)='object'),
  registered_at timestamptz NOT NULL,
  UNIQUE(actor_id,request_key),
  FOREIGN KEY(project_id,team_id) REFERENCES public.projects(id,team_id),
  FOREIGN KEY(project_id,cycle_id,policy_version_id) REFERENCES public.projects(id,cycle_id,policy_version_id),
  FOREIGN KEY(team_id,offering_id) REFERENCES public.teams(id,curriculum_offering_id),
  FOREIGN KEY(membership_id,team_id,actor_id) REFERENCES public.team_memberships(id,team_id,user_id),
  FOREIGN KEY(registration_policy_version_id,offering_id,cycle_id,policy_version_id)
    REFERENCES public.project_registration_policy_versions(id,offering_id,cycle_id,policy_version_id)
);
CREATE TRIGGER freeze_project_registration BEFORE UPDATE OR DELETE ON public.student_project_registrations
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation();
CREATE INDEX ix_registration_membership_history ON public.student_project_registrations(membership_id,registered_at);
CREATE FUNCTION public.smartpro_registration_membership_history() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF NEW.left_at IS NOT NULL AND EXISTS(SELECT FROM public.student_project_registrations r
    WHERE r.membership_id=OLD.id AND NEW.left_at<=r.registered_at) THEN
    RAISE EXCEPTION 'membership edit would falsify project registration eligibility' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER preserve_project_registration_eligibility BEFORE UPDATE OF left_at ON public.team_memberships
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_registration_membership_history();
CREATE INDEX ix_projects_team_page ON public.projects(team_id,id);

CREATE FUNCTION public.smartpro_register_student_project(
  p_actor_id uuid,p_team_id uuid,p_project_type text,p_code text,p_title text,p_key text,p_digest text
) RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE dept uuid; semester text; offering uuid; cycle uuid; member uuid;
        window_record public.project_registration_policy_versions%ROWTYPE;
        previous public.student_project_registrations%ROWTYPE;
        effective_at timestamptz; project uuid; body jsonb;
BEGIN
  IF p_team_id IS NULL OR p_project_type IS NULL OR p_project_type NOT IN ('MINI','MAJOR')
    OR p_code IS NULL OR length(btrim(p_code)) NOT BETWEEN 1 AND 120
    OR p_title IS NULL OR length(btrim(p_title)) NOT BETWEEN 1 AND 500
    OR p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 128
    OR p_key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
    OR p_digest IS NULL OR p_digest !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'invalid project registration' USING ERRCODE='22023';
  END IF;
  -- A real profile write serializes same-actor retries at stronger isolation too.
  UPDATE public.student_profiles s SET membership_scope_revision=gen_random_uuid()
    WHERE s.user_id=p_actor_id RETURNING s.department_id,s.semester_key INTO dept,semester;
  IF NOT FOUND THEN RAISE EXCEPTION 'eligible student required' USING ERRCODE='42501'; END IF;
  PERFORM 1 FROM public.users u WHERE u.id=p_actor_id AND u.account_status='ACTIVE' FOR SHARE OF u;
  IF NOT FOUND THEN RAISE EXCEPTION 'eligible student required' USING ERRCODE='42501'; END IF;
  PERFORM 1 FROM public.department_role_assignments r WHERE r.user_id=p_actor_id
    AND r.department_id=dept AND r.role_code='STUDENT' AND r.valid_from<=clock_timestamp()
    AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until) LIMIT 1 FOR SHARE OF r;
  IF NOT FOUND THEN RAISE EXCEPTION 'eligible student required' USING ERRCODE='42501'; END IF;
  SELECT r.* INTO previous FROM public.student_project_registrations r
    WHERE r.actor_id=p_actor_id AND r.request_key=p_key;
  -- The digest is a retry fingerprint, never authority for an alternate team.
  IF FOUND AND (previous.request_sha256<>p_digest OR previous.team_id<>p_team_id
    OR previous.response_body->>'projectType' IS DISTINCT FROM p_project_type
    OR previous.response_body->>'projectCode' IS DISTINCT FROM btrim(p_code)
    OR previous.response_body->>'title' IS DISTINCT FROM btrim(p_title)) THEN
    RAISE EXCEPTION 'idempotency input conflict' USING ERRCODE='23505';
  END IF;
  SELECT t.curriculum_offering_id,t.cycle_id INTO offering,cycle FROM public.teams t WHERE t.id=p_team_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'eligible team required' USING ERRCODE='42501'; END IF;
  PERFORM 1 FROM public.curriculum_offerings o WHERE o.id=offering
    AND o.department_id=dept AND o.semester_key=semester AND o.cycle_id=cycle FOR SHARE OF o;
  IF NOT FOUND THEN RAISE EXCEPTION 'team outside current student scope' USING ERRCODE='42501'; END IF;
  IF previous.project_id IS NULL THEN
    SELECT v.* INTO window_record FROM public.offering_project_registration_policies b
      JOIN public.project_registration_policy_versions v ON v.id=b.registration_policy_version_id
      JOIN public.project_policy_versions p ON p.id=v.policy_version_id
      WHERE b.offering_id=offering AND b.project_type=p_project_type
        AND v.department_id=dept AND v.cycle_id=cycle AND p.policy_status='APPROVED'
        AND p.policy_data->'studentRegistration'='{"enabled":true}'::jsonb
      FOR SHARE OF b,v,p;
    IF NOT FOUND THEN RAISE EXCEPTION 'applicable approved registration policy required' USING ERRCODE='42501'; END IF;
  END IF;
  -- SHARE conflicts with 013's team revision write. Registrations may run
  -- concurrently for different members, but membership changes must wait.
  PERFORM 1 FROM public.teams t WHERE t.id=p_team_id FOR SHARE OF t;
  SELECT m.id INTO member FROM public.team_memberships m WHERE m.team_id=p_team_id AND m.user_id=p_actor_id
    AND m.joined_at<=clock_timestamp() AND (m.left_at IS NULL OR clock_timestamp()<m.left_at) FOR SHARE OF m;
  IF NOT FOUND THEN RAISE EXCEPTION 'current effective membership required' USING ERRCODE='42501'; END IF;
  PERFORM 1 FROM public.department_role_assignments r
    WHERE r.user_id=p_actor_id AND r.department_id=dept AND r.role_code='STUDENT'
      AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)
    LIMIT 1 FOR SHARE OF r;
  IF NOT FOUND THEN RAISE EXCEPTION 'effective student role required' USING ERRCODE='42501'; END IF;
  effective_at:=clock_timestamp();
  IF NOT EXISTS(SELECT FROM public.team_memberships m WHERE m.id=member
      AND m.joined_at<=effective_at AND (m.left_at IS NULL OR effective_at<m.left_at))
    OR NOT EXISTS(SELECT FROM public.department_role_assignments r
      WHERE r.user_id=p_actor_id AND r.department_id=dept AND r.role_code='STUDENT'
        AND r.valid_from<=effective_at AND (r.valid_until IS NULL OR effective_at<r.valid_until)) THEN
    RAISE EXCEPTION 'current effective membership and student role required' USING ERRCODE='42501';
  END IF;
  IF previous.project_id IS NOT NULL THEN
    RETURN jsonb_build_object('replayed',true,'project',previous.response_body);
  END IF;
  IF NOT(window_record.opens_at<=effective_at AND effective_at<window_record.closes_at) THEN
    RAISE EXCEPTION 'project registration window closed' USING ERRCODE='42501';
  END IF;
  INSERT INTO public.projects(department_id,cycle_id,team_id,project_type,policy_version_id,project_code,title,created_at)
    VALUES(dept,cycle,p_team_id,p_project_type,window_record.policy_version_id,btrim(p_code),btrim(p_title),effective_at)
    RETURNING id INTO project;
  body:=jsonb_build_object('id',project,'teamId',p_team_id,'offeringId',offering,'cycleId',cycle,
    'projectType',p_project_type,'projectCode',btrim(p_code),'title',btrim(p_title),
    'policyVersionId',window_record.policy_version_id,'registrationPolicyVersionId',window_record.id,
    'createdAt',effective_at);
  INSERT INTO public.student_project_registrations(project_id,actor_id,request_key,request_sha256,team_id,
    offering_id,cycle_id,policy_version_id,registration_policy_version_id,membership_id,response_body,registered_at)
    VALUES(project,p_actor_id,p_key,p_digest,p_team_id,offering,cycle,window_record.policy_version_id,
      window_record.id,member,body,effective_at);
  INSERT INTO public.audit_events(actor_id,project_id,action,target_type,target_id,metadata)
    VALUES(p_actor_id,project,'PROJECT_REGISTERED','PROJECT',project,
      jsonb_build_object('membershipId',member,'teamId',p_team_id,'offeringId',offering,
        'policyVersionId',window_record.policy_version_id,'registrationPolicyVersionId',window_record.id));
  RETURN jsonb_build_object('replayed',false,'project',body);
END $$;

CREATE FUNCTION public.smartpro_student_projects(p_actor_id uuid,after_id uuid DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE profile jsonb; page jsonb; next_cursor uuid;
BEGIN
  profile:=public.smartpro_student_profile(p_actor_id);
  WITH candidates AS (
    SELECT p.*,t.curriculum_offering_id,r.registration_policy_version_id FROM public.projects p
      JOIN public.teams t ON t.id=p.team_id JOIN public.curriculum_offerings o ON o.id=t.curriculum_offering_id
      LEFT JOIN public.student_project_registrations r ON r.project_id=p.id
    WHERE o.department_id=(profile->'department'->>'id')::uuid AND o.semester_key=profile->>'semester'
      AND EXISTS(SELECT FROM public.team_memberships m WHERE m.user_id=p_actor_id AND m.team_id=t.id
        AND m.joined_at<=statement_timestamp() AND (m.left_at IS NULL OR statement_timestamp()<m.left_at))
      AND (after_id IS NULL OR p.id>after_id) ORDER BY p.id LIMIT 51
  ), numbered AS (SELECT *,row_number() OVER(ORDER BY id) AS position FROM candidates)
  SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'teamId',team_id,'offeringId',curriculum_offering_id,
    'cycleId',cycle_id,'projectType',project_type,'projectCode',project_code,'title',title,
    'policyVersionId',policy_version_id,'registrationPolicyVersionId',registration_policy_version_id,
    'createdAt',created_at) ORDER BY id) FILTER(WHERE position<=50),'[]'::jsonb),
    CASE WHEN count(*)>50 THEN (array_agg(id ORDER BY id) FILTER(WHERE position=50))[1] END
  INTO page,next_cursor FROM numbered;
  RETURN jsonb_build_object('results',page,'nextCursor',next_cursor);
END $$;

REVOKE ALL ON TABLE public.project_registration_policy_versions,public.offering_project_registration_policies,
  public.student_project_registrations FROM PUBLIC,smartpro_runtime;
REVOKE ALL ON FUNCTION public.smartpro_registration_policy_approval() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.smartpro_registration_membership_history() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.smartpro_audit_registration_policy() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.smartpro_register_student_project(uuid,uuid,text,text,text,text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.smartpro_student_projects(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_register_student_project(uuid,uuid,text,text,text,text,text) TO smartpro_runtime;
GRANT EXECUTE ON FUNCTION public.smartpro_student_projects(uuid,uuid) TO smartpro_runtime;
COMMIT;
