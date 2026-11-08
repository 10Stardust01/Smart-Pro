-- Candidate migration 010, expansion phase. NOT in the automatic migrations path.
-- Apply only as migration owner after 001-009, with application writes stopped.
BEGIN;
DO $$ BEGIN
  IF to_regprocedure('public.smartpro_review_definition_history()') IS NULL
    OR to_regprocedure('public.smartpro_submitter_snapshot()') IS NULL THEN
    RAISE EXCEPTION 'Install baseline 001-009 historical integrity guards before curriculum preparation';
  END IF;
END $$;
-- Student registration needs only the confirmed five details. Preserve existing
-- addresses and the validity/uniqueness checks on any supplied email.
ALTER TABLE users ALTER COLUMN email DROP NOT NULL;
CREATE TABLE student_profiles (
  user_id uuid PRIMARY KEY REFERENCES users(id),
  usn text NOT NULL UNIQUE,
  section text NOT NULL CHECK (btrim(section)<>''),
  semester_key text NOT NULL CHECK (btrim(semester_key)<>''),
  department_id uuid NOT NULL REFERENCES departments(id),
  CONSTRAINT canonical_student_usn CHECK (usn<>'' AND usn=upper(btrim(usn)))
);
-- No VTU format regex is invented; import and verify identities separately.
CREATE TABLE curriculum_types (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code text NOT NULL UNIQUE CHECK (code<>'' AND code=upper(btrim(code))),
  label text NOT NULL CHECK (btrim(label)<>'')
);
CREATE TABLE curriculum_offerings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  curriculum_type_id uuid NOT NULL REFERENCES curriculum_types(id),
  department_id uuid NOT NULL REFERENCES departments(id),
  cycle_id uuid NOT NULL,
  semester_key text NOT NULL CHECK (btrim(semester_key)<>''),
  student_team_creation_enabled boolean NOT NULL DEFAULT false,
  FOREIGN KEY (cycle_id,department_id) REFERENCES academic_cycles(id,department_id),
  UNIQUE (department_id,cycle_id,semester_key,curriculum_type_id),
  UNIQUE (id,cycle_id,department_id)
);
ALTER TABLE teams ADD COLUMN curriculum_offering_id uuid;
ALTER TABLE teams ADD CONSTRAINT team_offering_scope
  FOREIGN KEY (curriculum_offering_id,cycle_id,department_id)
  REFERENCES curriculum_offerings(id,cycle_id,department_id);
ALTER TABLE teams ADD UNIQUE (id,curriculum_offering_id);
ALTER TABLE team_memberships ADD COLUMN curriculum_offering_id uuid;
-- Nullable fields are for explicit legacy mapping only. This phase is not an
-- operational state for team writes; activation below is required before use.
COMMIT;
