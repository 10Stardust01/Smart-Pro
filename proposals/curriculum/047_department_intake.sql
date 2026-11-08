-- Imports are departmental records. They do not issue roles or credentials.
BEGIN;
CREATE TABLE public.department_intake_batches(
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), department_id uuid NOT NULL REFERENCES public.departments(id),
  actor_id uuid NOT NULL REFERENCES public.users(id), source text NOT NULL CHECK(source IN ('OFFICIAL','FORM_EXPORT')),
  kind text NOT NULL CHECK(kind IN ('STUDENT','FACULTY')), reference text NOT NULL, records jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(id,department_id)
);
CREATE TABLE public.department_intake_records(
  department_id uuid NOT NULL, source text NOT NULL, kind text NOT NULL, identity_key text NOT NULL,
  batch_id uuid NOT NULL, record jsonb NOT NULL, linked_user_id uuid REFERENCES public.users(id),
  PRIMARY KEY(department_id,source,kind,identity_key),
  FOREIGN KEY(batch_id,department_id) REFERENCES public.department_intake_batches(id,department_id)
);
CREATE UNIQUE INDEX intake_student_number_per_source ON public.department_intake_records(department_id,source,(record->>'usn'))
  WHERE kind='STUDENT';
CREATE TRIGGER retain_intake_batches BEFORE UPDATE OR DELETE ON public.department_intake_batches
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation();
REVOKE ALL ON public.department_intake_batches,public.department_intake_records FROM PUBLIC,smartpro_runtime;

CREATE FUNCTION public.smartpro_department_intake(actor uuid,dept uuid,action text,input jsonb,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE src text:=input->>'source'; kind_code text:=input->>'kind'; batch uuid; prior public.document_command_receipts%ROWTYPE;
  incoming jsonb; previous public.department_intake_records%ROWTYPE; issues jsonb:='[]';
  result jsonb; scope_role uuid; stamp timestamptz; target uuid; dept_code text;
  payload jsonb:=jsonb_build_object('departmentId',dept,'payload',input);
BEGIN
  IF action<>'READ' THEN
    PERFORM 1 FROM public.academic_governance_settings WHERE department_id=dept AND enabled FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Department intake is disabled' USING ERRCODE='42501'; END IF;
  END IF;
  SELECT r.id,d.code INTO scope_role,dept_code FROM public.department_role_assignments r
  JOIN public.users u ON u.id=r.user_id JOIN public.departments d ON d.id=r.department_id
  WHERE r.user_id=actor AND r.department_id=dept AND r.role_code='ACADEMIC_ADMIN'
    AND u.account_status='ACTIVE' AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)
    AND EXISTS(SELECT FROM public.staff_department_controls WHERE department_id=dept AND enabled)
  ORDER BY r.id LIMIT 1 FOR SHARE OF r,u;
  IF scope_role IS NULL THEN RAISE EXCEPTION 'Current Department Admin required' USING ERRCODE='42501'; END IF;
  IF action='READ' THEN
    RETURN jsonb_build_object('departmentCode',dept_code,
      'batches',(SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY created_at DESC),'[]') FROM (
        SELECT id,source,kind,reference,created_at,jsonb_array_length(records) AS count FROM public.department_intake_batches
        WHERE department_id=dept ORDER BY created_at DESC LIMIT 30)x),
      'records',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM (
        SELECT source,kind,identity_key,batch_id,record,linked_user_id FROM public.department_intake_records
        WHERE department_id=dept ORDER BY batch_id DESC,identity_key LIMIT 100)x));
  END IF;
  IF action IN ('APPLY','RECONCILE') THEN
    IF key IS NULL OR key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' THEN RAISE EXCEPTION 'Request key required' USING ERRCODE='22023'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(actor::text||':intake:'||key,0));
    SELECT * INTO prior FROM public.document_command_receipts WHERE actor_id=actor AND request_key=key;
    IF FOUND THEN
      IF prior.action<>'INTAKE_'||action OR prior.input<>payload THEN RAISE EXCEPTION 'Request key changed' USING ERRCODE='23514'; END IF;
      RETURN prior.output;
    END IF;
  END IF;
  IF src IS NULL OR src NOT IN ('OFFICIAL','FORM_EXPORT') OR kind_code IS NULL OR kind_code NOT IN ('STUDENT','FACULTY')
    OR (src='FORM_EXPORT' AND kind_code<>'STUDENT') THEN RAISE EXCEPTION 'Supported record source required' USING ERRCODE='22023'; END IF;
  IF action IN ('PREVIEW','APPLY') THEN
    IF jsonb_typeof(input->'records') IS DISTINCT FROM 'array' OR jsonb_array_length(input->'records') NOT BETWEEN 1 AND 200 THEN
      RAISE EXCEPTION 'Upload one to 200 mapped records' USING ERRCODE='22023';
    END IF;
    SELECT coalesce(jsonb_agg(jsonb_build_object('row',n,'message',problem) ORDER BY n),'[]') INTO issues FROM (
      SELECT n,CASE
        WHEN r->>'department' IS DISTINCT FROM dept_code THEN 'Department does not match this workspace'
        WHEN nullif(r->>'key','') IS NULL OR nullif(r->>'name','') IS NULL THEN 'Identity reference and name are required'
        WHEN kind_code='STUDENT' AND (nullif(r->>'usn','') IS NULL OR nullif(r->>'semester','') IS NULL OR nullif(r->>'section','') IS NULL)
          THEN 'USN, semester and section are required'
        WHEN count(*) OVER(PARTITION BY r->>'key')>1 THEN 'Duplicate identity reference in file'
        WHEN kind_code='STUDENT' AND count(*) OVER(PARTITION BY r->>'usn')>1 THEN 'Duplicate USN in file'
        WHEN kind_code='STUDENT' AND EXISTS(SELECT FROM public.department_intake_records old
          WHERE old.department_id=dept AND old.kind='STUDENT' AND old.source=src AND
            ((old.identity_key=r->>'key' AND old.record->>'usn' IS DISTINCT FROM r->>'usn')
              OR (old.identity_key<>r->>'key' AND old.record->>'usn'=r->>'usn')))
          THEN 'USN conflicts with an existing identity reference'
        WHEN kind_code='STUDENT' AND EXISTS(SELECT FROM public.student_profiles s WHERE s.usn=r->>'usn' AND s.department_id<>dept)
          THEN 'USN belongs to another department'
      END AS problem
      FROM jsonb_array_elements(input->'records') WITH ORDINALITY AS rows(r,n)
    ) checked WHERE problem IS NOT NULL;
    IF action='PREVIEW' OR jsonb_array_length(issues)>0 THEN
      RETURN jsonb_build_object('issues',issues,'count',jsonb_array_length(input->'records'));
    END IF;
    IF input->'confirmed' IS DISTINCT FROM 'true'::jsonb OR nullif(btrim(input->>'reference'),'') IS NULL THEN
      RAISE EXCEPTION 'Verify the source and record its reference' USING ERRCODE='22023';
    END IF;
    SELECT id INTO batch FROM public.department_intake_batches WHERE department_id=dept AND source=src AND kind=kind_code
      AND reference=input->>'reference' AND records=input->'records' ORDER BY created_at DESC LIMIT 1;
    IF NOT FOUND THEN
      INSERT INTO public.department_intake_batches(department_id,actor_id,source,kind,reference,records)
        VALUES(dept,actor,src,kind_code,input->>'reference',input->'records') RETURNING id INTO batch;
      INSERT INTO public.department_intake_records(department_id,source,kind,identity_key,batch_id,record)
        SELECT dept,src,kind_code,r->>'key',batch,r FROM jsonb_array_elements(input->'records') r
        ON CONFLICT(department_id,source,kind,identity_key) DO UPDATE SET batch_id=excluded.batch_id,record=excluded.record;
    END IF;
    result:=jsonb_build_object('batchId',batch,'issues','[]'::jsonb);
  ELSIF action='RECONCILE' THEN
    SELECT * INTO previous FROM public.department_intake_records WHERE department_id=dept AND source=src AND kind=kind_code
      AND identity_key=input->>'identityKey' FOR UPDATE;
    target:=(input->>'userId')::uuid;
    IF NOT FOUND OR previous.batch_id IS DISTINCT FROM (input->>'expectedBatchId')::uuid
      OR input->'confirmed' IS DISTINCT FROM 'true'::jsonb OR previous.linked_user_id IS NOT NULL
      AND previous.linked_user_id<>target THEN RAISE EXCEPTION 'Verify an unchanged intake identity' USING ERRCODE='23514'; END IF;
    stamp:=clock_timestamp();
    IF NOT public.smartpro_has_role(target,dept,kind_code,stamp) THEN
      RAISE EXCEPTION 'Existing verified departmental account required' USING ERRCODE='42501';
    END IF;
    IF kind_code='STUDENT' THEN
      PERFORM 1 FROM public.student_profiles WHERE user_id=target AND department_id=dept
        AND usn=previous.record->>'usn' AND semester_key=previous.record->>'semester' FOR UPDATE;
      IF NOT FOUND THEN RAISE EXCEPTION 'Verified USN and semester must match the existing profile' USING ERRCODE='23514'; END IF;
      IF src='OFFICIAL' THEN UPDATE public.student_profiles SET section=previous.record->>'section' WHERE user_id=target; END IF;
    END IF;
    UPDATE public.department_intake_records SET linked_user_id=target WHERE department_id=dept AND source=src
      AND kind=kind_code AND identity_key=previous.identity_key;
    batch:=previous.batch_id;
    result:=jsonb_build_object('batchId',batch,'linked',true);
  ELSE RAISE EXCEPTION 'Supported intake action required' USING ERRCODE='22023'; END IF;
  IF NOT EXISTS(SELECT FROM public.department_role_assignments WHERE id=scope_role
      AND (valid_until IS NULL OR clock_timestamp()<valid_until)) THEN
    RAISE EXCEPTION 'Department Admin appointment expired' USING ERRCODE='42501';
  END IF;
  INSERT INTO public.document_command_receipts VALUES(actor,key,'INTAKE_'||action,payload,result);
  INSERT INTO public.audit_events(actor_id,action,target_type,target_id,metadata)
    VALUES(actor,'INTAKE_'||action,'DEPARTMENT_INTAKE',batch,
      jsonb_build_object('departmentId',dept,'adminRoleId',scope_role,'source',src,'kind',kind_code,'linkedUserId',target));
  RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_department_intake(uuid,uuid,text,jsonb,text) FROM PUBLIC,smartpro_runtime;
GRANT EXECUTE ON FUNCTION public.smartpro_department_intake(uuid,uuid,text,jsonb,text) TO smartpro_runtime;
COMMIT;
