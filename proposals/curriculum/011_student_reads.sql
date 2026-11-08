-- Dependent on reviewed candidate 010 activation. Explicit owner-run rollout only.
-- Never run against real academic records without the approved upgrade procedure.
BEGIN;
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_attribute
                 WHERE attrelid='public.teams'::regclass
                   AND attname='curriculum_offering_id' AND attnotnull) THEN
    RAISE EXCEPTION 'Activate curriculum 010 before installing student reads';
  END IF;
END $$;

-- Explicit publication scope, independent of cycle dates or formation permission.
-- Empty by default. Only migration/administrative provisioning can configure it;
-- a future audited staff command must not grant runtime direct table writes.
CREATE TABLE student_offering_windows (
  offering_id uuid PRIMARY KEY REFERENCES curriculum_offerings(id),
  visible_from timestamptz NOT NULL,
  visible_until timestamptz NOT NULL,
  CHECK (visible_until > visible_from)
);
CREATE INDEX ix_student_offerings_scope
  ON curriculum_offerings(department_id,semester_key,id);

-- These functions are trusted-server capabilities, not per-student DB identity.
-- Only the authentication adapter may supply actor_id; never HTTP body/query data.
CREATE FUNCTION smartpro_student_profile(actor_id uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE profile jsonb;
BEGIN
  SELECT jsonb_build_object(
    'id',u.id,'name',u.display_name,'usn',s.usn,'section',s.section,
    'semester',s.semester_key,
    'department',jsonb_build_object('id',d.id,'code',d.code,'name',d.name))
  INTO profile
  FROM public.users u JOIN public.student_profiles s ON s.user_id=u.id
  JOIN public.departments d ON d.id=s.department_id
  WHERE u.id=actor_id AND u.account_status='ACTIVE'
    AND EXISTS (SELECT FROM public.department_role_assignments r
                WHERE r.user_id=u.id AND r.department_id=s.department_id
                  AND r.role_code='STUDENT' AND r.valid_from<=now()
                  AND (r.valid_until IS NULL OR now()<r.valid_until));
  IF profile IS NULL THEN
    RAISE EXCEPTION 'Active student profile required' USING ERRCODE='42501';
  END IF;
  RETURN profile;
END;
$$;

CREATE FUNCTION smartpro_student_offerings(actor_id uuid, after_id uuid DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE profile jsonb; page jsonb; next_cursor uuid;
BEGIN
  profile := public.smartpro_student_profile(actor_id);
  -- Scope is derived from the same statement snapshot as account/role validation.
  WITH eligible AS (
    SELECT o.id,o.semester_key,o.student_team_creation_enabled,
           c.id AS cycle_id,c.code AS cycle_code,t.code,t.label
    FROM public.curriculum_offerings o
    JOIN public.student_offering_windows w ON w.offering_id=o.id
    JOIN public.academic_cycles c ON c.id=o.cycle_id
    JOIN public.curriculum_types t ON t.id=o.curriculum_type_id
    WHERE o.department_id=(profile->'department'->>'id')::uuid
      AND o.semester_key=profile->>'semester'
      AND w.visible_from<=now() AND now()<w.visible_until
      AND (after_id IS NULL OR o.id>after_id)
    ORDER BY o.id LIMIT 51
  ), numbered AS (
    SELECT *, row_number() OVER (ORDER BY id) AS position FROM eligible
  )
  SELECT coalesce(jsonb_agg(jsonb_build_object(
           'id',id,'semester',semester_key,'code',code,'label',label,
           'cycle',jsonb_build_object('id',cycle_id,'code',cycle_code),
           'studentTeamCreationEnabled',student_team_creation_enabled)
         ORDER BY id) FILTER (WHERE position<=50),'[]'::jsonb),
         CASE WHEN count(*)>50 THEN
           (array_agg(id ORDER BY id) FILTER (WHERE position=50))[1] END
  INTO page,next_cursor FROM numbered;
  RETURN jsonb_build_object('results',page,'nextCursor',next_cursor);
END;
$$;
REVOKE ALL ON TABLE student_offering_windows FROM PUBLIC,smartpro_runtime;
REVOKE ALL ON FUNCTION smartpro_student_profile(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION smartpro_student_offerings(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION smartpro_student_profile(uuid) TO smartpro_runtime;
GRANT EXECUTE ON FUNCTION smartpro_student_offerings(uuid,uuid) TO smartpro_runtime;
COMMIT;
