# SMART-PRO application correction milestone — 6 November 2026

Local only, `feature/finalized-academic-policies`, continuing `89f1fcc`.
Backend/security/startup increment: `36bbbd4`; the following frontend commit completes this verified milestone.
No GitHub operations, production activation, persistent-database reset or historical
migration edits. SMART-PRO is a departmental application, not a seeded product.

## Root causes corrected

- Mandatory notes existed in forms, DRF validation, SQL functions and constraints.
  Appointment/revocation, assignments, planning, configuration, scoring, publication
  and original-evaluator corrections now accept omitted/blank notes. No fabricated
  explanation is substituted. Automatic actor/time/action/history auditing remains.
- Candidates 019–023 forced every configuration through an in-app approval chain.
  Admin can now record and implement HOD-approved external instructions directly.
  The existing exact-request approval path remains compatible, but is optional.
  External records explicitly identify their source, responsible HOD mandate,
  recording Admin and optional reference. They do not fabricate a HOD login/click.
- Persistent fixture setup/serving was treated as normal startup. That launcher is
  archived. Normal startup never seeds data, creates approvals or runs migrations.
  New browser verification uses a schema-only isolated database with identity and
  authority fixtures, initially zero offerings/policies/projects/assignments/results.
- The HOD frontend incorrectly depended on legacy staff-read grants found in old
  fixtures. It now uses the already-authorized academic workspace and policy API.
- Initial proposals lacked a persisted description. The coherent offering → team
  → title/description/PDF → review → submission flow now retains immutable details.
  Server-generated references/classifications and existing retry/transaction guards
  remain. Changed-description retries conflict rather than overwrite evidence.
- Legacy synopsis permission conflated guide and reviewer. Guides and assigned
  evaluators may read relevant submissions, but only explicitly assigned synopsis
  reviewers may decide them, under the configured faculty-approval policy.
- Setup is organized into expandable tasks; project search/status filters, relevant
  empty states and readable evaluator names replace fixture/developer annotations.
  Proposal, synopsis, guide, evaluation and published results are separate facts.

## Authority matrix

| Responsibility | Authorized actions | Exclusions |
|---|---|---|
| Student | Eligible offerings, current team membership, proposals/descriptions/private PDF versions, feedback, personal published totals/history | No offering/policy configuration, staff assignment or unrelated academic records |
| Admin | Record and implement HOD-approved external instructions: cycles, curriculum types, project/team policy, review plans, existing-account eligibility/faculty access, offering windows/requirements | Cannot self-appoint HOD/coordinator, make synopsis decisions, enter/publish/correct marks or access academic PDFs |
| HOD | Active explicit departmental mandate: governance, coordinator appointment/revocation, scoped assignment/oversight/publication; rubric approval still requires the existing scheme authority | HOD is not automatically Admin or an evaluator; selected responsibility remains enforced |
| Coordinator | Active appointment and source-HOD chain; established review/oversight operations; explicitly delegated guide allocation/scheduling and routine faculty permissions | No independent policy authority, self-delegation or another evaluator's marks |
| Faculty/guide | Active department faculty role and actual project assignment: authorized document reading | Guide or evaluator assignment alone does not authorize a synopsis decision |
| Synopsis reviewer | Explicit current REVIEWER assignment and applicable requirement configuration: feedback/revision/approval | No unrelated documents or evaluator powers |
| Evaluator | Authorized review assignment: own marks/finalization/direct published correction | Original active evaluator only; no coordinator approval; all earlier results retained |
| TECH_ADMIN alone | Technical operations | No independent academic authority |

The same eligible faculty member may be separately assigned guide and evaluator.
Faculty eligibility is an effective departmental FACULTY role plus the authorized
assignment; display names and student-role membership confer no eligibility.

External instructions are an institutional trust boundary: the authorized Admin
records instructions actually received. SMART-PRO validates the active Admin and
HOD scope and preserves provenance; it cannot independently authenticate an
out-of-application conversation. The UI requires acknowledgement of approved
instructions, not a written justification or a new approval ticket. External
`approved_at` values record entry time, not an independently verified meeting date.

## Forward SQL and API contracts

Apply only in reviewed isolated test environments, in order after 024:

| Candidate | Change |
|---|---|
| 025_optional_notes.sql | Optional notes across existing commands/constraints; preserves old no-note receipt payloads and grants/history |
| 026_external_instructions.sql | External instruction provenance; scoped atomic Admin RECORD operation; read options/history |
| 027_proposal_details.sql | Private immutable project description, audited creation and retry conflict protection; fresh unprofiled-student department discovery |
| 028_document_responsibilities.sql | Separate assigned-faculty reading from explicit synopsis-review decisions |

`POST /api/v1/staff/departments/{departmentId}/setup` adds `action: RECORD` with
`kind`, existing exact `configuration`, optional `reason`, and:

```json
{"authority":{"hodMandateId":"<current department mandate UUID>",
 "source":"EXTERNAL_INSTRUCTION","confirmed":true,"reference":""}}
```

Supported kinds: CYCLE, TYPE, PROJECT_POLICY, TEAM_POLICY, REVIEW_BLUEPRINT,
STUDENT_PROFILE, FACULTY_ACCESS, DOCUMENT_NOT_REQUIRED, OFFERING. OFFERING uses the
existing 13-field configuration contract; `adminRoleId` must match the authenticated
Admin. No actor is accepted from the client. Role context, enabled department/API
controls, HOD scope, rubric mandate and target eligibility are checked. Existing
REQUEST/APPROVE/APPLY and AUTHORIZE/CONFIGURE routes remain compatible.

`GET .../setup` includes `instructionSources`; setup/instruction history exposes
`approval_source`, `recorded_by`, and optional `instruction_reference`.
`POST /api/v1/projects` additionally accepts `description` (up to 10,000 characters).
The current UI requires it; old three-field clients remain compatible. The existing
scoped document workspace returns it. No update/delete API is provided for this
initial evidence. Existing synopsis storage/version/review APIs are reused.
All commands continue requiring private idempotency keys and relevant revisions.
Optional notes are strings up to 500 characters; unknown/malformed fields fail.

## Actual verification

Counts below are separate suites, not a claim of unique combined test cases:

- **281 backend tests passed**, 0 failures/skips. Real PostgreSQL, disposable fixture
  database; `.test-data/definitive-backend.log` and `documents-backend-final.xml`.
- **40 PostgreSQL/document/configuration contracts passed**, 0 failures/skips;
  `.test-data/definitive-contracts-final.log`. Covers external provenance, missing
  authority/disabled gates/wrong roles, no-note appointment/revocation/correction,
  historical receipt replay, concurrent proposal and file retries, failed storage,
  rollback/recovery, immutable descriptions, guide/read versus reviewer/decision,
  expired/foreign faculty, preserved submissions/results and candidate prerequisites.
- **8 existing application/authentication compatibility tests passed**, 0 failures/
  skips; `.test-data/definitive-compatibility.log` (overlaps behavior above).
- Native-JS workflow assertions and every frontend JS syntax check passed; Ruff
  F/E9 and Django system checks passed; no remote CI was contacted.

Browser acceptance used `smartpro_test_demo_acceptance_696b2fe6c3ee`, created with
no academic configuration/data. Admin authored cycle/type/project/team/review-plan
and eligibility from explicit test instructions, then configured the first offering.
HOD appointed → revoked → reappointed Dev Menon without notes; old appointment
remained. Student Arjun Mehta created a team and submitted title, description and
actual synopsis PDF. Separately assigned guide/reviewer Anika Rao opened the file,
requested revision, then approved version 2. Student and coordinator saw the same
files and feedback history. HOD assigned/published evaluation; the original faculty
corrected **86.00 → 88.00** with a blank note and no coordinator approval. Student
saw both results. The isolated database retains two document versions, two result
versions and two coordinator-appointment records. Test values are not institutional
policy defaults or real academic decisions.

Desktop and 390px mobile layouts were inspected, including empty Admin setup,
search/no-match behavior, actual private PDF preview, separate project statuses,
expandable configuration tasks and both student result versions. No horizontal
overflow. Evidence: `.test-data/definitive-student-desktop.jpg`,
`definitive-admin-desktop.jpg`, `definitive-faculty-pdf.jpg`,
`definitive-student-mobile.jpg`, `definitive-results-mobile.jpg`.

## Local launch and fixture isolation

From the repository with the existing virtualenv and local PostgreSQL/PDF tools:

```powershell
# Normal application: use an explicitly provisioned DATABASE_URL.
# Does not seed, migrate or enable test identity. Institutional sign-in stays blocked.
.venv\Scripts\python.exe scripts/application.py serve --port 8000

# Separate browser acceptance: schema-only copy; no academic fixtures are seeded.
.venv\Scripts\python.exe scripts/application.py test-workspace --port 8001

# Resume the explicitly isolated workspace without seeding or running candidates:
.venv\Scripts\python.exe scripts/application.py serve --port 8001 --test-manifest .test-data/smartpro_test_demo_acceptance_696b2fe6c3ee.json
```

The test command prints its unique database manifest. It needs existing local
`.test-data/pg-memberships.env.json`, PostgreSQL binaries under
`.test-data/postgres/pgsql/bin`, and private storage in its unique `.test-data`
subdirectory. Credentials are not printed or committed. Test authentication requires
explicit switches plus a loopback `smartpro_test*` database. Normal startup provides
no fake login choices. Tests alone may execute candidates 010–015 in disposable
regression fixtures under the user's existing exception.

Existing fixture-origin databases `smartpro_test_demo_department` and
`smartpro_test_academic_audit`, their old synthetic users/policies/results and private
files remain preserved. They are archived test evidence, not operating department
records. No deletions were performed; any later removal requires separate approval.
The new launcher does not connect normal operating startup to either database.

## Remaining limitations / activation blockers

- Verified institutional identity, account provisioning/bootstrap and deployment
  controls are still undecided/disabled. No real-user access is activated.
- Current eligibility contracts are department, semester and academic cycle. A
  separate program/cohort model and its mapping/eligibility rules are not approved
  or implemented; no invented defaults are applied.
- The complete retrospective-roster/routine-delegation administration interface,
  additional academic document types and comprehensive large-department paging
  remain outside this verified synopsis/evaluation journey.
- Production storage scanning/isolation, security/load tests, backup/restore/crash
  recovery, monitoring and legacy direct-write hardening remain deployment gates.
- Historical migration/candidate files 001–024 are preserved. New candidates were
  exercised only in isolated test databases; no operating/production upgrade ran.

The core corrected academic journey is verified. This is not a declaration that
all institutional MVP requirements or production readiness are complete.


## Lifecycle continuation — candidates 029–035

This forward-only increment continues checkpoint `464c16f`. Candidates are owner-run
isolated-test SQL, not Django auto-migrations or normal-startup actions. Apply after
028 in numeric order. 001–009 and earlier candidate sources remain unchanged.

| Candidate | Behavior |
|---|---|
| 029_offering_lifecycle | Audited revision-checked settings, pause/archive/restore; used scope stays frozen |
| 030_configuration_lifecycle | Cycle dates/code/history; reject dates excluding existing evidence |
| 031_assignment_lifecycle | Prospective guide/reviewer ending; coordinator operation revocation/history |
| 032_configurable_documents | Versioned named requirements, keyed reviewers, feedback-only decisions and existing private PDF versions |
| 033_explicit_submission_requirements | Explicit synopsis requirement; absent/optional requirements do not impose synopsis registration windows |
| 034_project_draft_revisions | Current eligible student proposal revisions before submission/evaluation; immutable before/after history |
| 035_evaluator_lifecycle | Audited unfinished evaluator reassignment, retained withdrawn drafts, safe finalization/publication |

New or extended contracts (all authenticated, department/project scoped):

- `GET/POST /api/v1/staff/departments/{id}/offering-management`: EDIT or AVAILABILITY,
  expectedRevision and recorded HOD instruction provenance.
- `GET/POST .../configuration-management`: cycle revision, date safety, history.
- `GET/POST .../assignment-management`: END_ASSIGNMENT or REVOKE_OPERATION;
  routine faculty delegation/revocation reuses the existing academic endpoints.
- `GET/POST .../document-requirements`: offeringId, optional requirementKey and
  expectedPolicyId, name, opensAt/closesAt, maxBytes, required, allowRevisions,
  allowChanges, allowApproval, reviewerIds and authority provenance.
- Existing document upload/command routes accept requirementKey. Workspace returns
  requirements with pinned cases/history; COMMENT records feedback without ending
  the awaiting-review state. Private content/preview/download routes are unchanged.
- `POST /api/v1/projects/{id}/proposal-details`: expectedRevision, title, description;
  append history and close editing after the first submitted academic evidence.
- `GET/POST /api/v1/academic/departments/{id}/reviews/{reviewId}/management`:
  expectedReviewRevision/facultyIds, assignment and roster history. Existing roster
  correction and new-review-round endpoints are reused; finalized work is retained.
- Offering configuration adds explicit requiresSynopsis. Old clients' explicit
  synopsis contract remains compatible; the current form starts unchecked.

Synthetic browser acceptance used a separate clone and private storage, leaving
original projects, document versions and result versions intact. Generic document
review remains restricted to configured active departmental faculty. HOD/coordinator
oversight does not independently confer formal document approval authority.

Launch normal local data with `scripts/application.py serve`; this does not install
candidates or seed records. For isolated browser data use `--test-manifest` with an
existing explicit acceptance manifest. Never use the archived seeding launcher for
normal startup. Additional document names/review responsibilities remain departmental
configuration; no hardcoded extra requirement is introduced.


## Guide allocation and automatic synopsis responsibility — 036

`036_guide_synopsis_responsibility.sql` follows 035. It does not backfill historical
authority. An authorized GUIDE command creates an explicit keyed reviewer row and
an immutable guide/reviewer link plus actor/time audit. Save an existing guide
through the same authorized command to establish the responsibility prospectively.
No new endpoint or duplicated academic model is introduced.

Reassignment/end closes linked reviewer intervals atomically with the guide change.
Manual additional reviewer grants remain separate, including grants to the same
faculty. The assignment-management response exposes source_guide_id; the UI names
linked responsibilities and requires ending/reassigning the guide to end them.
Synopsis policy approval/changes flags remain binding. Guide status alone, legacy
owner-created guide rows, and guide/evaluator status on other document keys never
supply implicit decision authority. Candidate installation preserves all existing
projects, document versions, decisions, results and faculty assignments.

Local verification: 53 document/lifecycle/guide contracts and 8 compatibility tests
passed; native frontend assertions/syntax, Ruff and Django checks passed. Browser
accepted a new Community synopsis from the student, allocated its primary guide as
HOD, opened the private actual PDF as that guide and approved under the configured
synopsis rule without the additional-reviewer form. Existing case/decision history
remained visible. This synthetic workflow did not activate production access.
