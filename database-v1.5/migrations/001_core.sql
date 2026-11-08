-- SMART-PRO reference schema, v1.5 (PostgreSQL 15+).
-- DRAFT engineering prototype, not faculty-approved policy or production release.
BEGIN;
-- gen_random_uuid() is built into supported PostgreSQL versions.

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  display_name text NOT NULL CHECK (btrim(display_name) <> ''),
  email text NOT NULL CHECK (email = btrim(email) AND position('@' in email) > 1),
  external_subject text UNIQUE,
  account_status text NOT NULL DEFAULT 'ACTIVE' CHECK (account_status IN ('ACTIVE','DISABLED')),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_users_email_ci ON users (lower(email));

CREATE TABLE departments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code text NOT NULL UNIQUE CHECK (btrim(code) <> ''),
  name text NOT NULL CHECK (btrim(name) <> '')
);
CREATE TABLE academic_cycles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  department_id uuid NOT NULL REFERENCES departments(id),
  code text NOT NULL CHECK (btrim(code) <> ''),
  starts_on date NOT NULL,
  ends_on date NOT NULL,
  CHECK (starts_on < ends_on),
  UNIQUE (department_id, code),
  UNIQUE (id, department_id)
);
CREATE TABLE department_role_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id),
  department_id uuid NOT NULL REFERENCES departments(id),
  role_code text NOT NULL CHECK (role_code IN ('STUDENT','FACULTY','COORDINATOR','HOD','ACADEMIC_ADMIN','TECH_ADMIN')),
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_until timestamptz,
  CHECK (valid_until IS NULL OR valid_until > valid_from)
);
CREATE UNIQUE INDEX uq_active_department_role ON department_role_assignments(user_id, department_id, role_code) WHERE valid_until IS NULL;

CREATE TABLE project_policy_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  department_id uuid NOT NULL REFERENCES departments(id),
  project_type text NOT NULL CHECK (project_type IN ('MINI','MAJOR')),
  version_no integer NOT NULL CHECK (version_no > 0),
  policy_status text NOT NULL DEFAULT 'DRAFT' CHECK (policy_status IN ('DRAFT','APPROVED','RETIRED')),
  policy_data jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(policy_data)='object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (department_id, project_type, version_no),
  UNIQUE (id, department_id, project_type)
);

CREATE TABLE teams (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  department_id uuid NOT NULL,
  cycle_id uuid NOT NULL,
  name text NOT NULL CHECK (btrim(name) <> ''),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (cycle_id, department_id) REFERENCES academic_cycles(id, department_id),
  UNIQUE (id, cycle_id, department_id)
);
CREATE TABLE team_memberships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  team_id uuid NOT NULL REFERENCES teams(id),
  user_id uuid NOT NULL REFERENCES users(id),
  joined_at timestamptz NOT NULL DEFAULT now(),
  left_at timestamptz,
  CHECK (left_at IS NULL OR left_at > joined_at),
  UNIQUE (id, team_id, user_id)
);
CREATE UNIQUE INDEX uq_active_team_member ON team_memberships(team_id, user_id) WHERE left_at IS NULL;

CREATE TABLE projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  department_id uuid NOT NULL,
  cycle_id uuid NOT NULL,
  team_id uuid NOT NULL,
  project_type text NOT NULL CHECK (project_type IN ('MINI','MAJOR')),
  policy_version_id uuid NOT NULL,
  project_code text NOT NULL CHECK (btrim(project_code) <> ''),
  title text NOT NULL CHECK (btrim(title) <> ''),
  row_version integer NOT NULL DEFAULT 1 CHECK (row_version > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (cycle_id, department_id) REFERENCES academic_cycles(id, department_id),
  FOREIGN KEY (team_id, cycle_id, department_id) REFERENCES teams(id, cycle_id, department_id),
  FOREIGN KEY (policy_version_id, department_id, project_type)
    REFERENCES project_policy_versions(id, department_id, project_type),
  UNIQUE (department_id, project_code),
  UNIQUE (id, cycle_id, policy_version_id),
  UNIQUE (id, team_id),
  UNIQUE (id, department_id)
);
CREATE TABLE faculty_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id),
  faculty_user_id uuid NOT NULL REFERENCES users(id),
  assignment_type text NOT NULL CHECK (assignment_type IN ('GUIDE','REVIEWER','EVALUATOR')),
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_until timestamptz,
  CHECK (valid_until IS NULL OR valid_until > valid_from),
  UNIQUE (id, project_id)
);
CREATE TABLE milestones (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id),
  title text NOT NULL CHECK (btrim(title) <> ''),
  due_at timestamptz,
  state text NOT NULL DEFAULT 'PENDING' CHECK (state IN ('PENDING','ACTIVE','COMPLETED','CANCELLED'))
);
CREATE INDEX ix_projects_cycle ON projects(cycle_id);
CREATE INDEX ix_faculty_assignments_user ON faculty_assignments(faculty_user_id, valid_until);
CREATE INDEX ix_team_membership_user ON team_memberships(user_id);
COMMIT;
