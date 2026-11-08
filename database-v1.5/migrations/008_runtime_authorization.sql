BEGIN;
-- SELECT row locking requires UPDATE rights. Encapsulate only the authorization
-- lookup/locks rather than giving the synopsis role identity/membership edits.
CREATE FUNCTION smartpro_project_permission(pid uuid,actor uuid,permission_name text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF permission_name='student' THEN
    PERFORM m.id FROM projects p JOIN team_memberships m ON m.team_id=p.team_id
      JOIN department_role_assignments r ON r.department_id=p.department_id AND r.user_id=m.user_id
      JOIN users u ON u.id=m.user_id WHERE p.id=pid AND m.user_id=actor AND r.role_code='STUDENT'
      AND m.joined_at<=statement_timestamp() AND (m.left_at IS NULL OR statement_timestamp()<m.left_at)
      AND r.valid_from<=statement_timestamp() AND (r.valid_until IS NULL OR statement_timestamp()<r.valid_until)
      AND u.account_status='ACTIVE' LIMIT 1 FOR SHARE OF m,r,u;
  ELSIF permission_name='reviewer' THEN
    PERFORM f.id FROM projects p JOIN faculty_assignments f ON f.project_id=p.id
      JOIN department_role_assignments r ON r.department_id=p.department_id AND r.user_id=f.faculty_user_id
      JOIN users u ON u.id=f.faculty_user_id WHERE p.id=pid AND f.faculty_user_id=actor
      AND f.assignment_type IN ('GUIDE','REVIEWER') AND r.role_code='FACULTY'
      AND f.valid_from<=statement_timestamp() AND (f.valid_until IS NULL OR statement_timestamp()<f.valid_until)
      AND r.valid_from<=statement_timestamp() AND (r.valid_until IS NULL OR statement_timestamp()<r.valid_until)
      AND u.account_status='ACTIVE' LIMIT 1 FOR SHARE OF f,r,u;
  ELSE RETURN false;
  END IF;
  RETURN FOUND;
END;
$$;
REVOKE ALL ON FUNCTION smartpro_project_permission(uuid,uuid,text) FROM PUBLIC;
-- Trigger-only definer function: fixed search_path, no dynamic SQL, no new API.
ALTER FUNCTION smartpro_decision_authority() SECURITY DEFINER;
ALTER FUNCTION smartpro_decision_authority() SET search_path=pg_catalog,public,pg_temp;
COMMIT;
