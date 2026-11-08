-- Paginate immutable leadership terms independently of current appointment controls.
BEGIN;
CREATE FUNCTION public.smartpro_department_leadership_history(
  actor uuid,dept uuid,acting_role text,search_text text,page_number integer
) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE leadership jsonb;
BEGIN
  IF acting_role IS DISTINCT FROM 'Admin' AND acting_role IS DISTINCT FROM 'HOD' THEN
    RAISE EXCEPTION 'Current department leadership required' USING ERRCODE='42501';
  END IF;
  leadership:=public.smartpro_department_leadership(actor,dept,acting_role);
  IF search_text IS NULL OR length(search_text)>120
    OR page_number IS NULL OR page_number NOT BETWEEN 1 AND 99999999 THEN
    RAISE EXCEPTION 'Invalid leadership history filters' USING ERRCODE='22023';
  END IF;
  RETURN leadership || (
    WITH terms AS (
      SELECT r.id,r.user_id,u.display_name,r.role_code,r.valid_from,r.valid_until,
        r.valid_from<=statement_timestamp() AND (r.valid_until IS NULL OR statement_timestamp()<r.valid_until) AS active
      FROM public.department_role_assignments r JOIN public.users u ON u.id=r.user_id
      WHERE r.department_id=dept AND r.role_code IN ('HOD','ACADEMIC_ADMIN')
    ), matching AS (
      SELECT * FROM terms WHERE search_text='' OR strpos(lower(display_name),lower(search_text))>0
    ), paged AS (
      SELECT * FROM matching ORDER BY valid_from DESC,id DESC LIMIT 25 OFFSET (page_number::bigint-1)*25
    ), attributed AS (
      SELECT p.*,(SELECT a.display_name FROM public.audit_events event JOIN public.users a ON a.id=event.actor_id
        WHERE event.target_type='DEPARTMENT_ROLE' AND event.target_id=p.id
          AND event.action IN ('DEPARTMENT_APPOINT_ADMIN','DEPARTMENT_REPLACE_ADMIN','DEPARTMENT_APPOINT_HOD')
        ORDER BY event.occurred_at LIMIT 1) AS appointed_by
      FROM paged p
    )
    SELECT jsonb_build_object('historyPage',page_number,'historyTotal',(SELECT count(*) FROM matching),
      'appointments',(SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY valid_from DESC,id DESC),'[]') FROM terms t WHERE active),
      'history',(SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY valid_from DESC,id DESC),'[]') FROM attributed t))
  );
END $$;
REVOKE ALL ON FUNCTION public.smartpro_department_leadership_history(uuid,uuid,text,text,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_department_leadership_history(uuid,uuid,text,text,integer) TO smartpro_runtime;
COMMIT;
