-- Separate guide allocation, review planning and explicit coordinator delegation.
BEGIN;
DO $$ BEGIN IF to_regprocedure('public.smartpro_setup_current(uuid,uuid,text,jsonb,text)') IS NULL THEN RAISE EXCEPTION 'Reviewed 023 required'; END IF; END $$;
DO $$ BEGIN IF NOT EXISTS(SELECT FROM pg_constraint WHERE conrelid='public.faculty_assignments'::regclass AND conname='one_temporal_primary_guide') THEN
 ALTER TABLE public.faculty_assignments ADD CONSTRAINT one_temporal_primary_guide EXCLUDE USING gist(project_id WITH =,tstzrange(valid_from,valid_until,'[)') WITH &&) WHERE(assignment_type='GUIDE');
END IF; END $$;
CREATE TABLE IF NOT EXISTS public.coordinator_operation_grants (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),mandate_id uuid NOT NULL REFERENCES academic_coordinator_mandates(id),
 operation text NOT NULL CHECK(operation IN ('GUIDE','SCHEDULE')),valid_until timestamptz NOT NULL,
 granted_by uuid NOT NULL REFERENCES users(id),reason text NOT NULL CHECK(btrim(reason)<>''),created_at timestamptz NOT NULL DEFAULT clock_timestamp());
DO $$ BEGIN IF NOT EXISTS(SELECT FROM pg_trigger WHERE tgrelid='public.coordinator_operation_grants'::regclass AND tgname='preserve_operation_grant') THEN
 CREATE TRIGGER preserve_operation_grant BEFORE UPDATE OR DELETE ON public.coordinator_operation_grants FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation(); END IF; END $$;
REVOKE ALL ON public.coordinator_operation_grants FROM PUBLIC,smartpro_runtime;
CREATE OR REPLACE FUNCTION public.smartpro_project_operation(actor uuid,dept uuid,action text,input jsonb,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE auth jsonb; prior public.document_command_receipts%ROWTYPE; old public.faculty_assignments%ROWTYPE; p public.projects%ROWTYPE; r public.project_reviews%ROWTYPE; stamp timestamptz; rid uuid; result jsonb; role_id uuid;
BEGIN
 IF NOT EXISTS(SELECT FROM public.academic_governance_settings WHERE department_id=dept AND enabled) OR NOT EXISTS(SELECT FROM public.staff_department_controls WHERE department_id=dept AND enabled) THEN RAISE EXCEPTION 'department operations disabled' USING ERRCODE='42501'; END IF;
 auth:=public.smartpro_academic_authority(actor,dept,action='DELEGATE_OPERATION');
 IF input->>'_actingRole'='Coordinator' THEN
  SELECT m.id INTO rid FROM public.academic_coordinator_mandates m JOIN public.academic_hod_mandates h ON h.id=m.hod_mandate_id
    JOIN public.department_role_assignments cr ON cr.id=m.role_assignment_id JOIN public.department_role_assignments hr ON hr.id=h.role_assignment_id JOIN public.users hu ON hu.id=h.user_id
   WHERE m.user_id=actor AND m.department_id=dept AND NOT m.revoked AND h.enabled AND hu.account_status='ACTIVE'
    AND cr.valid_from<=clock_timestamp() AND (cr.valid_until IS NULL OR clock_timestamp()<cr.valid_until)
    AND hr.valid_from<=clock_timestamp() AND (hr.valid_until IS NULL OR clock_timestamp()<hr.valid_until) ORDER BY m.id LIMIT 1 FOR UPDATE OF m,h,cr,hr FOR SHARE OF hu;
  IF rid IS NULL THEN RAISE EXCEPTION 'current coordinator mandate required' USING ERRCODE='42501'; END IF;
  auth:=auth||jsonb_build_object('coordinatorMandateId',rid);
 END IF;
 IF auth->>'coordinatorMandateId' IS NOT NULL AND NOT EXISTS(SELECT FROM public.coordinator_operation_grants WHERE mandate_id=(auth->>'coordinatorMandateId')::uuid AND operation=action AND clock_timestamp()<valid_until) THEN RAISE EXCEPTION 'explicit coordinator operation delegation required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(actor::text||key,0));
 SELECT * INTO prior FROM public.document_command_receipts WHERE actor_id=actor AND request_key=key;
 IF FOUND THEN IF prior.action<>'OPERATION_'||action OR prior.input<>jsonb_build_object('departmentId',dept,'payload',input) THEN RAISE EXCEPTION 'request key changed' USING ERRCODE='23514'; END IF; RETURN prior.output; END IF;
 IF action='DELEGATE_OPERATION' THEN
  PERFORM 1 FROM public.academic_coordinator_mandates m WHERE m.id=(input->>'mandateId')::uuid AND m.department_id=dept AND m.hod_mandate_id=(auth->>'hodMandateId')::uuid AND NOT m.revoked FOR UPDATE;
  IF NOT FOUND OR input->>'operation' NOT IN ('GUIDE','SCHEDULE') OR (input->>'validUntil')::timestamptz<=clock_timestamp() THEN RAISE EXCEPTION 'active scoped appointment and finite delegation required' USING ERRCODE='23514'; END IF;
  INSERT INTO public.coordinator_operation_grants(mandate_id,operation,valid_until,granted_by,reason)
   VALUES((input->>'mandateId')::uuid,input->>'operation',(input->>'validUntil')::timestamptz,actor,input->>'reason') RETURNING id INTO rid;
  result:=jsonb_build_object('id',rid,'status','Delegated');
 ELSIF action='GUIDE' THEN
  SELECT * INTO p FROM public.projects WHERE id=(input->>'projectId')::uuid AND department_id=dept FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'scoped project required' USING ERRCODE='42501'; END IF;
  PERFORM 1 FROM public.users WHERE id=(input->>'facultyId')::uuid AND account_status='ACTIVE' FOR SHARE;
  SELECT id INTO role_id FROM public.department_role_assignments WHERE user_id=(input->>'facultyId')::uuid AND department_id=dept AND role_code='FACULTY' AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until) ORDER BY id LIMIT 1 FOR SHARE;
  IF role_id IS NULL OR NOT public.smartpro_has_role((input->>'facultyId')::uuid,dept,'FACULTY',clock_timestamp()) THEN RAISE EXCEPTION 'active scoped faculty appointment required' USING ERRCODE='42501'; END IF;
  SELECT * INTO old FROM public.faculty_assignments WHERE project_id=p.id AND assignment_type='GUIDE' AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until) FOR UPDATE;
  IF old.id IS DISTINCT FROM (input->>'expectedGuideId')::uuid THEN RAISE EXCEPTION 'guide changed; refresh' USING ERRCODE='23514'; END IF;
  IF old.faculty_user_id=(input->>'facultyId')::uuid THEN rid:=old.id;
  ELSE
   stamp:=clock_timestamp();
   IF old.id IS NOT NULL THEN UPDATE public.faculty_assignments SET valid_until=stamp WHERE id=old.id; END IF;
   INSERT INTO public.faculty_assignments(project_id,faculty_user_id,assignment_type,valid_from) VALUES(p.id,(input->>'facultyId')::uuid,'GUIDE',stamp) RETURNING id INTO rid;
  END IF;
  result:=jsonb_build_object('id',rid,'status','Guide assigned');
 ELSIF action='SCHEDULE' THEN
  SELECT x.* INTO r FROM public.project_reviews x JOIN public.projects pr ON pr.id=x.project_id WHERE x.id=(input->>'reviewId')::uuid AND pr.department_id=dept FOR UPDATE OF x;
  IF NOT FOUND THEN RAISE EXCEPTION 'scoped review required' USING ERRCODE='42501'; END IF;
  IF r.row_version IS DISTINCT FROM (input->>'expectedReviewVersion')::integer OR r.review_state NOT IN ('SCHEDULED','OPEN') OR EXISTS(SELECT FROM public.assessments WHERE review_id=r.id AND state='FINALIZED') THEN RAISE EXCEPTION 'review planning no longer editable' USING ERRCODE='23514'; END IF;
  UPDATE public.project_reviews SET scheduled_at=(input->>'scheduledAt')::timestamptz,row_version=row_version+1 WHERE id=r.id;
  rid:=r.id;
  result:=jsonb_build_object('id',r.id,'status','Review scheduled');
 ELSE RAISE EXCEPTION 'unsupported project operation' USING ERRCODE='22023'; END IF;
 -- Row/advisory lock waits can outlive a finite appointment or delegation.
 -- Reauthorize before committing; any preceding writes roll back on expiry.
 PERFORM public.smartpro_academic_authority(actor,dept,action='DELEGATE_OPERATION');
 IF auth->>'coordinatorMandateId' IS NOT NULL AND (
   NOT EXISTS(SELECT FROM public.academic_coordinator_mandates m JOIN public.department_role_assignments cr ON cr.id=m.role_assignment_id
     JOIN public.academic_hod_mandates h ON h.id=m.hod_mandate_id JOIN public.department_role_assignments hr ON hr.id=h.role_assignment_id
     WHERE m.id=(auth->>'coordinatorMandateId')::uuid AND NOT m.revoked AND h.enabled
      AND cr.valid_from<=clock_timestamp() AND (cr.valid_until IS NULL OR clock_timestamp()<cr.valid_until)
      AND hr.valid_from<=clock_timestamp() AND (hr.valid_until IS NULL OR clock_timestamp()<hr.valid_until))
   OR NOT EXISTS(SELECT FROM public.coordinator_operation_grants WHERE mandate_id=(auth->>'coordinatorMandateId')::uuid AND operation=action AND clock_timestamp()<valid_until)
 ) THEN RAISE EXCEPTION 'coordinator authority expired while waiting' USING ERRCODE='42501'; END IF;
 INSERT INTO public.document_command_receipts VALUES(actor,key,'OPERATION_'||action,jsonb_build_object('departmentId',dept,'payload',input),result);
 INSERT INTO public.audit_events(actor_id,project_id,action,target_type,target_id,metadata)
  VALUES(actor,coalesce(p.id,r.project_id),'PROJECT_'||action,'ACADEMIC_OPERATION',rid,jsonb_build_object('departmentId',dept,'authority',auth,'beforeGuide',to_jsonb(old),'beforeReview',to_jsonb(r),'input',input,'result',result));
 RETURN result;
END $$;
CREATE OR REPLACE FUNCTION public.smartpro_coordination_options(actor uuid,dept uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE auth jsonb;
BEGIN
 auth:=public.smartpro_academic_authority(actor,dept);
 RETURN jsonb_build_object('canGuide',auth->>'coordinatorMandateId' IS NULL OR EXISTS(SELECT FROM public.coordinator_operation_grants WHERE mandate_id=(auth->>'coordinatorMandateId')::uuid AND operation='GUIDE' AND clock_timestamp()<valid_until),
 'canSchedule',auth->>'coordinatorMandateId' IS NULL OR EXISTS(SELECT FROM public.coordinator_operation_grants WHERE mandate_id=(auth->>'coordinatorMandateId')::uuid AND operation='SCHEDULE' AND clock_timestamp()<valid_until),
 'coordinators',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM(SELECT m.id,u.display_name,m.appointed_by,(NOT m.revoked AND h.enabled AND u.account_status='ACTIVE' AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)) AS active FROM public.academic_coordinator_mandates m JOIN public.users u ON u.id=m.user_id JOIN public.department_role_assignments r ON r.id=m.role_assignment_id JOIN public.academic_hod_mandates h ON h.id=m.hod_mandate_id WHERE m.department_id=dept ORDER BY u.display_name LIMIT 50)x));
END $$;
REVOKE ALL ON FUNCTION public.smartpro_project_operation(uuid,uuid,text,jsonb,text),public.smartpro_coordination_options(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_project_operation(uuid,uuid,text,jsonb,text),public.smartpro_coordination_options(uuid,uuid) TO smartpro_runtime;
CREATE OR REPLACE FUNCTION public.smartpro_coordination_role_options(actor uuid,dept uuid,role text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE result jsonb; mandate uuid;
BEGIN
 result:=public.smartpro_coordination_options(actor,dept);
 IF role='Coordinator' THEN
  SELECT id INTO mandate FROM public.academic_coordinator_mandates WHERE user_id=actor AND department_id=dept AND NOT revoked ORDER BY id LIMIT 1;
  result:=result||jsonb_build_object('canGuide',EXISTS(SELECT FROM public.coordinator_operation_grants WHERE mandate_id=mandate AND operation='GUIDE' AND clock_timestamp()<valid_until),'canSchedule',EXISTS(SELECT FROM public.coordinator_operation_grants WHERE mandate_id=mandate AND operation='SCHEDULE' AND clock_timestamp()<valid_until));
 END IF;
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_coordination_role_options(uuid,uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_coordination_role_options(uuid,uuid,text) TO smartpro_runtime;
COMMIT;
