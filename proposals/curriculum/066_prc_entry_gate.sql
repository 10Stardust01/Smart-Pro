-- Candidate only: approved PRC ordering and append-only synopsis outcomes.
-- No runtime activation, committee appointments or decision-writing authority.
-- Those operations require the original faculty requirements before implementation.
BEGIN;
DO $$ BEGIN
 IF to_regprocedure('public.smartpro_document_command(uuid,uuid,text,jsonb,text)') IS NULL
    OR to_regprocedure('public.smartpro_document_scope(uuid,uuid,text)') IS NULL
    OR to_regprocedure('public.smartpro_course_access(uuid,uuid,text,text)') IS NULL
 THEN RAISE EXCEPTION 'Install the reviewed document and course lifecycle first'; END IF;
END $$;

CREATE TABLE public.prc_offering_gates (
 offering_id uuid PRIMARY KEY REFERENCES public.curriculum_offerings(id),
 activated_by uuid NOT NULL REFERENCES public.users(id),
 activated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE public.prc_synopsis_decisions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 project_id uuid NOT NULL REFERENCES public.projects(id),
 attempt_id uuid NOT NULL UNIQUE,
 recorded_by uuid NOT NULL REFERENCES public.users(id),
 decision text NOT NULL CHECK (decision IN ('APPROVE','REQUEST_MODIFICATION','REJECT')),
 comment text NOT NULL DEFAULT '',
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY (attempt_id,project_id) REFERENCES public.submission_attempts(id,project_id)
);
CREATE INDEX prc_decision_project_history ON public.prc_synopsis_decisions(project_id,recorded_at);
REVOKE ALL ON public.prc_offering_gates,public.prc_synopsis_decisions FROM PUBLIC,smartpro_runtime;
CREATE TRIGGER prc_preserve_activation BEFORE UPDATE OR DELETE ON public.prc_offering_gates
 FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation();
CREATE TRIGGER prc_preserve_decision BEFORE UPDATE OR DELETE ON public.prc_synopsis_decisions
 FOR EACH ROW EXECUTE FUNCTION public.smartpro_forbid_mutation();

CREATE FUNCTION public.smartpro_prc_outcome_integrity() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $f$
BEGIN
 PERFORM 1 FROM public.projects WHERE id=NEW.project_id FOR UPDATE;
 IF NOT EXISTS (
  SELECT FROM public.submission_attempts a JOIN public.submission_cases c ON c.id=a.case_id
  WHERE a.id=NEW.attempt_id AND a.project_id=NEW.project_id AND c.requirement_key='SYNOPSIS'
   AND a.attempt_state=CASE WHEN NEW.decision='APPROVE' THEN 'APPROVED' ELSE 'CHANGES_REQUESTED' END
   AND c.state=a.attempt_state
   AND NOT EXISTS(SELECT FROM public.submission_attempts newer
     WHERE newer.case_id=a.case_id AND newer.attempt_no>a.attempt_no)
 ) THEN RAISE EXCEPTION 'PRC outcome must match the latest decided synopsis attempt'
    USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $f$;
CREATE TRIGGER prc_outcome_matches_synopsis BEFORE INSERT ON public.prc_synopsis_decisions
 FOR EACH ROW EXECUTE FUNCTION public.smartpro_prc_outcome_integrity();

CREATE FUNCTION public.smartpro_prc_required(pid uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $f$
 SELECT EXISTS (
  SELECT FROM public.projects p JOIN public.teams t ON t.id=p.team_id
   JOIN public.prc_offering_gates g ON g.offering_id=t.curriculum_offering_id
  WHERE p.id=pid AND NOT EXISTS (
   SELECT FROM public.faculty_assignments f WHERE f.project_id=p.id
    AND f.assignment_type='GUIDE' AND f.valid_from<g.activated_at)
 );
$f$;

CREATE FUNCTION public.smartpro_prc_approved(pid uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $f$
 SELECT coalesce((
  SELECT d.decision='APPROVE' AND a.attempt_state='APPROVED' AND c.state='APPROVED'
  FROM public.submission_cases c JOIN public.submission_attempts a ON a.case_id=c.id
  LEFT JOIN public.prc_synopsis_decisions d ON d.attempt_id=a.id
  WHERE c.project_id=pid AND c.requirement_key='SYNOPSIS'
  ORDER BY a.attempt_no DESC LIMIT 1
 ),false);
$f$;

CREATE FUNCTION public.smartpro_prc_guide_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $f$
BEGIN
 -- Serialize the check with document commands, which already lock the project.
 -- A future PRC writer must use this same project-first lock order.
 PERFORM 1 FROM public.projects WHERE id=NEW.project_id FOR UPDATE;
 IF NEW.assignment_type='GUIDE' AND public.smartpro_prc_required(NEW.project_id)
    AND NOT public.smartpro_prc_approved(NEW.project_id)
 THEN RAISE EXCEPTION 'PRC synopsis approval required before Guide allocation'
    USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $f$;
CREATE TRIGGER require_prc_before_guide_insert BEFORE INSERT ON public.faculty_assignments
 FOR EACH ROW EXECUTE FUNCTION public.smartpro_prc_guide_guard();
CREATE TRIGGER require_prc_before_guide_update
 BEFORE UPDATE OF project_id,assignment_type,faculty_user_id ON public.faculty_assignments
 FOR EACH ROW EXECUTE FUNCTION public.smartpro_prc_guide_guard();

CREATE FUNCTION public.smartpro_prc_resubmission_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $f$
BEGIN
 IF EXISTS (
  SELECT FROM public.prc_synopsis_decisions d
  JOIN public.submission_attempts rejected ON rejected.id=d.attempt_id
  JOIN public.submission_items old_item ON old_item.attempt_id=rejected.id
  JOIN public.document_versions old_version ON old_version.id=old_item.document_version_id
  JOIN public.document_versions submitted ON submitted.id=NEW.document_version_id
  WHERE d.project_id=NEW.project_id AND d.decision='REJECT'
   AND old_version.document_id=submitted.document_id
   AND submitted.version_no<=old_version.version_no
 ) THEN RAISE EXCEPTION 'PRC rejection requires a fresh synopsis version and submission'
    USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $f$;
CREATE TRIGGER require_fresh_synopsis_after_prc_rejection BEFORE INSERT ON public.submission_items
 FOR EACH ROW EXECUTE FUNCTION public.smartpro_prc_resubmission_guard();

-- REJECT and REQUEST_MODIFICATION remain distinct permanent outcomes. The
-- existing document command requires an unused PDF version and a NEW attempt
-- for resubmission. A rejected attempt can therefore never be reused/approved
-- in place; a later attempt needs its own PRC approval before Guide allocation.
-- Do not invent project deletion, a new team, a new title, or quorum rules.
REVOKE ALL ON FUNCTION public.smartpro_prc_required(uuid),
 public.smartpro_prc_approved(uuid),public.smartpro_prc_guide_guard(),
 public.smartpro_prc_outcome_integrity(),public.smartpro_prc_resubmission_guard()
 FROM PUBLIC,smartpro_runtime;

-- Read existing evidence under existing role/scope checks. No write authority is
-- inferred from Coordinator management or from Faculty document-reading access.
CREATE FUNCTION public.smartpro_prc_project_status(actor uuid,pid uuid,acting_role text)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $f$
DECLARE oid uuid; permitted boolean:=false;
BEGIN
 IF NOT public.smartpro_role_choices(actor) ? acting_role
 THEN RAISE EXCEPTION 'Current selected responsibility required' USING ERRCODE='42501'; END IF;
 SELECT t.curriculum_offering_id INTO oid FROM public.projects p
 JOIN public.teams t ON t.id=p.team_id WHERE p.id=pid;
 IF acting_role='Coordinator' THEN
  permitted:=public.smartpro_course_access(actor,oid,'READ','Coordinator');
 ELSIF acting_role='Student' THEN
  permitted:=public.smartpro_document_scope(actor,pid,'student');
 ELSIF acting_role='Faculty' THEN
  permitted:=public.smartpro_document_scope(actor,pid,'faculty_read');
 ELSIF acting_role='HOD' THEN
  permitted:=public.smartpro_document_scope(actor,pid,'read');
 END IF;
 IF NOT coalesce(permitted,false)
 THEN RAISE EXCEPTION 'Current project access required' USING ERRCODE='42501'; END IF;
 RETURN jsonb_build_object('enabled',public.smartpro_prc_required(pid),
  'approved',public.smartpro_prc_approved(pid),
  'synopsisState',(SELECT state FROM public.submission_cases WHERE project_id=pid AND requirement_key='SYNOPSIS'),
  'latestDecision',(SELECT d.decision FROM public.submission_cases c
    JOIN public.submission_attempts a ON a.case_id=c.id
    LEFT JOIN public.prc_synopsis_decisions d ON d.attempt_id=a.id
    WHERE c.project_id=pid AND c.requirement_key='SYNOPSIS' ORDER BY a.attempt_no DESC LIMIT 1),
  'history',(SELECT coalesce(jsonb_agg(jsonb_build_object(
    'attemptNo',a.attempt_no,'decision',d.decision,'comment',d.comment,
    'recordedAt',d.recorded_at) ORDER BY a.attempt_no),'[]'::jsonb)
   FROM public.prc_synopsis_decisions d JOIN public.submission_attempts a ON a.id=d.attempt_id
   WHERE d.project_id=pid));
END $f$;
CREATE FUNCTION public.smartpro_prc_offering_status(actor uuid,oid uuid,acting_role text,page integer)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $f$
BEGIN
 IF acting_role IS DISTINCT FROM 'Coordinator'
    OR NOT public.smartpro_role_choices(actor) ? 'Coordinator'
    OR NOT coalesce(public.smartpro_course_access(actor,oid,'READ','Coordinator'),false)
 THEN RAISE EXCEPTION 'Assigned offering Coordinator required' USING ERRCODE='42501'; END IF;
 IF page IS NULL OR page<1 OR page>99999999
 THEN RAISE EXCEPTION 'Valid page required' USING ERRCODE='22023'; END IF;
 RETURN jsonb_build_object('page',page,'pageSize',25,
  'enabled',EXISTS(SELECT FROM public.prc_offering_gates WHERE offering_id=oid),
  'total',(SELECT count(*) FROM public.projects p JOIN public.teams t ON t.id=p.team_id
    WHERE t.curriculum_offering_id=oid),
  'projects',(SELECT coalesce(jsonb_agg(jsonb_build_object('id',x.id,'title',x.title,
    'status',public.smartpro_prc_project_status(actor,x.id,acting_role)) ORDER BY x.id),'[]'::jsonb)
    FROM (SELECT p.id,p.title FROM public.projects p JOIN public.teams t ON t.id=p.team_id
      WHERE t.curriculum_offering_id=oid ORDER BY p.id LIMIT 25 OFFSET (page::bigint-1)*25) x));
END $f$;
REVOKE ALL ON FUNCTION public.smartpro_prc_project_status(uuid,uuid,text),
 public.smartpro_prc_offering_status(uuid,uuid,text,integer) FROM PUBLIC,smartpro_runtime;
GRANT EXECUTE ON FUNCTION public.smartpro_prc_project_status(uuid,uuid,text),
 public.smartpro_prc_offering_status(uuid,uuid,text,integer) TO smartpro_runtime;
COMMIT;
