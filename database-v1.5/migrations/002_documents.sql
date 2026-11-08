BEGIN;
CREATE TABLE file_assets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  storage_key text NOT NULL UNIQUE,
  sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
  mime_type text NOT NULL,
  upload_status text NOT NULL DEFAULT 'PENDING' CHECK (upload_status IN ('PENDING','READY','REJECTED')),
  uploaded_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  verified_at timestamptz
);
CREATE TABLE documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id),
  document_type text NOT NULL CHECK (document_type IN ('SYNOPSIS','REPORT','PRESENTATION','SOURCE_CODE','DATASET','OTHER')),
  label text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, project_id)
);
CREATE TABLE document_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL,
  document_id uuid NOT NULL,
  version_no integer NOT NULL CHECK (version_no > 0),
  file_asset_id uuid NOT NULL UNIQUE REFERENCES file_assets(id),
  uploaded_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (document_id, project_id) REFERENCES documents(id,project_id),
  UNIQUE (document_id, version_no),
  UNIQUE (id, document_id, project_id),
  UNIQUE (id, project_id)
);

CREATE TABLE submission_cases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id),
  requirement_key text NOT NULL CHECK (btrim(requirement_key) <> ''),
  submission_type text NOT NULL CHECK (submission_type IN ('SYNOPSIS','REVIEW_DOCUMENT','FINAL_REPORT','OTHER')),
  state text NOT NULL DEFAULT 'DRAFT' CHECK (state IN ('DRAFT','AWAITING_REVIEW','CHANGES_REQUESTED','APPROVED','REJECTED')),
  row_version integer NOT NULL DEFAULT 1 CHECK (row_version > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, requirement_key),
  UNIQUE (id, project_id)
);
CREATE TABLE submission_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id uuid NOT NULL,
  project_id uuid NOT NULL,
  attempt_no integer NOT NULL CHECK (attempt_no > 0),
  submitted_by uuid NOT NULL REFERENCES users(id),
  submitted_at timestamptz NOT NULL DEFAULT now(),
  attempt_state text NOT NULL DEFAULT 'SUBMITTED' CHECK (attempt_state IN ('SUBMITTED','CHANGES_REQUESTED','APPROVED','REJECTED')),
  FOREIGN KEY (case_id,project_id) REFERENCES submission_cases(id,project_id),
  UNIQUE (case_id,attempt_no),
  UNIQUE (id,project_id),
  UNIQUE (id,case_id)
);
CREATE TABLE submission_items (
  attempt_id uuid NOT NULL,
  project_id uuid NOT NULL,
  document_id uuid NOT NULL,
  document_version_id uuid NOT NULL,
  PRIMARY KEY(attempt_id,document_id),
  FOREIGN KEY(attempt_id,project_id) REFERENCES submission_attempts(id,project_id),
  FOREIGN KEY(document_version_id,document_id,project_id)
    REFERENCES document_versions(id,document_id,project_id)
);
CREATE TABLE approval_decisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  attempt_id uuid NOT NULL,
  project_id uuid NOT NULL,
  reviewer_user_id uuid NOT NULL REFERENCES users(id),
  decision text NOT NULL CHECK (decision IN ('APPROVE','REQUEST_CHANGES','REJECT')),
  comment text,
  decided_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(attempt_id,project_id) REFERENCES submission_attempts(id,project_id),
  UNIQUE(attempt_id,reviewer_user_id)
);
CREATE INDEX ix_document_versions_document ON document_versions(document_id,version_no DESC);
CREATE INDEX ix_submissions_cases_project ON submission_cases(project_id);
CREATE INDEX ix_attempts_case ON submission_attempts(case_id,attempt_no DESC);
CREATE INDEX ix_approval_decisions_reviewer ON approval_decisions(reviewer_user_id,decided_at DESC);
COMMIT;
