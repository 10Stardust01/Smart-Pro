BEGIN;
DO $$ BEGIN IF to_regprocedure('public.smartpro_manage_configuration(uuid,uuid,text,jsonb,text)') IS NULL THEN RAISE EXCEPTION 'Reviewed 030 required'; END IF; END $$;
CREATE TABLE IF NOT EXISTS public.coordinator_operation_revocations(
 grant_id uuid PRIMARY KEY REFERENCES coordinator_operation_grants(id),revoked_by uuid NOT NULL REFERENCES users(id),revoked_at timestamptz NOT NULL DEFAULT clock_timestamp());
REVOKE ALL ON public.coordinator_operation_revocations FROM PUBLIC,smartpro_runtime;
DO $$ BEGIN IF NOT EXISTS(SELECT FROM pg_trigger WHERE tgrelid='public.coordinator_operation_revocations'::regclass AND tgname='retain_operation_revocation') THEN
 CREATE TRIGGER retain_operation_revocation BEFORE UPDATE OR DELETE ON public.coordinator_operation_revocations FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation(); END IF; END $$;
-- Every existing capability check must honor a prospective revocation.
DO $$ DECLARE sig text; def text; BEGIN
 FOREACH sig IN ARRAY ARRAY['public.smartpro_project_operation(uuid,uuid,text,jsonb,text)','public.smartpro_coordination_options(uuid,uuid)','public.smartpro_coordination_role_options(uuid,uuid,text)'] LOOP
  def:=pg_get_functiondef(to_regprocedure(sig));
  IF strpos(def,'coordinator_operation_revocations')=0 THEN
   def:=regexp_replace(def,'(FROM public.coordinator_operation_grants WHERE[^;\n]*?clock_timestamp\(\)<valid_until)',E'\\1 AND NOT EXISTS(SELECT FROM public.coordinator_operation_revocations v WHERE v.grant_id=coordinator_operation_grants.id)','g');
   EXECUTE def;
  END IF;
 END LOOP;
END $$;
DO $$ DECLARE def text; BEGIN
 def:=pg_get_functiondef('public.smartpro_assignment_integrity()'::regprocedure);
 IF strpos(def,'-- Prospective assignment closure')=0 THEN
  def:=replace(def,'  IF NOT smartpro_has_role(NEW.faculty_user_id',E'  -- Prospective assignment closure does not require a still-active faculty role.\n  IF TG_TABLE_NAME=''faculty_assignments'' THEN\n   IF TG_OP=''UPDATE'' THEN\n    IF (to_jsonb(NEW)-''valid_until'')=(to_jsonb(OLD)-''valid_until'') AND NEW.valid_until IS NOT NULL AND (OLD.valid_until IS NULL OR NEW.valid_until<=OLD.valid_until) THEN RETURN NEW; END IF;\n   END IF;\n  END IF;\n  IF NOT smartpro_has_role(NEW.faculty_user_id');
  EXECUTE def;
 END IF;
END $$;
CREATE OR REPLACE FUNCTION public.smartpro_assignment_management(actor uuid,dept uuid,acting_role text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF NOT public.smartpro_role_choices(actor) ? acting_role OR acting_role NOT IN ('HOD','Coordinator') THEN RAISE EXCEPTION 'Academic management responsibility required' USING ERRCODE='42501'; END IF;
 PERFORM public.smartpro_academic_authority(actor,dept,acting_role='HOD');
 RETURN jsonb_build_object('assignments',(SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.valid_from DESC),'[]') FROM (
  SELECT f.*,p.title,u.display_name FROM public.faculty_assignments f JOIN public.projects p ON p.id=f.project_id JOIN public.users u ON u.id=f.faculty_user_id WHERE p.department_id=dept ORDER BY f.valid_from DESC LIMIT 200)x),
 'operationGrants',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM (
  SELECT g.*,u.display_name,v.revoked_at FROM public.coordinator_operation_grants g JOIN public.academic_coordinator_mandates m ON m.id=g.mandate_id JOIN public.users u ON u.id=m.user_id LEFT JOIN public.coordinator_operation_revocations v ON v.grant_id=g.id WHERE m.department_id=dept ORDER BY g.created_at DESC LIMIT 100)x),
 'facultyRoles',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM (SELECT r.id,r.user_id,u.display_name FROM public.department_role_assignments r JOIN public.users u ON u.id=r.user_id WHERE r.department_id=dept AND r.role_code='FACULTY' AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until) AND u.account_status='ACTIVE' ORDER BY u.display_name LIMIT 200)x),
 'routineGrants',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM (SELECT g.*,u.display_name,m.user_id AS coordinator_id FROM public.staff_permission_assignments g JOIN public.academic_faculty_delegations d ON d.grant_id=g.id JOIN public.academic_coordinator_mandates m ON m.id=d.coordinator_mandate_id JOIN public.users u ON u.id=g.user_id WHERE g.department_id=dept AND (acting_role='HOD' OR m.user_id=actor) ORDER BY g.valid_from DESC LIMIT 100)x));
END $$;
CREATE OR REPLACE FUNCTION public.smartpro_manage_assignment(actor uuid,dept uuid,action text,input jsonb,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE auth jsonb; prior public.document_command_receipts%ROWTYPE; assignment public.faculty_assignments%ROWTYPE; g public.coordinator_operation_grants%ROWTYPE; result jsonb; stamp timestamptz; mandate uuid;
BEGIN
 IF input->>'_actingRole' NOT IN ('HOD','Coordinator') OR NOT public.smartpro_role_choices(actor) ? (input->>'_actingRole') THEN RAISE EXCEPTION 'Academic management responsibility required' USING ERRCODE='42501'; END IF;
 auth:=public.smartpro_academic_authority(actor,dept,input->>'_actingRole'='HOD' OR action='REVOKE_OPERATION');
 IF key IS NULL OR key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' THEN RAISE EXCEPTION 'Request key required' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(actor::text||':assignment:'||key,0));
 SELECT * INTO prior FROM public.document_command_receipts WHERE actor_id=actor AND request_key=key;
 IF FOUND THEN IF prior.action<>'ASSIGNMENT_'||action OR prior.input<>jsonb_build_object('departmentId',dept,'payload',input) THEN RAISE EXCEPTION 'Retry changed' USING ERRCODE='23514'; END IF;RETURN prior.output; END IF;
 IF action='REVOKE_OPERATION' THEN
  IF input->>'_actingRole'<>'HOD' THEN RAISE EXCEPTION 'HOD responsibility required' USING ERRCODE='42501'; END IF;
  SELECT x.* INTO g FROM public.coordinator_operation_grants x JOIN public.academic_coordinator_mandates m ON m.id=x.mandate_id WHERE x.id=(input->>'grantId')::uuid AND m.department_id=dept AND m.hod_mandate_id=(auth->>'hodMandateId')::uuid FOR UPDATE OF x;
  IF NOT FOUND THEN RAISE EXCEPTION 'Own department appointment grant required' USING ERRCODE='42501'; END IF;
  INSERT INTO public.coordinator_operation_revocations(grant_id,revoked_by) VALUES(g.id,actor) ON CONFLICT DO NOTHING;
  result:=jsonb_build_object('id',g.id,'status','Revoked');
 ELSIF action='END_ASSIGNMENT' THEN
  SELECT f.* INTO assignment FROM public.faculty_assignments f JOIN public.projects p ON p.id=f.project_id WHERE f.id=(input->>'assignmentId')::uuid AND p.department_id=dept;
  IF NOT FOUND THEN RAISE EXCEPTION 'Department project assignment required' USING ERRCODE='42501'; END IF;
  PERFORM 1 FROM public.projects WHERE id=assignment.project_id FOR UPDATE;
  SELECT * INTO assignment FROM public.faculty_assignments WHERE id=assignment.id FOR UPDATE;
  IF assignment.valid_until IS NOT NULL AND assignment.valid_until<=clock_timestamp() THEN RAISE EXCEPTION 'Assignment already ended; refresh' USING ERRCODE='23514'; END IF;
  IF input->>'_actingRole'='Coordinator' THEN
   SELECT m.id INTO mandate FROM public.academic_coordinator_mandates m JOIN public.department_role_assignments r ON r.id=m.role_assignment_id JOIN public.academic_hod_mandates h ON h.id=m.hod_mandate_id JOIN public.department_role_assignments hr ON hr.id=h.role_assignment_id
    WHERE m.user_id=actor AND m.department_id=dept AND NOT m.revoked AND h.enabled AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until) AND hr.valid_from<=clock_timestamp() AND (hr.valid_until IS NULL OR clock_timestamp()<hr.valid_until) ORDER BY m.id LIMIT 1 FOR UPDATE OF m,r,h,hr;
   IF assignment.assignment_type='GUIDE' THEN
    PERFORM 1 FROM public.coordinator_operation_grants x WHERE x.mandate_id=mandate AND operation='GUIDE' AND valid_until>clock_timestamp() ORDER BY x.id FOR UPDATE;
   END IF;
   IF mandate IS NULL OR (assignment.assignment_type='GUIDE' AND NOT EXISTS(SELECT FROM public.coordinator_operation_grants x WHERE x.mandate_id=mandate AND operation='GUIDE' AND valid_until>clock_timestamp() AND NOT EXISTS(SELECT FROM public.coordinator_operation_revocations WHERE grant_id=x.id))) THEN RAISE EXCEPTION 'Delegated assignment responsibility required' USING ERRCODE='42501'; END IF;
  END IF;
  stamp:=clock_timestamp();
  UPDATE public.faculty_assignments SET valid_until=stamp WHERE id=assignment.id;
  result:=jsonb_build_object('id',assignment.id,'status','Ended','endedAt',stamp);
 ELSE RAISE EXCEPTION 'Supported assignment operation required' USING ERRCODE='22023'; END IF;
 PERFORM public.smartpro_academic_authority(actor,dept,input->>'_actingRole'='HOD' OR action='REVOKE_OPERATION');
 INSERT INTO public.document_command_receipts VALUES(actor,key,'ASSIGNMENT_'||action,jsonb_build_object('departmentId',dept,'payload',input),result);
 INSERT INTO public.audit_events(actor_id,project_id,action,target_type,target_id,metadata) VALUES(actor,assignment.project_id,'ASSIGNMENT_'||action,'ACADEMIC_ASSIGNMENT',coalesce(assignment.id,g.id),jsonb_build_object('departmentId',dept,'before',to_jsonb(assignment),'grant',to_jsonb(g),'result',result,'authority',auth));
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_assignment_management(uuid,uuid,text),public.smartpro_manage_assignment(uuid,uuid,text,jsonb,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_assignment_management(uuid,uuid,text),public.smartpro_manage_assignment(uuid,uuid,text,jsonb,text) TO smartpro_runtime;
COMMIT;
