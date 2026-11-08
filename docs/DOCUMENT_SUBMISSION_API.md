# Current document authority amendments (025–028)

Admin may record and implement externally communicated HOD-approved instructions
through setup `action: RECORD`, with source/recording-actor provenance. The older
in-app AUTHORIZE/CONFIGURE path below remains optional and compatible. Notes are
optional; automatic history is mandatory. Guide/evaluator assignments permit scoped
reading, while formal feedback/decisions require explicit synopsis REVIEWER assignment
and the pinned faculty-approval configuration. No public file URLs are introduced.
See [current contracts and verification](APPLICATION_CORRECTIONS.md).

# Local synopsis submission and review

Implemented on the existing Django/DRF, PostgreSQL and private local file store.
No production identity, deployment or real-data migration is enabled. Candidate
019 follows 018; migrations 001–018 are unchanged.

## Authority and lifecycle

- An explicit, active HOD mandate authorizes an immutable offering instruction:
  existing curriculum type/cycle/semester, approved project/team policy versions,
  named ACADEMIC_ADMIN role record, visibility/registration and submission windows,
  PDF size, team-creation choice and faculty-approval choice.
- The named, active Admin executes that exact instruction. The original HOD
  mandate must remain active. Admin cannot supply replacement configuration,
  authorize policy, review submissions or read documents through this role.
  TECH_ADMIN alone still grants no academic powers. HOD and Admin have distinct
  synthetic identities and dashboard labels.
- Configuration creates an offering or reuses its existing scoped identity.
  Subsequent instructions append requirement/registration versions. New cases
  use the current requirement; existing cases retain their original policy.
  Older pending instructions cannot roll back a newer configured version.
- Student eligibility comes from active account, effective STUDENT role, trusted
  department/semester profile, current team membership and the project's offering
  and cycle. Existing registration/membership services remain authoritative.
- HOD or appointed coordinator explicitly assigns a project REVIEWER. Existing
  GUIDE/REVIEWER assignments with active scoped FACULTY roles authorize document
  review; evaluator assignment alone does not grant synopsis-review powers.
- The user explicitly authorized assigned faculty to approve synopses on
  5 November 2026. Each HOD instruction still chooses
  `facultyApprovalEnabled`; omission/false does not activate approval. Supported
  decisions are REQUEST_CHANGES and, when enabled, APPROVE. One authorized
  decision closes the latest pending attempt, following the existing contract.
  No coordinator approval or additional document-review quorum is invented.
- New attempts are accepted from DRAFT/CHANGES_REQUESTED. Approval closes that
  case. Original PDF versions, attempts, feedback, actor identities and timestamps
  remain stored. This slice provides no retrospective reopening/deadline exception.

## Routes

All routes require trusted authentication. Demo authentication still needs both
explicit demo switches. `SMARTPRO_DOCUMENT_API=YES` and the academic API gate are
required; enabled departmental governance/staff controls are also checked.

`GET /api/v1/documents/departments/{departmentId}` returns authorized projects,
requirements, file versions, submission attempts/feedback, applicable operational
instructions and role-appropriate configuration choices. Bounded to 50 projects,
instructions and option rows; no public storage keys or URLs are returned.

`POST` to that same route accepts `action` and exactly these fields:

| Action | Fields |
|---|---|
| AUTHORIZE | configuration, reason |
| CONFIGURE | instructionId |
| ASSIGN_REVIEWER | projectId, facultyId |
| PREPARE | projectId |
| SUBMIT | projectId, documentVersionId, expectedCaseVersion |
| DECIDE | projectId, attemptId, expectedCaseVersion, decision, comment |

Configuration fields: `curriculumTypeId`, `cycleId`, `semester`,
`projectPolicyId`, `teamPolicyId`, `adminRoleId`, `visibleFrom`, `visibleUntil`,
`submissionOpensAt`, `submissionClosesAt`, `maxBytes`,
`facultyApprovalEnabled`, `teamCreationEnabled`. Dates require explicit offsets;
booleans are explicit. Options come from existing scoped backend records.

`POST /api/v1/documents/departments/{departmentId}/projects/{projectId}/uploads`
accepts multipart `file` only. Filename suffix and MIME must be PDF. The streamed
request/file is bounded, maximum 2 MiB or the lower approved requirement limit.
PDF signature/completion, prohibited active-content markers and the installed
`pdfinfo` parser are checked; PDFs must have 1–50 pages. This is not a malware
scanner or a production parser sandbox.

`GET /api/v1/document-versions/{versionId}/content` returns authorized PDF bytes;
`?download=1` requests an attachment. `?preview=1&page=1` returns a private PNG
rendered by local `pdftoppm`, with `X-Document-Pages` for navigation. Each request
reauthorizes access, verifies stored size/SHA-256 and records an access audit.
Responses are private/no-store; there is no static/media document URL.

The existing `/api/v1/me/curriculum-offerings` adds `projectTypes` from open,
approved offering registration policies. The student UI offers these actual
classifications rather than assuming MAJOR. Candidate 022 now derives that class
on the backend; the current student form never selects it or supplies a project
code. See APPLICATION_CORRECTIONS.md for the managed proposal and role header contract.

## Transactions, files and installation

Commands require Idempotency-Key (upload keys up to 110 characters). Private
receipts bind actor/action/payload; retries reauthorize before returning results.
Whole-transaction 40001/40P01 retries reuse the reviewed staff command service.
Project synopsis operations serialize, uploads receive ordered document versions,
and submission/review uses a case revision. Stale/conflicting commands fail.

The existing documents/file_assets/document_versions/upload_sessions and
submission_cases/attempts/items/approval_decisions are reused. New tables store
HOD instructions, executions, immutable requirement policies, their current
offering pointer, pinned case bindings and private command receipts. Narrow
definer commands have fixed search paths; managed-record guards reject legacy
direct runtime writes without changing older academic evidence.

Private files stay under SMARTPRO_DATA_DIR/files, using server-generated UUID
keys. Atomic no-replace hard links publish fsynced staging bytes. Failed metadata
commits can leave private orphan bytes; same-key retries reuse the verified object.
No prior object is overwritten. Storage must support hard links. Orphan retention,
quotas, scanner isolation and backup/restore are production work, not silently
enabled cleanup jobs.

Owner-run order: 019_document_workflow.sql → 019_document_reads.sql →
019_document_guards.sql. Apply as one transaction with application writes stopped;
the synthetic `install_documents` helper strips the individual wrappers and does
this atomically. Each part checks prerequisites. The demo launcher installs these
only in its reviewed synthetic clone; it never runs 010–015 for demo setup.

Run verification: `.venv\Scripts\python.exe scripts/test_document_workflow.py`.
It creates and removes only newly named disposable clones, with temporary private
storage; source/live demo data remains persistent. Coverage includes actual PDF
retrieval/rendering, revisions/approval, role and revoked-access denials, disabled
controls, malformed/oversized files, stale commands, idempotency/concurrency,
rollback/retry, corruption/missing storage, policy pinning, direct-write guards,
and clean/missing-prerequisite candidate installation.
