BEGIN;
-- The academic cycle and policy determine which review definitions apply.
CREATE TABLE review_definitions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  policy_version_id uuid NOT NULL,
  department_id uuid NOT NULL,
  project_type text NOT NULL,
  review_code text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal > 0),
  label text NOT NULL,
  FOREIGN KEY(policy_version_id, department_id, project_type)
    REFERENCES project_policy_versions(id, department_id, project_type),
  UNIQUE (policy_version_id,review_code),
  UNIQUE (policy_version_id,ordinal),
  UNIQUE (id,policy_version_id),
  UNIQUE (id,department_id)
);
CREATE TABLE evaluation_schemes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  department_id uuid NOT NULL,
  cycle_id uuid NOT NULL,
  review_definition_id uuid NOT NULL,
  label text NOT NULL,
  FOREIGN KEY(cycle_id,department_id) REFERENCES academic_cycles(id,department_id),
  FOREIGN KEY(review_definition_id,department_id) REFERENCES review_definitions(id,department_id),
  UNIQUE (cycle_id,review_definition_id),
  UNIQUE (id,cycle_id,review_definition_id)
);
CREATE TABLE scheme_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scheme_id uuid NOT NULL,
  cycle_id uuid NOT NULL,
  review_definition_id uuid NOT NULL,
  version_no integer NOT NULL CHECK (version_no > 0),
  state text NOT NULL DEFAULT 'DRAFT' CHECK (state IN ('DRAFT','APPROVED','ACTIVE','RETIRED')),
  approved_by uuid REFERENCES users(id),
  approved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(scheme_id,cycle_id,review_definition_id)
    REFERENCES evaluation_schemes(id,cycle_id,review_definition_id),
  UNIQUE(scheme_id,version_no),
  UNIQUE(id,cycle_id,review_definition_id)
);
CREATE UNIQUE INDEX uq_active_scheme_version ON scheme_versions(scheme_id) WHERE state='ACTIVE';
CREATE TABLE rubric_criteria (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scheme_version_id uuid NOT NULL REFERENCES scheme_versions(id),
  code text NOT NULL,
  label text NOT NULL,
  maximum NUMERIC(9,2) NOT NULL CHECK (maximum > 0),
  sort_order integer NOT NULL CHECK (sort_order > 0),
  UNIQUE(scheme_version_id,code),
  UNIQUE(scheme_version_id,sort_order),
  UNIQUE(id,scheme_version_id)
);
CREATE TABLE scheme_modes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scheme_version_id uuid NOT NULL REFERENCES scheme_versions(id),
  mode_code text NOT NULL CHECK (mode_code IN ('TEAM','INDIVIDUAL','COMBINED')),
  UNIQUE(scheme_version_id,mode_code),
  UNIQUE(scheme_version_id,id),
  UNIQUE(id,scheme_version_id)
);
CREATE TABLE mode_criteria (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scheme_version_id uuid NOT NULL,
  scheme_mode_id uuid NOT NULL,
  criterion_id uuid NOT NULL,
  score_scope text NOT NULL CHECK (score_scope IN ('TEAM','STUDENT')),
  FOREIGN KEY(scheme_version_id,scheme_mode_id) REFERENCES scheme_modes(scheme_version_id,id),
  FOREIGN KEY(criterion_id,scheme_version_id) REFERENCES rubric_criteria(id,scheme_version_id),
  UNIQUE(scheme_mode_id,criterion_id),
  UNIQUE(id,scheme_mode_id,score_scope)
);

CREATE TABLE project_reviews (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL,
  cycle_id uuid NOT NULL,
  policy_version_id uuid NOT NULL,
  review_definition_id uuid NOT NULL,
  round_no integer NOT NULL DEFAULT 1 CHECK(round_no > 0),
  scheme_version_id uuid NOT NULL,
  scheme_mode_id uuid,
  review_state text NOT NULL DEFAULT 'SCHEDULED'
    CHECK(review_state IN ('SCHEDULED','OPEN','FINALIZED','RELEASED','CANCELLED')),
  scheduled_at timestamptz,
  roster_locked_at timestamptz,
  row_version integer NOT NULL DEFAULT 1 CHECK(row_version > 0),
  FOREIGN KEY(project_id,cycle_id,policy_version_id)
    REFERENCES projects(id,cycle_id,policy_version_id),
  FOREIGN KEY(review_definition_id,policy_version_id)
    REFERENCES review_definitions(id,policy_version_id),
  FOREIGN KEY(scheme_version_id,cycle_id,review_definition_id)
    REFERENCES scheme_versions(id,cycle_id,review_definition_id),
  FOREIGN KEY(scheme_version_id,scheme_mode_id)
    REFERENCES scheme_modes(scheme_version_id,id),
  CHECK(review_state IN ('SCHEDULED','CANCELLED') OR (scheme_mode_id IS NOT NULL AND roster_locked_at IS NOT NULL)),
  UNIQUE(project_id,review_definition_id,round_no),
  UNIQUE(id,project_id),
  UNIQUE(id,scheme_mode_id),
  UNIQUE(id,scheme_version_id,scheme_mode_id)
);
CREATE TABLE review_roster_members (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  review_id uuid NOT NULL,
  project_id uuid NOT NULL,
  team_id uuid NOT NULL,
  membership_id uuid NOT NULL,
  student_user_id uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(review_id,project_id) REFERENCES project_reviews(id,project_id),
  FOREIGN KEY(project_id,team_id) REFERENCES projects(id,team_id),
  FOREIGN KEY(membership_id,team_id,student_user_id)
    REFERENCES team_memberships(id,team_id,user_id),
  UNIQUE(review_id,student_user_id),
  UNIQUE(id,review_id)
);
CREATE TABLE evaluator_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  review_id uuid NOT NULL REFERENCES project_reviews(id),
  faculty_user_id uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(review_id,faculty_user_id),
  UNIQUE(id,review_id)
);
CREATE TABLE assessments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  review_id uuid NOT NULL,
  scheme_mode_id uuid NOT NULL,
  evaluator_assignment_id uuid NOT NULL,
  state text NOT NULL DEFAULT 'DRAFT' CHECK(state IN ('DRAFT','FINALIZED')),
  row_version integer NOT NULL DEFAULT 1 CHECK(row_version > 0),
  finalized_at timestamptz,
  FOREIGN KEY(review_id,scheme_mode_id) REFERENCES project_reviews(id,scheme_mode_id),
  FOREIGN KEY(evaluator_assignment_id,review_id)
    REFERENCES evaluator_assignments(id,review_id),
  UNIQUE(evaluator_assignment_id),
  UNIQUE(id,scheme_mode_id),
  UNIQUE(id,review_id),
  UNIQUE(id,review_id,scheme_mode_id)
);
CREATE TABLE team_criterion_scores (
  assessment_id uuid NOT NULL,
  scheme_mode_id uuid NOT NULL,
  mode_criterion_id uuid NOT NULL,
  score_scope text NOT NULL DEFAULT 'TEAM' CHECK(score_scope='TEAM'),
  marks NUMERIC(9,2) NOT NULL CHECK(marks >= 0),
  PRIMARY KEY(assessment_id,mode_criterion_id),
  FOREIGN KEY(assessment_id,scheme_mode_id) REFERENCES assessments(id,scheme_mode_id),
  FOREIGN KEY(mode_criterion_id,scheme_mode_id,score_scope)
    REFERENCES mode_criteria(id,scheme_mode_id,score_scope)
);
CREATE TABLE student_criterion_scores (
  assessment_id uuid NOT NULL,
  review_id uuid NOT NULL,
  scheme_mode_id uuid NOT NULL,
  roster_member_id uuid NOT NULL,
  mode_criterion_id uuid NOT NULL,
  score_scope text NOT NULL DEFAULT 'STUDENT' CHECK(score_scope='STUDENT'),
  marks NUMERIC(9,2) NOT NULL CHECK(marks >= 0),
  PRIMARY KEY(assessment_id,roster_member_id,mode_criterion_id),
  FOREIGN KEY(assessment_id,review_id,scheme_mode_id)
    REFERENCES assessments(id,review_id,scheme_mode_id),
  FOREIGN KEY(roster_member_id,review_id)
    REFERENCES review_roster_members(id,review_id),
  FOREIGN KEY(mode_criterion_id,scheme_mode_id,score_scope)
    REFERENCES mode_criteria(id,scheme_mode_id,score_scope)
);
CREATE TABLE result_releases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  review_id uuid NOT NULL,
  release_no integer NOT NULL CHECK(release_no>0),
  scheme_version_id uuid NOT NULL,
  scheme_mode_id uuid NOT NULL,
  calculation_snapshot jsonb NOT NULL CHECK(jsonb_typeof(calculation_snapshot)='object'),
  released_by uuid NOT NULL REFERENCES users(id),
  released_at timestamptz NOT NULL DEFAULT now(),
  supersedes_id uuid,
  FOREIGN KEY(review_id,scheme_version_id,scheme_mode_id)
    REFERENCES project_reviews(id,scheme_version_id,scheme_mode_id),
  UNIQUE(review_id,release_no),
  UNIQUE(id,review_id),
  FOREIGN KEY(supersedes_id,review_id) REFERENCES result_releases(id,review_id)
);
CREATE TABLE result_student_scores (
  release_id uuid NOT NULL,
  review_id uuid NOT NULL,
  roster_member_id uuid NOT NULL,
  total_marks NUMERIC(9,2) NOT NULL CHECK(total_marks>=0),
  breakdown jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(breakdown)='object'),
  PRIMARY KEY(release_id,roster_member_id),
  FOREIGN KEY(release_id,review_id) REFERENCES result_releases(id,review_id),
  FOREIGN KEY(roster_member_id,review_id) REFERENCES review_roster_members(id,review_id)
);
CREATE TABLE result_source_assessments (
  release_id uuid NOT NULL,
  review_id uuid NOT NULL,
  assessment_id uuid NOT NULL,
  PRIMARY KEY(release_id,assessment_id),
  FOREIGN KEY(release_id,review_id) REFERENCES result_releases(id,review_id),
  FOREIGN KEY(assessment_id,review_id) REFERENCES assessments(id,review_id)
);

CREATE INDEX ix_review_project ON project_reviews(project_id,review_definition_id);
CREATE INDEX ix_roster_review ON review_roster_members(review_id);
CREATE INDEX ix_assessments_review ON assessments(review_id);
CREATE INDEX ix_releases_review ON result_releases(review_id,release_no DESC);
COMMIT;
