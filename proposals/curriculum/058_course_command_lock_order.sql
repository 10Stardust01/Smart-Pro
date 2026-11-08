-- Owner-run candidate. Preserve authority checks and use the same lock order
-- as smartpro_academic_review_command: governance before authority mandates.
BEGIN;
DO $$
DECLARE
    definition text := pg_get_functiondef('public.smartpro_course_command(uuid,uuid,text,jsonb,text)'::regprocedure);
    check_role text := $source$ IF NOT public.smartpro_role_choices(actor) ? role THEN RAISE EXCEPTION 'Current responsibility required' USING ERRCODE='42501'; END IF;$source$;
    lock_governance text := $source$ PERFORM 1 FROM public.academic_governance_settings WHERE department_id=o.department_id AND enabled FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Academic controls disabled' USING ERRCODE='42501'; END IF;$source$;
    old_order text := check_role || chr(10) || lock_governance;
BEGIN
    IF array_length(string_to_array(definition, old_order), 1) IS DISTINCT FROM 2 THEN
        RAISE EXCEPTION 'Unexpected course command definition; review lock-order prerequisite';
    END IF;
    -- Role discovery currently reaches the locking academic-authority helper.
    -- Taking the same department lock first removes the observed inverse order
    -- without weakening checks against concurrent authority changes.
    EXECUTE replace(definition, old_order, lock_governance || chr(10) || check_role);
END $$;
COMMIT;
