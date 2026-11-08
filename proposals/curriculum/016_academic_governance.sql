-- Owner-run candidate after 015. Empty/disabled bootstrap; synthetic use only.
BEGIN;
DO $$ BEGIN
  IF to_regprocedure('public.smartpro_staff_command(uuid,uuid,text,uuid,jsonb,text)') IS NULL THEN
    RAISE EXCEPTION 'Install reviewed 010-015 before academic governance';
  END IF;
END $$;
CREATE TABLE public.academic_governance_settings (
  department_id uuid PRIMARY KEY REFERENCES public.departments(id),
  enabled boolean NOT NULL DEFAULT false,
  revision bigint NOT NULL DEFAULT 0 CHECK(revision>=0)
);
-- Only an owner can provision an explicit mandate for an existing HOD role.
-- A database operator/TECH_ADMIN has no application-level appointment capability.
CREATE TABLE public.academic_hod_mandates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  department_id uuid NOT NULL REFERENCES public.departments(id),
  role_assignment_id uuid NOT NULL,
  user_id uuid NOT NULL,
  role_code text NOT NULL DEFAULT 'HOD' CHECK(role_code='HOD'),
  enabled boolean NOT NULL DEFAULT false,
  FOREIGN KEY(role_assignment_id,user_id,department_id,role_code)
    REFERENCES public.department_role_assignments(id,user_id,department_id,role_code),
  UNIQUE(id,department_id)
);
CREATE TABLE public.academic_coordinator_mandates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  department_id uuid NOT NULL,
  hod_mandate_id uuid NOT NULL,
  role_assignment_id uuid NOT NULL,
  user_id uuid NOT NULL,
  role_code text NOT NULL DEFAULT 'COORDINATOR' CHECK(role_code='COORDINATOR'),
  revoked boolean NOT NULL DEFAULT false,
  appointed_by uuid NOT NULL REFERENCES public.users(id),
  reason text NOT NULL CHECK(btrim(reason)<>''),
  FOREIGN KEY(hod_mandate_id,department_id) REFERENCES public.academic_hod_mandates(id,department_id),
  FOREIGN KEY(role_assignment_id,user_id,department_id,role_code)
    REFERENCES public.department_role_assignments(id,user_id,department_id,role_code),
  UNIQUE(id,department_id)
);
CREATE TABLE public.academic_faculty_delegations (
  grant_id uuid PRIMARY KEY REFERENCES public.staff_permission_assignments(id),
  coordinator_mandate_id uuid NOT NULL REFERENCES public.academic_coordinator_mandates(id)
);
CREATE TABLE public.academic_evaluation_policies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  department_id uuid NOT NULL REFERENCES public.departments(id),
  version_no integer NOT NULL CHECK(version_no>0),
  evaluator_quorum integer NOT NULL CHECK(evaluator_quorum>0),
  aggregation text NOT NULL CHECK(aggregation IN ('MEAN','MIN','MAX','WEIGHTED_MEAN')),
  evaluator_weights jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(evaluator_weights)='object'),
  approved_by uuid NOT NULL REFERENCES public.users(id),
  approved_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  reason text NOT NULL CHECK(btrim(reason)<>''),
  CHECK((aggregation='WEIGHTED_MEAN') OR evaluator_weights='{}'),
  UNIQUE(department_id,version_no), UNIQUE(id,department_id)
);
CREATE TABLE public.academic_command_receipts (
  actor_id uuid NOT NULL REFERENCES public.users(id), request_key text NOT NULL,
  department_id uuid NOT NULL REFERENCES public.departments(id),
  action text NOT NULL, target_id uuid, input jsonb NOT NULL, output jsonb NOT NULL,
  authority jsonb NOT NULL DEFAULT '{}',
  occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(actor_id,request_key)
);
CREATE TRIGGER immutable_academic_policy BEFORE UPDATE OR DELETE ON public.academic_evaluation_policies
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation();
CREATE TRIGGER immutable_academic_receipt BEFORE UPDATE OR DELETE ON public.academic_command_receipts
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation();
CREATE TRIGGER immutable_delegation_source BEFORE UPDATE OR DELETE ON public.academic_faculty_delegations
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation();
CREATE FUNCTION public.smartpro_coordinator_history() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'retain appointment history' USING ERRCODE='23514'; END IF;
  IF (to_jsonb(NEW)-'revoked') IS DISTINCT FROM (to_jsonb(OLD)-'revoked') OR (OLD.revoked AND NOT NEW.revoked) THEN
    RAISE EXCEPTION 'append authority; revocation is final' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER freeze_coordinator_mandate BEFORE UPDATE OR DELETE ON public.academic_coordinator_mandates
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_coordinator_history();
CREATE FUNCTION public.smartpro_hod_mandate_history() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'retain HOD mandate history' USING ERRCODE='23514'; END IF;
  IF (to_jsonb(NEW)-'enabled') IS DISTINCT FROM (to_jsonb(OLD)-'enabled') THEN
    RAISE EXCEPTION 'HOD mandate identity is immutable' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER freeze_hod_mandate BEFORE UPDATE OR DELETE ON public.academic_hod_mandates
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_hod_mandate_history();
CREATE FUNCTION public.smartpro_audit_governance_bootstrap() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF TG_TABLE_NAME='academic_governance_settings' AND TG_OP='UPDATE' AND NEW.enabled=OLD.enabled THEN RETURN NULL; END IF;
  INSERT INTO public.audit_events(action,target_type,target_id,metadata)
    VALUES('ACADEMIC_BOOTSTRAP_CONFIGURED',TG_TABLE_NAME,coalesce(to_jsonb(NEW)->>'department_id',to_jsonb(OLD)->>'department_id')::uuid,
      jsonb_build_object('old',CASE WHEN TG_OP<>'INSERT' THEN to_jsonb(OLD) END,
        'new',CASE WHEN TG_OP<>'DELETE' THEN to_jsonb(NEW) END,'databaseActor',session_user));
  RETURN NULL;
END $$;
CREATE TRIGGER audit_governance_settings AFTER INSERT OR UPDATE OR DELETE ON public.academic_governance_settings
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_audit_governance_bootstrap();
CREATE TRIGGER audit_hod_mandate AFTER INSERT OR UPDATE OR DELETE ON public.academic_hod_mandates
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_audit_governance_bootstrap();
CREATE FUNCTION public.smartpro_governance_settings_history() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'disable governance; retain history' USING ERRCODE='23514'; END IF;
  IF NEW.department_id<>OLD.department_id OR NEW.revision<OLD.revision THEN
    RAISE EXCEPTION 'governance identity/revision is monotonic' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER preserve_governance_settings BEFORE UPDATE OR DELETE ON public.academic_governance_settings
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_governance_settings_history();

CREATE FUNCTION public.smartpro_academic_authority(actor uuid,dept uuid,hod_only boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE h public.academic_hod_mandates%ROWTYPE; c public.academic_coordinator_mandates%ROWTYPE; stamp timestamptz;
BEGIN
  PERFORM 1 FROM public.users WHERE id=actor AND account_status='ACTIVE' FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'active academic authority required' USING ERRCODE='42501'; END IF;
  SELECT x.* INTO h FROM public.academic_hod_mandates x WHERE x.department_id=dept AND x.user_id=actor AND x.enabled ORDER BY x.id LIMIT 1 FOR UPDATE;
  IF NOT FOUND AND NOT hod_only THEN
    SELECT x.* INTO c FROM public.academic_coordinator_mandates x JOIN public.department_role_assignments r ON r.id=x.role_assignment_id
      WHERE x.department_id=dept AND x.user_id=actor AND NOT x.revoked
        AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)
      ORDER BY x.id LIMIT 1 FOR UPDATE OF x,r;
    IF FOUND THEN SELECT x.* INTO h FROM public.academic_hod_mandates x WHERE x.id=c.hod_mandate_id AND x.enabled FOR UPDATE; END IF;
  END IF;
  IF h.id IS NULL OR (hod_only AND h.user_id<>actor) THEN
    RAISE EXCEPTION 'explicit HOD/coordinator mandate required' USING ERRCODE='42501';
  END IF;
  PERFORM 1 FROM public.department_role_assignments r JOIN public.users u ON u.id=r.user_id
    WHERE r.id=h.role_assignment_id AND u.account_status='ACTIVE' FOR UPDATE OF r FOR SHARE OF u;
  stamp:=clock_timestamp();
  IF NOT FOUND OR NOT EXISTS(SELECT FROM public.department_role_assignments r WHERE r.id=h.role_assignment_id
      AND r.valid_from<=stamp AND (r.valid_until IS NULL OR stamp<r.valid_until))
    OR (c.id IS NOT NULL AND NOT EXISTS(SELECT FROM public.department_role_assignments r WHERE r.id=c.role_assignment_id
      AND r.valid_from<=stamp AND (r.valid_until IS NULL OR stamp<r.valid_until))) THEN
    RAISE EXCEPTION 'academic authority expired' USING ERRCODE='42501';
  END IF;
  RETURN jsonb_build_object('hodMandateId',h.id,'coordinatorMandateId',c.id,'actorId',actor,
    'hodRoleId',h.role_assignment_id,'coordinatorRoleId',c.role_assignment_id,'authorizedAt',stamp);
END $$;
CREATE FUNCTION public.smartpro_academic_role_history() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF EXISTS(SELECT FROM public.academic_command_receipts r
    WHERE (r.authority->>'hodRoleId'=OLD.id::text OR r.authority->>'coordinatorRoleId'=OLD.id::text)
      AND (NEW.valid_from>r.occurred_at OR (NEW.valid_until IS NOT NULL AND NEW.valid_until<=r.occurred_at))) THEN
    RAISE EXCEPTION 'role edit invalidates academic authority history' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER preserve_academic_role_history BEFORE UPDATE OF valid_from,valid_until ON public.department_role_assignments
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_academic_role_history();

-- Keep existing 015 permissions, adding live provenance checks only for grants
-- issued through the new coordinator path. Old owner grants are not relabelled.
CREATE FUNCTION public.smartpro_delegation_authority(g uuid)
RETURNS void LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE source uuid;
BEGIN
  SELECT coordinator_mandate_id INTO source FROM public.academic_faculty_delegations WHERE grant_id=g;
  IF FOUND THEN
    PERFORM 1 FROM public.academic_coordinator_mandates c
      JOIN public.department_role_assignments cr ON cr.id=c.role_assignment_id
      JOIN public.academic_hod_mandates h ON h.id=c.hod_mandate_id
      JOIN public.department_role_assignments hr ON hr.id=h.role_assignment_id
      JOIN public.academic_governance_settings s ON s.department_id=c.department_id
      JOIN public.users cu ON cu.id=c.user_id JOIN public.users hu ON hu.id=h.user_id
      WHERE c.id=source AND NOT c.revoked AND h.enabled AND s.enabled AND cu.account_status='ACTIVE' AND hu.account_status='ACTIVE'
        AND cr.valid_from<=clock_timestamp() AND (cr.valid_until IS NULL OR clock_timestamp()<cr.valid_until)
        AND hr.valid_from<=clock_timestamp() AND (hr.valid_until IS NULL OR clock_timestamp()<hr.valid_until)
      FOR SHARE OF c,cr,h,hr,s,cu,hu;
    IF NOT FOUND OR NOT EXISTS(SELECT FROM public.academic_coordinator_mandates c
      JOIN public.department_role_assignments cr ON cr.id=c.role_assignment_id
      JOIN public.academic_hod_mandates h ON h.id=c.hod_mandate_id
      JOIN public.department_role_assignments hr ON hr.id=h.role_assignment_id
      WHERE c.id=source AND cr.valid_from<=clock_timestamp() AND (cr.valid_until IS NULL OR clock_timestamp()<cr.valid_until)
        AND hr.valid_from<=clock_timestamp() AND (hr.valid_until IS NULL OR clock_timestamp()<hr.valid_until)) THEN
      RAISE EXCEPTION 'delegation provenance no longer effective' USING ERRCODE='42501'; END IF;
  END IF;
END $$;
CREATE OR REPLACE FUNCTION public.smartpro_staff_authority(actor uuid,dept uuid,permission_name text,project uuid DEFAULT NULL,for_write boolean DEFAULT false)
RETURNS uuid LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE g uuid;
BEGIN
  PERFORM 1 FROM public.users u WHERE u.id=actor AND u.account_status='ACTIVE' FOR SHARE OF u;
  IF NOT FOUND THEN RAISE EXCEPTION 'active staff account required' USING ERRCODE='42501'; END IF;
  SELECT a.id INTO g FROM public.staff_permission_assignments a JOIN public.department_role_assignments r ON r.id=a.role_assignment_id
    WHERE a.user_id=actor AND a.department_id=dept AND a.permission=permission_name AND NOT a.revoked
      AND (a.project_id IS NULL OR a.project_id=project OR (project IS NULL AND permission_name='READ_PROJECTS'))
      AND a.valid_from<=clock_timestamp() AND (a.valid_until IS NULL OR clock_timestamp()<a.valid_until)
      AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)
      AND (NOT EXISTS(SELECT FROM public.academic_faculty_delegations WHERE grant_id=a.id) OR EXISTS(
        SELECT FROM public.academic_faculty_delegations d JOIN public.academic_coordinator_mandates c ON c.id=d.coordinator_mandate_id
        JOIN public.department_role_assignments cr ON cr.id=c.role_assignment_id JOIN public.users cu ON cu.id=c.user_id
        JOIN public.academic_hod_mandates h ON h.id=c.hod_mandate_id JOIN public.department_role_assignments hr ON hr.id=h.role_assignment_id
        JOIN public.users hu ON hu.id=h.user_id JOIN public.academic_governance_settings s ON s.department_id=c.department_id
        WHERE d.grant_id=a.id AND NOT c.revoked AND h.enabled AND s.enabled AND cu.account_status='ACTIVE' AND hu.account_status='ACTIVE'
          AND cr.valid_from<=clock_timestamp() AND (cr.valid_until IS NULL OR clock_timestamp()<cr.valid_until)
          AND hr.valid_from<=clock_timestamp() AND (hr.valid_until IS NULL OR clock_timestamp()<hr.valid_until)))
    ORDER BY a.id LIMIT 1;
  IF NOT FOUND THEN RAISE EXCEPTION 'effective staff authority required' USING ERRCODE='42501'; END IF;
  IF for_write THEN
    PERFORM 1 FROM public.staff_permission_assignments a JOIN public.department_role_assignments r ON r.id=a.role_assignment_id
      WHERE a.id=g AND NOT a.revoked AND a.valid_from<=clock_timestamp() AND (a.valid_until IS NULL OR clock_timestamp()<a.valid_until)
        AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until) FOR UPDATE OF a,r;
  ELSE
    PERFORM 1 FROM public.staff_permission_assignments a JOIN public.department_role_assignments r ON r.id=a.role_assignment_id
      WHERE a.id=g AND NOT a.revoked AND a.valid_from<=clock_timestamp() AND (a.valid_until IS NULL OR clock_timestamp()<a.valid_until)
        AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until) FOR SHARE OF a,r;
  END IF;
  IF NOT FOUND THEN RAISE EXCEPTION 'staff authority changed while waiting' USING ERRCODE='42501'; END IF;
  PERFORM public.smartpro_delegation_authority(g);
  RETURN g;
END $$;
CREATE FUNCTION public.smartpro_delegation_receipt_guard() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  PERFORM public.smartpro_delegation_authority(NEW.grant_id);
  RETURN NEW;
END $$;
CREATE TRIGGER check_delegation_at_command_completion BEFORE INSERT ON public.staff_command_receipts
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_delegation_receipt_guard();

CREATE FUNCTION public.smartpro_academic_governance(actor uuid,dept uuid,action_name text,input jsonb,request_key text)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE controls public.academic_governance_settings%ROWTYPE; auth jsonb; prior public.academic_command_receipts%ROWTYPE;
        target uuid; role_id uuid; result jsonb; stamp timestamptz; expires timestamptz; p text; row_before jsonb; row_after jsonb;
BEGIN
  IF request_key IS NULL OR request_key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
    OR jsonb_typeof(input) IS DISTINCT FROM 'object' OR length(btrim(coalesce(input->>'reason',''))) NOT BETWEEN 1 AND 500 THEN
    RAISE EXCEPTION 'invalid academic request' USING ERRCODE='22023';
  END IF;
  SELECT s.* INTO controls FROM public.academic_governance_settings s WHERE s.department_id=dept FOR UPDATE;
  IF NOT FOUND OR NOT controls.enabled THEN RAISE EXCEPTION 'academic governance disabled' USING ERRCODE='42501'; END IF;
  auth:=public.smartpro_academic_authority(actor,dept,action_name IN ('APPOINT_COORDINATOR','REVOKE_COORDINATOR'));
  SELECT r.* INTO prior FROM public.academic_command_receipts r WHERE r.actor_id=actor AND r.request_key=smartpro_academic_governance.request_key;
  IF FOUND THEN
    IF (prior.department_id,prior.action,prior.input) IS DISTINCT FROM (dept,action_name,input) THEN
      RAISE EXCEPTION 'idempotency conflict' USING ERRCODE='23505'; END IF;
    RETURN prior.output;
  END IF;
  IF coalesce(input->>'expectedRevision','') !~ '^[0-9]+$' OR controls.revision<>(input->>'expectedRevision')::bigint THEN
    RAISE EXCEPTION 'stale academic revision' USING ERRCODE='23514'; END IF;
  stamp:=clock_timestamp();
  IF action_name='APPOINT_COORDINATOR' THEN
    expires:=(input->>'validUntil')::timestamptz;
    IF expires IS NULL OR expires<=stamp THEN RAISE EXCEPTION 'finite future appointment required' USING ERRCODE='22023'; END IF;
    PERFORM 1 FROM public.users u JOIN public.department_role_assignments r ON r.user_id=u.id
      WHERE u.id=(input->>'userId')::uuid AND u.account_status='ACTIVE' AND r.department_id=dept AND r.role_code='FACULTY'
        AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until) FOR SHARE OF u,r;
    IF NOT FOUND THEN RAISE EXCEPTION 'active appointee required' USING ERRCODE='42501'; END IF;
    stamp:=clock_timestamp();
    IF expires<=stamp THEN RAISE EXCEPTION 'appointment term expired while waiting' USING ERRCODE='42501'; END IF;
    INSERT INTO public.department_role_assignments(user_id,department_id,role_code,valid_from,valid_until)
      VALUES((input->>'userId')::uuid,dept,'COORDINATOR',stamp,expires) RETURNING id INTO role_id;
    INSERT INTO public.academic_coordinator_mandates(department_id,hod_mandate_id,role_assignment_id,user_id,appointed_by,reason)
      VALUES(dept,(auth->>'hodMandateId')::uuid,role_id,(input->>'userId')::uuid,actor,btrim(input->>'reason')) RETURNING id INTO target;
  ELSIF action_name='REVOKE_COORDINATOR' THEN
    target:=(input->>'mandateId')::uuid;
    SELECT to_jsonb(x) INTO row_before FROM public.academic_coordinator_mandates x WHERE x.id=target AND x.department_id=dept
      AND x.hod_mandate_id=(auth->>'hodMandateId')::uuid FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'appointment outside authority' USING ERRCODE='42501'; END IF;
    UPDATE public.academic_coordinator_mandates SET revoked=true WHERE id=target;
    UPDATE public.staff_permission_assignments g SET revoked=true FROM public.academic_faculty_delegations d
      WHERE d.grant_id=g.id AND d.coordinator_mandate_id=target;
  ELSIF action_name='DELEGATE_FACULTY' THEN
    IF auth->>'coordinatorMandateId' IS NULL THEN RAISE EXCEPTION 'coordinator delegation required' USING ERRCODE='42501'; END IF;
    p:=input->>'permission';
    IF p IS NULL OR p NOT IN ('READ_POLICIES','READ_PROJECTS','CORRECT_PROJECT') THEN
      RAISE EXCEPTION 'routine permissions only' USING ERRCODE='42501'; END IF;
    expires:=(input->>'validUntil')::timestamptz;
    SELECT r.id INTO role_id FROM public.department_role_assignments r JOIN public.users u ON u.id=r.user_id
      WHERE r.id=(input->>'roleAssignmentId')::uuid AND r.department_id=dept AND r.role_code='FACULTY' AND u.account_status='ACTIVE'
        AND r.valid_from<=stamp AND (r.valid_until IS NULL OR stamp<r.valid_until) FOR UPDATE OF r;
    IF NOT FOUND OR expires IS NULL OR expires<=clock_timestamp() THEN RAISE EXCEPTION 'effective faculty and term required' USING ERRCODE='42501'; END IF;
    stamp:=clock_timestamp();
    IF NOT EXISTS(SELECT FROM public.department_role_assignments r WHERE r.id=role_id AND r.valid_from<=stamp AND (r.valid_until IS NULL OR stamp<r.valid_until)) THEN
      RAISE EXCEPTION 'faculty role expired while waiting' USING ERRCODE='42501'; END IF;
    INSERT INTO public.staff_permission_assignments(user_id,department_id,role_assignment_id,required_role,permission,project_id,
        valid_from,valid_until,granted_by,grant_reason)
      SELECT r.user_id,dept,r.id,'FACULTY',p,(input->>'projectId')::uuid,stamp,expires,actor,btrim(input->>'reason')
        FROM public.department_role_assignments r WHERE r.id=role_id RETURNING id INTO target;
    INSERT INTO public.academic_faculty_delegations VALUES(target,(auth->>'coordinatorMandateId')::uuid);
  ELSIF action_name='REVOKE_DELEGATION' THEN
    target:=(input->>'grantId')::uuid;
    PERFORM 1 FROM public.academic_faculty_delegations d WHERE d.grant_id=target
      AND d.coordinator_mandate_id=(auth->>'coordinatorMandateId')::uuid;
    IF NOT FOUND THEN RAISE EXCEPTION 'own delegation required' USING ERRCODE='42501'; END IF;
    SELECT to_jsonb(g) INTO row_before FROM public.staff_permission_assignments g WHERE g.id=target FOR UPDATE;
    UPDATE public.staff_permission_assignments SET revoked=true WHERE id=target;
  ELSIF action_name='CREATE_POLICY' THEN
    IF jsonb_typeof(input->'evaluatorWeights') IS DISTINCT FROM 'object'
      OR coalesce(input->>'evaluatorQuorum','') !~ '^[1-9][0-9]*$' THEN
      RAISE EXCEPTION 'explicit quorum and weights required' USING ERRCODE='22023'; END IF;
    IF input->>'aggregation'='WEIGHTED_MEAN' AND input->'evaluatorWeights'='{}' THEN
      RAISE EXCEPTION 'weighted aggregation requires explicit weights' USING ERRCODE='22023'; END IF;
    IF EXISTS(SELECT FROM jsonb_each(input->'evaluatorWeights') WHERE key IS DISTINCT FROM key::uuid::text) THEN
      RAISE EXCEPTION 'canonical evaluator UUID weight keys required' USING ERRCODE='22023'; END IF;
    FOR p IN SELECT value FROM jsonb_each_text(input->'evaluatorWeights') LOOP
      IF p !~ '^[0-9]+(\.[0-9]+)?$' OR p::numeric<=0 THEN RAISE EXCEPTION 'positive decimal weights required' USING ERRCODE='22023'; END IF;
    END LOOP;
    INSERT INTO public.academic_evaluation_policies(department_id,version_no,evaluator_quorum,aggregation,evaluator_weights,approved_by,reason)
      SELECT dept,coalesce(max(version_no),0)+1,(input->>'evaluatorQuorum')::integer,input->>'aggregation',input->'evaluatorWeights',actor,btrim(input->>'reason')
      FROM public.academic_evaluation_policies WHERE department_id=dept RETURNING id INTO target;
  ELSE RAISE EXCEPTION 'unsupported academic command' USING ERRCODE='22023';
  END IF;
  UPDATE public.department_role_assignments SET staff_authority_revision=gen_random_uuid()
    WHERE id IN ((auth->>'hodRoleId')::uuid,(auth->>'coordinatorRoleId')::uuid);
  auth:=public.smartpro_academic_authority(actor,dept,action_name IN ('APPOINT_COORDINATOR','REVOKE_COORDINATOR'));
  UPDATE public.academic_governance_settings SET revision=revision+1 WHERE department_id=dept RETURNING revision INTO controls.revision;
  IF action_name='CREATE_POLICY' THEN
    SELECT to_jsonb(x) INTO row_after FROM public.academic_evaluation_policies x WHERE x.id=target;
  ELSIF action_name IN ('APPOINT_COORDINATOR','REVOKE_COORDINATOR') THEN
    SELECT to_jsonb(x)||jsonb_build_object('effectiveRole',to_jsonb(r)) INTO row_after
      FROM public.academic_coordinator_mandates x JOIN public.department_role_assignments r ON r.id=x.role_assignment_id WHERE x.id=target;
  ELSE
    SELECT to_jsonb(x) INTO row_after FROM public.staff_permission_assignments x WHERE x.id=target;
  END IF;
  result:=jsonb_build_object('id',target,'revision',controls.revision);
  INSERT INTO public.audit_events(actor_id,action,target_type,target_id,metadata) VALUES(actor,'ACADEMIC_'||action_name,'ACADEMIC_GOVERNANCE',target,
    jsonb_build_object('departmentId',dept,'authority',auth,'old',row_before,'new',row_after,'input',input,'reason',input->>'reason'));
  INSERT INTO public.academic_command_receipts(actor_id,request_key,department_id,action,target_id,input,output,authority,occurred_at)
    VALUES(actor,request_key,dept,action_name,target,input,result,auth,(auth->>'authorizedAt')::timestamptz);
  RETURN result;
END $$;

REVOKE ALL ON TABLE public.academic_governance_settings,public.academic_hod_mandates,public.academic_coordinator_mandates,
  public.academic_faculty_delegations,public.academic_evaluation_policies,public.academic_command_receipts FROM PUBLIC,smartpro_runtime;
REVOKE ALL ON FUNCTION public.smartpro_coordinator_history(),public.smartpro_academic_authority(uuid,uuid,boolean),
  public.smartpro_hod_mandate_history(),public.smartpro_audit_governance_bootstrap(),
  public.smartpro_delegation_authority(uuid),public.smartpro_delegation_receipt_guard(),
  public.smartpro_academic_role_history(),
  public.smartpro_governance_settings_history(),
  public.smartpro_staff_authority(uuid,uuid,text,uuid,boolean),
  public.smartpro_academic_governance(uuid,uuid,text,jsonb,text) FROM PUBLIC,smartpro_runtime;
GRANT EXECUTE ON FUNCTION public.smartpro_academic_governance(uuid,uuid,text,jsonb,text) TO smartpro_runtime;
COMMIT;
