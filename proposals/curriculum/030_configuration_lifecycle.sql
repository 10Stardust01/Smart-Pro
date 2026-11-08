BEGIN;
DO $$ BEGIN IF to_regprocedure('public.smartpro_manage_offering(uuid,uuid,text,jsonb,text)') IS NULL THEN RAISE EXCEPTION 'Reviewed 029 required'; END IF; END $$;
ALTER TABLE public.academic_cycles ADD COLUMN IF NOT EXISTS management_revision integer NOT NULL DEFAULT 0;
CREATE OR REPLACE FUNCTION public.smartpro_configuration_management(actor uuid,dept uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 PERFORM public.smartpro_department_setup_read(actor,dept);
 RETURN jsonb_build_object('cycles',(SELECT coalesce(jsonb_agg(to_jsonb(c) ORDER BY starts_on DESC),'[]') FROM public.academic_cycles c WHERE department_id=dept),
 'history',(SELECT coalesce(jsonb_agg(to_jsonb(a) ORDER BY occurred_at DESC),'[]') FROM (SELECT id,target_id,actor_id,occurred_at,metadata FROM public.audit_events WHERE action='CYCLE_UPDATED' AND metadata->>'departmentId'=dept::text ORDER BY occurred_at DESC LIMIT 100)a));
END $$;
CREATE OR REPLACE FUNCTION public.smartpro_manage_configuration(actor uuid,dept uuid,action text,input jsonb,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE auth jsonb; c public.academic_cycles%ROWTYPE; prior public.document_command_receipts%ROWTYPE; result jsonb; after_state jsonb;
BEGIN
 auth:=public.smartpro_operational_authority(actor,dept,input->'authority');
 IF action<>'CYCLE' OR key IS NULL OR key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' THEN RAISE EXCEPTION 'Supported configuration command required' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(actor::text||':configuration:'||key,0));
 SELECT * INTO prior FROM public.document_command_receipts WHERE actor_id=actor AND request_key=key;
 IF FOUND THEN IF prior.action<>'CONFIGURATION_'||action OR prior.input<>jsonb_build_object('departmentId',dept,'payload',input) THEN RAISE EXCEPTION 'Retry changed' USING ERRCODE='23514'; END IF;RETURN prior.output; END IF;
 SELECT * INTO c FROM public.academic_cycles WHERE id=(input->>'cycleId')::uuid AND department_id=dept FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Department cycle required' USING ERRCODE='42501'; END IF;
 IF c.management_revision IS DISTINCT FROM (input->>'expectedRevision')::integer THEN RAISE EXCEPTION 'Cycle changed; refresh' USING ERRCODE='23514'; END IF;
 IF length(btrim(input->>'code')) NOT BETWEEN 1 AND 80 OR (input->>'startsOn')::date >= (input->>'endsOn')::date THEN RAISE EXCEPTION 'Ordered cycle dates and name required' USING ERRCODE='22023'; END IF;
 -- A date correction must not exclude existing academic evidence from its cycle.
 IF EXISTS(SELECT FROM public.projects p WHERE p.cycle_id=c.id AND (p.created_at::date<(input->>'startsOn')::date OR p.created_at::date>(input->>'endsOn')::date))
  OR EXISTS(SELECT FROM public.project_reviews r WHERE r.cycle_id=c.id AND r.roster_locked_at IS NOT NULL AND (r.roster_locked_at::date<(input->>'startsOn')::date OR r.roster_locked_at::date>(input->>'endsOn')::date)) THEN RAISE EXCEPTION 'Cycle dates must preserve recorded academic activity' USING ERRCODE='23514'; END IF;
 UPDATE public.academic_cycles SET code=btrim(input->>'code'),starts_on=(input->>'startsOn')::date,ends_on=(input->>'endsOn')::date,management_revision=management_revision+1 WHERE id=c.id RETURNING to_jsonb(academic_cycles.*) INTO after_state;
 PERFORM public.smartpro_operational_authority(actor,dept,input->'authority');
 result:=jsonb_build_object('id',c.id,'revision',c.management_revision+1);
 INSERT INTO public.document_command_receipts VALUES(actor,key,'CONFIGURATION_'||action,jsonb_build_object('departmentId',dept,'payload',input),result);
 INSERT INTO public.audit_events(actor_id,action,target_type,target_id,metadata) VALUES(actor,'CYCLE_UPDATED','ACADEMIC_CYCLE',c.id,jsonb_build_object('departmentId',dept,'before',to_jsonb(c),'after',after_state,'authority',input->'authority'));
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_configuration_management(uuid,uuid),public.smartpro_manage_configuration(uuid,uuid,text,jsonb,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_configuration_management(uuid,uuid),public.smartpro_manage_configuration(uuid,uuid,text,jsonb,text) TO smartpro_runtime;
COMMIT;
