-- Forward correction: a human explanation is not an authorization requirement.
-- Existing records, immutable-history triggers and function grants are retained.
BEGIN;
DO $$ BEGIN
 IF to_regprocedure('public.smartpro_project_operation(uuid,uuid,text,jsonb,text)') IS NULL THEN
  RAISE EXCEPTION 'Reviewed candidates through 024 required';
 END IF;
END $$;

ALTER TABLE public.academic_coordinator_mandates DROP CONSTRAINT IF EXISTS academic_coordinator_mandates_reason_check;
ALTER TABLE public.academic_evaluation_policies DROP CONSTRAINT IF EXISTS academic_evaluation_policies_reason_check;
ALTER TABLE public.staff_permission_assignments DROP CONSTRAINT IF EXISTS staff_permission_assignments_grant_reason_check;
ALTER TABLE public.coordinator_operation_grants DROP CONSTRAINT IF EXISTS coordinator_operation_grants_reason_check;
ALTER TABLE public.department_setup_requests DROP CONSTRAINT IF EXISTS department_setup_requests_reason_check;
ALTER TABLE public.offering_operational_instructions DROP CONSTRAINT IF EXISTS offering_operational_instructions_reason_check;

-- Preserve the reviewed bodies rather than duplicating their authorization,
-- locking and audit implementations. Each change is restricted to note handling.
DO $migration$
DECLARE signature text; definition text; original text; marker text;
BEGIN
 FOREACH signature IN ARRAY ARRAY[
  'public.smartpro_academic_governance(uuid,uuid,text,jsonb,text)',
  'public.smartpro_academic_review_command(uuid,uuid,text,jsonb,text)',
  'public.smartpro_initial_evaluation(uuid,uuid,text,jsonb,text)',
  'public.smartpro_staff_command(uuid,uuid,text,uuid,jsonb,text)',
  'public.smartpro_document_command(uuid,uuid,text,jsonb,text)',
  'public.smartpro_department_setup(uuid,uuid,text,jsonb,text)',
  'public.smartpro_setup_current(uuid,uuid,text,jsonb,text)',
  'public.smartpro_project_operation(uuid,uuid,text,jsonb,text)'
 ] LOOP
  IF to_regprocedure(signature) IS NULL THEN RAISE EXCEPTION 'Missing prerequisite %',signature; END IF;
  SELECT pg_get_functiondef(to_regprocedure(signature)) INTO original;
  definition:=replace(original,'length(btrim(coalesce(input->>''reason'',''''))) NOT BETWEEN 1 AND 500','length(coalesce(input->>''reason'','''')) > 500');
  definition:=replace(definition,'OR (action_name<>''EVALUATE'' AND btrim(coalesce(input->>''reason'',''''))='''')','');
  definition:=replace(definition,' OR btrim(input->>''reason'')=''''','');
  marker:=E'BEGIN\n';
  IF strpos(definition,'-- Optional user note (025)')=0 THEN
   IF strpos(definition,marker)=0 THEN RAISE EXCEPTION 'Unrecognized function body %',signature; END IF;
   definition:=overlay(definition placing E'BEGIN\n -- Optional user note (025); never fabricate an explanation.\n IF jsonb_typeof(input) IS DISTINCT FROM ''object'' OR (input ? ''reason'' AND jsonb_typeof(input->''reason'') IS DISTINCT FROM ''string'') OR length(coalesce(input->>''reason'',''''))>500 THEN\n  RAISE EXCEPTION ''Optional note must be a string of at most 500 characters'' USING ERRCODE=''22023''; END IF;\n IF NOT input ? ''reason'' THEN input:=input||jsonb_build_object(''reason'',''''); END IF;\n' from strpos(definition,marker) for length(marker));
  END IF;
  -- Commands which never accepted a note retain their original receipt payload.
  -- In particular, old CONFIGURE / SUBMIT / APPLY retries must still compare equal.
  IF signature='public.smartpro_document_command(uuid,uuid,text,jsonb,text)' THEN
   definition:=replace(definition,'IF NOT input ? ''reason'' THEN','IF action=''AUTHORIZE'' AND NOT input ? ''reason'' THEN');
  ELSIF signature IN ('public.smartpro_department_setup(uuid,uuid,text,jsonb,text)','public.smartpro_setup_current(uuid,uuid,text,jsonb,text)') THEN
   definition:=replace(definition,'IF NOT input ? ''reason'' THEN','IF action=''REQUEST'' AND NOT input ? ''reason'' THEN');
  END IF;
  EXECUTE definition;
 END LOOP;
END $migration$;
COMMIT;
