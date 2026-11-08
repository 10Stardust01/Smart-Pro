-- Authorized guide allocation records explicit synopsis-review responsibility.
-- No requirement, policy approval or assignment is backfilled by installation.
BEGIN;
DO $$ BEGIN
 IF to_regclass('public.evaluator_assignment_events') IS NULL THEN RAISE EXCEPTION 'Reviewed 035 required'; END IF;
END $$;
CREATE TABLE public.guide_synopsis_responsibilities(
 reviewer_assignment_id uuid PRIMARY KEY,
 guide_assignment_id uuid NOT NULL,
 project_id uuid NOT NULL REFERENCES public.projects(id),
 faculty_user_id uuid NOT NULL REFERENCES public.users(id),
 assigned_by uuid NOT NULL REFERENCES public.users(id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(reviewer_assignment_id,project_id,faculty_user_id) REFERENCES public.faculty_assignments(id,project_id,faculty_user_id),
 FOREIGN KEY(guide_assignment_id,project_id,faculty_user_id) REFERENCES public.faculty_assignments(id,project_id,faculty_user_id),
 CHECK(reviewer_assignment_id<>guide_assignment_id));
CREATE INDEX guide_synopsis_by_guide ON public.guide_synopsis_responsibilities(guide_assignment_id);
REVOKE ALL ON public.guide_synopsis_responsibilities FROM PUBLIC,smartpro_runtime;
CREATE TRIGGER retain_guide_synopsis_responsibility BEFORE UPDATE OR DELETE ON public.guide_synopsis_responsibilities
 FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation();
CREATE FUNCTION public.smartpro_guide_responsibility_integrity() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF NOT EXISTS(SELECT FROM public.faculty_assignments WHERE id=NEW.guide_assignment_id AND assignment_type='GUIDE')
  OR NOT EXISTS(SELECT FROM public.faculty_assignments WHERE id=NEW.reviewer_assignment_id AND assignment_type='REVIEWER' AND requirement_key='SYNOPSIS')
 THEN RAISE EXCEPTION 'Guide and explicit synopsis reviewer required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER valid_guide_synopsis_responsibility BEFORE INSERT ON public.guide_synopsis_responsibilities
 FOR EACH ROW EXECUTE FUNCTION public.smartpro_guide_responsibility_integrity();

-- Private helper: called only inside the authorized, project-locked guide command.
CREATE FUNCTION public.smartpro_sync_guide_synopsis(actor uuid,pid uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE guide public.faculty_assignments%ROWTYPE; reviewer uuid; stamp timestamptz;
BEGIN
 PERFORM 1 FROM public.projects WHERE id=pid FOR UPDATE;
 stamp:=clock_timestamp();
 SELECT * INTO guide FROM public.faculty_assignments WHERE project_id=pid AND assignment_type='GUIDE'
  AND valid_from<=stamp AND (valid_until IS NULL OR stamp<valid_until) FOR UPDATE;
 -- Close only responsibilities derived from earlier guides, not independent grants.
 UPDATE public.faculty_assignments f SET valid_until=stamp
  FROM public.guide_synopsis_responsibilities link
  WHERE f.id=link.reviewer_assignment_id AND link.project_id=pid
   AND link.guide_assignment_id IS DISTINCT FROM guide.id
   AND f.valid_from<=stamp AND (f.valid_until IS NULL OR stamp<f.valid_until);
 IF guide.id IS NULL THEN RETURN NULL; END IF;
 SELECT f.id INTO reviewer FROM public.guide_synopsis_responsibilities link JOIN public.faculty_assignments f ON f.id=link.reviewer_assignment_id
  WHERE link.guide_assignment_id=guide.id AND f.valid_from<=stamp AND (f.valid_until IS NULL OR stamp<f.valid_until);
 IF reviewer IS NOT NULL THEN RETURN reviewer; END IF;
 IF NOT public.smartpro_has_role(guide.faculty_user_id,(SELECT department_id FROM public.projects WHERE id=pid),'FACULTY',clock_timestamp())
 THEN RAISE EXCEPTION 'Current departmental faculty guide required' USING ERRCODE='42501'; END IF;
 INSERT INTO public.faculty_assignments(project_id,faculty_user_id,assignment_type,requirement_key,valid_from,valid_until)
  VALUES(pid,guide.faculty_user_id,'REVIEWER','SYNOPSIS',stamp,guide.valid_until) RETURNING id INTO reviewer;
 INSERT INTO public.guide_synopsis_responsibilities(reviewer_assignment_id,guide_assignment_id,project_id,faculty_user_id,assigned_by)
  VALUES(reviewer,guide.id,pid,guide.faculty_user_id,actor);
 INSERT INTO public.audit_events(actor_id,project_id,action,target_type,target_id,metadata)
  VALUES(actor,pid,'GUIDE_SYNOPSIS_RESPONSIBILITY','FACULTY_ASSIGNMENT',reviewer,jsonb_build_object('guideAssignmentId',guide.id,'facultyId',guide.faculty_user_id,'requirementKey','SYNOPSIS'));
 RETURN reviewer;
END $$;
REVOKE ALL ON FUNCTION public.smartpro_guide_responsibility_integrity(),public.smartpro_sync_guide_synopsis(uuid,uuid) FROM PUBLIC,smartpro_runtime;

DO $$ DECLARE def text; marker text; BEGIN
 def:=pg_get_functiondef('public.smartpro_project_operation(uuid,uuid,text,jsonb,text)'::regprocedure);
 marker:='result:=jsonb_build_object(''id'',rid,''status'',''Guide assigned'');';
 IF strpos(def,marker)=0 THEN RAISE EXCEPTION 'Guide command prerequisite changed'; END IF;
 def:=replace(def,marker,E'PERFORM public.smartpro_sync_guide_synopsis(actor,p.id);\n  '||marker);
 EXECUTE def;

 def:=pg_get_functiondef('public.smartpro_manage_assignment(uuid,uuid,text,jsonb,text)'::regprocedure);
 marker:='  stamp:=clock_timestamp();';
 IF strpos(def,marker)=0 THEN RAISE EXCEPTION 'Assignment command prerequisite changed'; END IF;
 def:=replace(def,marker,E'  IF EXISTS(SELECT FROM public.guide_synopsis_responsibilities WHERE reviewer_assignment_id=assignment.id) THEN RAISE EXCEPTION ''End or reassign the primary guide to end its linked synopsis responsibility'' USING ERRCODE=''23514''; END IF;\n'||marker);
 marker:='UPDATE public.faculty_assignments SET valid_until=stamp WHERE id=assignment.id;';
 def:=replace(def,marker,marker||E'\n  IF assignment.assignment_type=''GUIDE'' THEN PERFORM public.smartpro_sync_guide_synopsis(actor,assignment.project_id); END IF;');
 EXECUTE def;

 -- Configured manual reviewer lists cannot erase linked guide responsibility or
 -- mistake it for an independent grant to the same faculty member.
 def:=pg_get_functiondef('public.smartpro_configure_requirement(uuid,uuid,text,jsonb,text)'::regprocedure);
 marker:='AND f.assignment_type=''REVIEWER''';
 IF strpos(def,marker)=0 THEN RAISE EXCEPTION 'Requirement command prerequisite changed'; END IF;
 def:=replace(def,marker,marker||' AND NOT EXISTS(SELECT FROM public.guide_synopsis_responsibilities link WHERE link.reviewer_assignment_id=f.id)');
 EXECUTE def;

 -- Even an owner-side prospective guide closure cannot leave a live decision
 -- right through its linked reviewer. Independent reviewer grants remain valid.
 def:=pg_get_functiondef('public.smartpro_requirement_access(uuid,uuid,text,text,boolean)'::regprocedure);
 marker:='RETURN EXISTS(SELECT FROM public.faculty_assignments f WHERE';
 IF strpos(def,marker)=0 THEN RAISE EXCEPTION 'Requirement access prerequisite changed'; END IF;
 def:=replace(def,marker,marker||' (NOT EXISTS(SELECT FROM public.guide_synopsis_responsibilities link WHERE link.reviewer_assignment_id=f.id) OR EXISTS(SELECT FROM public.guide_synopsis_responsibilities link JOIN public.faculty_assignments g ON g.id=link.guide_assignment_id WHERE link.reviewer_assignment_id=f.id AND g.assignment_type=''GUIDE'' AND g.valid_from<=clock_timestamp() AND (g.valid_until IS NULL OR clock_timestamp()<g.valid_until))) AND');
 EXECUTE def;

 def:=pg_get_functiondef('public.smartpro_assignment_management(uuid,uuid,text)'::regprocedure);
 def:=replace(def,'SELECT f.*,p.title,u.display_name','SELECT f.*,(SELECT guide_assignment_id FROM public.guide_synopsis_responsibilities WHERE reviewer_assignment_id=f.id) AS source_guide_id,p.title,u.display_name');
 EXECUTE def;
END $$;
COMMIT;
