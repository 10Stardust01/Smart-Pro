-- Crosswalk assertions are evidence only. Authentication and academic grants use existing identities.
BEGIN;
CREATE TABLE public.faculty_identity_links (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  department_id uuid NOT NULL REFERENCES public.departments(id),
  faculty_id uuid NOT NULL REFERENCES public.users(id),
  directory_ref text NOT NULL,
  identifier_source text NOT NULL,
  external_identifier text NOT NULL,
  evidence text NOT NULL,
  state text NOT NULL DEFAULT 'PROPOSED' CHECK(state IN ('PROPOSED','VERIFIED','REJECTED','REVOKED')),
  proposed_by uuid NOT NULL REFERENCES public.users(id),
  proposed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE UNIQUE INDEX faculty_identity_verified_identifier ON public.faculty_identity_links(department_id,identifier_source,external_identifier) WHERE state='VERIFIED';
CREATE UNIQUE INDEX faculty_identity_verified_directory ON public.faculty_identity_links(department_id,directory_ref) WHERE state='VERIFIED';
CREATE UNIQUE INDEX faculty_identity_verified_person ON public.faculty_identity_links(department_id,faculty_id) WHERE state='VERIFIED';
CREATE INDEX faculty_identity_by_person ON public.faculty_identity_links(department_id,faculty_id,proposed_at DESC);
REVOKE ALL ON public.faculty_identity_links FROM PUBLIC,smartpro_runtime;

CREATE FUNCTION public.smartpro_department_record(actor uuid,dept uuid,person uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  PERFORM public.smartpro_department_intake_code(actor,dept);
  IF NOT EXISTS(SELECT FROM public.student_profiles WHERE user_id=person AND department_id=dept)
    AND NOT EXISTS(SELECT FROM public.department_role_assignments WHERE user_id=person AND department_id=dept AND role_code='FACULTY') THEN
    RAISE EXCEPTION 'Department record required' USING ERRCODE='42501';
  END IF;
  RETURN (
    SELECT jsonb_build_object('name',u.display_name,'status',u.account_status,
      'student',(SELECT jsonb_build_object('usn',s.usn,'semester',s.semester_key,'section',s.section)
        FROM public.student_profiles s WHERE s.user_id=person AND s.department_id=dept),
      'faculty',EXISTS(SELECT FROM public.department_role_assignments WHERE user_id=person AND department_id=dept AND role_code='FACULTY'),
      'links',(SELECT coalesce(jsonb_agg(to_jsonb(l) ORDER BY l.proposed_at DESC),'[]') FROM public.faculty_identity_links l
        WHERE l.department_id=dept AND l.faculty_id=person),
      'imports',(SELECT coalesce(jsonb_agg(to_jsonb(b) ORDER BY b.created_at DESC),'[]') FROM (
        SELECT b.reference,b.created_at,a.display_name AS actor,b.source,b.kind
        FROM public.department_intake_batches b JOIN public.users a ON a.id=b.actor_id
        WHERE b.department_id=dept AND EXISTS(SELECT FROM public.department_intake_records r
          WHERE r.department_id=dept AND r.linked_user_id=person AND r.kind=b.kind AND r.source=b.source
            AND b.records @> jsonb_build_array(jsonb_build_object('key',r.identity_key)))
      ) b),
      'history',(SELECT coalesce(jsonb_agg(to_jsonb(h) ORDER BY h.occurred_at DESC),'[]') FROM (
        SELECT e.action,e.occurred_at,a.display_name AS actor,e.metadata->>'evidenceReference' AS evidence
        FROM public.audit_events e LEFT JOIN public.users a ON a.id=e.actor_id
        WHERE (e.action='INTAKE_RECONCILE' AND e.metadata->>'departmentId'=dept::text AND e.metadata->>'linkedUserId'=person::text)
           OR (e.target_type='FACULTY_IDENTITY_LINK' AND EXISTS(SELECT FROM public.faculty_identity_links l
                WHERE l.id=e.target_id AND l.department_id=dept AND l.faculty_id=person))
        UNION ALL
        SELECT CASE r.kind WHEN 'STUDENT_PROFILE' THEN 'STUDENT_PROFILE_CONFIGURED' ELSE 'FACULTY_ACCESS_CONFIGURED' END,
          x.configured_at,a.display_name,NULL::text
        FROM public.department_setup_requests r JOIN public.department_setup_executions x ON x.request_id=r.id
        JOIN public.users a ON a.id=x.configured_by
        WHERE r.department_id=dept AND r.kind IN ('STUDENT_PROFILE','FACULTY_ACCESS') AND r.configuration->>'userId'=person::text
      ) h))
    FROM public.users u WHERE u.id=person
  );
END $$;

CREATE FUNCTION public.smartpro_faculty_identity_command(actor uuid,dept uuid,operation text,person uuid,input jsonb,request_key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE link public.faculty_identity_links%ROWTYPE; next_state text; prior public.document_command_receipts%ROWTYPE;
  payload jsonb:=jsonb_build_object('department',dept,'person',person,'input',input);
  result jsonb; reused boolean:=false; event text:='FACULTY_IDENTITY_'||operation;
BEGIN
  PERFORM 1 FROM public.academic_governance_settings WHERE department_id=dept AND enabled FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Department reconciliation is disabled' USING ERRCODE='42501'; END IF;
  PERFORM public.smartpro_department_intake_code(actor,dept);
  IF operation IN ('PROPOSE','VERIFY') AND NOT public.smartpro_has_role(person,dept,'FACULTY',clock_timestamp()) THEN
    RAISE EXCEPTION 'Effective faculty record required' USING ERRCODE='42501';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(actor::text||':faculty-crosswalk:'||request_key,0));
  SELECT * INTO prior FROM public.document_command_receipts WHERE actor_id=actor AND document_command_receipts.request_key=smartpro_faculty_identity_command.request_key;
  IF FOUND THEN
    IF prior.action<>event OR prior.input<>payload THEN RAISE EXCEPTION 'Request key changed' USING ERRCODE='23514'; END IF;
    RETURN prior.output;
  END IF;
  IF coalesce(length(btrim(input->>'evidence')),0) NOT BETWEEN 1 AND 500 THEN
    RAISE EXCEPTION 'Identity verification evidence required' USING ERRCODE='22023';
  END IF;
  IF operation='PROPOSE' THEN
    IF coalesce(length(btrim(input->>'directoryRef')),0) NOT BETWEEN 1 AND 200
      OR coalesce(length(btrim(input->>'source')),0) NOT BETWEEN 1 AND 120
      OR coalesce(length(btrim(input->>'identifier')),0) NOT BETWEEN 1 AND 120 THEN
      RAISE EXCEPTION 'Institutional source and identifier required' USING ERRCODE='22023';
    END IF;
    SELECT * INTO link FROM public.faculty_identity_links WHERE department_id=dept AND faculty_id=person
      AND directory_ref=input->>'directoryRef' AND identifier_source=lower(btrim(input->>'source'))
      AND external_identifier=btrim(input->>'identifier') AND state IN ('PROPOSED','VERIFIED');
    reused:=FOUND;
    IF NOT reused THEN
    INSERT INTO public.faculty_identity_links(department_id,faculty_id,directory_ref,identifier_source,external_identifier,evidence,proposed_by)
      VALUES(dept,person,input->>'directoryRef',lower(btrim(input->>'source')),btrim(input->>'identifier'),input->>'evidence',actor)
      RETURNING * INTO link;
    END IF;
  ELSE
    SELECT * INTO link FROM public.faculty_identity_links WHERE id=(input->>'linkId')::uuid AND department_id=dept AND faculty_id=person FOR UPDATE;
    next_state:=CASE WHEN link.state='PROPOSED' AND operation='VERIFY' THEN 'VERIFIED'
                     WHEN link.state='PROPOSED' AND operation='REJECT' THEN 'REJECTED'
                     WHEN link.state='VERIFIED' AND operation='REVOKE' THEN 'REVOKED' END;
    IF next_state IS NULL THEN RAISE EXCEPTION 'Identity link state changed' USING ERRCODE='23514'; END IF;
    UPDATE public.faculty_identity_links SET state=next_state WHERE id=link.id RETURNING * INTO link;
  END IF;
  result:=to_jsonb(link);
  INSERT INTO public.document_command_receipts VALUES(actor,request_key,event,payload,result);
  IF NOT reused THEN
  INSERT INTO public.audit_events(actor_id,action,target_type,target_id,metadata)
    VALUES(actor,event,'FACULTY_IDENTITY_LINK',link.id,jsonb_build_object('evidenceReference',input->>'evidence','state',link.state));
  END IF;
  RETURN result;
END $$;

CREATE FUNCTION public.smartpro_appointment_candidates(actor uuid,dept uuid,acting_role text,q text,p integer) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF acting_role='Admin' THEN PERFORM public.smartpro_department_intake_code(actor,dept);
  ELSIF acting_role='HOD' THEN PERFORM public.smartpro_academic_authority(actor,dept,true);
  ELSE RAISE EXCEPTION 'Department leadership required' USING ERRCODE='42501'; END IF;
  IF q IS NULL OR length(q)>120 OR p IS NULL OR p NOT BETWEEN 1 AND 99999999 THEN
    RAISE EXCEPTION 'Invalid candidate filters' USING ERRCODE='22023';
  END IF;
  RETURN (
    WITH matches AS (
      SELECT u.id,u.display_name FROM public.users u WHERE u.account_status='ACTIVE'
        AND strpos(lower(u.display_name),lower(q))>0
        AND EXISTS(SELECT FROM public.department_role_assignments r WHERE r.user_id=u.id AND r.department_id=dept
          AND r.role_code='FACULTY' AND r.valid_from<=statement_timestamp()
          AND (r.valid_until IS NULL OR r.valid_until>statement_timestamp()))
    ), paged AS (
      SELECT * FROM matches ORDER BY lower(display_name),id LIMIT 25 OFFSET (p::bigint-1)*25
    )
    SELECT jsonb_build_object('page',p,'total',(SELECT count(*) FROM matches),
      'records',(SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY lower(x.display_name),x.id),'[]') FROM paged x))
  );
END $$;
REVOKE ALL ON FUNCTION public.smartpro_department_record(uuid,uuid,uuid),public.smartpro_faculty_identity_command(uuid,uuid,text,uuid,jsonb,text),public.smartpro_appointment_candidates(uuid,uuid,text,text,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_department_record(uuid,uuid,uuid),public.smartpro_faculty_identity_command(uuid,uuid,text,uuid,jsonb,text),public.smartpro_appointment_candidates(uuid,uuid,text,text,integer) TO smartpro_runtime;
COMMIT;
