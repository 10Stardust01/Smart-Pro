-- Offering-scoped accountable coordinators; no appointment backfill.
BEGIN;
DO $$ BEGIN IF to_regclass('public.guide_synopsis_responsibilities') IS NULL THEN RAISE EXCEPTION 'Reviewed 036 required'; END IF; END $$;
CREATE TABLE public.course_coordinator_versions(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),offering_id uuid NOT NULL REFERENCES curriculum_offerings(id),user_id uuid NOT NULL REFERENCES users(id),
 version integer NOT NULL CHECK(version>0),supersedes_id uuid,mandate_id uuid NOT NULL UNIQUE REFERENCES academic_coordinator_mandates(id),
 active boolean NOT NULL,valid_from timestamptz NOT NULL,valid_until timestamptz NOT NULL CHECK(valid_from<valid_until),
 responsibilities text[] NOT NULL CHECK(responsibilities<@ARRAY['OVERVIEW','REQUIREMENTS','PLAN','GUIDE','EVALUATORS','SUBMISSIONS','DEADLINES','RESULTS','CORRECTIONS','HISTORY']::text[]),
 actor_id uuid NOT NULL REFERENCES users(id),authority jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(offering_id,user_id,version),UNIQUE(id,offering_id,user_id),
 FOREIGN KEY(supersedes_id,offering_id,user_id) REFERENCES course_coordinator_versions(id,offering_id,user_id));
CREATE INDEX course_coordinator_latest ON public.course_coordinator_versions(offering_id,user_id,version DESC);
CREATE TRIGGER immutable_course_coordinator BEFORE UPDATE OR DELETE ON public.course_coordinator_versions FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation();
REVOKE ALL ON public.course_coordinator_versions FROM PUBLIC,smartpro_runtime;
CREATE FUNCTION public.smartpro_course_coordinators(oid uuid) RETURNS SETOF public.course_coordinator_versions
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT v.* FROM (SELECT DISTINCT ON(user_id) * FROM public.course_coordinator_versions WHERE offering_id=oid ORDER BY user_id,version DESC)v
 JOIN public.curriculum_offerings o ON o.id=v.offering_id JOIN public.academic_coordinator_mandates m ON m.id=v.mandate_id
 JOIN public.academic_hod_mandates h ON h.id=m.hod_mandate_id
 WHERE v.active AND v.valid_from<=clock_timestamp() AND clock_timestamp()<v.valid_until AND NOT m.revoked AND h.enabled
 AND public.smartpro_has_role(v.user_id,o.department_id,'COORDINATOR',clock_timestamp()) AND public.smartpro_has_role(v.user_id,o.department_id,'FACULTY',clock_timestamp())
 AND public.smartpro_has_role(h.user_id,o.department_id,'HOD',clock_timestamp())
 AND EXISTS(SELECT FROM public.academic_governance_settings WHERE department_id=o.department_id AND enabled)
 AND EXISTS(SELECT FROM public.staff_department_controls WHERE department_id=o.department_id AND enabled);
$$;
CREATE FUNCTION public.smartpro_course_access(actor uuid,oid uuid,permission text,acting_role text) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE dept uuid;
BEGIN
 SELECT department_id INTO dept FROM public.curriculum_offerings WHERE id=oid;
 IF NOT FOUND OR NOT public.smartpro_role_choices(actor) ? acting_role THEN RETURN false; END IF;
 IF acting_role='HOD' THEN
  BEGIN PERFORM public.smartpro_academic_authority(actor,dept,true); RETURN true; EXCEPTION WHEN insufficient_privilege THEN RETURN false; END;
 END IF;
 RETURN acting_role='Coordinator' AND EXISTS(SELECT FROM public.smartpro_course_coordinators(oid) c WHERE c.user_id=actor AND (permission='READ' OR permission=ANY(c.responsibilities)));
END $$;
CREATE FUNCTION public.smartpro_course_authority(actor uuid,oid uuid,permission text,acting_role text) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 PERFORM 1 FROM public.academic_governance_settings s JOIN public.curriculum_offerings o ON o.department_id=s.department_id WHERE o.id=oid AND s.enabled FOR UPDATE OF s;
 PERFORM 1 FROM public.curriculum_offerings WHERE id=oid FOR UPDATE;
 IF NOT public.smartpro_course_access(actor,oid,permission,acting_role) THEN RAISE EXCEPTION 'Current offering responsibility required' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.course_coordinator_versions WHERE id IN(SELECT id FROM public.smartpro_course_coordinators(oid) WHERE user_id=actor) FOR SHARE;
 IF NOT public.smartpro_course_access(actor,oid,permission,acting_role) THEN RAISE EXCEPTION 'Offering responsibility expired' USING ERRCODE='42501'; END IF;
END $$;
CREATE FUNCTION public.smartpro_appoint_course(actor uuid,oid uuid,action text,input jsonb,key text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE o public.curriculum_offerings%ROWTYPE; auth jsonb; prior public.document_command_receipts%ROWTYPE; old public.course_coordinator_versions%ROWTYPE;
 uid uuid; role_id uuid; mandate uuid; target uuid; expiry timestamptz; stamp timestamptz; result jsonb; role text;
BEGIN
 SELECT * INTO o FROM public.curriculum_offerings WHERE id=oid;
 IF NOT FOUND THEN RAISE EXCEPTION 'Offering required' USING ERRCODE='42501'; END IF;
 role:=input->>'_actingRole';
 IF role='HOD' THEN auth:=public.smartpro_academic_authority(actor,o.department_id,true);
 ELSIF role='Admin' THEN auth:=public.smartpro_operational_authority(actor,o.department_id,input->'authority');
 ELSE RAISE EXCEPTION 'HOD or instructed Admin required' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.academic_governance_settings WHERE department_id=o.department_id AND enabled FOR UPDATE;
 PERFORM 1 FROM public.curriculum_offerings WHERE id=oid FOR UPDATE;
 IF key IS NULL OR key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' OR action<>'APPOINT' THEN RAISE EXCEPTION 'Appointment command required' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(actor::text||':course:'||key,0));
 SELECT * INTO prior FROM public.document_command_receipts WHERE actor_id=actor AND request_key=key;
 IF FOUND THEN IF prior.action<>'COURSE_APPOINT' OR prior.input<>jsonb_build_object('offeringId',oid,'payload',input) THEN RAISE EXCEPTION 'Retry changed' USING ERRCODE='23514'; END IF; RETURN prior.output; END IF;
 uid:=(input->>'userId')::uuid;
 SELECT * INTO old FROM public.course_coordinator_versions WHERE offering_id=oid AND user_id=uid ORDER BY version DESC LIMIT 1;
 IF coalesce(old.version,0) IS DISTINCT FROM (input->>'expectedVersion')::integer THEN RAISE EXCEPTION 'Appointment changed; refresh' USING ERRCODE='23514'; END IF;
 IF jsonb_typeof(input->'responsibilities') IS DISTINCT FROM 'array' OR jsonb_typeof(input->'active') IS DISTINCT FROM 'boolean' THEN RAISE EXCEPTION 'Explicit responsibilities and state required' USING ERRCODE='22023'; END IF;
 PERFORM 1 FROM public.department_role_assignments r JOIN public.users u ON u.id=r.user_id WHERE r.user_id=uid AND r.department_id=o.department_id AND r.role_code='FACULTY' AND u.account_status='ACTIVE' AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until) FOR SHARE OF r,u;
 IF NOT FOUND THEN RAISE EXCEPTION 'Active department faculty required' USING ERRCODE='42501'; END IF;
 stamp:=clock_timestamp();expiry:=(input->>'validUntil')::timestamptz;
 IF expiry IS NULL OR expiry<=stamp OR expiry>(SELECT (ends_on+1)::timestamptz FROM public.academic_cycles WHERE id=o.cycle_id) THEN RAISE EXCEPTION 'Finite term within the offering cycle required' USING ERRCODE='22023'; END IF;
 INSERT INTO public.department_role_assignments(user_id,department_id,role_code,valid_from,valid_until) VALUES(uid,o.department_id,'COORDINATOR',stamp,expiry) RETURNING id INTO role_id;
 INSERT INTO public.academic_coordinator_mandates(department_id,hod_mandate_id,role_assignment_id,user_id,appointed_by,reason)
 VALUES(o.department_id,(auth->>'hodMandateId')::uuid,role_id,uid,actor,coalesce(input->>'reason','')) RETURNING id INTO mandate;
 INSERT INTO public.course_coordinator_versions(offering_id,user_id,version,supersedes_id,mandate_id,active,valid_from,valid_until,responsibilities,actor_id,authority)
 VALUES(oid,uid,coalesce(old.version,0)+1,old.id,mandate,(input->>'active')::boolean,stamp,expiry,ARRAY(SELECT value FROM jsonb_array_elements_text(input->'responsibilities')),actor,auth||jsonb_build_object('source',CASE WHEN role='Admin' THEN 'EXTERNAL_INSTRUCTION' ELSE 'HOD_COMMAND' END,'instruction',input->'authority')) RETURNING id INTO target;
 INSERT INTO public.coordinator_operation_grants(mandate_id,operation,valid_until,granted_by,reason)
 SELECT mandate,x,expiry,actor,'' FROM unnest(ARRAY['GUIDE','SCHEDULE']) x WHERE (x='GUIDE' AND input->'responsibilities' ? 'GUIDE') OR (x='SCHEDULE' AND input->'responsibilities' ? 'PLAN');
 IF old.id IS NOT NULL THEN UPDATE public.academic_coordinator_mandates SET revoked=true WHERE id=old.mandate_id; END IF;
 IF o.availability='ACTIVE' AND NOT EXISTS(SELECT FROM public.smartpro_course_coordinators(oid)) THEN RAISE EXCEPTION 'Appoint a replacement or pause the offering before removing its last coordinator' USING ERRCODE='23514'; END IF;
 IF role='Admin' THEN PERFORM public.smartpro_operational_authority(actor,o.department_id,input->'authority'); ELSE PERFORM public.smartpro_academic_authority(actor,o.department_id,true); END IF;
 result:=jsonb_build_object('id',target,'version',coalesce(old.version,0)+1,'offeringId',oid);
 INSERT INTO public.document_command_receipts VALUES(actor,key,'COURSE_APPOINT',jsonb_build_object('offeringId',oid,'payload',input),result);
 INSERT INTO public.audit_events(actor_id,action,target_type,target_id,metadata) VALUES(actor,'COURSE_COORDINATOR_APPOINTMENT','OFFERING',oid,jsonb_build_object('before',to_jsonb(old),'after',(SELECT to_jsonb(v) FROM public.course_coordinator_versions v WHERE id=target),'authority',auth));
 RETURN result;
END $$;
CREATE FUNCTION public.smartpro_course_catalog(actor uuid,dept uuid,acting_role text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF acting_role='Admin' THEN PERFORM public.smartpro_department_setup_read(actor,dept);
 ELSIF acting_role='HOD' THEN PERFORM public.smartpro_academic_authority(actor,dept,true);
 ELSIF acting_role<>'Coordinator' OR NOT public.smartpro_role_choices(actor) ? acting_role THEN RAISE EXCEPTION 'Course management responsibility required' USING ERRCODE='42501'; END IF;
 RETURN jsonb_build_object('offerings',(SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY label,semester_key),'[]') FROM(
 SELECT o.*,ct.label,c.code AS cycle_label,EXISTS(SELECT FROM public.smartpro_course_coordinators(o.id)) AS has_coordinator,
 coalesce((SELECT to_jsonb(a.responsibilities) FROM public.smartpro_course_coordinators(o.id) a WHERE user_id=actor),'[]') AS responsibilities,
 (SELECT coalesce(jsonb_agg(to_jsonb(v)||jsonb_build_object('name',u.display_name,'current',v.id IN(SELECT id FROM public.smartpro_course_coordinators(o.id))) ORDER BY v.created_at DESC),'[]') FROM public.course_coordinator_versions v JOIN public.users u ON u.id=v.user_id WHERE offering_id=o.id) AS appointments
 FROM public.curriculum_offerings o JOIN public.curriculum_types ct ON ct.id=o.curriculum_type_id JOIN public.academic_cycles c ON c.id=o.cycle_id
 WHERE o.department_id=dept AND (acting_role IN('HOD','Admin') OR public.smartpro_course_access(actor,o.id,'READ',acting_role)) ORDER BY ct.label,o.id LIMIT 200)x),
 'faculty',(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM(SELECT DISTINCT u.id,u.display_name FROM public.users u JOIN public.department_role_assignments r ON r.user_id=u.id WHERE r.department_id=dept AND r.role_code='FACULTY' AND u.account_status='ACTIVE' AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until) ORDER BY u.display_name LIMIT 200)x));
END $$;
-- Existing APIs keep their contracts; eligibility is additionally fail-closed.
DO $$ DECLARE def text; BEGIN
 def:=pg_get_functiondef('public.smartpro_student_offerings(uuid,uuid)'::regprocedure);
 def:=replace(def,'WHERE o.department_id=', 'WHERE EXISTS(SELECT FROM public.smartpro_course_coordinators(o.id)) AND o.department_id=');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_create_student_team(uuid,uuid,text,text,text)'::regprocedure);
 def:=replace(def,'effective_at:=clock_timestamp();',E'IF NOT EXISTS(SELECT FROM public.smartpro_course_coordinators(p_offering_id)) THEN RAISE EXCEPTION ''Offering coordinator required'' USING ERRCODE=''42501''; END IF;\n  effective_at:=clock_timestamp();');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_register_student_project(uuid,uuid,text,text,text,text,text)'::regprocedure);
 def:=replace(def,'IF previous.project_id IS NULL THEN',E'IF previous.project_id IS NULL THEN\n IF NOT EXISTS(SELECT FROM public.smartpro_course_coordinators(offering)) THEN RAISE EXCEPTION ''Offering coordinator required'' USING ERRCODE=''42501''; END IF;');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_proposal_offering(uuid,uuid)'::regprocedure);
 def:=replace(def,'BEGIN',E'BEGIN
 IF NOT EXISTS(SELECT FROM public.smartpro_course_coordinators(offering)) THEN RAISE EXCEPTION ''Offering coordinator required'' USING ERRCODE=''42501''; END IF;');EXECUTE def;
 def:=pg_get_functiondef('public.smartpro_manage_offering(uuid,uuid,text,jsonb,text)'::regprocedure);
 def:=replace(def,'IF input->>''availability''=''ACTIVE'' THEN',E'IF input->>''availability''=''ACTIVE'' THEN
   IF NOT EXISTS(SELECT FROM public.smartpro_course_coordinators(o.id)) THEN RAISE EXCEPTION ''Appoint a course coordinator before activation'' USING ERRCODE=''23514''; END IF;');EXECUTE def;
END $$;
-- Preserve the older projection internally, narrowing coordinator data by course.
ALTER FUNCTION public.smartpro_role_workspace(uuid,text) RENAME TO smartpro_role_workspace_pre037;
REVOKE ALL ON FUNCTION public.smartpro_role_workspace_pre037(uuid,text) FROM PUBLIC,smartpro_runtime;
CREATE FUNCTION public.smartpro_role_workspace(actor uuid,role text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE w jsonb;
BEGIN
 w:=public.smartpro_role_workspace_pre037(actor,role);
 IF role='Coordinator' THEN
  w:=w||jsonb_build_object('assignedProjects',(SELECT coalesce(jsonb_agg(p),'[]') FROM jsonb_array_elements(w->'assignedProjects') p WHERE EXISTS(SELECT FROM public.projects pr JOIN public.teams t ON t.id=pr.team_id WHERE pr.id=(p->>'id')::uuid AND public.smartpro_course_access(actor,t.curriculum_offering_id,'READ',role))),
  'reviews',(SELECT coalesce(jsonb_agg(r),'[]') FROM jsonb_array_elements(w->'reviews') r WHERE EXISTS(SELECT FROM public.projects p JOIN public.teams t ON t.id=p.team_id WHERE p.id=(r->>'projectId')::uuid AND public.smartpro_course_access(actor,t.curriculum_offering_id,'READ',role))),
  'audit',(SELECT coalesce(jsonb_agg(a),'[]') FROM jsonb_array_elements(w->'audit') a WHERE EXISTS(SELECT FROM public.projects p JOIN public.teams t ON t.id=p.team_id WHERE p.id=(a->>'project_id')::uuid AND public.smartpro_course_access(actor,t.curriculum_offering_id,'READ',role))));
 END IF;
 RETURN w;
END $$;
GRANT EXECUTE ON FUNCTION public.smartpro_role_workspace(uuid,text) TO smartpro_runtime;
ALTER FUNCTION public.smartpro_role_documents(uuid,uuid,text) RENAME TO smartpro_role_documents_pre037;
REVOKE ALL ON FUNCTION public.smartpro_role_documents_pre037(uuid,uuid,text) FROM PUBLIC,smartpro_runtime;
CREATE FUNCTION public.smartpro_role_documents(actor uuid,dept uuid,role text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE w jsonb;
BEGIN
 w:=public.smartpro_role_documents_pre037(actor,dept,role);
 IF role='Coordinator' THEN
  w:=w||jsonb_build_object('projects',(SELECT coalesce(jsonb_agg(p),'[]') FROM jsonb_array_elements(w->'projects') p WHERE public.smartpro_course_access(actor,(p->>'offeringId')::uuid,'READ',role)),'instructions','[]'::jsonb);
 END IF;
 RETURN w;
END $$;
GRANT EXECUTE ON FUNCTION public.smartpro_role_documents(uuid,uuid,text) TO smartpro_runtime;
DO $$ DECLARE def text; BEGIN
 def:=pg_get_functiondef('public.smartpro_document_scope(uuid,uuid,text)'::regprocedure);
 def:=replace(def,'BEGIN PERFORM public.smartpro_academic_authority(actor,p.department_id); RETURN true;',E'BEGIN PERFORM public.smartpro_academic_authority(actor,p.department_id);
 IF public.smartpro_course_access(actor,(SELECT curriculum_offering_id FROM public.teams WHERE id=p.team_id),''READ'',''HOD'') OR public.smartpro_course_access(actor,(SELECT curriculum_offering_id FROM public.teams WHERE id=p.team_id),''READ'',''Coordinator'') THEN RETURN true; END IF;');EXECUTE def;
 -- Existing operation delegation stays finite; the entry point adds exact scope.
 def:=pg_get_functiondef('public.smartpro_project_operation(uuid,uuid,text,jsonb,text)'::regprocedure);
 def:=replace(def,' IF input->>''_actingRole''=''Coordinator'' THEN',E' IF input->>''_actingRole''=''Coordinator'' THEN
  PERFORM public.smartpro_course_authority(actor,coalesce((SELECT t.curriculum_offering_id FROM public.projects scoped_project JOIN public.teams t ON t.id=scoped_project.team_id WHERE scoped_project.id=(input->>''projectId'')::uuid),(SELECT t.curriculum_offering_id FROM public.project_reviews scoped_review JOIN public.projects scoped_project ON scoped_project.id=scoped_review.project_id JOIN public.teams t ON t.id=scoped_project.team_id WHERE scoped_review.id=(input->>''reviewId'')::uuid)),CASE WHEN action=''SCHEDULE'' THEN ''PLAN'' ELSE action END,''Coordinator'');');def:=replace(def,'WHERE m.user_id=actor AND m.department_id=dept AND NOT m.revoked',E'WHERE m.user_id=actor AND m.department_id=dept AND NOT m.revoked AND m.id IN(SELECT mandate_id FROM public.smartpro_course_coordinators(coalesce((SELECT t.curriculum_offering_id FROM public.projects scoped_project JOIN public.teams t ON t.id=scoped_project.team_id WHERE scoped_project.id=(input->>''projectId'')::uuid),(SELECT t.curriculum_offering_id FROM public.project_reviews scoped_review JOIN public.projects scoped_project ON scoped_project.id=scoped_review.project_id JOIN public.teams t ON t.id=scoped_project.team_id WHERE scoped_review.id=(input->>''reviewId'')::uuid))) WHERE user_id=actor)');EXECUTE def;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_course_coordinators(uuid),public.smartpro_course_access(uuid,uuid,text,text),public.smartpro_course_authority(uuid,uuid,text,text),public.smartpro_appoint_course(uuid,uuid,text,jsonb,text),public.smartpro_course_catalog(uuid,uuid,text) FROM PUBLIC,smartpro_runtime;
GRANT EXECUTE ON FUNCTION public.smartpro_appoint_course(uuid,uuid,text,jsonb,text),public.smartpro_course_catalog(uuid,uuid,text) TO smartpro_runtime;
COMMIT;
