-- Candidate 065: remove an unintended policy gate from the separately
-- authorized, exceptional post-publication OVERALL result correction.
--
-- The pinned 'allowFinalCorrections' flag continues to govern exceptional
-- corrections to underlying FINALIZED STAGE MARKS (smartpro_course_correction_guard
-- and the stage/evaluator interfaces). It does not veto the approved assigned
-- Guide -> responsible Coordinator exceptional overall release process.
--
-- Forward-only, fail-closed source rewrite. Preserves function signatures,
-- SECURITY DEFINER ownership, runtime EXECUTE grants and immutable histories.
-- Never reapply 059-064 or modify any historical framework/result/marks.
BEGIN;

DO $fix$
DECLARE
  writer regprocedure := to_regprocedure('public.smartpro_course_final_revision(uuid,uuid,text,jsonb,text)');
  guide_page regprocedure := to_regprocedure('public.smartpro_guide_final_correction_project(uuid,text,uuid,integer,timestamptz)');
  guide_legacy regprocedure := to_regprocedure('public.smartpro_guide_final_corrections(uuid,text)');
  original text;
  revised text;
  obsolete_gate text := E' IF NOT coalesce((cfg->>\'allowFinalCorrections\')::boolean,false) THEN\n   RAISE EXCEPTION \'Pinned framework disallows final correction\' USING ERRCODE=\'42501\';\n END IF;';
  obsolete_filter text := E'AND coalesce((fw.configuration->>\'allowFinalCorrections\')::boolean,false)';
  replacement text := E' -- Exceptional overall-result revision is authorized by the currently assigned\n -- Guide and the responsible Coordinator, even when ordinary stage-mark\n -- corrections remain closed under the original pinned academic framework.';
BEGIN
  IF writer IS NULL OR guide_page IS NULL OR guide_legacy IS NULL
    OR to_regprocedure('public.smartpro_course_correction_guard(uuid,uuid,jsonb)') IS NULL
  THEN RAISE EXCEPTION 'Installed 059-064 correction and staged-mark services required'; END IF;

  SELECT pg_get_functiondef(writer) INTO original;
  IF strpos(original,obsolete_gate)=0
     OR length(original)-length(replace(original,obsolete_gate,''))<>length(obsolete_gate)
     OR strpos(original,'STAGE_EVIDENCE_OVERALL_CORRECTION')=0
     OR strpos(original,'smartpro_current_project_guide')=0
     OR strpos(original,'smartpro_course_authority')=0
  THEN RAISE EXCEPTION 'Published overall correction writer differs; verify candidate 065 manually'; END IF;
  revised:=replace(original,obsolete_gate,replacement);
  EXECUTE revised;

  SELECT pg_get_functiondef(guide_page) INTO original;
  IF strpos(original,obsolete_filter)=0
     OR length(original)-length(replace(original,obsolete_filter,''))<>length(obsolete_filter)
     OR strpos(original,'smartpro_current_project_guide')=0
  THEN RAISE EXCEPTION 'Scoped Guide correction reader differs; verify candidate 065 manually'; END IF;
  revised:=replace(original,obsolete_filter,'TRUE /* overall revisions independent of stage correction toggle */');
  EXECUTE revised;

  SELECT pg_get_functiondef(guide_legacy) INTO original;
  IF strpos(original,obsolete_filter)=0
     OR length(original)-length(replace(original,obsolete_filter,''))<>length(obsolete_filter)
     OR strpos(original,'smartpro_current_project_guide')=0
  THEN RAISE EXCEPTION 'Legacy Guide correction reader differs; verify candidate 065 manually'; END IF;
  revised:=replace(original,obsolete_filter,'TRUE /* overall revisions independent of stage correction toggle */');
  EXECUTE revised;

  -- Fail closed if the original ordinary-stage correction enforcement has
  -- inadvertently been changed by another deployment.
  IF strpos(pg_get_functiondef('public.smartpro_course_correction_guard(uuid,uuid,jsonb)'::regprocedure),
             'allowFinalCorrections')=0
  THEN RAISE EXCEPTION 'Ordinary stage correction guard missing'; END IF;
END $fix$;
COMMIT;
