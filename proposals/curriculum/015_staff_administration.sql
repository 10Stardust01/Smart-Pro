-- Owner-run candidate 015 after activated 010-014 and reviewed runtime boundaries.
-- No automatic upgrade, role assumption, real-data activation or policy ratification.
BEGIN;
DO $$ BEGIN
  IF to_regprocedure('public.smartpro_register_student_project(uuid,uuid,text,text,text,text,text)') IS NULL THEN
    RAISE EXCEPTION 'Install activated curriculum 010-014 before staff administration';
  END IF;
END $$;
ALTER TABLE public.department_role_assignments ADD UNIQUE(id,user_id,department_id,role_code);
ALTER TABLE public.department_role_assignments ADD COLUMN staff_authority_revision uuid NOT NULL DEFAULT gen_random_uuid();
CREATE TABLE public.staff_department_controls (
  department_id uuid PRIMARY KEY REFERENCES public.departments(id),
  enabled boolean NOT NULL DEFAULT false,
  allow_title_corrections boolean NOT NULL DEFAULT false,
  revision bigint NOT NULL DEFAULT 0 CHECK(revision>=0)
);
CREATE TABLE public.staff_permission_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  department_id uuid NOT NULL,
  role_assignment_id uuid NOT NULL,
  required_role text NOT NULL CHECK(required_role IN ('HOD','COORDINATOR','FACULTY')),
  permission text NOT NULL CHECK(permission IN ('READ_POLICIES','MANAGE_OFFERINGS','MANAGE_TEAM_POLICY',
    'MANAGE_REGISTRATION_POLICY','READ_PROJECTS','CORRECT_PROJECT')),
  project_id uuid,
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_until timestamptz,
  revoked boolean NOT NULL DEFAULT false,
  authority_revision uuid NOT NULL DEFAULT gen_random_uuid(),
  granted_by uuid REFERENCES public.users(id),
  grant_reason text NOT NULL CHECK(btrim(grant_reason)<>''),
  CHECK(valid_until IS NULL OR valid_until>valid_from),
  CHECK(project_id IS NULL OR permission IN ('READ_PROJECTS','CORRECT_PROJECT')),
  CHECK(permission NOT IN ('MANAGE_OFFERINGS','MANAGE_TEAM_POLICY','MANAGE_REGISTRATION_POLICY')
        OR required_role IN ('HOD','COORDINATOR')),
  FOREIGN KEY(role_assignment_id,user_id,department_id,required_role)
    REFERENCES public.department_role_assignments(id,user_id,department_id,role_code),
  FOREIGN KEY(project_id,department_id) REFERENCES public.projects(id,department_id),
  UNIQUE(id,user_id,department_id)
);
CREATE INDEX ix_staff_authority ON public.staff_permission_assignments(user_id,department_id,permission,project_id);
CREATE INDEX ix_staff_grant_role ON public.staff_permission_assignments(role_assignment_id);
CREATE TABLE public.staff_command_receipts (
  actor_id uuid NOT NULL,
  request_key text NOT NULL CHECK(length(request_key) BETWEEN 1 AND 128 AND request_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'),
  department_id uuid NOT NULL,
  action text NOT NULL CHECK(action IN ('PUBLICATION','TEAM_POLICY','REGISTRATION','CORRECT_TITLE')),
  target_id uuid NOT NULL,
  offering_id uuid REFERENCES public.curriculum_offerings(id),
  project_id uuid REFERENCES public.projects(id),
  grant_id uuid NOT NULL,
  request_body jsonb NOT NULL CHECK(jsonb_typeof(request_body)='object'),
  response_body jsonb NOT NULL CHECK(jsonb_typeof(response_body)='object'),
  occurred_at timestamptz NOT NULL,
  PRIMARY KEY(actor_id,request_key),
  FOREIGN KEY(grant_id,actor_id,department_id) REFERENCES public.staff_permission_assignments(id,user_id,department_id),
  CHECK((action='CORRECT_TITLE' AND project_id IS NOT NULL AND project_id=target_id AND offering_id IS NULL)
     OR (action<>'CORRECT_TITLE' AND offering_id IS NOT NULL AND offering_id=target_id AND project_id IS NULL))
);
CREATE TRIGGER immutable_staff_receipt BEFORE UPDATE OR DELETE ON public.staff_command_receipts
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation();
CREATE INDEX ix_staff_receipt_grant ON public.staff_command_receipts(grant_id,occurred_at);
CREATE INDEX ix_staff_receipt_department ON public.staff_command_receipts(department_id);
CREATE FUNCTION public.smartpro_staff_control_history() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    IF EXISTS(SELECT FROM public.staff_command_receipts WHERE department_id=OLD.department_id) THEN
      RAISE EXCEPTION 'retain staff control history; disable instead' USING ERRCODE='23514';
    END IF;
    RETURN OLD;
  END IF;
  IF NEW.department_id<>OLD.department_id OR NEW.revision<OLD.revision THEN
    RAISE EXCEPTION 'staff control identity and revision are monotonic' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER freeze_staff_control_history BEFORE UPDATE OR DELETE ON public.staff_department_controls
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_staff_control_history();

CREATE FUNCTION public.smartpro_staff_grant_history() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'retain staff grant history' USING ERRCODE='23514'; END IF;
  IF (to_jsonb(NEW)-ARRAY['valid_until','revoked','authority_revision']) IS DISTINCT FROM
     (to_jsonb(OLD)-ARRAY['valid_until','revoked','authority_revision'])
    OR (OLD.revoked AND NOT NEW.revoked)
    OR (OLD.valid_until IS NOT NULL AND (NEW.valid_until IS NULL OR NEW.valid_until>OLD.valid_until))
    OR EXISTS(SELECT FROM public.staff_command_receipts r WHERE r.grant_id=OLD.id
      AND NEW.valid_until IS NOT NULL AND NEW.valid_until<=r.occurred_at) THEN
    RAISE EXCEPTION 'end grants prospectively; append new authority' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER freeze_staff_grant BEFORE UPDATE OR DELETE ON public.staff_permission_assignments
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_staff_grant_history();
CREATE FUNCTION public.smartpro_staff_role_history() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF EXISTS(SELECT FROM public.staff_command_receipts c
    JOIN public.staff_permission_assignments g ON g.id=c.grant_id WHERE g.role_assignment_id=OLD.id
    AND (NEW.valid_from>c.occurred_at OR (NEW.valid_until IS NOT NULL AND NEW.valid_until<=c.occurred_at))) THEN
    RAISE EXCEPTION 'role edit would invalidate recorded staff authority' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER preserve_staff_role_history BEFORE UPDATE OF valid_from,valid_until ON public.department_role_assignments
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_staff_role_history();
CREATE FUNCTION public.smartpro_audit_staff_role() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF EXISTS(SELECT FROM public.staff_permission_assignments WHERE role_assignment_id=OLD.id) THEN
    INSERT INTO public.audit_events(action,target_type,target_id,metadata)
      VALUES('STAFF_ROLE_AUTHORITY_CHANGED','DEPARTMENT_ROLE_ASSIGNMENT',OLD.id,
        jsonb_build_object('old',to_jsonb(OLD),'new',to_jsonb(NEW),'databaseActor',session_user));
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER audit_staff_role_scope AFTER UPDATE OF valid_from,valid_until ON public.department_role_assignments
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_audit_staff_role();
CREATE FUNCTION public.smartpro_audit_staff_configuration() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE old_row jsonb; new_row jsonb;
BEGIN
  IF TG_OP<>'INSERT' THEN old_row:=to_jsonb(OLD); END IF;
  IF TG_OP<>'DELETE' THEN new_row:=to_jsonb(NEW); END IF;
  IF TG_TABLE_NAME='staff_department_controls' AND TG_OP='UPDATE'
    AND (new_row->'enabled',new_row->'allow_title_corrections') IS NOT DISTINCT FROM
        (old_row->'enabled',old_row->'allow_title_corrections') THEN
    RETURN NULL;
  END IF;
  IF TG_TABLE_NAME='staff_permission_assignments' AND TG_OP='UPDATE'
    AND (new_row-'authority_revision') IS NOT DISTINCT FROM (old_row-'authority_revision') THEN
    RETURN NULL;
  END IF;
  INSERT INTO public.audit_events(action,target_type,target_id,metadata)
    VALUES('STAFF_AUTHORITY_CONFIGURED',TG_TABLE_NAME,
      CASE WHEN TG_TABLE_NAME='staff_department_controls' THEN coalesce(new_row->>'department_id',old_row->>'department_id')::uuid
           ELSE coalesce(new_row->>'id',old_row->>'id')::uuid END,
      jsonb_build_object('old',old_row,'new',new_row,'databaseActor',session_user));
  RETURN NULL;
END $$;
CREATE TRIGGER audit_staff_controls AFTER INSERT OR UPDATE OR DELETE ON public.staff_department_controls
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_audit_staff_configuration();
CREATE TRIGGER audit_staff_assignments AFTER INSERT OR UPDATE OR DELETE ON public.staff_permission_assignments
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_audit_staff_configuration();

-- Private capability: no caller can grant itself rights. Even HOD/coordinator
-- needs an explicit effective assignment; no role is an implicit administrator.
CREATE FUNCTION public.smartpro_staff_authority(actor uuid,dept uuid,permission_name text,project uuid DEFAULT NULL,for_write boolean DEFAULT false)
RETURNS uuid LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE grant_id uuid;
BEGIN
  PERFORM 1 FROM public.users u WHERE u.id=actor AND u.account_status='ACTIVE' FOR SHARE OF u;
  IF NOT FOUND THEN RAISE EXCEPTION 'scoped staff authority required' USING ERRCODE='42501'; END IF;
  SELECT g.id INTO grant_id FROM public.staff_permission_assignments g
    JOIN public.department_role_assignments r ON r.id=g.role_assignment_id
    WHERE g.user_id=actor AND g.department_id=dept AND g.permission=permission_name
      AND NOT g.revoked
      AND (g.project_id IS NULL OR g.project_id=project OR (project IS NULL AND permission_name='READ_PROJECTS'))
      AND g.valid_from<=clock_timestamp() AND (g.valid_until IS NULL OR clock_timestamp()<g.valid_until)
      AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)
    ORDER BY g.id LIMIT 1;
  IF NOT FOUND THEN RAISE EXCEPTION 'scoped staff authority required' USING ERRCODE='42501'; END IF;
  -- Commands take their strongest lock up front, avoiding SHARE-to-UPDATE
  -- upgrades racing with an authority revoker. Recheck after any lock wait.
  IF for_write THEN
    PERFORM 1 FROM public.staff_permission_assignments g JOIN public.department_role_assignments r ON r.id=g.role_assignment_id
      WHERE g.id=grant_id AND NOT g.revoked AND g.valid_from<=clock_timestamp()
        AND (g.valid_until IS NULL OR clock_timestamp()<g.valid_until)
        AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)
      FOR UPDATE OF g,r;
  ELSE
    PERFORM 1 FROM public.staff_permission_assignments g JOIN public.department_role_assignments r ON r.id=g.role_assignment_id
      WHERE g.id=grant_id AND NOT g.revoked AND g.valid_from<=clock_timestamp()
        AND (g.valid_until IS NULL OR clock_timestamp()<g.valid_until)
        AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)
      FOR SHARE OF g,r;
  END IF;
  IF NOT FOUND THEN RAISE EXCEPTION 'staff authority changed while waiting' USING ERRCODE='42501'; END IF;
  RETURN grant_id;
END $$;

CREATE FUNCTION public.smartpro_staff_offering_state(offering uuid) RETURNS jsonb
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
  SELECT jsonb_build_object('id',o.id,'departmentId',o.department_id,'cycleId',o.cycle_id,
    'semester',o.semester_key,'curriculumCode',t.code,'teamCreationEnabled',o.student_team_creation_enabled,
    'publication',CASE WHEN w.offering_id IS NOT NULL THEN jsonb_build_object(
       'visibleFrom',w.visible_from,'visibleUntil',w.visible_until,
       'isVisible',w.visible_from<=clock_timestamp() AND clock_timestamp()<w.visible_until) END,
    'teamPolicy',CASE WHEN v.id IS NOT NULL THEN jsonb_build_object('id',v.id,'version',v.version_no,
       'allowJoin',v.allow_join,'allowLeave',v.allow_leave,'allowTransfer',v.allow_transfer,
       'minimumMembers',v.minimum_members,'maximumMembers',v.maximum_members,'sizeMode',v.size_mode) END,
    'registrationPolicies',coalesce((SELECT jsonb_agg(jsonb_build_object('id',rv.id,'projectType',rv.project_type,
       'version',rv.version_no,'policyVersionId',rv.policy_version_id,'opensAt',rv.opens_at,'closesAt',rv.closes_at,
       'policyStatus',p.policy_status,'isOpen',p.policy_status='APPROVED' AND rv.opens_at<=clock_timestamp()
         AND clock_timestamp()<rv.closes_at) ORDER BY rv.project_type)
       FROM public.offering_project_registration_policies b
       JOIN public.project_registration_policy_versions rv ON rv.id=b.registration_policy_version_id
       JOIN public.project_policy_versions p ON p.id=rv.policy_version_id WHERE b.offering_id=o.id),'[]'::jsonb))
  FROM public.curriculum_offerings o JOIN public.curriculum_types t ON t.id=o.curriculum_type_id
  LEFT JOIN public.student_offering_windows w ON w.offering_id=o.id
  LEFT JOIN public.offering_membership_policies b ON b.offering_id=o.id
  LEFT JOIN public.team_membership_policy_versions v ON v.id=b.policy_version_id WHERE o.id=offering
$$;

ALTER TABLE public.projects ADD COLUMN admin_evidence_revision uuid NOT NULL DEFAULT gen_random_uuid();
ALTER TABLE public.projects ADD COLUMN admin_evidence_started boolean NOT NULL DEFAULT false;
CREATE FUNCTION public.smartpro_project_has_academic_evidence(project uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
  SELECT EXISTS(SELECT FROM public.projects WHERE id=project AND admin_evidence_started)
    OR EXISTS(SELECT FROM public.documents WHERE project_id=project)
    OR EXISTS(SELECT FROM public.submission_cases WHERE project_id=project)
    OR EXISTS(SELECT FROM public.project_reviews WHERE project_id=project)
    OR EXISTS(SELECT FROM public.faculty_assignments WHERE project_id=project)
    OR EXISTS(SELECT FROM public.milestones WHERE project_id=project)
$$;
CREATE INDEX ix_staff_projects_page ON public.projects(department_id,id);
CREATE INDEX ix_staff_document_evidence ON public.documents(project_id);
CREATE INDEX ix_staff_assignment_evidence ON public.faculty_assignments(project_id);
CREATE INDEX ix_staff_milestone_evidence ON public.milestones(project_id);
-- Latch activity predating 015 as well as future inserts. Otherwise deleting a
-- pre-upgrade draft could incorrectly reopen an already evidenced project.
-- The project's ALTER TABLE lock is held until this installation commits.
UPDATE public.projects p SET admin_evidence_started=true
  WHERE public.smartpro_project_has_academic_evidence(p.id);
CREATE FUNCTION public.smartpro_stamp_project_evidence() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF TG_OP='UPDATE' AND NEW.project_id IS NOT DISTINCT FROM OLD.project_id THEN RETURN NEW; END IF;
  UPDATE public.projects SET admin_evidence_revision=gen_random_uuid(),admin_evidence_started=true WHERE id=NEW.project_id;
  RETURN NEW;
END $$;
CREATE TRIGGER stamp_document_evidence BEFORE INSERT OR UPDATE OF project_id ON public.documents
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_stamp_project_evidence();
CREATE TRIGGER stamp_case_evidence BEFORE INSERT OR UPDATE OF project_id ON public.submission_cases
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_stamp_project_evidence();
CREATE TRIGGER stamp_review_evidence BEFORE INSERT OR UPDATE OF project_id ON public.project_reviews
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_stamp_project_evidence();
CREATE TRIGGER stamp_assignment_evidence BEFORE INSERT OR UPDATE OF project_id ON public.faculty_assignments
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_stamp_project_evidence();
CREATE TRIGGER stamp_milestone_evidence BEFORE INSERT OR UPDATE OF project_id ON public.milestones
  FOR EACH ROW EXECUTE FUNCTION public.smartpro_stamp_project_evidence();

CREATE FUNCTION public.smartpro_staff_command(actor uuid,dept uuid,action_name text,target uuid,input jsonb,request_key text)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE authority uuid; permission_name text; controls public.staff_department_controls%ROWTYPE;
        receipt public.staff_command_receipts%ROWTYPE; before_state jsonb; after_state jsonb; body jsonb;
        offering_record public.curriculum_offerings%ROWTYPE; project_record public.projects%ROWTYPE;
        policy_id uuid; version_no integer; start_time timestamptz; end_time timestamptz;
        authority_snapshot jsonb; effective_at timestamptz; fields text[];
BEGIN
  permission_name:=CASE action_name WHEN 'PUBLICATION' THEN 'MANAGE_OFFERINGS'
    WHEN 'TEAM_POLICY' THEN 'MANAGE_TEAM_POLICY' WHEN 'REGISTRATION' THEN 'MANAGE_REGISTRATION_POLICY'
    WHEN 'CORRECT_TITLE' THEN 'CORRECT_PROJECT' END;
  fields:=CASE action_name WHEN 'PUBLICATION' THEN ARRAY['expectedRevision','visibleFrom','visibleUntil','teamCreationEnabled','reason']
    WHEN 'TEAM_POLICY' THEN ARRAY['expectedRevision','allowJoin','allowLeave','allowTransfer','minimumMembers','maximumMembers','sizeMode','reason']
    WHEN 'REGISTRATION' THEN ARRAY['expectedRevision','projectType','policyVersionId','opensAt','closesAt','reason']
    WHEN 'CORRECT_TITLE' THEN ARRAY['expectedProjectVersion','title','reason'] END;
  IF permission_name IS NULL OR target IS NULL OR input IS NULL OR jsonb_typeof(input)<>'object'
    OR input-fields<>'{}'::jsonb OR NOT input ?& fields
    OR length(btrim(coalesce(input->>'reason',''))) NOT BETWEEN 1 AND 500
    OR request_key IS NULL OR length(request_key) NOT BETWEEN 1 AND 128
    OR request_key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$' THEN
    RAISE EXCEPTION 'invalid staff command' USING ERRCODE='22023';
  END IF;
  IF (action_name='CORRECT_TITLE' AND coalesce(input->>'expectedProjectVersion','') !~ '^[1-9][0-9]*$')
    OR (action_name<>'CORRECT_TITLE' AND coalesce(input->>'expectedRevision','') !~ '^[0-9]+$') THEN
    RAISE EXCEPTION 'explicit integer revision required' USING ERRCODE='22023';
  END IF;
  -- Serialize same-actor receipts before taking any shared authority locks.
  PERFORM 1 FROM public.users u WHERE u.id=actor AND u.account_status='ACTIVE' FOR UPDATE OF u;
  IF NOT FOUND THEN RAISE EXCEPTION 'active staff account required' USING ERRCODE='42501'; END IF;
  authority:=public.smartpro_staff_authority(actor,dept,permission_name,
      CASE WHEN action_name='CORRECT_TITLE' THEN target END,true);
  IF action_name='CORRECT_TITLE' THEN
    SELECT c.* INTO controls FROM public.staff_department_controls c WHERE c.department_id=dept FOR SHARE OF c;
  ELSE
    SELECT c.* INTO controls FROM public.staff_department_controls c WHERE c.department_id=dept FOR UPDATE OF c;
  END IF;
  IF NOT FOUND OR NOT controls.enabled OR (action_name='CORRECT_TITLE' AND NOT controls.allow_title_corrections) THEN
    RAISE EXCEPTION 'staff operation is disabled' USING ERRCODE='42501';
  END IF;
  IF NOT EXISTS(SELECT FROM public.staff_permission_assignments g
      JOIN public.department_role_assignments r ON r.id=g.role_assignment_id
      WHERE g.id=authority AND NOT g.revoked AND g.valid_from<=clock_timestamp() AND (g.valid_until IS NULL OR clock_timestamp()<g.valid_until)
        AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)) THEN
    RAISE EXCEPTION 'staff authority expired while waiting' USING ERRCODE='42501';
  END IF;
  SELECT r.* INTO receipt FROM public.staff_command_receipts r WHERE r.actor_id=actor AND r.request_key=smartpro_staff_command.request_key;
  IF FOUND THEN
    IF (receipt.department_id,receipt.action,receipt.target_id) IS DISTINCT FROM (dept,action_name,target)
      OR receipt.request_body IS DISTINCT FROM input THEN
      RAISE EXCEPTION 'staff idempotency input conflict' USING ERRCODE='23505';
    END IF;
    RETURN jsonb_build_object('replayed',true,'result',receipt.response_body);
  END IF;
  IF action_name='CORRECT_TITLE' THEN
    SELECT p.* INTO project_record FROM public.projects p WHERE p.id=target AND p.department_id=dept FOR UPDATE OF p;
    IF NOT FOUND THEN RAISE EXCEPTION 'project outside department' USING ERRCODE='42501'; END IF;
    IF project_record.row_version<>(input->>'expectedProjectVersion')::integer
      OR public.smartpro_project_has_academic_evidence(target) THEN
      RAISE EXCEPTION 'stale project or academic evidence requires separate review' USING ERRCODE='23514';
    END IF;
    IF length(btrim(coalesce(input->>'title',''))) NOT BETWEEN 1 AND 500 THEN
      RAISE EXCEPTION 'invalid project title' USING ERRCODE='22023';
    END IF;
    before_state:=jsonb_build_object('id',target,'title',project_record.title,'rowVersion',project_record.row_version,
      'teamId',project_record.team_id,'cycleId',project_record.cycle_id,'policyVersionId',project_record.policy_version_id);
    UPDATE public.projects SET title=btrim(input->>'title'),row_version=row_version+1 WHERE id=target
      RETURNING jsonb_build_object('id',id,'title',title,'rowVersion',row_version,
        'teamId',team_id,'cycleId',cycle_id,'policyVersionId',policy_version_id) INTO after_state;
  ELSE
    IF controls.revision<>(input->>'expectedRevision')::bigint THEN
      RAISE EXCEPTION 'stale department policy revision' USING ERRCODE='23514';
    END IF;
    SELECT o.* INTO offering_record FROM public.curriculum_offerings o
      WHERE o.id=target AND o.department_id=dept FOR UPDATE OF o;
    IF NOT FOUND THEN RAISE EXCEPTION 'offering outside department' USING ERRCODE='42501'; END IF;
    before_state:=public.smartpro_staff_offering_state(target);
    IF action_name='PUBLICATION' THEN
      start_time:=(input->>'visibleFrom')::timestamptz; end_time:=(input->>'visibleUntil')::timestamptz;
      IF (start_time IS NULL)<>(end_time IS NULL) OR (start_time IS NOT NULL AND start_time>=end_time)
        OR jsonb_typeof(input->'teamCreationEnabled') IS DISTINCT FROM 'boolean' THEN
        RAISE EXCEPTION 'invalid publication window' USING ERRCODE='22023';
      END IF;
      UPDATE public.curriculum_offerings SET student_team_creation_enabled=(input->>'teamCreationEnabled')::boolean WHERE id=target;
      IF start_time IS NULL THEN DELETE FROM public.student_offering_windows WHERE offering_id=target;
      ELSE
        INSERT INTO public.student_offering_windows VALUES(target,start_time,end_time)
          ON CONFLICT(offering_id) DO UPDATE SET visible_from=excluded.visible_from,visible_until=excluded.visible_until;
      END IF;
    ELSIF action_name='TEAM_POLICY' THEN
      IF jsonb_typeof(input->'allowJoin') IS DISTINCT FROM 'boolean'
        OR jsonb_typeof(input->'allowLeave') IS DISTINCT FROM 'boolean'
        OR jsonb_typeof(input->'allowTransfer') IS DISTINCT FROM 'boolean' THEN
        RAISE EXCEPTION 'invalid membership permissions' USING ERRCODE='22023';
      END IF;
      SELECT coalesce(max(v.version_no),0)+1 INTO version_no FROM public.team_membership_policy_versions v WHERE v.department_id=dept;
      INSERT INTO public.team_membership_policy_versions(department_id,version_no,allow_join,allow_leave,allow_transfer,
        minimum_members,maximum_members,size_mode)
        VALUES(dept,version_no,(input->>'allowJoin')::boolean,(input->>'allowLeave')::boolean,(input->>'allowTransfer')::boolean,
          (input->>'minimumMembers')::integer,(input->>'maximumMembers')::integer,input->>'sizeMode') RETURNING id INTO policy_id;
      INSERT INTO public.offering_membership_policies VALUES(target,offering_record.cycle_id,dept,policy_id)
        ON CONFLICT(offering_id) DO UPDATE SET policy_version_id=excluded.policy_version_id;
    ELSE
      IF coalesce(input->>'projectType','') NOT IN ('MINI','MAJOR') THEN
        RAISE EXCEPTION 'invalid project classification' USING ERRCODE='22023';
      END IF;
      policy_id:=(input->>'policyVersionId')::uuid;
      start_time:=(input->>'opensAt')::timestamptz; end_time:=(input->>'closesAt')::timestamptz;
      IF policy_id IS NULL AND start_time IS NULL AND end_time IS NULL THEN
        DELETE FROM public.offering_project_registration_policies WHERE offering_id=target AND project_type=input->>'projectType';
      ELSE
        IF policy_id IS NULL OR start_time IS NULL OR end_time IS NULL OR start_time>=end_time THEN
          RAISE EXCEPTION 'invalid registration window' USING ERRCODE='22023';
        END IF;
        PERFORM 1 FROM public.project_policy_versions p WHERE p.id=policy_id AND p.department_id=dept
          AND p.project_type=input->>'projectType' AND p.policy_status='APPROVED'
          AND p.policy_data->'studentRegistration'='{"enabled":true}'::jsonb FOR SHARE OF p;
        IF NOT FOUND THEN RAISE EXCEPTION 'approved supported department policy required' USING ERRCODE='42501'; END IF;
        SELECT coalesce(max(v.version_no),0)+1 INTO version_no FROM public.project_registration_policy_versions v
          WHERE v.offering_id=target AND v.project_type=input->>'projectType';
        INSERT INTO public.project_registration_policy_versions(offering_id,cycle_id,department_id,project_type,
          policy_version_id,version_no,opens_at,closes_at)
          VALUES(target,offering_record.cycle_id,dept,input->>'projectType',policy_id,version_no,start_time,end_time) RETURNING id INTO policy_id;
        INSERT INTO public.offering_project_registration_policies VALUES(target,input->>'projectType',policy_id)
          ON CONFLICT(offering_id,project_type) DO UPDATE SET registration_policy_version_id=excluded.registration_policy_version_id;
      END IF;
    END IF;
    UPDATE public.staff_department_controls SET revision=revision+1 WHERE department_id=dept RETURNING revision INTO controls.revision;
    after_state:=public.smartpro_staff_offering_state(target);
  END IF;
  effective_at:=clock_timestamp();
  SELECT jsonb_build_object('grantId',g.id,'roleAssignmentId',r.id,'role',r.role_code,
    'permission',g.permission,'projectId',g.project_id,'authorizedAt',effective_at,
    'grantValidFrom',g.valid_from,'grantValidUntil',g.valid_until,'grantRevoked',g.revoked,
    'roleValidFrom',r.valid_from,'roleValidUntil',r.valid_until)
    INTO authority_snapshot FROM public.staff_permission_assignments g
    JOIN public.department_role_assignments r ON r.id=g.role_assignment_id
    WHERE g.id=authority AND NOT g.revoked AND g.valid_from<=effective_at AND (g.valid_until IS NULL OR effective_at<g.valid_until)
      AND r.valid_from<=effective_at AND (r.valid_until IS NULL OR effective_at<r.valid_until);
  IF NOT FOUND THEN RAISE EXCEPTION 'staff authority expired during command' USING ERRCODE='42501'; END IF;
  -- Locks alone do not invalidate an older REPEATABLE READ owner snapshot.
  -- Real revision writes force retroactive role/grant edits to retry, where
  -- the history guards can see this command's committed receipt.
  UPDATE public.staff_permission_assignments SET authority_revision=gen_random_uuid() WHERE id=authority;
  UPDATE public.department_role_assignments SET staff_authority_revision=gen_random_uuid()
    WHERE id=(SELECT g.role_assignment_id FROM public.staff_permission_assignments g WHERE g.id=authority);
  body:=jsonb_build_object('departmentId',dept,'action',action_name,'targetId',target,
    'revision',controls.revision,'state',after_state);
  INSERT INTO public.audit_events(actor_id,project_id,action,target_type,target_id,metadata)
    VALUES(actor,CASE WHEN action_name='CORRECT_TITLE' THEN target END,'STAFF_'||action_name,
      CASE WHEN action_name='CORRECT_TITLE' THEN 'PROJECT' ELSE 'CURRICULUM_OFFERING' END,target,
      jsonb_build_object('departmentId',dept,'reason',btrim(input->>'reason'),'old',before_state,'new',after_state,
                        'authority',authority_snapshot,'revision',controls.revision));
  INSERT INTO public.staff_command_receipts(actor_id,request_key,department_id,action,target_id,offering_id,
    project_id,grant_id,request_body,response_body,occurred_at)
    VALUES(actor,request_key,dept,action_name,target,CASE WHEN action_name<>'CORRECT_TITLE' THEN target END,
      CASE WHEN action_name='CORRECT_TITLE' THEN target END,authority,input,body,effective_at);
  RETURN jsonb_build_object('replayed',false,'result',body);
END $$;

CREATE FUNCTION public.smartpro_staff_policies(actor uuid,dept uuid,after_id uuid DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE revision bigint; page jsonb; next_cursor uuid;
BEGIN
  PERFORM public.smartpro_staff_authority(actor,dept,'READ_POLICIES');
  SELECT c.revision INTO revision FROM public.staff_department_controls c WHERE c.department_id=dept AND c.enabled FOR SHARE OF c;
  IF NOT FOUND THEN RAISE EXCEPTION 'staff administration disabled' USING ERRCODE='42501'; END IF;
  PERFORM public.smartpro_staff_authority(actor,dept,'READ_POLICIES');
  WITH candidates AS (SELECT o.id FROM public.curriculum_offerings o WHERE o.department_id=dept
    AND (after_id IS NULL OR o.id>after_id) ORDER BY o.id LIMIT 51),
  numbered AS (SELECT *,row_number() OVER(ORDER BY id) AS position FROM candidates)
  SELECT coalesce(jsonb_agg(public.smartpro_staff_offering_state(id) ORDER BY id) FILTER(WHERE position<=50),'[]'::jsonb),
    CASE WHEN count(*)>50 THEN (array_agg(id ORDER BY id) FILTER(WHERE position=50))[1] END
    INTO page,next_cursor FROM numbered;
  RETURN jsonb_build_object('departmentId',dept,'revision',revision,'results',page,'nextCursor',next_cursor);
END $$;
CREATE FUNCTION public.smartpro_staff_projects(actor uuid,dept uuid,after_id uuid DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE page jsonb; next_cursor uuid;
BEGIN
  PERFORM public.smartpro_staff_authority(actor,dept,'READ_PROJECTS');
  PERFORM 1 FROM public.staff_department_controls c WHERE c.department_id=dept AND c.enabled FOR SHARE OF c;
  IF NOT FOUND THEN RAISE EXCEPTION 'staff administration disabled' USING ERRCODE='42501'; END IF;
  PERFORM public.smartpro_staff_authority(actor,dept,'READ_PROJECTS');
  WITH candidates AS (
    SELECT p.id,p.title,p.project_code,p.project_type,p.team_id,p.cycle_id,p.row_version,
      public.smartpro_project_has_academic_evidence(p.id) AS has_evidence
    FROM public.projects p WHERE p.department_id=dept AND (after_id IS NULL OR p.id>after_id)
      AND EXISTS(SELECT FROM public.staff_permission_assignments g JOIN public.department_role_assignments r ON r.id=g.role_assignment_id
        WHERE g.user_id=actor AND g.department_id=dept AND g.permission='READ_PROJECTS'
          AND NOT g.revoked
          AND (g.project_id IS NULL OR g.project_id=p.id)
          AND g.valid_from<=clock_timestamp() AND (g.valid_until IS NULL OR clock_timestamp()<g.valid_until)
          AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until))
    ORDER BY p.id LIMIT 51), numbered AS (SELECT *,row_number() OVER(ORDER BY id) AS position FROM candidates)
  SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'title',title,'projectCode',project_code,'projectType',project_type,
    'teamId',team_id,'cycleId',cycle_id,'rowVersion',row_version,'hasAcademicEvidence',has_evidence)
    ORDER BY id) FILTER(WHERE position<=50),'[]'::jsonb),
    CASE WHEN count(*)>50 THEN (array_agg(id ORDER BY id) FILTER(WHERE position=50))[1] END
    INTO page,next_cursor FROM numbered;
  RETURN jsonb_build_object('departmentId',dept,'results',page,'nextCursor',next_cursor);
END $$;

REVOKE ALL ON TABLE public.staff_department_controls,public.staff_permission_assignments,public.staff_command_receipts FROM PUBLIC,smartpro_runtime;
REVOKE ALL ON FUNCTION public.smartpro_staff_grant_history(),public.smartpro_audit_staff_configuration(),
  public.smartpro_staff_role_history(),public.smartpro_staff_control_history(),public.smartpro_audit_staff_role(),
  public.smartpro_staff_authority(uuid,uuid,text,uuid,boolean),public.smartpro_staff_offering_state(uuid),
  public.smartpro_project_has_academic_evidence(uuid),public.smartpro_stamp_project_evidence(),
  public.smartpro_staff_command(uuid,uuid,text,uuid,jsonb,text),public.smartpro_staff_policies(uuid,uuid,uuid),
  public.smartpro_staff_projects(uuid,uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_staff_command(uuid,uuid,text,uuid,jsonb,text),
  public.smartpro_staff_policies(uuid,uuid,uuid),public.smartpro_staff_projects(uuid,uuid,uuid) TO smartpro_runtime;
COMMIT;
