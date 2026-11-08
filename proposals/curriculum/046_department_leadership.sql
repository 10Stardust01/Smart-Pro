-- Department leadership terms use the existing temporal role records.
BEGIN;

ALTER TABLE public.department_role_assignments ADD CONSTRAINT department_hod_terms_do_not_overlap
  EXCLUDE USING gist (department_id WITH =, tstzrange(valid_from,valid_until,'[)') WITH &&)
  WHERE (role_code='HOD');
ALTER TABLE public.academic_governance_settings ADD COLUMN admin_capacity integer NOT NULL DEFAULT 1
  CHECK(admin_capacity BETWEEN 1 AND 50);

CREATE FUNCTION public.smartpro_leadership_people(dept uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path=pg_catalog,public,pg_temp AS $$
  SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY display_name,id),'[]') FROM (
    SELECT u.id,u.display_name
    FROM public.users u
    WHERE u.account_status='ACTIVE' AND public.smartpro_has_role(u.id,dept,'FACULTY',statement_timestamp())
    ORDER BY u.display_name,u.id LIMIT 200
  ) x;
$$;

CREATE FUNCTION public.smartpro_department_leadership(actor uuid,dept uuid,role text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF role='HOD' THEN PERFORM public.smartpro_academic_authority(actor,dept,true);
  ELSIF role IS DISTINCT FROM 'Admin' OR NOT public.smartpro_has_role(actor,dept,'ACADEMIC_ADMIN',clock_timestamp()) THEN
    RAISE EXCEPTION 'Current department leadership required' USING ERRCODE='42501';
  END IF;
  RETURN jsonb_build_object(
    'adminCapacity',(SELECT admin_capacity FROM public.academic_governance_settings WHERE department_id=dept),
    'people',public.smartpro_leadership_people(dept),
    'appointments',(SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY valid_from DESC),'[]') FROM (
      SELECT r.id,r.user_id,u.display_name,r.role_code,r.valid_from,r.valid_until,
        (r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)) AS active
      FROM public.department_role_assignments r JOIN public.users u ON u.id=r.user_id
      WHERE r.department_id=dept AND r.role_code IN ('HOD','ACADEMIC_ADMIN')
      ORDER BY (r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)) DESC,r.valid_from DESC
      LIMIT 200
    ) x),
    'vacancyByResignation', EXISTS(
      SELECT FROM public.document_command_receipts a WHERE a.action='DEPARTMENT_RESIGN_HOD'
        AND a.output->>'appointmentId'=(SELECT id::text FROM public.department_role_assignments
                         WHERE department_id=dept AND role_code='HOD' ORDER BY valid_from DESC LIMIT 1)
    ) AND NOT EXISTS(SELECT FROM public.department_role_assignments WHERE department_id=dept AND role_code='HOD'
      AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until)));
END $$;

CREATE FUNCTION public.smartpro_change_department_leadership(actor uuid,dept uuid,action text,input jsonb,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE selected_role text:=input->>'_actingRole'; actor_role uuid; uid uuid:=(input->>'userId')::uuid;
  term uuid:=(input->>'appointmentId')::uuid; previous public.department_role_assignments%ROWTYPE;
  prior public.document_command_receipts%ROWTYPE; stamp timestamptz; new_term uuid; capacity integer;
  output jsonb; payload jsonb:=jsonb_build_object('departmentId',dept,'payload',input);
BEGIN
  IF key IS NULL OR key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' THEN
    RAISE EXCEPTION 'Request key required' USING ERRCODE='22023';
  END IF;
  SELECT admin_capacity INTO capacity FROM public.academic_governance_settings
    WHERE department_id=dept AND enabled FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Department governance is unavailable' USING ERRCODE='42501'; END IF;
  IF action='APPOINT_HOD' AND selected_role='Admin' THEN
    SELECT r.id INTO actor_role FROM public.department_role_assignments r JOIN public.users u ON u.id=r.user_id
    WHERE r.user_id=actor AND r.department_id=dept AND r.role_code='ACADEMIC_ADMIN'
      AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)
      AND u.account_status='ACTIVE' ORDER BY r.id LIMIT 1 FOR SHARE OF r,u;
    IF actor_role IS NULL THEN RAISE EXCEPTION 'Current department Admin required' USING ERRCODE='42501'; END IF;
  ELSIF action IN ('APPOINT_ADMIN','REPLACE_ADMIN','END_ADMIN','SET_ADMIN_CAPACITY','RESIGN_HOD') AND selected_role='HOD' THEN
    actor_role:=(public.smartpro_academic_authority(actor,dept,true)->>'hodRoleId')::uuid;
  ELSE
    RAISE EXCEPTION 'Selected department leadership responsibility required' USING ERRCODE='42501';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(actor::text||':leadership:'||key,0));
  SELECT * INTO prior FROM public.document_command_receipts WHERE actor_id=actor AND request_key=key;
  IF FOUND THEN
    IF prior.action<>'DEPARTMENT_'||action OR prior.input<>payload THEN
      RAISE EXCEPTION 'Request key changed' USING ERRCODE='23514';
    END IF;
    RETURN prior.output;
  END IF;

  IF action IN ('APPOINT_HOD','APPOINT_ADMIN','REPLACE_ADMIN') THEN
    PERFORM 1 FROM public.department_role_assignments r JOIN public.users u ON u.id=r.user_id
    WHERE r.user_id=uid AND r.department_id=dept AND r.role_code='FACULTY' AND u.account_status='ACTIVE'
      AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)
    FOR SHARE OF r,u;
    IF NOT FOUND OR uid=actor THEN
      RAISE EXCEPTION 'Another eligible department faculty account is required' USING ERRCODE='42501';
    END IF;
  END IF;
  stamp:=clock_timestamp();
  IF NOT EXISTS(SELECT FROM public.department_role_assignments WHERE id=actor_role
     AND valid_from<=stamp AND (valid_until IS NULL OR stamp<valid_until)) THEN
    RAISE EXCEPTION 'Department leadership term expired' USING ERRCODE='42501';
  END IF;

  IF action='APPOINT_HOD' THEN
    SELECT * INTO previous FROM public.department_role_assignments WHERE department_id=dept AND role_code='HOD'
      ORDER BY valid_from DESC LIMIT 1 FOR UPDATE;
    IF NOT FOUND OR previous.valid_until IS NULL OR previous.valid_until>stamp OR NOT EXISTS(
      SELECT FROM public.document_command_receipts receipt WHERE receipt.action='DEPARTMENT_RESIGN_HOD' AND receipt.output->>'appointmentId'=previous.id::text
    ) THEN RAISE EXCEPTION 'A vacancy created by voluntary resignation is required' USING ERRCODE='23514'; END IF;
    INSERT INTO public.department_role_assignments(user_id,department_id,role_code,valid_from)
      VALUES(uid,dept,'HOD',stamp) RETURNING id INTO new_term;
    INSERT INTO public.academic_hod_mandates(department_id,role_assignment_id,user_id,enabled)
      VALUES(dept,new_term,uid,true);
  ELSIF action='RESIGN_HOD' THEN
    IF term IS DISTINCT FROM actor_role THEN
      RAISE EXCEPTION 'Only the current holder may resign' USING ERRCODE='42501';
    END IF;
    UPDATE public.department_role_assignments SET valid_until=stamp WHERE id=actor_role;
    new_term:=actor_role;
  ELSIF action='SET_ADMIN_CAPACITY' THEN
    capacity:=(input->>'capacity')::integer;
    IF capacity IS NULL OR capacity NOT BETWEEN 1 AND 50 OR capacity<(
      SELECT count(*) FROM public.department_role_assignments WHERE department_id=dept AND role_code='ACADEMIC_ADMIN'
       AND valid_from<=stamp AND (valid_until IS NULL OR stamp<valid_until)
    ) THEN RAISE EXCEPTION 'Capacity must accommodate active Admin appointments' USING ERRCODE='23514'; END IF;
    UPDATE public.academic_governance_settings SET admin_capacity=capacity WHERE department_id=dept;
  ELSE
    IF action IN ('REPLACE_ADMIN','END_ADMIN') THEN
      SELECT * INTO previous FROM public.department_role_assignments WHERE id=term AND department_id=dept
        AND role_code='ACADEMIC_ADMIN' AND valid_from<=stamp AND (valid_until IS NULL OR stamp<valid_until) FOR UPDATE;
      IF NOT FOUND THEN RAISE EXCEPTION 'Admin appointment changed' USING ERRCODE='23514'; END IF;
      UPDATE public.department_role_assignments SET valid_until=stamp WHERE id=term;
      new_term:=term;
    END IF;
    IF action IN ('APPOINT_ADMIN','REPLACE_ADMIN') THEN
      IF action='APPOINT_ADMIN' AND capacity<=(
        SELECT count(*) FROM public.department_role_assignments WHERE department_id=dept AND role_code='ACADEMIC_ADMIN'
          AND valid_from<=stamp AND (valid_until IS NULL OR stamp<valid_until)
      ) THEN RAISE EXCEPTION 'Department Admin capacity reached' USING ERRCODE='23514'; END IF;
      IF EXISTS(SELECT FROM public.department_role_assignments WHERE user_id=uid AND department_id=dept
        AND role_code='ACADEMIC_ADMIN' AND valid_from<=stamp AND (valid_until IS NULL OR stamp<valid_until)) THEN
        RAISE EXCEPTION 'Faculty account already has an Admin appointment' USING ERRCODE='23514';
      END IF;
      INSERT INTO public.department_role_assignments(user_id,department_id,role_code,valid_from)
        VALUES(uid,dept,'ACADEMIC_ADMIN',stamp) RETURNING id INTO new_term;
    END IF;
  END IF;
  output:=jsonb_build_object('appointmentId',new_term,'adminCapacity',capacity);
  INSERT INTO public.audit_events(actor_id,action,target_type,target_id,metadata)
    VALUES(actor,'DEPARTMENT_'||action,'DEPARTMENT_ROLE',coalesce(new_term,dept),
      jsonb_build_object('departmentId',dept,'actorRoleId',actor_role,'before',to_jsonb(previous),'request',input,'result',output));
  INSERT INTO public.document_command_receipts VALUES(actor,key,'DEPARTMENT_'||action,payload,output);
  RETURN output;
END $$;

-- The database owner invokes this once for an institutionally verified account.
CREATE FUNCTION public.smartpro_bootstrap_first_hod(dept uuid,uid uuid,reference text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE term uuid;
BEGIN
  IF nullif(btrim(reference),'') IS NULL OR length(reference)>500 THEN
    RAISE EXCEPTION 'Institutional verification reference required' USING ERRCODE='22023';
  END IF;
  PERFORM 1 FROM public.departments WHERE id=dept FOR UPDATE;
  IF NOT FOUND OR EXISTS(SELECT FROM public.department_role_assignments WHERE department_id=dept AND role_code='HOD') THEN
    RAISE EXCEPTION 'First HOD bootstrap requires an unused department HOD history' USING ERRCODE='23514';
  END IF;
  IF NOT public.smartpro_has_role(uid,dept,'FACULTY',clock_timestamp()) THEN
    RAISE EXCEPTION 'Verified active departmental faculty account required' USING ERRCODE='42501';
  END IF;
  INSERT INTO public.academic_governance_settings(department_id,enabled) VALUES(dept,true) ON CONFLICT DO NOTHING;
  INSERT INTO public.staff_department_controls(department_id,enabled) VALUES(dept,true) ON CONFLICT DO NOTHING;
  INSERT INTO public.department_role_assignments(user_id,department_id,role_code,valid_from)
    VALUES(uid,dept,'HOD',clock_timestamp()) RETURNING id INTO term;
  INSERT INTO public.academic_hod_mandates(department_id,role_assignment_id,user_id,enabled) VALUES(dept,term,uid,true);
  INSERT INTO public.audit_events(action,target_type,target_id,metadata)
    VALUES('DEPARTMENT_BOOTSTRAP_HOD','DEPARTMENT_ROLE',term,
      jsonb_build_object('departmentId',dept,'verifiedAccount',uid,'reference',reference,'databaseActor',session_user));
  RETURN term;
END $$;

REVOKE ALL ON FUNCTION public.smartpro_leadership_people(uuid),public.smartpro_department_leadership(uuid,uuid,text),
  public.smartpro_change_department_leadership(uuid,uuid,text,jsonb,text),public.smartpro_bootstrap_first_hod(uuid,uuid,text)
  FROM PUBLIC,smartpro_runtime;
GRANT EXECUTE ON FUNCTION public.smartpro_department_leadership(uuid,uuid,text),
  public.smartpro_change_department_leadership(uuid,uuid,text,jsonb,text) TO smartpro_runtime;

COMMIT;
