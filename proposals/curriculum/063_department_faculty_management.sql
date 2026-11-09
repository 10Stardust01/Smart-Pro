-- Candidate 063: scoped non-HOD faculty details and Faculty term management.
-- Read/write metadata is departmental; global users and academic results unchanged.
BEGIN;
DO $$ BEGIN
 IF to_regprocedure('public.smartpro_department_record(uuid,uuid,uuid)') IS NULL
 THEN RAISE EXCEPTION 'Candidate 057 required'; END IF;
 IF to_regprocedure('public.smartpro_faculty_manage(uuid,uuid,uuid,text,jsonb,text)') IS NOT NULL
 THEN RAISE EXCEPTION 'Candidate 063 already installed'; END IF;
END $$;
CREATE TABLE public.department_faculty_details(
 department_id uuid REFERENCES public.departments(id) NOT NULL,
 faculty_id uuid REFERENCES public.users(id) NOT NULL,
 display_name text NOT NULL,
 designation text NOT NULL DEFAULT '',
 contact_email text NOT NULL DEFAULT '',
 revision integer NOT NULL DEFAULT 1 CHECK(revision>0),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(department_id,faculty_id),
 CHECK(length(display_name) BETWEEN 2 AND 120),
 CHECK(length(designation)<=120 AND length(contact_email)<=254)
);
REVOKE ALL ON TABLE public.department_faculty_details FROM PUBLIC,smartpro_runtime;

CREATE FUNCTION public.smartpro_faculty_manage_read(actor uuid,dept uuid,person uuid)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE result jsonb;
BEGIN
 PERFORM public.smartpro_department_intake_code(actor,dept);
 IF NOT EXISTS(SELECT 1 FROM public.department_role_assignments
       WHERE user_id=person AND department_id=dept AND role_code='FACULTY')
 THEN RAISE EXCEPTION 'Department faculty record required' USING ERRCODE='42501'; END IF;
 SELECT jsonb_build_object(
   'details',jsonb_build_object(
     'displayName',coalesce(d.display_name,u.display_name),
     'designation',coalesce(d.designation,''),
     'contactEmail',coalesce(d.contact_email,''),
     'revision',coalesce(d.revision,0)),
   'accountStatus',u.account_status,
   'canManage',person<>actor AND NOT EXISTS(
      SELECT 1 FROM public.department_role_assignments h
      WHERE h.user_id=person AND h.department_id=dept AND h.role_code='HOD'
        AND h.valid_from<=statement_timestamp()
        AND (h.valid_until IS NULL OR statement_timestamp()<h.valid_until)),
   'terms',(SELECT coalesce(jsonb_agg(to_jsonb(z) ORDER BY z.valid_from DESC,z.id),'[]'::jsonb)
    FROM (SELECT r.id,r.valid_from,r.valid_until,r.staff_authority_revision,
      r.valid_from<=statement_timestamp() AND
        (r.valid_until IS NULL OR statement_timestamp()<r.valid_until) AND
        u.account_status='ACTIVE' AS active
      FROM public.department_role_assignments r
      WHERE r.user_id=person AND r.department_id=dept AND r.role_code='FACULTY'
      ORDER BY r.valid_from DESC,r.id DESC LIMIT 25) z))
 INTO result FROM public.users u LEFT JOIN public.department_faculty_details d
   ON d.department_id=dept AND d.faculty_id=u.id WHERE u.id=person;
 RETURN result;
END $$;

CREATE FUNCTION public.smartpro_faculty_manage(
 actor uuid,dept uuid,person uuid,operation text,input jsonb,request_key text)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE current_term public.department_role_assignments%ROWTYPE;
 old_receipt public.document_command_receipts%ROWTYPE;
 old_record jsonb;new_record jsonb;outcome jsonb;
 actor_action text:='FACULTY_MANAGE_'||operation;
 fingerprint jsonb:=jsonb_build_object('department',dept,'person',person,'input',input);
 stamp timestamptz; new_expiry timestamptz;
 busy boolean;old_rev integer;
BEGIN
 IF operation NOT IN ('EDIT_DETAILS','AMEND_TERM','TERMINATE','REINSTATE')
 THEN RAISE EXCEPTION 'Unknown faculty management operation' USING ERRCODE='22023'; END IF;
 PERFORM 1 FROM public.academic_governance_settings
   WHERE department_id=dept AND enabled FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Department governance disabled' USING ERRCODE='42501'; END IF;
 PERFORM public.smartpro_department_intake_code(actor,dept);
 stamp:=clock_timestamp();
 IF actor=person THEN RAISE EXCEPTION 'Self-management forbidden' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.users WHERE id=person FOR UPDATE;
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM public.department_role_assignments
   WHERE department_id=dept AND user_id=person AND role_code='FACULTY')
 THEN RAISE EXCEPTION 'Department faculty record required' USING ERRCODE='42501'; END IF;
 IF EXISTS(SELECT 1 FROM public.department_role_assignments
   WHERE user_id=person AND department_id=dept AND role_code='HOD'
   AND valid_from<=stamp AND (valid_until IS NULL OR stamp<valid_until))
 THEN RAISE EXCEPTION 'HOD management is outside Admin faculty authority' USING ERRCODE='42501'; END IF;
 IF input IS NULL OR jsonb_typeof(input)<>'object'
   OR coalesce(length(btrim(input->>'reason')),0) NOT BETWEEN 1 AND 500
 THEN RAISE EXCEPTION 'Reason required for faculty history' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(actor::text||':faculty:'||request_key,0));
 SELECT * INTO old_receipt FROM public.document_command_receipts
   WHERE actor_id=actor AND document_command_receipts.request_key=smartpro_faculty_manage.request_key;
 IF FOUND THEN
  IF old_receipt.action<>actor_action OR old_receipt.input<>fingerprint
  THEN RAISE EXCEPTION 'Changed idempotency request' USING ERRCODE='23514'; END IF;
  RETURN old_receipt.output;
 END IF;
 old_record:=public.smartpro_faculty_manage_read(actor,dept,person);
 SELECT * INTO current_term FROM public.department_role_assignments
   WHERE user_id=person AND department_id=dept AND role_code='FACULTY'
   AND valid_from<=stamp AND (valid_until IS NULL OR stamp<valid_until)
   ORDER BY valid_from DESC,id DESC LIMIT 1 FOR UPDATE;
 IF operation='EDIT_DETAILS' THEN
   IF coalesce(length(btrim(input->>'displayName')),0) NOT BETWEEN 2 AND 120
      OR length(coalesce(input->>'designation',''))>120
      OR length(coalesce(input->>'contactEmail',''))>254
   THEN RAISE EXCEPTION 'Valid department faculty details required' USING ERRCODE='22023'; END IF;
   old_rev:=(old_record->'details'->>'revision')::integer;
   IF (input->>'expectedRevision')::integer IS DISTINCT FROM old_rev
   THEN RAISE EXCEPTION 'Details changed; refresh' USING ERRCODE='23514'; END IF;
   IF old_rev=0 THEN
     INSERT INTO public.department_faculty_details
       (department_id,faculty_id,display_name,designation,contact_email)
     VALUES(dept,person,btrim(input->>'displayName'),
       btrim(coalesce(input->>'designation','')),btrim(coalesce(input->>'contactEmail','')));
   ELSE
     UPDATE public.department_faculty_details
       SET display_name=btrim(input->>'displayName'),
           designation=btrim(coalesce(input->>'designation','')),
           contact_email=btrim(coalesce(input->>'contactEmail','')),
           revision=revision+1,updated_at=clock_timestamp()
     WHERE department_id=dept AND faculty_id=person AND revision=old_rev;
     IF NOT FOUND THEN RAISE EXCEPTION 'Details changed; refresh' USING ERRCODE='23514'; END IF;
   END IF;
 ELSIF operation IN ('AMEND_TERM','TERMINATE') THEN
   IF current_term.id IS NULL
     OR current_term.id IS DISTINCT FROM (input->>'termId')::uuid
     OR current_term.staff_authority_revision IS DISTINCT FROM (input->>'expectedAuthorityRevision')::uuid
   THEN RAISE EXCEPTION 'Faculty term changed; refresh' USING ERRCODE='23514'; END IF;
   new_expiry:=CASE WHEN operation='TERMINATE' THEN stamp
                    ELSE (input->>'validUntil')::timestamptz END;
   IF new_expiry IS NULL OR new_expiry<=current_term.valid_from
     OR (operation='AMEND_TERM' AND new_expiry<=stamp)
   THEN RAISE EXCEPTION 'Invalid new term end' USING ERRCODE='22023'; END IF;
   -- Do not strand an active academic assignment or silently restore one later.
   SELECT EXISTS(SELECT 1 FROM public.faculty_assignments a
       JOIN public.projects p ON p.id=a.project_id
       WHERE p.department_id=dept AND a.faculty_user_id=person
         AND a.valid_from<=stamp AND (a.valid_until IS NULL OR stamp<a.valid_until))
      OR EXISTS(SELECT 1 FROM public.curriculum_offerings o
        CROSS JOIN LATERAL public.smartpro_course_coordinators(o.id) c
        WHERE o.department_id=dept AND c.user_id=person)
   INTO busy;
   IF busy AND (operation='TERMINATE' OR current_term.valid_until IS NULL
                OR new_expiry<current_term.valid_until)
   THEN RAISE EXCEPTION 'Reassign active project/Coordinator duties before ending or shortening this Faculty term'
      USING ERRCODE='23514'; END IF;
   UPDATE public.department_role_assignments SET valid_until=new_expiry,
     staff_authority_revision=gen_random_uuid() WHERE id=current_term.id;
 ELSE
   IF current_term.id IS NOT NULL THEN
     RAISE EXCEPTION 'Faculty term already effective' USING ERRCODE='23514'; END IF;
   IF NOT EXISTS(SELECT 1 FROM public.users WHERE id=person AND account_status='ACTIVE')
   THEN RAISE EXCEPTION 'Disabled global identity requires institutional recovery' USING ERRCODE='23514'; END IF;
   IF EXISTS(SELECT 1 FROM public.department_role_assignments
     WHERE department_id=dept AND user_id=person AND role_code='FACULTY'
       AND (valid_until IS NULL OR valid_from>stamp))
   THEN RAISE EXCEPTION 'Unresolved future faculty term' USING ERRCODE='23514'; END IF;
   IF EXISTS(SELECT 1 FROM public.faculty_assignments a JOIN public.projects p ON p.id=a.project_id
        WHERE p.department_id=dept AND a.faculty_user_id=person AND a.valid_until IS NULL)
       OR EXISTS(SELECT 1 FROM public.course_coordinator_versions v
         JOIN public.curriculum_offerings o ON o.id=v.offering_id
         WHERE o.department_id=dept AND v.user_id=person AND v.active AND v.valid_until>stamp
           AND v.id=(SELECT z.id FROM public.course_coordinator_versions z
             WHERE z.offering_id=v.offering_id AND z.user_id=person
             ORDER BY z.version DESC LIMIT 1))
   THEN RAISE EXCEPTION 'Close previous project/Coordinator appointments before reinstatement'
     USING ERRCODE='23514'; END IF;
   INSERT INTO public.department_role_assignments(user_id,department_id,role_code,valid_from)
     VALUES(person,dept,'FACULTY',stamp);
 END IF;
 new_record:=public.smartpro_faculty_manage_read(actor,dept,person);
 outcome:=jsonb_build_object('operation',operation,'record',new_record);
 INSERT INTO public.document_command_receipts(actor_id,request_key,action,input,output)
 VALUES(actor,request_key,actor_action,fingerprint,outcome);
 INSERT INTO public.audit_events(actor_id,action,target_type,target_id,metadata)
 VALUES(actor,actor_action,'FACULTY_RECORD',person,jsonb_build_object(
   'departmentId',dept,'reason',input->>'reason','before',old_record,'after',new_record));
 RETURN outcome;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_faculty_manage_read(uuid,uuid,uuid),
 public.smartpro_faculty_manage(uuid,uuid,uuid,text,jsonb,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_faculty_manage_read(uuid,uuid,uuid),
 public.smartpro_faculty_manage(uuid,uuid,uuid,text,jsonb,text) TO smartpro_runtime;
COMMIT;
