-- Department directory reads use academic records and effective appointments.
BEGIN;
DO $$
BEGIN
  IF to_regprocedure('public.smartpro_department_intake_code(uuid,uuid)') IS NULL THEN
    RAISE EXCEPTION 'Department intake paging candidate 051 is required';
  END IF;
END $$;
CREATE INDEX student_profiles_department_directory ON public.student_profiles(department_id,user_id);
CREATE INDEX department_intake_linked_directory ON public.department_intake_records(department_id,linked_user_id,kind)
  WHERE linked_user_id IS NOT NULL;
CREATE FUNCTION public.smartpro_department_directory_page(
  actor uuid,dept uuid,record_kind text,search_text text,page_number integer
) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  PERFORM public.smartpro_department_intake_code(actor,dept);
  IF record_kind IS NULL OR record_kind NOT IN ('STUDENT','FACULTY')
     OR search_text IS NULL OR length(search_text)>120
     OR page_number IS NULL OR page_number NOT BETWEEN 1 AND 99999999 THEN
    RAISE EXCEPTION 'Invalid directory filters' USING ERRCODE='22023';
  END IF;
  RETURN (
    WITH people AS (
      SELECT u.id,u.display_name,u.account_status,s.usn,s.semester_key,s.section
      FROM public.student_profiles s JOIN public.users u ON u.id=s.user_id
      WHERE record_kind='STUDENT' AND s.department_id=dept
      UNION ALL
      SELECT u.id,u.display_name,u.account_status,NULL,NULL,NULL
      FROM public.users u
      JOIN (
        SELECT DISTINCT user_id FROM public.department_role_assignments
        WHERE record_kind='FACULTY' AND department_id=dept AND role_code='FACULTY'
          AND valid_from<=statement_timestamp()
          AND (valid_until IS NULL OR statement_timestamp()<valid_until)
      ) f ON f.user_id=u.id
    ), matching AS (
      SELECT * FROM people WHERE search_text=''
        OR strpos(lower(display_name),lower(search_text))>0
        OR strpos(lower(usn),lower(search_text))>0
        OR EXISTS(SELECT FROM public.department_intake_records r
          WHERE r.department_id=dept AND r.linked_user_id=people.id AND r.kind=record_kind
            AND strpos(lower(r.identity_key),lower(search_text))>0)
    ), paged AS (
      SELECT * FROM matching ORDER BY lower(display_name),id
      LIMIT 25 OFFSET (page_number::bigint-1)*25
    )
    SELECT jsonb_build_object('page',page_number,'total',(SELECT count(*) FROM matching),
      'records',(SELECT coalesce(jsonb_agg(to_jsonb(p)||jsonb_build_object(
        'officiallyLinked',EXISTS(SELECT FROM public.department_intake_records r
          WHERE r.department_id=dept AND r.linked_user_id=p.id AND r.kind=record_kind AND r.source='OFFICIAL')
      ) ORDER BY lower(p.display_name),p.id),'[]') FROM paged p))
  );
END $$;
REVOKE ALL ON FUNCTION public.smartpro_department_directory_page(uuid,uuid,text,text,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_department_directory_page(uuid,uuid,text,text,integer) TO smartpro_runtime;
COMMIT;
