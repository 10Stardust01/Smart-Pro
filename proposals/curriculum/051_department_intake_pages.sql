-- Scoped, read-only pages over the existing intake and immutable import batches.
BEGIN;
DO $$
BEGIN
  IF to_regprocedure('public.smartpro_department_intake(uuid,uuid,text,jsonb,text)') IS NULL THEN
    RAISE EXCEPTION 'Department intake candidate 047 is required';
  END IF;
END $$;
CREATE INDEX department_intake_batch_page ON public.department_intake_batches(department_id,created_at DESC,id DESC);
CREATE FUNCTION public.smartpro_department_intake_code(actor uuid,dept uuid) RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF NOT public.smartpro_has_role(actor,dept,'ACADEMIC_ADMIN',statement_timestamp())
    OR NOT EXISTS(SELECT FROM public.users WHERE id=actor AND account_status='ACTIVE')
    OR NOT EXISTS(SELECT FROM public.staff_department_controls WHERE department_id=dept AND enabled) THEN
    RAISE EXCEPTION 'Current Department Admin required' USING ERRCODE='42501';
  END IF;
  RETURN (SELECT code FROM public.departments WHERE id=dept);
END $$;
REVOKE ALL ON FUNCTION public.smartpro_department_intake_code(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_department_intake_code(uuid,uuid) TO smartpro_runtime;
CREATE FUNCTION public.smartpro_department_intake_page(
  actor uuid,dept uuid,record_kind text,search_text text,record_page integer,batch_page integer
) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  PERFORM public.smartpro_department_intake_code(actor,dept);
  IF record_kind IS NULL OR record_kind NOT IN ('STUDENT','FACULTY')
    OR search_text IS NULL OR length(search_text)>120
    OR record_page IS NULL OR record_page NOT BETWEEN 1 AND 99999999
    OR batch_page IS NULL OR batch_page NOT BETWEEN 1 AND 99999999 THEN
    RAISE EXCEPTION 'Invalid department records filters' USING ERRCODE='22023';
  END IF;
  RETURN (
    WITH matching AS (
      SELECT source,kind,identity_key,batch_id,record,linked_user_id
      FROM public.department_intake_records
      WHERE department_id=dept AND kind=record_kind AND (
        search_text='' OR strpos(lower(record->>'name'),lower(search_text))>0
        OR strpos(lower(identity_key),lower(search_text))>0
        OR strpos(lower(record->>'usn'),lower(search_text))>0
      )
    ), records AS (
      SELECT * FROM matching ORDER BY lower(record->>'name'),source,identity_key
      LIMIT 25 OFFSET (record_page::bigint-1)*25
    ), batches AS (
      SELECT b.id,b.source,b.kind,b.reference,b.created_at,jsonb_array_length(b.records) AS count,u.display_name AS actor_name
      FROM public.department_intake_batches b JOIN public.users u ON u.id=b.actor_id
      WHERE b.department_id=dept ORDER BY b.created_at DESC,b.id DESC
      LIMIT 25 OFFSET (batch_page::bigint-1)*25
    )
    SELECT jsonb_build_object(
      'page',record_page,'batchPage',batch_page,'recordCount',(SELECT count(*) FROM matching),
      'batchCount',(SELECT count(*) FROM public.department_intake_batches WHERE department_id=dept),
      'records',(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY lower(r.record->>'name'),r.source,r.identity_key),'[]') FROM records r),
      'batches',(SELECT coalesce(jsonb_agg(to_jsonb(b) ORDER BY b.created_at DESC,b.id DESC),'[]') FROM batches b)
    )
  );
END $$;
REVOKE ALL ON FUNCTION public.smartpro_department_intake_page(uuid,uuid,text,text,integer,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_department_intake_page(uuid,uuid,text,text,integer,integer) TO smartpro_runtime;
COMMIT;
