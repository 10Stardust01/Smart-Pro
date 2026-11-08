-- Candidate 012, depends on activated curriculum 010 and student reads 011.
-- Reviewed owner-run install only; never an automatic real-data migration.
-- All student commands remain inaccessible until the application rollout gate is enabled.
BEGIN;
DO $$
BEGIN
  IF to_regclass('public.student_offering_windows') IS NULL
    OR NOT EXISTS (
      SELECT FROM pg_catalog.pg_attribute
      WHERE attrelid='public.team_memberships'::regclass
        AND attname='curriculum_offering_id' AND attnotnull
    ) THEN
    RAISE EXCEPTION 'Activate curriculum 010 and student reads 011 before team commands';
  END IF;
END;
$$;

CREATE INDEX ix_team_offering_discovery ON public.teams(curriculum_offering_id,id);

-- A trusted server supplies actor_id. Runtime cannot directly INSERT teams,
-- and the owner-run security read boundary limits direct legacy SELECT grants.
-- Production database identity/privileges must match the reviewed rollout.
-- Lock order: student profile -> user/role -> idempotency record -> offering
-- -> team -> membership -> audit. The function holds its authorization locks
-- until commit to serialize enrollment changes.
CREATE FUNCTION public.smartpro_create_student_team(
  p_actor_id uuid, p_offering_id uuid, team_name text,
  request_key text, request_digest text
) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp
AS $$
DECLARE
  profile_department uuid;
  profile_semester text;
  offered_cycle uuid;
  record_id uuid;
  record_digest text;
  record_state text;
  prior_body jsonb;
  created_team uuid;
  created_membership uuid;
  effective_at timestamptz;
  cleaned_name text;
  body jsonb;
BEGIN
  cleaned_name:=btrim(team_name);
  IF cleaned_name IS NULL OR cleaned_name='' OR length(cleaned_name)>120 THEN
    RAISE EXCEPTION 'invalid team name' USING ERRCODE='22023';
  END IF;
  IF request_key IS NULL OR length(request_key) NOT BETWEEN 1 AND 128
     OR request_key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
     OR request_digest IS NULL OR request_digest !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'invalid idempotency request' USING ERRCODE='22023';
  END IF;

  -- Lock this identity scope first, including concurrent semester corrections.
  SELECT s.department_id,s.semester_key
  INTO profile_department,profile_semester
  FROM public.student_profiles s
  WHERE s.user_id=p_actor_id FOR UPDATE OF s;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'active eligible student required' USING ERRCODE='42501';
  END IF;
  PERFORM 1 FROM public.users u WHERE u.id=p_actor_id
    AND u.account_status='ACTIVE' FOR SHARE OF u;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'active eligible student required' USING ERRCODE='42501';
  END IF;
  PERFORM 1 FROM public.department_role_assignments r
    WHERE r.user_id=p_actor_id AND r.department_id=profile_department
      AND r.role_code='STUDENT'
      AND r.valid_from<=statement_timestamp()
      AND (r.valid_until IS NULL OR statement_timestamp()<r.valid_until)
    LIMIT 1 FOR SHARE OF r;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'active eligible student required' USING ERRCODE='42501';
  END IF;

  -- ON CONFLICT waits for a concurrent same-key creator's transaction. A
  -- conflicting payload never creates another team; retries reuse committed
  -- response bytes and never create a second audit record.
  INSERT INTO public.idempotency_records(actor_id,operation,key,request_sha256,state)
  VALUES(p_actor_id,'STUDENT_CREATE_TEAM',request_key,request_digest,'IN_PROGRESS')
  ON CONFLICT (actor_id,operation,key) DO NOTHING;
  SELECT i.id,i.request_sha256,i.state,i.response_body
  INTO record_id,record_digest,record_state,prior_body
  FROM public.idempotency_records i
  WHERE i.actor_id=p_actor_id AND i.operation='STUDENT_CREATE_TEAM' AND i.key=request_key
  FOR UPDATE OF i;
  IF record_id IS NULL THEN
    RAISE EXCEPTION 'idempotency record unavailable' USING ERRCODE='40001';
  END IF;
  IF record_digest<>request_digest THEN
    RAISE EXCEPTION 'idempotency key already used with different input' USING ERRCODE='23505';
  END IF;
  IF record_state='COMPLETE' THEN
    RETURN jsonb_build_object('replayed',true,'team',prior_body);
  END IF;
  IF record_state<>'IN_PROGRESS' THEN
    RAISE EXCEPTION 'idempotency record has unexpected state' USING ERRCODE='40001';
  END IF;

  -- A committed retry is returned even if registration subsequently closed;
  -- new commands revalidate the offering after the idempotency reservation.
  SELECT o.cycle_id INTO offered_cycle
  FROM public.curriculum_offerings o
  JOIN public.student_offering_windows w ON w.offering_id=o.id
  WHERE o.id=p_offering_id
    AND o.department_id=profile_department
    AND o.semester_key=profile_semester
    AND o.student_team_creation_enabled=true
    AND w.visible_from<=statement_timestamp()
    AND statement_timestamp()<w.visible_until
  FOR SHARE OF o,w;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'offering is not eligible for team creation' USING ERRCODE='42501';
  END IF;

  -- A row lock can outlive either eligibility deadline. The statement start
  -- time is not authority to admit a student after that wait has completed.
  effective_at:=clock_timestamp();
  IF NOT EXISTS(SELECT FROM public.department_role_assignments r
      WHERE r.user_id=p_actor_id AND r.department_id=profile_department
        AND r.role_code='STUDENT' AND r.valid_from<=effective_at
        AND (r.valid_until IS NULL OR effective_at<r.valid_until))
    OR NOT EXISTS(SELECT FROM public.student_offering_windows w
      WHERE w.offering_id=p_offering_id AND w.visible_from<=effective_at
        AND effective_at<w.visible_until) THEN
    RAISE EXCEPTION 'team creation eligibility expired while waiting' USING ERRCODE='42501';
  END IF;

  INSERT INTO public.teams(department_id,cycle_id,name,curriculum_offering_id)
  VALUES(profile_department,offered_cycle,cleaned_name,p_offering_id)
  RETURNING id INTO created_team;
  -- Existing 010 membership-scope trigger and temporal exclusion constraint
  -- remain authoritative: conflicting concurrent membership rolls all back.
  INSERT INTO public.team_memberships(team_id,user_id,curriculum_offering_id,joined_at)
  VALUES(created_team,p_actor_id,p_offering_id,effective_at)
  RETURNING id INTO created_membership;

  body:=jsonb_build_object(
    'id',created_team,'name',cleaned_name,
    'offeringId',p_offering_id,'membershipId',created_membership
  );
  INSERT INTO public.audit_events(actor_id,action,target_type,target_id,metadata)
  VALUES(p_actor_id,'TEAM_CREATED','TEAM',created_team,
    jsonb_build_object('offeringId',p_offering_id,'membershipId',created_membership));

  UPDATE public.idempotency_records SET state='COMPLETE',
    response_status=201,response_body=body WHERE id=record_id;
  RETURN jsonb_build_object('replayed',false,'team',body);
END;
$$;

CREATE FUNCTION public.smartpro_student_eligible_teams(
  p_actor_id uuid, p_offering_id uuid, after_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp
AS $$
DECLARE
  profile jsonb;
  page jsonb;
  next_cursor uuid;
BEGIN
  profile:=public.smartpro_student_profile(p_actor_id);
  -- Discovery visibility follows the authorized published offering, regardless
  -- of whether new team creation is enabled. No roster/USN directory exposed.
  PERFORM 1 FROM public.curriculum_offerings o
  JOIN public.student_offering_windows w ON w.offering_id=o.id
  WHERE o.id=p_offering_id
    AND o.department_id=(profile->'department'->>'id')::uuid
    AND o.semester_key=profile->>'semester'
    AND w.visible_from<=statement_timestamp()
    AND statement_timestamp()<w.visible_until;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'offering not eligible for discovery' USING ERRCODE='42501';
  END IF;

  WITH candidates AS (
    SELECT t.id,t.name,COUNT(m.id)::integer AS member_count
    FROM public.teams t
    LEFT JOIN public.team_memberships m
      ON m.team_id=t.id AND m.joined_at<=statement_timestamp()
      AND (m.left_at IS NULL OR statement_timestamp()<m.left_at)
    WHERE t.curriculum_offering_id=p_offering_id
      AND (after_id IS NULL OR t.id>after_id)
    GROUP BY t.id
    ORDER BY t.id LIMIT 51
  ), numbered AS (
    SELECT *,row_number() OVER (ORDER BY id) AS position FROM candidates
  )
  SELECT coalesce(jsonb_agg(jsonb_build_object(
    'id',id,'name',name,'memberCount',member_count,'offeringId',p_offering_id
    ) ORDER BY id) FILTER (WHERE position<=50),'[]'::jsonb),
    CASE WHEN COUNT(*)>50 THEN (array_agg(id ORDER BY id)
      FILTER (WHERE position=50))[1] END
  INTO page,next_cursor FROM numbered;
  RETURN jsonb_build_object('results',page,'nextCursor',next_cursor);
END;
$$;

REVOKE ALL ON FUNCTION public.smartpro_create_student_team(uuid,uuid,text,text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.smartpro_student_eligible_teams(uuid,uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_create_student_team(uuid,uuid,text,text,text) TO smartpro_runtime;
GRANT EXECUTE ON FUNCTION public.smartpro_student_eligible_teams(uuid,uuid,uuid) TO smartpro_runtime;
COMMIT;
