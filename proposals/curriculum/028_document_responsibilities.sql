-- Guide/evaluator read access is separate from an explicit synopsis-review assignment.
BEGIN;
DO $$ BEGIN IF to_regclass('public.project_proposal_details') IS NULL THEN RAISE EXCEPTION 'Reviewed 027 required'; END IF; END $$;
CREATE OR REPLACE FUNCTION public.smartpro_document_scope(actor uuid,pid uuid,mode text) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.projects%ROWTYPE; o public.curriculum_offerings%ROWTYPE; profile public.student_profiles%ROWTYPE;
BEGIN
 SELECT * INTO p FROM public.projects WHERE id=pid;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM public.users WHERE id=actor AND account_status='ACTIVE' FOR SHARE;
 IF NOT FOUND OR NOT EXISTS(SELECT FROM public.academic_governance_settings WHERE department_id=p.department_id AND enabled)
   OR NOT EXISTS(SELECT FROM public.staff_department_controls WHERE department_id=p.department_id AND enabled) THEN RETURN false; END IF;
 IF mode IN ('student','read') AND public.smartpro_project_permission(pid,actor,'student') THEN
  SELECT x.* INTO o FROM public.curriculum_offerings x JOIN public.teams t ON t.curriculum_offering_id=x.id WHERE t.id=p.team_id;
  SELECT * INTO profile FROM public.student_profiles WHERE user_id=actor FOR SHARE;
  IF profile.department_id=o.department_id AND profile.semester_key=o.semester_key AND o.cycle_id=p.cycle_id
    AND EXISTS(SELECT FROM public.academic_cycles WHERE id=o.cycle_id AND starts_on<=current_date AND current_date<=ends_on) THEN RETURN true; END IF;
 END IF;
 IF mode IN ('reviewer','faculty_read','read') THEN
  PERFORM 1 FROM public.department_role_assignments r WHERE r.user_id=actor AND r.department_id=p.department_id AND r.role_code='FACULTY'
    AND r.valid_from<=clock_timestamp() AND (r.valid_until IS NULL OR clock_timestamp()<r.valid_until) FOR SHARE;
  IF FOUND THEN
   PERFORM 1 FROM public.faculty_assignments f WHERE f.project_id=pid AND f.faculty_user_id=actor
    AND (f.assignment_type='REVIEWER' OR (mode<>'reviewer' AND f.assignment_type='GUIDE'))
    AND f.valid_from<=clock_timestamp() AND (f.valid_until IS NULL OR clock_timestamp()<f.valid_until) FOR SHARE;
   IF FOUND THEN RETURN true; END IF;
   IF mode<>'reviewer' AND EXISTS(SELECT FROM public.evaluator_assignments e JOIN public.project_reviews r ON r.id=e.review_id WHERE r.project_id=pid AND e.faculty_user_id=actor) THEN RETURN true; END IF;
  END IF;
 END IF;
 IF mode='read' THEN
  BEGIN PERFORM public.smartpro_academic_authority(actor,p.department_id); RETURN true;
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 END IF;
 RETURN false;
END $$;

DO $$ DECLARE def text; sig text; BEGIN
 def:=pg_get_functiondef('public.smartpro_role_documents(uuid,uuid,text)'::regprocedure);
 def:=replace(def,'(role=''Faculty'' AND (p->>''canReview'')::boolean)','(role=''Faculty'' AND public.smartpro_document_scope(actor,(p->>''id'')::uuid,''faculty_read''))');
 EXECUTE def;
 FOREACH sig IN ARRAY ARRAY['public.smartpro_role_file(uuid,uuid,text)','public.smartpro_role_case_access(uuid,uuid,text)'] LOOP
  def:=pg_get_functiondef(to_regprocedure(sig));
  def:=replace(def,'WHEN ''Faculty'' THEN ''reviewer''','WHEN ''Faculty'' THEN ''faculty_read''');
  EXECUTE def;
 END LOOP;
END $$;
COMMIT;
