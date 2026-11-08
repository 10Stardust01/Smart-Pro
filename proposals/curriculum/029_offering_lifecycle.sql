-- Forward management lifecycle; no fixture data, resets or historical rewrites.
BEGIN;
DO $$ BEGIN IF to_regclass('public.project_proposal_details') IS NULL OR to_regprocedure('public.smartpro_document_scope(uuid,uuid,text)') IS NULL THEN RAISE EXCEPTION 'Reviewed 027-028 required'; END IF; END $$;
ALTER TABLE public.curriculum_offerings ADD COLUMN IF NOT EXISTS management_revision integer NOT NULL DEFAULT 0;
ALTER TABLE public.curriculum_offerings ADD COLUMN IF NOT EXISTS availability text NOT NULL DEFAULT 'ACTIVE' CHECK(availability IN ('ACTIVE','PAUSED','ARCHIVED'));
CREATE TABLE IF NOT EXISTS public.offering_management_history(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),offering_id uuid NOT NULL REFERENCES curriculum_offerings(id),
 revision integer NOT NULL,actor_id uuid NOT NULL REFERENCES users(id),action text NOT NULL,
 before_state jsonb NOT NULL,after_state jsonb NOT NULL,authority jsonb NOT NULL,occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),UNIQUE(offering_id,revision));
REVOKE ALL ON public.offering_management_history FROM PUBLIC,smartpro_runtime;
DO $$ BEGIN IF NOT EXISTS(SELECT FROM pg_trigger WHERE tgrelid='public.offering_management_history'::regclass AND tgname='preserve_offering_management') THEN
 CREATE TRIGGER preserve_offering_management BEFORE UPDATE OR DELETE ON public.offering_management_history FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation(); END IF; END $$;

CREATE OR REPLACE FUNCTION public.smartpro_operational_authority(actor uuid,dept uuid,authority jsonb) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE mandate public.academic_hod_mandates%ROWTYPE; rid uuid;
BEGIN
 IF NOT EXISTS(SELECT FROM public.academic_governance_settings WHERE department_id=dept AND enabled) OR NOT EXISTS(SELECT FROM public.staff_department_controls WHERE department_id=dept AND enabled) THEN RAISE EXCEPTION 'Department configuration disabled' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.users WHERE id=actor AND account_status='ACTIVE' FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Active Admin required' USING ERRCODE='42501'; END IF;
 SELECT id INTO rid FROM public.department_role_assignments WHERE user_id=actor AND department_id=dept AND role_code='ACADEMIC_ADMIN' AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until) ORDER BY id LIMIT 1 FOR SHARE;
 IF rid IS NULL THEN RAISE EXCEPTION 'Department Admin required' USING ERRCODE='42501'; END IF;
 IF authority->>'source' IS DISTINCT FROM 'EXTERNAL_INSTRUCTION' OR authority->'confirmed' IS DISTINCT FROM 'true'::jsonb OR length(coalesce(authority->>'reference',''))>500 THEN RAISE EXCEPTION 'Record approved departmental instructions' USING ERRCODE='22023'; END IF;
 SELECT * INTO mandate FROM public.academic_hod_mandates WHERE id=(authority->>'hodMandateId')::uuid AND department_id=dept AND enabled FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Current departmental HOD required' USING ERRCODE='42501'; END IF;
 PERFORM public.smartpro_academic_authority(mandate.user_id,dept,true);
 RETURN jsonb_build_object('adminRoleId',rid,'hodMandateId',mandate.id,'hodId',mandate.user_id);
END $$;

CREATE OR REPLACE FUNCTION public.smartpro_offering_management(actor uuid,dept uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 PERFORM public.smartpro_department_setup_read(actor,dept);
 RETURN jsonb_build_object('semesters',(SELECT coalesce(jsonb_agg(s ORDER BY s),'[]') FROM (SELECT DISTINCT semester_key s FROM public.student_profiles WHERE department_id=dept UNION SELECT DISTINCT semester_key FROM public.curriculum_offerings WHERE department_id=dept)x),
 'offerings',(SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.label,x.semester_key),'[]') FROM (
  SELECT o.*,t.label,c.code AS cycle_label,w.visible_from,w.visible_until,
   (SELECT count(*) FROM public.teams WHERE curriculum_offering_id=o.id) AS team_count,
   (SELECT i.configuration FROM public.offering_instruction_executions e JOIN public.offering_operational_instructions i ON i.id=e.instruction_id WHERE e.offering_id=o.id ORDER BY e.configured_at DESC LIMIT 1) AS configuration,
   (SELECT coalesce(jsonb_agg(to_jsonb(h) ORDER BY h.revision DESC),'[]') FROM public.offering_management_history h WHERE h.offering_id=o.id) AS history
  FROM public.curriculum_offerings o JOIN public.curriculum_types t ON t.id=o.curriculum_type_id JOIN public.academic_cycles c ON c.id=o.cycle_id LEFT JOIN public.student_offering_windows w ON w.offering_id=o.id WHERE o.department_id=dept ORDER BY t.label,o.id LIMIT 200)x));
END $$;

CREATE OR REPLACE FUNCTION public.smartpro_manage_offering(actor uuid,dept uuid,action text,input jsonb,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE auth jsonb; o public.curriculum_offerings%ROWTYPE; before_state jsonb; after_state jsonb; cfg jsonb; result jsonb; prior public.document_command_receipts%ROWTYPE; stamp timestamptz;
BEGIN
 auth:=public.smartpro_operational_authority(actor,dept,input->'authority');
 IF key IS NULL OR key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' OR action NOT IN ('EDIT','AVAILABILITY') THEN RAISE EXCEPTION 'Valid management command required' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(actor::text||':offering:'||key,0));
 SELECT * INTO prior FROM public.document_command_receipts WHERE actor_id=actor AND request_key=key;
 IF FOUND THEN IF prior.action<>'OFFERING_'||action OR prior.input<>jsonb_build_object('departmentId',dept,'payload',input) THEN RAISE EXCEPTION 'Retry changed' USING ERRCODE='23514'; END IF;RETURN prior.output; END IF;
 SELECT * INTO o FROM public.curriculum_offerings WHERE id=(input->>'offeringId')::uuid AND department_id=dept FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Department offering required' USING ERRCODE='42501'; END IF;
 IF o.management_revision IS DISTINCT FROM (input->>'expectedRevision')::integer THEN RAISE EXCEPTION 'Offering changed; refresh' USING ERRCODE='23514'; END IF;
 before_state:=jsonb_build_object('offering',to_jsonb(o),'publication',(SELECT to_jsonb(w) FROM public.student_offering_windows w WHERE offering_id=o.id),'configuration',(SELECT i.configuration FROM public.offering_instruction_executions e JOIN public.offering_operational_instructions i ON i.id=e.instruction_id WHERE e.offering_id=o.id ORDER BY e.configured_at DESC LIMIT 1));
 IF action='EDIT' THEN
  cfg:=input->'configuration';
  IF cfg->>'adminRoleId' IS DISTINCT FROM auth->>'adminRoleId' THEN RAISE EXCEPTION 'Authenticated Admin scope required' USING ERRCODE='42501'; END IF;
  IF (o.cycle_id,o.curriculum_type_id,o.semester_key) IS DISTINCT FROM ((cfg->>'cycleId')::uuid,(cfg->>'curriculumTypeId')::uuid,cfg->>'semester') THEN
   IF EXISTS(SELECT FROM public.teams WHERE curriculum_offering_id=o.id) OR EXISTS(SELECT FROM public.project_registration_policy_versions WHERE offering_id=o.id AND cycle_id IS DISTINCT FROM (cfg->>'cycleId')::uuid) THEN RAISE EXCEPTION 'Used offering scope must be preserved; create a new offering' USING ERRCODE='23514'; END IF;
   UPDATE public.curriculum_offerings SET cycle_id=(cfg->>'cycleId')::uuid,curriculum_type_id=(cfg->>'curriculumTypeId')::uuid,semester_key=cfg->>'semester' WHERE id=o.id;
  END IF;
  -- Publication writes remain closed for paused offerings outside this transaction.
  UPDATE public.curriculum_offerings SET availability='ACTIVE' WHERE id=o.id;
  result:=public.smartpro_record_instruction(actor,dept,'RECORD',jsonb_build_object('kind','OFFERING','configuration',cfg,'authority',input->'authority','reason',coalesce(input->>'reason','')),'edit:'||encode(sha256(convert_to(actor::text||key,'UTF8')),'hex'));
  IF result->>'offeringId' IS DISTINCT FROM o.id::text THEN RAISE EXCEPTION 'Offering identity changed' USING ERRCODE='23514'; END IF;
  UPDATE public.curriculum_offerings SET availability=o.availability WHERE id=o.id;
  IF o.availability<>'ACTIVE' THEN DELETE FROM public.student_offering_windows WHERE offering_id=o.id; END IF;
 ELSE
  IF input->>'availability' NOT IN ('ACTIVE','PAUSED','ARCHIVED') OR input->>'availability' IS NULL THEN RAISE EXCEPTION 'Availability choice required' USING ERRCODE='22023'; END IF;
  UPDATE public.curriculum_offerings SET availability=input->>'availability' WHERE id=o.id;
  IF input->>'availability'='ACTIVE' THEN
   SELECT i.configuration INTO cfg FROM public.offering_instruction_executions e JOIN public.offering_operational_instructions i ON i.id=e.instruction_id WHERE e.offering_id=o.id ORDER BY e.configured_at DESC LIMIT 1;
   IF cfg IS NULL THEN RAISE EXCEPTION 'Configure approved offering dates before activation' USING ERRCODE='23514'; END IF;
   INSERT INTO public.student_offering_windows VALUES(o.id,(cfg->>'visibleFrom')::timestamptz,(cfg->>'visibleUntil')::timestamptz) ON CONFLICT(offering_id) DO UPDATE SET visible_from=excluded.visible_from,visible_until=excluded.visible_until;
  ELSE DELETE FROM public.student_offering_windows WHERE offering_id=o.id; END IF;
 END IF;
 PERFORM public.smartpro_operational_authority(actor,dept,input->'authority');
 UPDATE public.curriculum_offerings SET management_revision=management_revision+1 WHERE id=o.id;
 after_state:=jsonb_build_object('offering',(SELECT to_jsonb(x) FROM public.curriculum_offerings x WHERE id=o.id),'publication',(SELECT to_jsonb(w) FROM public.student_offering_windows w WHERE offering_id=o.id),'configuration',coalesce(cfg,before_state->'configuration'));
 INSERT INTO public.offering_management_history(offering_id,revision,actor_id,action,before_state,after_state,authority) VALUES(o.id,o.management_revision+1,actor,action,before_state,after_state,input->'authority');
 result:=jsonb_build_object('offeringId',o.id,'revision',o.management_revision+1,'status','Saved');
 INSERT INTO public.document_command_receipts VALUES(actor,key,'OFFERING_'||action,jsonb_build_object('departmentId',dept,'payload',input),result);
 INSERT INTO public.audit_events(actor_id,action,target_type,target_id,metadata) VALUES(actor,'OFFERING_'||action,'OFFERING',o.id,jsonb_build_object('departmentId',dept,'before',before_state,'after',after_state,'authority',input->'authority'));
 RETURN result;
END $$;

-- The original blanket scope freeze prevented correction even before any team
-- existed. Keep IDs/departments immutable and permit owner-command corrections
-- only while there is no academic relationship to invalidate.
DO $$ DECLARE def text; BEGIN
 def:=pg_get_functiondef('public.smartpro_curriculum_identity_guard()'::regprocedure);
 def:=replace(def,E'      RAISE EXCEPTION ''offering scope is immutable; create a separate offering''\n        USING ERRCODE=''23514'';',E'      IF (NEW.id,NEW.department_id) IS DISTINCT FROM (OLD.id,OLD.department_id) OR current_user<>pg_get_userbyid((SELECT proowner FROM pg_proc WHERE oid=''public.smartpro_manage_offering(uuid,uuid,text,jsonb,text)''::regprocedure)) OR EXISTS(SELECT FROM public.teams WHERE curriculum_offering_id=OLD.id) THEN\n       RAISE EXCEPTION ''Used offering scope is immutable; create a separate offering'' USING ERRCODE=''23514''; END IF;');
 EXECUTE def;
END $$;

-- A legacy configuration route must not silently reactivate an archived offering.
CREATE OR REPLACE FUNCTION public.smartpro_offering_publication_guard() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 PERFORM 1 FROM public.curriculum_offerings WHERE id=NEW.offering_id AND availability='ACTIVE' FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Offering is paused or archived' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
DO $$ BEGIN IF NOT EXISTS(SELECT FROM pg_trigger WHERE tgrelid='public.student_offering_windows'::regclass AND tgname='offering_availability_boundary') THEN
 CREATE TRIGGER offering_availability_boundary BEFORE INSERT OR UPDATE ON public.student_offering_windows FOR EACH ROW EXECUTE FUNCTION public.smartpro_offering_publication_guard(); END IF; END $$;
REVOKE ALL ON FUNCTION public.smartpro_operational_authority(uuid,uuid,jsonb),public.smartpro_offering_management(uuid,uuid),public.smartpro_manage_offering(uuid,uuid,text,jsonb,text),public.smartpro_offering_publication_guard() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_offering_management(uuid,uuid),public.smartpro_manage_offering(uuid,uuid,text,jsonb,text) TO smartpro_runtime;
COMMIT;
