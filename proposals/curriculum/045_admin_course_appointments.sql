-- Separate offering appointments from the term of a particular HOD.
BEGIN;

ALTER TABLE public.academic_coordinator_mandates ALTER COLUMN hod_mandate_id DROP NOT NULL;

DO $migration$
DECLARE definition text; first_at integer; last_at integer;
BEGIN
  definition:=pg_get_functiondef('public.smartpro_course_coordinators(uuid)'::regprocedure);
  definition:=replace(definition,' JOIN public.academic_hod_mandates h ON h.id=m.hod_mandate_id','');
  definition:=replace(definition,' AND NOT m.revoked AND h.enabled',' AND NOT m.revoked');
  definition:=replace(definition,' AND public.smartpro_has_role(h.user_id,o.department_id,''HOD'',clock_timestamp())','');
  EXECUTE definition;

  definition:=pg_get_functiondef('public.smartpro_appoint_course(uuid,uuid,text,jsonb,text)'::regprocedure);
  first_at:=strpos(definition,' IF role=''HOD'' THEN');
  last_at:=strpos(definition,' PERFORM 1 FROM public.academic_governance_settings');
  IF first_at=0 OR last_at<=first_at THEN RAISE EXCEPTION 'Reviewed coordinator appointment command required'; END IF;
  definition:=left(definition,first_at-1)||$admin$
 IF role IS DISTINCT FROM 'Admin' THEN RAISE EXCEPTION 'Department Admin required' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.academic_governance_settings WHERE department_id=o.department_id AND enabled FOR UPDATE;
 IF NOT FOUND OR NOT EXISTS(SELECT FROM public.staff_department_controls WHERE department_id=o.department_id AND enabled) THEN
   RAISE EXCEPTION 'Department operations disabled' USING ERRCODE='42501';
 END IF;
 SELECT r.id INTO role_id FROM public.department_role_assignments r JOIN public.users u ON u.id=r.user_id
 WHERE r.user_id=actor AND r.department_id=o.department_id AND r.role_code='ACADEMIC_ADMIN'
   AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until)
   AND u.account_status='ACTIVE' ORDER BY r.id LIMIT 1 FOR SHARE OF r,u;
 IF role_id IS NULL THEN RAISE EXCEPTION 'Effective Department Admin required' USING ERRCODE='42501'; END IF;
 auth:=jsonb_build_object('source','ADMIN_APPOINTMENT','adminRoleId',role_id,'actorId',actor);
$admin$||substr(definition,last_at);
  definition:=replace(definition,$old$auth||jsonb_build_object('source',CASE WHEN role='Admin' THEN 'EXTERNAL_INSTRUCTION' ELSE 'HOD_COMMAND' END,'instruction',input->'authority')$old$,'auth');
  definition:=replace(definition,$old$IF role='Admin' THEN PERFORM public.smartpro_operational_authority(actor,o.department_id,input->'authority'); ELSE PERFORM public.smartpro_academic_authority(actor,o.department_id,true); END IF;$old$,
    $new$IF NOT EXISTS(SELECT FROM public.department_role_assignments WHERE id=(auth->>'adminRoleId')::uuid
      AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR clock_timestamp()<valid_until)) THEN
    RAISE EXCEPTION 'Department Admin appointment expired' USING ERRCODE='42501';
  END IF;$new$);
  IF strpos(definition,'smartpro_operational_authority')>0 THEN RAISE EXCEPTION 'Legacy appointment check remains'; END IF;
  EXECUTE definition;

  definition:=pg_get_functiondef('public.smartpro_role_choices(uuid)'::regprocedure);
  definition:=replace(definition,' IF EXISTS(SELECT FROM public.academic_coordinator_mandates',
    $scope$ IF EXISTS(SELECT FROM public.curriculum_offerings o CROSS JOIN LATERAL public.smartpro_course_coordinators(o.id) c
      WHERE o.department_id=dept AND c.user_id=actor) OR EXISTS(SELECT FROM public.academic_coordinator_mandates$scope$);
  EXECUTE definition;

  definition:=pg_get_functiondef('public.smartpro_academic_authority(uuid,uuid,boolean)'::regprocedure);
  definition:=replace(definition,'  IF NOT FOUND AND NOT hod_only THEN',$scope$
  IF NOT FOUND AND NOT hod_only THEN
    SELECT m.* INTO c FROM public.curriculum_offerings o
    CROSS JOIN LATERAL public.smartpro_course_coordinators(o.id) v
    JOIN public.academic_coordinator_mandates m ON m.id=v.mandate_id
    JOIN public.department_role_assignments r ON r.id=m.role_assignment_id
    WHERE o.department_id=dept AND v.user_id=actor ORDER BY m.id LIMIT 1 FOR UPDATE OF m,r;
    IF FOUND THEN
      RETURN jsonb_build_object('hodMandateId',c.hod_mandate_id,'coordinatorMandateId',c.id,
        'actorId',actor,'coordinatorRoleId',c.role_assignment_id,'authorizedAt',clock_timestamp());
    END IF;$scope$);
  EXECUTE definition;

  definition:=pg_get_functiondef('public.smartpro_project_operation(uuid,uuid,text,jsonb,text)'::regprocedure);
  first_at:=strpos(definition,'  SELECT m.id INTO rid FROM public.academic_coordinator_mandates');
  last_at:=strpos(definition,'  IF rid IS NULL THEN');
  IF first_at=0 OR last_at<=first_at THEN RAISE EXCEPTION 'Reviewed guide and schedule command required'; END IF;
  definition:=left(definition,first_at-1)||$scope$
  SELECT v.mandate_id INTO rid FROM public.smartpro_course_coordinators(coalesce(
    public.smartpro_course_project_offering((input->>'projectId')::uuid),
    public.smartpro_course_project_offering((SELECT project_id FROM public.project_reviews WHERE id=(input->>'reviewId')::uuid)))) v
  WHERE v.user_id=actor;
$scope$||substr(definition,last_at);
  first_at:=strpos(definition,'   NOT EXISTS(SELECT FROM public.academic_coordinator_mandates');
  last_at:=strpos(definition,'   OR NOT EXISTS(SELECT FROM public.coordinator_operation_grants');
  IF first_at=0 OR last_at<=first_at THEN RAISE EXCEPTION 'Reviewed operation reauthorization required'; END IF;
  definition:=left(definition,first_at-1)||$scope$
   NOT EXISTS(SELECT FROM public.smartpro_course_coordinators(public.smartpro_course_project_offering(coalesce(p.id,r.project_id))) v
     WHERE v.mandate_id=(auth->>'coordinatorMandateId')::uuid AND v.user_id=actor)
$scope$||substr(definition,last_at);
  EXECUTE definition;

  definition:=pg_get_functiondef('public.smartpro_manage_assignment(uuid,uuid,text,jsonb,text)'::regprocedure);
  first_at:=strpos(definition,'   SELECT m.id INTO mandate FROM public.academic_coordinator_mandates');
  last_at:=strpos(definition,'   IF assignment.assignment_type=''GUIDE'' THEN');
  IF first_at=0 OR last_at<=first_at THEN RAISE EXCEPTION 'Reviewed assignment command required'; END IF;
  definition:=left(definition,first_at-1)||$scope$
   SELECT v.mandate_id INTO mandate FROM public.smartpro_course_coordinators(
     public.smartpro_course_project_offering(assignment.project_id)) v WHERE v.user_id=actor;
$scope$||substr(definition,last_at);
  EXECUTE definition;

  definition:=pg_get_functiondef('public.smartpro_academic_governance(uuid,uuid,text,jsonb,text)'::regprocedure);
  definition:=replace(definition,'  stamp:=clock_timestamp();',$scope$
  IF action_name='REVOKE_COORDINATOR' AND EXISTS(
    SELECT FROM public.course_coordinator_versions WHERE mandate_id=(input->>'mandateId')::uuid
  ) THEN RAISE EXCEPTION 'Department Admin manages course appointments' USING ERRCODE='42501'; END IF;
  stamp:=clock_timestamp();$scope$);
  EXECUTE definition;
END
$migration$;

DO $migration$
DECLARE definition text; marker text:='IF NOT public.smartpro_course_access(actor,';
BEGIN
  definition:=pg_get_functiondef('public.smartpro_academic_review_command(uuid,uuid,text,jsonb,text)'::regprocedure);
  IF strpos(definition,marker)=0 THEN RAISE EXCEPTION 'Reviewed course review guard required'; END IF;
  definition:=replace(definition,marker,$scope$IF input->>'_actingRole' IS DISTINCT FROM 'HOD'
    OR NOT public.smartpro_course_access(actor,$scope$);
  definition:=replace(definition,'prior.action,prior.input) IS DISTINCT FROM (dept,action_name,input)',
    $scope$prior.action,prior.input) IS DISTINCT FROM (dept,action_name,
      CASE WHEN prior.input ? '_actingRole' THEN input ELSE input-'_actingRole' END)$scope$);
  EXECUTE definition;
  definition:=pg_get_functiondef('public.smartpro_document_command(uuid,uuid,text,jsonb,text)'::regprocedure);
  IF strpos(definition,marker)=0 THEN RAISE EXCEPTION 'Reviewed course reviewer guard required'; END IF;
  definition:=replace(definition,marker,$scope$IF input->>'_actingRole' IS DISTINCT FROM 'HOD'
    OR NOT public.smartpro_course_access(actor,$scope$);
  definition:=replace(definition,'  IF old.action<>action OR old.input<>input THEN',$scope$
  IF old.action<>action OR old.input<>(CASE WHEN old.input ? '_actingRole' THEN input ELSE input-'_actingRole' END) THEN$scope$);
  EXECUTE definition;
END
$migration$;

COMMIT;
