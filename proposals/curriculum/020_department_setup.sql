-- Additive local candidate after 019. No bootstrap, fixtures or policy defaults.
BEGIN;
DO $$ BEGIN IF to_regclass('public.submission_offering_requirements') IS NULL THEN RAISE EXCEPTION 'Reviewed 019 required'; END IF; END $$;
CREATE TABLE public.department_setup_requests (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),department_id uuid NOT NULL REFERENCES departments(id),
 requested_by uuid NOT NULL REFERENCES users(id),role_id uuid NOT NULL REFERENCES department_role_assignments(id),
 kind text NOT NULL CHECK(kind IN ('CYCLE','TYPE','DOCUMENT_NOT_REQUIRED')),
 configuration jsonb NOT NULL,reason text NOT NULL CHECK(length(btrim(reason)) BETWEEN 1 AND 500),created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE public.department_setup_approvals (
 request_id uuid PRIMARY KEY REFERENCES department_setup_requests(id),approved_by uuid NOT NULL REFERENCES users(id),
 mandate_id uuid NOT NULL REFERENCES academic_hod_mandates(id),approved_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE public.department_setup_executions (
 request_id uuid PRIMARY KEY REFERENCES department_setup_requests(id),configured_by uuid NOT NULL REFERENCES users(id),
 result jsonb NOT NULL,configured_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE public.department_curriculum_types (
 department_id uuid NOT NULL REFERENCES departments(id),type_id uuid NOT NULL REFERENCES curriculum_types(id),
 PRIMARY KEY(department_id,type_id));
CREATE TABLE public.offering_document_dispositions (
 offering_id uuid PRIMARY KEY REFERENCES curriculum_offerings(id),request_id uuid NOT NULL REFERENCES department_setup_requests(id),
 disposition text NOT NULL CHECK(disposition='NOT_REQUIRED'));
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['department_setup_requests','department_setup_approvals','department_setup_executions','department_curriculum_types','offering_document_dispositions'] LOOP
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,smartpro_runtime',t);
  EXECUTE format('CREATE TRIGGER preserve_setup BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation()',t);
 END LOOP;
END $$;
CREATE FUNCTION public.smartpro_department_setup(actor uuid,dept uuid,action text,input jsonb,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r public.department_setup_requests%ROWTYPE; a public.department_setup_approvals%ROWTYPE; auth jsonb; role uuid; result jsonb; old public.document_command_receipts%ROWTYPE; cfg jsonb; rid uuid;
BEGIN
 PERFORM 1 FROM public.users WHERE id=actor AND account_status='ACTIVE' FOR SHARE;
 IF NOT FOUND OR NOT EXISTS(SELECT FROM public.academic_governance_settings WHERE department_id=dept AND enabled) OR NOT EXISTS(SELECT FROM public.staff_department_controls WHERE department_id=dept AND enabled) THEN RAISE EXCEPTION 'active department access required' USING ERRCODE='42501'; END IF;
 IF action='REQUEST' THEN
  SELECT id INTO role FROM public.department_role_assignments WHERE user_id=actor AND department_id=dept AND role_code='ACADEMIC_ADMIN'
   AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until) ORDER BY id LIMIT 1 FOR SHARE;
  IF role IS NULL THEN RAISE EXCEPTION 'operational Admin required' USING ERRCODE='42501'; END IF;
 ELSE
  SELECT * INTO r FROM public.department_setup_requests WHERE id=(input->>'requestId')::uuid AND department_id=dept FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'scoped setup request required' USING ERRCODE='42501'; END IF;
  IF action='APPROVE' THEN auth:=public.smartpro_academic_authority(actor,dept,true);
  ELSIF action='APPLY' THEN
   PERFORM 1 FROM public.department_role_assignments WHERE id=r.role_id AND user_id=actor AND role_code='ACADEMIC_ADMIN'
    AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until) FOR SHARE;
   IF NOT FOUND THEN RAISE EXCEPTION 'original Admin required' USING ERRCODE='42501'; END IF;
   SELECT * INTO a FROM public.department_setup_approvals WHERE request_id=r.id;
   PERFORM 1 FROM public.academic_hod_mandates WHERE id=a.mandate_id AND enabled FOR SHARE;
   IF NOT FOUND THEN RAISE EXCEPTION 'HOD approval required' USING ERRCODE='42501'; END IF;
   PERFORM public.smartpro_academic_authority(a.approved_by,dept,true);
  ELSE RAISE EXCEPTION 'unknown action' USING ERRCODE='22023'; END IF;
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(actor::text||key,0));
 SELECT * INTO old FROM public.document_command_receipts WHERE actor_id=actor AND request_key=key;
 IF FOUND THEN IF old.action<>'SETUP_'||action OR old.input<>jsonb_build_object('departmentId',dept,'payload',input) THEN RAISE EXCEPTION 'key conflict' USING ERRCODE='23514'; END IF; RETURN old.output; END IF;
 IF action='REQUEST' THEN
  cfg:=input->'configuration';
  IF input->>'kind'='CYCLE' THEN
   IF (SELECT count(*) FROM jsonb_object_keys(cfg))<>3 OR NOT cfg ?& ARRAY['code','startsOn','endsOn'] OR NOT (cfg->>'startsOn')::date<(cfg->>'endsOn')::date THEN RAISE EXCEPTION 'cycle fields required' USING ERRCODE='22023'; END IF;
  ELSIF input->>'kind'='TYPE' THEN
   IF (SELECT count(*) FROM jsonb_object_keys(cfg))<>2 OR NOT cfg ?& ARRAY['code','label'] THEN RAISE EXCEPTION 'type fields required' USING ERRCODE='22023'; END IF;
  ELSIF input->>'kind'='DOCUMENT_NOT_REQUIRED' THEN
   IF (SELECT count(*) FROM jsonb_object_keys(cfg))<>1 OR NOT EXISTS(SELECT FROM public.curriculum_offerings WHERE id=(cfg->>'offeringId')::uuid AND department_id=dept)
      OR EXISTS(SELECT FROM public.submission_offering_requirements WHERE offering_id=(cfg->>'offeringId')::uuid) THEN RAISE EXCEPTION 'unconfigured scoped offering required' USING ERRCODE='23514'; END IF;
  ELSE RAISE EXCEPTION 'unsupported setup kind' USING ERRCODE='22023'; END IF;
  INSERT INTO public.department_setup_requests(department_id,requested_by,role_id,kind,configuration,reason) VALUES(dept,actor,role,input->>'kind',cfg,input->>'reason') RETURNING id INTO rid;
  result:=jsonb_build_object('id',rid,'status','Awaiting authorization');
 ELSIF action='APPROVE' THEN
  INSERT INTO public.department_setup_approvals VALUES(r.id,actor,(auth->>'hodMandateId')::uuid,clock_timestamp()); result:=jsonb_build_object('id',r.id,'status','Authorized');
 ELSE
  cfg:=r.configuration;
  IF r.kind='CYCLE' THEN INSERT INTO public.academic_cycles(department_id,code,starts_on,ends_on) VALUES(dept,cfg->>'code',(cfg->>'startsOn')::date,(cfg->>'endsOn')::date) RETURNING id INTO rid;
  ELSIF r.kind='TYPE' THEN
   INSERT INTO public.curriculum_types(code,label) VALUES(cfg->>'code',cfg->>'label') RETURNING id INTO rid;
   INSERT INTO public.department_curriculum_types VALUES(dept,rid);
  ELSE
   PERFORM 1 FROM public.curriculum_offerings WHERE id=(cfg->>'offeringId')::uuid AND department_id=dept FOR UPDATE;
   IF EXISTS(SELECT FROM public.submission_offering_requirements WHERE offering_id=(cfg->>'offeringId')::uuid) THEN RAISE EXCEPTION 'configured requirement must be preserved' USING ERRCODE='23514'; END IF;
   INSERT INTO public.offering_document_dispositions VALUES((cfg->>'offeringId')::uuid,r.id,'NOT_REQUIRED');rid:=(cfg->>'offeringId')::uuid;
  END IF;
  result:=jsonb_build_object('id',rid,'status','Configured'); INSERT INTO public.department_setup_executions VALUES(r.id,actor,result,clock_timestamp());
 END IF;
 INSERT INTO public.document_command_receipts VALUES(actor,key,'SETUP_'||action,jsonb_build_object('departmentId',dept,'payload',input),result);
 INSERT INTO public.audit_events(actor_id,action,target_type,target_id,metadata) VALUES(actor,'DEPARTMENT_SETUP_'||action,'SETUP_REQUEST',coalesce(r.id,rid),jsonb_build_object('departmentId',dept,'input',input,'output',result));
 RETURN result;
END $$;
CREATE FUNCTION public.smartpro_department_setup_read(actor uuid,dept uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE manager boolean:=false;
BEGIN
 IF NOT EXISTS(SELECT FROM public.academic_governance_settings WHERE department_id=dept AND enabled) OR NOT EXISTS(SELECT FROM public.staff_department_controls WHERE department_id=dept AND enabled) THEN RAISE EXCEPTION 'department setup disabled' USING ERRCODE='42501'; END IF;
 BEGIN PERFORM public.smartpro_academic_authority(actor,dept);manager:=true; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 IF NOT manager AND NOT public.smartpro_has_role(actor,dept,'ACADEMIC_ADMIN',clock_timestamp()) THEN RAISE EXCEPTION 'scoped setup access required' USING ERRCODE='42501'; END IF;
 RETURN jsonb_build_object('requests',(SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.created_at DESC),'[]') FROM
  (SELECT r.*,a.approved_at,e.configured_at FROM public.department_setup_requests r LEFT JOIN public.department_setup_approvals a ON a.request_id=r.id LEFT JOIN public.department_setup_executions e ON e.request_id=r.id
   WHERE r.department_id=dept AND (manager OR r.requested_by=actor) ORDER BY r.created_at DESC LIMIT 50) x),
  'offerings',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM (SELECT o.id,t.label,o.semester_key FROM public.curriculum_offerings o JOIN public.curriculum_types t ON t.id=o.curriculum_type_id WHERE o.department_id=dept ORDER BY t.label LIMIT 50) x));
END $$;
CREATE FUNCTION public.smartpro_document_disposition(actor uuid,dept uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE w jsonb; p jsonb; out jsonb:='[]'; state text;
BEGIN
 w:=public.smartpro_document_workspace(actor,dept);
 FOR p IN SELECT value FROM jsonb_array_elements(w->'projects') LOOP
  state:=CASE WHEN p->'requirement'<>'null'::jsonb THEN NULL
    WHEN EXISTS(SELECT FROM public.offering_document_dispositions WHERE offering_id=(p->>'offeringId')::uuid) THEN 'NOT_REQUIRED'
    WHEN EXISTS(SELECT FROM public.department_setup_requests i WHERE department_id=dept AND kind='DOCUMENT_NOT_REQUIRED' AND configuration->>'offeringId'=p->>'offeringId' AND NOT EXISTS(SELECT FROM public.department_setup_approvals WHERE request_id=i.id)) THEN 'AWAITING_AUTHORIZATION'
    ELSE 'NOT_CONFIGURED' END;
  out:=out||jsonb_build_array(p||jsonb_build_object('projectType',(SELECT project_type FROM public.projects WHERE id=(p->>'id')::uuid),'requirementDisposition',state,'configurationPending',state='AWAITING_AUTHORIZATION'));
 END LOOP;
 RETURN jsonb_set(w,'{projects}',out);
END $$;
REVOKE ALL ON FUNCTION public.smartpro_department_setup(uuid,uuid,text,jsonb,text),public.smartpro_department_setup_read(uuid,uuid),public.smartpro_document_disposition(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_department_setup(uuid,uuid,text,jsonb,text),public.smartpro_department_setup_read(uuid,uuid),public.smartpro_document_disposition(uuid,uuid) TO smartpro_runtime;
COMMIT;
