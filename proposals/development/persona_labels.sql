-- Local owner-run support for the five synthetic development personas.
BEGIN;
DO $$
BEGIN
  IF current_database() <> 'smartpro_dev' THEN
    RAISE EXCEPTION 'Development persona lookup requires smartpro_dev';
  END IF;
END $$;
CREATE OR REPLACE FUNCTION public.smartpro_demo_persona_labels(ids uuid[]) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF current_database() <> 'smartpro_dev' OR cardinality(ids)>100 THEN
    RAISE EXCEPTION 'Explicit development database required' USING ERRCODE='42501';
  END IF;
  RETURN (SELECT coalesce(jsonb_object_agg(u.id::text,u.display_name),'{}')
    FROM public.users u
    JOIN (VALUES
      ('00000000-0000-4000-8000-000000000001'::uuid,'acceptance-1@example.invalid'),
      ('00000000-0000-4000-8000-000000000003'::uuid,'acceptance-3@example.invalid'),
      ('00000000-0000-4000-8000-000000000004'::uuid,'acceptance-4@example.invalid'),
      ('00000000-0000-4000-8000-000000000008'::uuid,'acceptance-8@example.invalid'),
      ('00000000-0000-4000-8000-000000000012'::uuid,'acceptance-12@example.invalid')
    ) AS persona(id,email) ON (u.id,u.email)=(persona.id,persona.email)
    WHERE u.id=ANY(ids) AND u.account_status='ACTIVE');
END $$;
REVOKE ALL ON FUNCTION public.smartpro_demo_persona_labels(uuid[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smartpro_demo_persona_labels(uuid[]) TO smartpro_runtime;
COMMIT;
