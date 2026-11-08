-- Candidate 013: owner-run after 010 activation, 011, 012 and security boundaries.
-- No real-data rollout is authorized by this file. No baseline migration changes.
BEGIN;
DO $$ BEGIN
  IF to_regprocedure('public.smartpro_create_student_team(uuid,uuid,text,text,text)') IS NULL THEN
    RAISE EXCEPTION 'Install activated curriculum 010-012 before membership commands';
  END IF;
END $$;

CREATE TABLE public.team_membership_policy_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  department_id uuid NOT NULL REFERENCES public.departments(id),
  version_no integer NOT NULL CHECK(version_no>0),
  allow_join boolean NOT NULL DEFAULT false,
  allow_leave boolean NOT NULL DEFAULT false,
  allow_transfer boolean NOT NULL DEFAULT false,
  minimum_members integer CHECK(minimum_members>=0),
  maximum_members integer CHECK(maximum_members>=1),
  size_mode text NOT NULL CHECK(size_mode IN ('ADVISORY','ENFORCED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(minimum_members IS NULL OR maximum_members IS NULL OR minimum_members<=maximum_members),
  UNIQUE(id,department_id), UNIQUE(department_id,version_no)
);
CREATE TRIGGER immutable_membership_policy BEFORE UPDATE OR DELETE
  ON public.team_membership_policy_versions FOR EACH ROW
  EXECUTE FUNCTION public.smartpro_forbid_mutation();
CREATE TABLE public.offering_membership_policies (
  offering_id uuid PRIMARY KEY,
  cycle_id uuid NOT NULL,
  department_id uuid NOT NULL,
  policy_version_id uuid NOT NULL,
  FOREIGN KEY(offering_id,cycle_id,department_id)
    REFERENCES public.curriculum_offerings(id,cycle_id,department_id),
  FOREIGN KEY(policy_version_id,department_id)
    REFERENCES public.team_membership_policy_versions(id,department_id)
);
-- Real row writes make stale REPEATABLE READ/SERIALIZABLE capacity checks abort.
ALTER TABLE public.teams ADD COLUMN membership_revision uuid NOT NULL DEFAULT gen_random_uuid();
CREATE INDEX ix_membership_capacity ON public.team_memberships(team_id,left_at);

CREATE FUNCTION public.smartpro_audit_membership_policy() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  INSERT INTO public.audit_events(action,target_type,target_id,metadata)
  VALUES('MEMBERSHIP_POLICY_BOUND','CURRICULUM_OFFERING',coalesce(NEW.offering_id,OLD.offering_id),
    jsonb_build_object('old',CASE WHEN TG_OP<>'INSERT' THEN to_jsonb(OLD) END,
                       'new',CASE WHEN TG_OP<>'DELETE' THEN to_jsonb(NEW) END,
                       'databaseActor',session_user));
  RETURN NULL;
END $$;
CREATE TRIGGER audit_membership_policy AFTER INSERT OR UPDATE OR DELETE
  ON public.offering_membership_policies FOR EACH ROW
  EXECUTE FUNCTION public.smartpro_audit_membership_policy();

-- Also protects the existing 012 create command: adding a creator must not
-- bypass a configured maximum. Future scheduled members reserve capacity.
CREATE FUNCTION public.smartpro_team_capacity_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE policy public.team_membership_policy_versions%ROWTYPE;
        others bigint; active_others bigint; boundary timestamptz; old_active boolean:=false;
        new_reserved boolean;
BEGIN
  -- Same lock hierarchy as commands: profile -> offering -> team -> membership.
  PERFORM 1 FROM public.student_profiles WHERE user_id=NEW.user_id FOR UPDATE;
  PERFORM 1 FROM public.curriculum_offerings WHERE id=NEW.curriculum_offering_id FOR SHARE;
  UPDATE public.teams SET membership_revision=gen_random_uuid() WHERE id=NEW.team_id;
  SELECT v.* INTO policy FROM public.offering_membership_policies b
    JOIN public.team_membership_policy_versions v ON v.id=b.policy_version_id
    WHERE b.offering_id=NEW.curriculum_offering_id FOR SHARE OF b,v;
  IF NOT FOUND OR policy.size_mode='ADVISORY' THEN RETURN NEW; END IF;
  boundary:=clock_timestamp();
  new_reserved:=NEW.left_at IS NULL OR NEW.left_at>boundary;
  IF TG_OP='UPDATE' THEN
    old_active:=OLD.joined_at<=boundary AND (OLD.left_at IS NULL OR OLD.left_at>boundary);
  END IF;
  SELECT count(*),count(*) FILTER(WHERE m.joined_at<=boundary) INTO others,active_others
    FROM public.team_memberships m
    WHERE m.team_id=NEW.team_id AND m.id<>NEW.id
      AND (m.left_at IS NULL OR m.left_at>boundary);
  IF new_reserved AND policy.maximum_members IS NOT NULL AND others+1>policy.maximum_members THEN
    RAISE EXCEPTION 'team capacity exceeded' USING ERRCODE='23514';
  END IF;
  IF old_active AND NOT new_reserved AND policy.minimum_members IS NOT NULL
     AND active_others<policy.minimum_members THEN
    RAISE EXCEPTION 'departure would violate team minimum' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
-- Runs after verify_membership_scope, which serializes profile admissions.
CREATE TRIGGER zz_enforce_team_capacity BEFORE INSERT OR UPDATE OF left_at
  ON public.team_memberships FOR EACH ROW
  EXECUTE FUNCTION public.smartpro_team_capacity_guard();

CREATE FUNCTION public.smartpro_student_membership(
  p_actor_id uuid,p_action text,p_membership_id uuid,p_team_id uuid,p_reason text,
  p_key text,p_digest text
) RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE dept uuid; semester text; source_team uuid; offering uuid; target_offering uuid;
        record_id uuid; stored_digest text; stored_state text; prior jsonb;
        policy public.team_membership_policy_versions%ROWTYPE;
        effective_at timestamptz; membership uuid; body jsonb;
        affected_team uuid; n bigint; active_n bigint; warnings jsonb:='[]'::jsonb;
BEGIN
  IF p_action IS NULL OR p_action NOT IN ('JOIN','LEAVE','TRANSFER')
    OR (p_action='JOIN' AND (p_team_id IS NULL OR p_membership_id IS NOT NULL))
    OR (p_action='LEAVE' AND (p_team_id IS NOT NULL OR p_membership_id IS NULL))
    OR (p_action='TRANSFER' AND (p_team_id IS NULL OR p_membership_id IS NULL))
    OR p_reason IS NULL OR length(p_reason)>500
    OR p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 128
    OR p_key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
    OR p_digest IS NULL OR p_digest !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'invalid membership command' USING ERRCODE='22023';
  END IF;
  SELECT s.department_id,s.semester_key INTO dept,semester FROM public.student_profiles s
    WHERE s.user_id=p_actor_id FOR UPDATE OF s;
  IF NOT FOUND THEN RAISE EXCEPTION 'eligible student required' USING ERRCODE='42501'; END IF;
  PERFORM 1 FROM public.users u WHERE u.id=p_actor_id AND u.account_status='ACTIVE' FOR SHARE OF u;
  IF NOT FOUND THEN RAISE EXCEPTION 'eligible student required' USING ERRCODE='42501'; END IF;
  PERFORM 1 FROM public.department_role_assignments r WHERE r.user_id=p_actor_id
    AND r.department_id=dept AND r.role_code='STUDENT' AND r.valid_from<=clock_timestamp()
    AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until) LIMIT 1 FOR SHARE OF r;
  IF NOT FOUND THEN RAISE EXCEPTION 'eligible student required' USING ERRCODE='42501'; END IF;

  INSERT INTO public.idempotency_records(actor_id,operation,key,request_sha256,state)
    VALUES(p_actor_id,'STUDENT_MEMBERSHIP:'||p_action,p_key,p_digest,'IN_PROGRESS')
    ON CONFLICT(actor_id,operation,key) DO NOTHING;
  SELECT i.id,i.request_sha256,i.state,i.response_body INTO record_id,stored_digest,stored_state,prior
    FROM public.idempotency_records i WHERE i.actor_id=p_actor_id
      AND i.operation='STUDENT_MEMBERSHIP:'||p_action AND i.key=p_key FOR UPDATE OF i;
  IF record_id IS NULL THEN RAISE EXCEPTION 'retry transaction' USING ERRCODE='40001'; END IF;
  IF stored_digest<>p_digest THEN RAISE EXCEPTION 'idempotency input conflict' USING ERRCODE='23505'; END IF;
  IF stored_state='COMPLETE' THEN
    -- Replays survive closed windows/ended membership, but never changed actor scope.
    PERFORM 1 FROM public.curriculum_offerings o WHERE o.id=(prior->>'offeringId')::uuid
      AND o.department_id=dept AND o.semester_key=semester;
    IF NOT FOUND THEN RAISE EXCEPTION 'replay outside current scope' USING ERRCODE='42501'; END IF;
    RETURN jsonb_build_object('replayed',true,'membership',prior);
  END IF;
  IF stored_state<>'IN_PROGRESS' THEN RAISE EXCEPTION 'retry transaction' USING ERRCODE='40001'; END IF;

  IF p_action<>'JOIN' THEN
    SELECT m.team_id,m.curriculum_offering_id INTO source_team,offering
      FROM public.team_memberships m WHERE m.id=p_membership_id AND m.user_id=p_actor_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'own membership required' USING ERRCODE='42501'; END IF;
  END IF;
  IF p_team_id IS NOT NULL THEN
    SELECT t.curriculum_offering_id INTO target_offering FROM public.teams t WHERE t.id=p_team_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'eligible target team required' USING ERRCODE='42501'; END IF;
    IF p_action='TRANSFER' AND (target_offering<>offering OR p_team_id=source_team) THEN
      RAISE EXCEPTION 'transfer requires a different team in the same offering' USING ERRCODE='23514';
    END IF;
    offering:=target_offering;
  END IF;
  PERFORM 1 FROM public.curriculum_offerings o WHERE o.id=offering
    AND o.department_id=dept AND o.semester_key=semester FOR SHARE OF o;
  IF NOT FOUND THEN RAISE EXCEPTION 'offering outside student scope' USING ERRCODE='42501'; END IF;
  SELECT v.* INTO policy FROM public.offering_membership_policies b
    JOIN public.team_membership_policy_versions v ON v.id=b.policy_version_id
    WHERE b.offering_id=offering FOR SHARE OF b,v;
  IF NOT FOUND OR (p_action='JOIN' AND NOT policy.allow_join)
    OR (p_action='LEAVE' AND NOT policy.allow_leave)
    OR (p_action='TRANSFER' AND NOT policy.allow_transfer) THEN
    RAISE EXCEPTION 'student membership operation disabled' USING ERRCODE='42501';
  END IF;
  IF p_action<>'LEAVE' THEN
    PERFORM 1 FROM public.student_offering_windows w WHERE w.offering_id=offering
      AND w.visible_from<=clock_timestamp() AND clock_timestamp()<w.visible_until FOR SHARE OF w;
    IF NOT FOUND THEN RAISE EXCEPTION 'offering not open' USING ERRCODE='42501'; END IF;
  END IF;
  -- Lock every affected team in UUID order. Real writes invalidate old capacity
  -- snapshots, including another student racing for the final place.
  FOR affected_team IN SELECT t.id FROM public.teams t
    WHERE t.id IN (source_team,p_team_id) ORDER BY t.id FOR UPDATE OF t
  LOOP
    UPDATE public.teams SET membership_revision=gen_random_uuid() WHERE id=affected_team;
  END LOOP;
  effective_at:=clock_timestamp();
  -- Time bounds can expire naturally while waiting for a row lock.
  IF NOT EXISTS(SELECT FROM public.department_role_assignments r WHERE r.user_id=p_actor_id
    AND r.department_id=dept AND r.role_code='STUDENT' AND r.valid_from<=effective_at
    AND (r.valid_until IS NULL OR effective_at<r.valid_until))
    OR (p_action<>'LEAVE' AND NOT EXISTS(SELECT FROM public.student_offering_windows w
      WHERE w.offering_id=offering AND w.visible_from<=effective_at AND effective_at<w.visible_until)) THEN
    RAISE EXCEPTION 'eligibility expired during command' USING ERRCODE='42501';
  END IF;
  IF p_action<>'JOIN' THEN
    PERFORM 1 FROM public.team_memberships m WHERE m.id=p_membership_id AND m.user_id=p_actor_id
      AND m.joined_at<effective_at AND (m.left_at IS NULL OR m.left_at>effective_at) FOR UPDATE OF m;
    IF NOT FOUND THEN RAISE EXCEPTION 'membership is not active' USING ERRCODE='23514'; END IF;
    UPDATE public.team_memberships SET left_at=effective_at WHERE id=p_membership_id;
  END IF;
  IF p_action<>'LEAVE' THEN
    INSERT INTO public.team_memberships(team_id,user_id,curriculum_offering_id,joined_at)
      VALUES(p_team_id,p_actor_id,offering,effective_at) RETURNING id INTO membership;
  END IF;
  IF policy.size_mode='ADVISORY' THEN
    FOR affected_team IN SELECT t.id FROM public.teams t
      WHERE t.id IN(source_team,p_team_id) ORDER BY t.id
    LOOP
      SELECT count(*),count(*) FILTER(WHERE m.joined_at<=effective_at) INTO n,active_n
        FROM public.team_memberships m WHERE m.team_id=affected_team
        AND (m.left_at IS NULL OR m.left_at>effective_at);
      IF policy.minimum_members IS NOT NULL AND active_n<policy.minimum_members THEN
        warnings:=warnings||jsonb_build_array(jsonb_build_object('teamId',affected_team,'code','BELOW_MINIMUM'));
      END IF;
      IF policy.maximum_members IS NOT NULL AND n>policy.maximum_members THEN
        warnings:=warnings||jsonb_build_array(jsonb_build_object('teamId',affected_team,'code','ABOVE_MAXIMUM'));
      END IF;
    END LOOP;
  END IF;
  body:=jsonb_build_object('action',p_action,'offeringId',offering,'teamId',coalesce(p_team_id,source_team),
    'membershipId',coalesce(membership,p_membership_id),'previousMembershipId',p_membership_id,
    'effectiveAt',effective_at,'policyVersionId',policy.id,'warnings',warnings);
  INSERT INTO public.audit_events(actor_id,action,target_type,target_id,metadata)
    VALUES(p_actor_id,'MEMBERSHIP_'||p_action,'TEAM_MEMBERSHIP',coalesce(membership,p_membership_id),
      body||jsonb_build_object('sourceTeamId',source_team,'reason',p_reason));
  UPDATE public.idempotency_records SET state='COMPLETE',response_status=CASE WHEN p_action='LEAVE' THEN 200 ELSE 201 END,
    response_body=body WHERE id=record_id;
  RETURN jsonb_build_object('replayed',false,'membership',body);
END $$;

REVOKE ALL ON TABLE public.team_membership_policy_versions,public.offering_membership_policies FROM PUBLIC,smartpro_runtime;
REVOKE ALL ON FUNCTION public.smartpro_audit_membership_policy() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.smartpro_team_capacity_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.smartpro_student_membership(uuid,text,uuid,uuid,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_student_membership(uuid,text,uuid,uuid,text,text,text) TO smartpro_runtime;

-- Students need their own membership IDs to leave/transfer existing teams.
-- Closed admission windows must not hide an otherwise permitted departure.
CREATE FUNCTION public.smartpro_student_memberships(p_actor_id uuid,after_id uuid DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE profile jsonb; page jsonb; next_cursor uuid;
BEGIN
  profile:=public.smartpro_student_profile(p_actor_id);
  WITH candidates AS (
    SELECT m.id,m.joined_at,m.left_at,t.id AS team_id,t.name,o.id AS offering_id,o.cycle_id
    FROM public.team_memberships m JOIN public.teams t ON t.id=m.team_id
    JOIN public.curriculum_offerings o ON o.id=m.curriculum_offering_id
    WHERE m.user_id=p_actor_id AND m.joined_at<=statement_timestamp()
      AND (m.left_at IS NULL OR statement_timestamp()<m.left_at)
      AND o.department_id=(profile->'department'->>'id')::uuid
      AND o.semester_key=profile->>'semester'
      AND (after_id IS NULL OR m.id>after_id)
    ORDER BY m.id LIMIT 51
  ), numbered AS (
    SELECT *,row_number() OVER(ORDER BY id) AS position FROM candidates
  )
  SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'teamId',team_id,'teamName',name,
    'offeringId',offering_id,'cycleId',cycle_id,'joinedAt',joined_at,'scheduledEndAt',left_at)
    ORDER BY id) FILTER(WHERE position<=50),'[]'::jsonb),
    CASE WHEN count(*)>50 THEN (array_agg(id ORDER BY id) FILTER(WHERE position=50))[1] END
  INTO page,next_cursor FROM numbered;
  RETURN jsonb_build_object('results',page,'nextCursor',next_cursor);
END $$;
REVOKE ALL ON FUNCTION public.smartpro_student_memberships(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_student_memberships(uuid,uuid) TO smartpro_runtime;
COMMIT;
