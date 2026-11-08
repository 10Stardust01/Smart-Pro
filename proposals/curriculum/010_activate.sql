-- Candidate migration 010, activation phase. Requires reviewed legacy mapping.
-- Stop application writers for the complete prepare/map/preflight/activate process.
BEGIN;
LOCK TABLE student_profiles,curriculum_types,curriculum_offerings,teams,team_memberships
  IN ACCESS EXCLUSIVE MODE;
DO $$
BEGIN
  IF EXISTS(SELECT 1 FROM teams WHERE curriculum_offering_id IS NULL) THEN
    RAISE EXCEPTION 'Map every existing team to a curriculum offering before activation'
      USING ERRCODE='23514';
  END IF;
  IF EXISTS(SELECT 1 FROM team_memberships m LEFT JOIN student_profiles s ON s.user_id=m.user_id
            WHERE s.user_id IS NULL) THEN
    RAISE EXCEPTION 'Verify USN identity for every historical and current member before activation'
      USING ERRCODE='23514';
  END IF;
  IF EXISTS(SELECT 1 FROM team_memberships m
            JOIN teams t ON t.id=m.team_id
            JOIN curriculum_offerings o ON o.id=t.curriculum_offering_id
            JOIN student_profiles s ON s.user_id=m.user_id
            WHERE (m.left_at IS NULL OR m.left_at>statement_timestamp())
              AND (s.department_id,s.semester_key) IS DISTINCT FROM (o.department_id,o.semester_key)) THEN
    RAISE EXCEPTION 'End incompatible current or scheduled memberships before activation'
      USING ERRCODE='23514';
  END IF;
END;
$$;
-- This adds classification only. Existing identities and membership intervals
-- are unchanged, and all previous historical eligibility triggers stay enabled.
UPDATE team_memberships m SET curriculum_offering_id=t.curriculum_offering_id
  FROM teams t WHERE t.id=m.team_id;
ALTER TABLE teams ALTER COLUMN curriculum_offering_id SET NOT NULL;
ALTER TABLE team_memberships ALTER COLUMN curriculum_offering_id SET NOT NULL;
ALTER TABLE team_memberships ADD CONSTRAINT membership_student_identity
  FOREIGN KEY (user_id) REFERENCES student_profiles(user_id);
ALTER TABLE team_memberships ADD CONSTRAINT membership_team_offering
  FOREIGN KEY (team_id,curriculum_offering_id) REFERENCES teams(id,curriculum_offering_id);
-- [joined_at,left_at) permits an atomic end + join at the same instant. GiST
-- exclusion also protects concurrent transactions; a pre-insert SELECT cannot.
-- Conflicting legacy intervals reject the whole activation; never rewrite them.
ALTER TABLE team_memberships ADD CONSTRAINT one_team_per_curriculum_offering
  EXCLUDE USING gist(user_id WITH =,curriculum_offering_id WITH =,
                     tstzrange(joined_at,left_at,'[)') WITH &&);

-- A real row version change serializes joins/extensions with profile edits,
-- including REPEATABLE READ snapshots (which must retry on SQLSTATE 40001).
ALTER TABLE student_profiles ADD COLUMN membership_scope_revision uuid NOT NULL DEFAULT gen_random_uuid();

-- New joins must be for the student's home department and current semester.
-- Historical memberships mapped during activation remain unchanged.
-- Future cross-department eligibility must be an explicit reviewed policy.
CREATE FUNCTION smartpro_membership_scope_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
  student_department uuid;
  student_semester text;
  offering_department uuid;
  offering_semester text;
BEGIN
  -- Shortening/closing an interval preserves history and needs no new eligibility.
  IF TG_OP='UPDATE' THEN
    IF OLD.left_at IS NULL OR (NEW.left_at IS NOT NULL AND NEW.left_at<=OLD.left_at) THEN
      RETURN NEW;
    END IF;
  END IF;
  UPDATE public.student_profiles s SET membership_scope_revision=gen_random_uuid()
    WHERE s.user_id=NEW.user_id
    RETURNING s.department_id,s.semester_key INTO student_department,student_semester;
  SELECT o.department_id,o.semester_key
    INTO offering_department,offering_semester
    FROM public.curriculum_offerings o
    WHERE o.id=NEW.curriculum_offering_id FOR SHARE OF o;
  -- Missing referenced records are handled by the existing FK constraints.
  IF student_department IS NOT NULL AND offering_department IS NOT NULL AND
      (student_department IS DISTINCT FROM offering_department OR
       student_semester IS DISTINCT FROM offering_semester) THEN
    RAISE EXCEPTION 'student may join only offerings in their home department and current semester'
      USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER verify_membership_scope BEFORE INSERT OR UPDATE OF left_at ON team_memberships
  FOR EACH ROW EXECUTE FUNCTION smartpro_membership_scope_guard();
REVOKE ALL ON FUNCTION smartpro_membership_scope_guard() FROM PUBLIC;

-- A scope edit must first end every incompatible unended/future interval.
-- The UPDATE row lock conflicts with the membership guard's revision write.
CREATE FUNCTION smartpro_student_scope_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF (NEW.department_id,NEW.semester_key) IS DISTINCT FROM (OLD.department_id,OLD.semester_key)
    AND EXISTS(SELECT 1 FROM public.team_memberships m
      JOIN public.curriculum_offerings o ON o.id=m.curriculum_offering_id
      WHERE m.user_id=OLD.user_id AND (m.left_at IS NULL OR m.left_at>statement_timestamp())
        AND (NEW.department_id,NEW.semester_key) IS DISTINCT FROM (o.department_id,o.semester_key)) THEN
    RAISE EXCEPTION 'End incompatible current or scheduled memberships before changing student scope'
      USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER verify_student_scope BEFORE UPDATE ON student_profiles
  FOR EACH ROW EXECUTE FUNCTION smartpro_student_scope_guard();
REVOKE ALL ON FUNCTION smartpro_student_scope_guard() FROM PUBLIC;

CREATE FUNCTION smartpro_curriculum_identity_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF TG_TABLE_NAME='teams' THEN
    IF (NEW.id,NEW.department_id,NEW.cycle_id,NEW.curriculum_offering_id)
      IS DISTINCT FROM (OLD.id,OLD.department_id,OLD.cycle_id,OLD.curriculum_offering_id) THEN
      RAISE EXCEPTION 'team offering identity is immutable; create a separate team'
        USING ERRCODE='23514';
    END IF;
  ELSIF TG_TABLE_NAME='team_memberships' THEN
    IF (NEW.id,NEW.team_id,NEW.user_id,NEW.curriculum_offering_id,NEW.joined_at)
      IS DISTINCT FROM (OLD.id,OLD.team_id,OLD.user_id,OLD.curriculum_offering_id,OLD.joined_at) THEN
      RAISE EXCEPTION 'membership identity is immutable; end and append membership'
        USING ERRCODE='23514';
    END IF;
  ELSIF TG_TABLE_NAME='curriculum_offerings' THEN
    IF (NEW.id,NEW.curriculum_type_id,NEW.department_id,NEW.cycle_id,NEW.semester_key)
      IS DISTINCT FROM (OLD.id,OLD.curriculum_type_id,OLD.department_id,OLD.cycle_id,OLD.semester_key) THEN
      RAISE EXCEPTION 'offering scope is immutable; create a separate offering'
        USING ERRCODE='23514';
    END IF;
  ELSIF TG_TABLE_NAME='curriculum_types' THEN
    IF (NEW.id,NEW.code) IS DISTINCT FROM (OLD.id,OLD.code) THEN
      RAISE EXCEPTION 'curriculum type identity is immutable' USING ERRCODE='23514';
    END IF;
  ELSIF NEW.user_id IS DISTINCT FROM OLD.user_id THEN
    RAISE EXCEPTION 'student identity is immutable; correct the USN on the same user'
      USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER freeze_team_curriculum BEFORE UPDATE ON teams
  FOR EACH ROW EXECUTE FUNCTION smartpro_curriculum_identity_guard();
CREATE TRIGGER freeze_membership_curriculum BEFORE UPDATE ON team_memberships
  FOR EACH ROW EXECUTE FUNCTION smartpro_curriculum_identity_guard();
CREATE TRIGGER freeze_offering_scope BEFORE UPDATE ON curriculum_offerings
  FOR EACH ROW EXECUTE FUNCTION smartpro_curriculum_identity_guard();
CREATE TRIGGER freeze_curriculum_type BEFORE UPDATE ON curriculum_types
  FOR EACH ROW EXECUTE FUNCTION smartpro_curriculum_identity_guard();
CREATE TRIGGER freeze_student_identity BEFORE UPDATE ON student_profiles
  FOR EACH ROW EXECUTE FUNCTION smartpro_curriculum_identity_guard();
REVOKE ALL ON FUNCTION smartpro_curriculum_identity_guard() FROM PUBLIC;
-- No new grants or callable SECURITY DEFINER write commands. Runtime cannot create teams,
-- grant itself permissions, read the USN registry or modify offerings/profiles.
COMMIT;
