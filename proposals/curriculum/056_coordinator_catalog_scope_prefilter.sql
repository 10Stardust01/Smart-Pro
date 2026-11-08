-- A Coordinator cannot access an offering without an appointment version.
-- Preselect those offerings before running the existing effective-authority check.
BEGIN;
CREATE INDEX course_coordinator_offer_lookup ON public.course_coordinator_versions(user_id,offering_id);
DO $$
DECLARE definition text;
DECLARE old_filter text:=$old$acting_role IN('HOD','Admin') OR public.smartpro_course_access(actor,o.id,'READ',acting_role)$old$;
BEGIN
  SELECT pg_get_functiondef('public.smartpro_course_catalog(uuid,uuid,text)'::regprocedure) INTO definition;
  IF strpos(definition,old_filter)=0 THEN
    RAISE EXCEPTION 'Reviewed course catalog definition required';
  END IF;
  EXECUTE replace(definition,old_filter,$new$acting_role IN('HOD','Admin') OR CASE WHEN EXISTS(
    SELECT FROM public.course_coordinator_versions v WHERE v.user_id=actor AND v.offering_id=o.id
  ) THEN public.smartpro_course_access(actor,o.id,'READ',acting_role) ELSE false END$new$);
END $$;
COMMIT;
