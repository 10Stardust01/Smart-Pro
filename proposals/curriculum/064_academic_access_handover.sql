-- Candidate 064: approved SMART-PRO application Faculty access revocation.
-- Not an HR/employment feature. Keep 063 historical and forward-only.
-- TERMINATE cannot be vetoed by active academic work; those duties become
-- visible as auditable handover records, not automatic new appointments.
BEGIN;
DO $pre$ BEGIN
 IF to_regprocedure('public.smartpro_faculty_manage(uuid,uuid,text,uuid,jsonb,text)') IS NULL
    OR to_regprocedure('public.smartpro_evaluator_active(uuid)') IS NULL
    OR to_regprocedure('public.smartpro_course_coordinators(uuid)') IS NULL
 THEN RAISE EXCEPTION 'Candidate 063 and academic assignment services required'; END IF;
 IF to_regclass('public.faculty_academic_access_handoffs') IS NOT NULL
 THEN RAISE EXCEPTION 'Candidate 064 already installed'; END IF;
END $pre$;

CREATE TABLE public.faculty_academic_access_handoffs(
 faculty_term_id uuid NOT NULL REFERENCES public.department_role_assignments(id),
 assignment_kind text NOT NULL CHECK(assignment_kind IN ('GUIDE','REVIEWER','EVALUATOR','COORDINATOR')),
 assignment_id uuid NOT NULL,
 department_id uuid NOT NULL REFERENCES public.departments(id),
 offering_id uuid NOT NULL REFERENCES public.curriculum_offerings(id),
 project_id uuid REFERENCES public.projects(id),
 effective_at timestamptz NOT NULL,
 recorded_by uuid NOT NULL REFERENCES public.users(id),
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(faculty_term_id,assignment_kind,assignment_id),
 CHECK((assignment_kind='COORDINATOR' AND project_id IS NULL)
    OR (assignment_kind<>'COORDINATOR' AND project_id IS NOT NULL))
);
CREATE INDEX faculty_academic_handoffs_offering ON
 public.faculty_academic_access_handoffs(offering_id,effective_at DESC,assignment_id);
CREATE INDEX faculty_academic_handoffs_assignment ON
 public.faculty_academic_access_handoffs(assignment_kind,assignment_id,effective_at);
CREATE INDEX faculty_academic_handoffs_project ON
 public.faculty_academic_access_handoffs(project_id,effective_at DESC)
 WHERE project_id IS NOT NULL;
REVOKE ALL ON public.faculty_academic_access_handoffs FROM PUBLIC,smartpro_runtime;

-- A published coordinator version is immutable. Its authorization can be
-- closed without deleting the historical appointment or bypassing ordinary
-- last-Coordinator protection for normal appointment commands.
DO $coordinator$ DECLARE def text; marker text; BEGIN
 def:=pg_get_functiondef('public.smartpro_course_coordinators(uuid)'::regprocedure);
 marker:='WHERE v.active AND v.valid_from<=clock_timestamp()';
 IF strpos(def,marker)=0
 THEN RAISE EXCEPTION 'Coordinator projection changed; review 064 manually'; END IF;
 def:=replace(def,marker,$coordinator_gate$WHERE v.active AND
 NOT EXISTS(SELECT FROM public.faculty_academic_access_handoffs h
    WHERE h.assignment_kind='COORDINATOR' AND h.assignment_id=v.id
      AND h.effective_at<=clock_timestamp())
 AND v.valid_from<=clock_timestamp()$coordinator_gate$);
 EXECUTE def;
END $coordinator$;

-- Amend the existing security-definer command, preserving Admin/HOD/self
-- checks, stale revisions, receipts, reasons, audit and all 063 details.
DO $change$ DECLARE def text; BEGIN
 def:=pg_get_functiondef('public.smartpro_faculty_manage(uuid,uuid,text,uuid,jsonb,text)'::regprocedure);
 IF strpos(def,$prior_guard$   -- Do not strand an active academic assignment or silently restore one later.
   SELECT EXISTS(SELECT 1 FROM public.faculty_assignments a
       JOIN public.projects p ON p.id=a.project_id
       WHERE p.department_id=dept AND a.faculty_user_id=person
         AND (a.valid_until IS NULL OR stamp<a.valid_until))
      OR EXISTS(SELECT 1 FROM public.course_coordinator_versions v
        JOIN public.curriculum_offerings o ON o.id=v.offering_id
        WHERE o.department_id=dept AND v.user_id=person AND v.active
          AND v.valid_until>stamp
          AND v.id=(SELECT z.id FROM public.course_coordinator_versions z
          WHERE z.offering_id=v.offering_id AND z.user_id=person
          ORDER BY z.version DESC LIMIT 1))
   INTO busy;
   IF busy AND (operation='TERMINATE' OR current_term.valid_until IS NULL
                OR new_expiry<current_term.valid_until)
   THEN RAISE EXCEPTION 'Reassign active project/Coordinator duties before ending or shortening this Faculty term'
      USING ERRCODE='23514'; END IF;
$prior_guard$)=0
 THEN RAISE EXCEPTION '063 term/assignment guard changed; inspect before 064'; END IF;
 def:=replace(def,$prior_guard$   -- Do not strand an active academic assignment or silently restore one later.
   SELECT EXISTS(SELECT 1 FROM public.faculty_assignments a
       JOIN public.projects p ON p.id=a.project_id
       WHERE p.department_id=dept AND a.faculty_user_id=person
         AND (a.valid_until IS NULL OR stamp<a.valid_until))
      OR EXISTS(SELECT 1 FROM public.course_coordinator_versions v
        JOIN public.curriculum_offerings o ON o.id=v.offering_id
        WHERE o.department_id=dept AND v.user_id=person AND v.active
          AND v.valid_until>stamp
          AND v.id=(SELECT z.id FROM public.course_coordinator_versions z
          WHERE z.offering_id=v.offering_id AND z.user_id=person
          ORDER BY z.version DESC LIMIT 1))
   INTO busy;
   IF busy AND (operation='TERMINATE' OR current_term.valid_until IS NULL
                OR new_expiry<current_term.valid_until)
   THEN RAISE EXCEPTION 'Reassign active project/Coordinator duties before ending or shortening this Faculty term'
      USING ERRCODE='23514'; END IF;
$prior_guard$,$next_guard$   -- A future term-shortening is still a planned scheduling change. A live
   -- TERMINATE must never be blocked by an academic assignment.
   IF operation='AMEND_TERM' AND
      (current_term.valid_until IS NULL OR new_expiry<current_term.valid_until)
   THEN
     SELECT EXISTS(SELECT FROM public.faculty_assignments a
       JOIN public.projects p ON p.id=a.project_id
       WHERE p.department_id=dept AND a.faculty_user_id=person
         AND a.valid_from<new_expiry
         AND (a.valid_until IS NULL OR new_expiry<a.valid_until))
       OR EXISTS(SELECT FROM public.course_coordinator_versions v
         JOIN public.curriculum_offerings o ON o.id=v.offering_id
         WHERE o.department_id=dept AND v.user_id=person AND v.active
           AND v.valid_from<new_expiry AND new_expiry<v.valid_until
           AND v.id=(SELECT z.id FROM public.course_coordinator_versions z
             WHERE z.offering_id=v.offering_id AND z.user_id=person
             ORDER BY z.version DESC LIMIT 1))
     INTO busy;
     IF busy THEN RAISE EXCEPTION 'Resolve scheduled academic coverage before shortening a future Faculty access term'
       USING ERRCODE='23514'; END IF;
   END IF;
   IF operation='TERMINATE' THEN
     -- Capture responsibilities before removing access; immutable history and
     -- old marks remain. Student projects are never automatically reassigned.
     INSERT INTO public.faculty_academic_access_handoffs
       (faculty_term_id,assignment_kind,assignment_id,department_id,offering_id,
        project_id,effective_at,recorded_by)
     SELECT current_term.id,a.assignment_type,a.id,dept,t.curriculum_offering_id,
       p.id,stamp,actor
     FROM public.faculty_assignments a JOIN public.projects p ON p.id=a.project_id
       JOIN public.teams t ON t.id=p.team_id
     WHERE p.department_id=dept AND a.faculty_user_id=person
       AND a.valid_from<=stamp AND (a.valid_until IS NULL OR stamp<a.valid_until)
     ON CONFLICT DO NOTHING;
     INSERT INTO public.faculty_academic_access_handoffs
       (faculty_term_id,assignment_kind,assignment_id,department_id,offering_id,
        project_id,effective_at,recorded_by)
     SELECT current_term.id,'EVALUATOR',e.id,dept,t.curriculum_offering_id,
       p.id,stamp,actor
     FROM public.evaluator_assignments e JOIN public.project_reviews r ON r.id=e.review_id
       JOIN public.projects p ON p.id=r.project_id JOIN public.teams t ON t.id=p.team_id
     WHERE p.department_id=dept AND e.faculty_user_id=person
       AND public.smartpro_evaluator_active(e.id)
     ON CONFLICT DO NOTHING;
     INSERT INTO public.faculty_academic_access_handoffs
       (faculty_term_id,assignment_kind,assignment_id,department_id,offering_id,
        project_id,effective_at,recorded_by)
     SELECT current_term.id,'COORDINATOR',v.id,dept,v.offering_id,
       NULL::uuid,stamp,actor
     FROM public.course_coordinator_versions v
       JOIN public.curriculum_offerings o ON o.id=v.offering_id
     WHERE o.department_id=dept AND v.user_id=person AND v.active
       AND v.valid_from<=stamp AND stamp<v.valid_until
       AND v.id=(SELECT z.id FROM public.course_coordinator_versions z
          WHERE z.offering_id=v.offering_id AND z.user_id=person
          ORDER BY z.version DESC LIMIT 1)
       AND NOT EXISTS(SELECT FROM public.faculty_academic_access_handoffs h
          WHERE h.assignment_kind='COORDINATOR' AND h.assignment_id=v.id
            AND h.effective_at<=stamp)
     ON CONFLICT DO NOTHING;
     -- Prospective close is already explicitly supported by the 031 assignment
     -- guard. Linked synopsis reviewers close too, without erasing decisions.
     UPDATE public.faculty_assignments a SET valid_until=stamp
     FROM public.projects p
     WHERE p.id=a.project_id AND p.department_id=dept
       AND a.faculty_user_id=person AND a.valid_from<=stamp
       AND (a.valid_until IS NULL OR stamp<a.valid_until);
     -- A revoked evaluator cannot quietly regain a prior pending assignment
     -- on a new Faculty term. Preserve past score rows and immutable results.
     INSERT INTO public.evaluator_assignment_events
       (assignment_id,version,active,actor_id)
     SELECT h.assignment_id,
       coalesce((SELECT max(ev.version) FROM public.evaluator_assignment_events ev
          WHERE ev.assignment_id=h.assignment_id),0)+1,false,actor
     FROM public.faculty_academic_access_handoffs h
     WHERE h.faculty_term_id=current_term.id AND h.assignment_kind='EVALUATOR'
       AND public.smartpro_evaluator_active(h.assignment_id)
     ORDER BY h.assignment_id;
   END IF;
$next_guard$);
 IF strpos(def,$prior_reinstate$   IF EXISTS(SELECT 1 FROM public.faculty_assignments a JOIN public.projects p ON p.id=a.project_id
        WHERE p.department_id=dept AND a.faculty_user_id=person
          AND (a.valid_until IS NULL OR stamp<a.valid_until))
       OR EXISTS(SELECT 1 FROM public.course_coordinator_versions v
         JOIN public.curriculum_offerings o ON o.id=v.offering_id
         WHERE o.department_id=dept AND v.user_id=person AND v.active AND v.valid_until>stamp
           AND v.id=(SELECT z.id FROM public.course_coordinator_versions z
             WHERE z.offering_id=v.offering_id AND z.user_id=person
             ORDER BY z.version DESC LIMIT 1))
   THEN RAISE EXCEPTION 'Close previous project/Coordinator appointments before reinstatement'
     USING ERRCODE='23514'; END IF;
$prior_reinstate$)=0
 THEN RAISE EXCEPTION '063 reinstatement guard changed; inspect before 064'; END IF;
 def:=replace(def,$prior_reinstate$   IF EXISTS(SELECT 1 FROM public.faculty_assignments a JOIN public.projects p ON p.id=a.project_id
        WHERE p.department_id=dept AND a.faculty_user_id=person
          AND (a.valid_until IS NULL OR stamp<a.valid_until))
       OR EXISTS(SELECT 1 FROM public.course_coordinator_versions v
         JOIN public.curriculum_offerings o ON o.id=v.offering_id
         WHERE o.department_id=dept AND v.user_id=person AND v.active AND v.valid_until>stamp
           AND v.id=(SELECT z.id FROM public.course_coordinator_versions z
             WHERE z.offering_id=v.offering_id AND z.user_id=person
             ORDER BY z.version DESC LIMIT 1))
   THEN RAISE EXCEPTION 'Close previous project/Coordinator appointments before reinstatement'
     USING ERRCODE='23514'; END IF;
$prior_reinstate$,$next_reinstate$   IF EXISTS(SELECT 1 FROM public.faculty_assignments a JOIN public.projects p ON p.id=a.project_id
        WHERE p.department_id=dept AND a.faculty_user_id=person
          AND (a.valid_until IS NULL OR stamp<a.valid_until))
       OR EXISTS(SELECT 1 FROM public.course_coordinator_versions v
         JOIN public.curriculum_offerings o ON o.id=v.offering_id
         WHERE o.department_id=dept AND v.user_id=person AND v.active AND v.valid_until>stamp
           AND NOT EXISTS(SELECT FROM public.faculty_academic_access_handoffs h
             WHERE h.assignment_kind='COORDINATOR' AND h.assignment_id=v.id
               AND h.effective_at<=stamp)
           AND v.id=(SELECT z.id FROM public.course_coordinator_versions z
             WHERE z.offering_id=v.offering_id AND z.user_id=person
             ORDER BY z.version DESC LIMIT 1))
   THEN RAISE EXCEPTION 'Close previous project/Coordinator appointments before reinstatement'
     USING ERRCODE='23514'; END IF;
$next_reinstate$);
 EXECUTE def;
END $change$;

-- Reviewer access uses the existing append-only evaluator events. The
-- termination action writes inactive events even for already finalized
-- assessments; immutable score/result histories are never rewritten.
-- New eligibility still requires explicit authorized assignment/review action.

-- Mark past access revocations alongside the existing bounded Coordinator
-- project queue. The count is historical evidence, not automatic reassignment
-- and not a claim that a replacement is still outstanding.
DO $handover_queue$ DECLARE def text; anchor text; BEGIN
 def:=pg_get_functiondef('public.smartpro_course_evaluation_queue(uuid,uuid,text,text,text,integer)'::regprocedure);
 anchor:='''frameworkVersion'',plan.framework_version,''stages'',stages';
 IF strpos(def,anchor)=0 THEN
   RAISE EXCEPTION 'Review queue projection changed; revise 064 before installing';
 END IF;
 def:=replace(def,anchor,$handover_projection$'frameworkVersion',plan.framework_version,
    'facultyAccessHandoverCount',(SELECT count(*) FROM public.faculty_academic_access_handoffs h
       WHERE h.project_id=project.id AND h.effective_at<=clock_timestamp()),
    'stages',stages$handover_projection$);
 EXECUTE def;
END $handover_queue$;

REVOKE ALL ON public.faculty_academic_access_handoffs FROM PUBLIC,smartpro_runtime;
COMMIT;
