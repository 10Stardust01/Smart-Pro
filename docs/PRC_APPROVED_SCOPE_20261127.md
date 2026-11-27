# SMART-PRO approved PRC increment — 27 November 2026

Branch: `feature/approved-prc-foundation-20261127`, based on `main` at
`0cf98f9926ce73b903ac6986d0c9025323965362`. Local development only. This is a
candidate foundation, not an activated or complete committee workflow.

## Sources and precedence

| Source | Recovered evidence | Treatment |
|---|---|---|
| November 5 development | `Inspect SMART-PRO repository` history and `APPLICATION_CORRECTIONS.md`: real departmental application, distinct five-role workspaces, offering-based student proposals, private PDFs, version history, explicit assignments | Preserve the established platform; PRC extends the academic lifecycle |
| November 12 faculty discussion | `Analyze SmartPro Files`, approval turn `495101f0-15e7-4b84-9ca9-9e89f3f3fc13`: user accepted PRC before Guide allocation and fresh synopsis after rejection; modification permits revision | Finalized user clarifications override the earlier diagram's ordering |
| Faculty requirements summarized in current README | PRC, presentation panels, final-report review, HOD final marks and closure | Reported faculty direction; the original diagram/development document was not returned by chat retrieval |
| November 14 discussion | No distinct SmartPro discussion for this date was located in available ChatGPT/Codex history; archived ChatGPT listing was empty | Do not reconstruct missing policy from assistant recollection |
| Current explicit user clarification | Coordinator manages PRC activities in their assigned offering; this grants neither member appointment nor authority to independently make/record a collective decision | Binding approved boundary for this increment |

Recovered assistant summaries are evidence of earlier work, not independent
institutional ratification. No COE integration, quorum, voting threshold,
mandatory notes, new HOD restrictions, or automatic appointments are introduced.

## Repository reconciliation before implementation

Inspected `main`, `deployment/reviewer-staging`, existing PRs, local source and
`feature/faculty-prc-workflow-20261127` at `10667509f029991a44573b3437b06278c6fec4ce`.
The existing faculty branch is 12 commits ahead of main. Reviewer staging is a
separate divergent line at `6b1ff0869de40881d213530516565f147e1ee55a`
(main has 131 unique commits; staging has 14). These are source refs, not claims
that a particular commit is currently running on Render.

| Requirement | Main / existing draft | This branch |
|---|---|---|
| Admin/HOD leadership, departmental records, offering configuration, Coordinator responsibilities | Existing implemented platform | Preserved |
| Student proposals, private PDFs, review attempts, Faculty evaluation, published/corrected results | Existing implemented platform | Reused, with regression coverage |
| PRC approval before Guide allocation | Missing on main; drafted on faculty branch | Candidate database guard on Guide insertion and assignment changes; latest synopsis approval must have separate PRC evidence |
| Rejection versus modification and complete history | Draft distinguishes labels but routes both through ordinary changes | Distinct immutable outcomes, fresh attempt/version after rejection, ordinary revision after modification; older unused PDFs also denied after rejection |
| Coordinator PRC management | Draft has activation/member controls | Offering-scoped read-only PRC progress, pagination, project evidence and history; no appointment or committee-decision controls |
| Student/assigned Faculty/HOD PRC visibility | Partial draft APIs/UI | Project-scoped reads reuse existing access checks; Admin/technical role alone has no academic access |
| PRC appointments and collective outcome recording | Draft assumes Coordinator appointments and any assigned member recording an outcome | Deliberately excluded until explicit authority is finalized |
| Presentation panels, report-reviewer workflow, HOD final-marks/closure gates | Missing or partial foundations | Remain gaps; missing source must be reconciled before new permissions or policy are implemented |

The older draft is not used as this branch's base. Its `066` and this branch's
`066` are alternative uninstalled candidates: do not apply both. It also lacks
PRC SQL/API regressions, truncates its queue at 200, and has no explicit PRC
write permission mapping in `ActiveRolePermission`. Its command validates a
request key without persisting/replaying a command receipt. Its mutation endpoints
are therefore not an accepted end-to-end workflow.

## Implemented boundaries

Candidate `066_prc_entry_gate.sql` creates empty gate/evidence tables and grants
the runtime only two scoped read functions. It grants no runtime table writes,
activation command, member appointment, or committee-outcome recording command.
Owner inserts in tests are synthetic fixture construction, not an application
workflow or an approved institutional power.

An explicitly gated offering denies Guide allocation until the latest synopsis
attempt is both approved by the existing document system and separately recorded
as PRC-approved. Generic Faculty approval alone does not satisfy PRC. Rejection
requires an unused, newer synopsis PDF version and a new submission attempt;
it does not delete the project, replace the team, prescribe a new topic, or
algorithmically judge whether the content is different. Modification uses the
existing revision/resubmission service. Old PDFs, attempts and outcomes remain.

Existing Guides predating a future gate activation remain historical evidence;
installing the candidate neither activates offerings nor changes assignments.
This is compatibility handling, not a newly ratified academic exemption policy.
The eventual activation workflow needs explicit authorization and legacy preflight.

Read APIs:

- `GET /api/v1/prc/offerings/{offeringId}?page=1`: current assigned Coordinator;
  25 projects per page with total count and subsequent pages.
- `GET /api/v1/prc/projects/{projectId}`: current Student, assigned Faculty,
  authorized HOD, or assigned offering Coordinator, using existing scope checks.
- Both use trusted identity, selected responsibility, private no-store responses
  and existing service gates. POST is denied. No new academic authority is granted.

The Coordinator's Course Management screen adds PRC activities. Project evidence
shows the current PRC state and earlier decisions; pending resubmissions do not
mislabel an earlier rejection as the current outcome. Existing forms and all five
workspaces remain available under their established permissions.

## Verification

See the verification addendum below for actual local results. New PRC coverage
includes ordering, rejection/modification, immutable history/private PDF retrieval,
generic approval denial, assignment bypasses, role/department/offering isolation,
runtime table denial, pagination beyond 25 and historical Guide preservation.

`prc-contracts.yml` is manual-only and uses an ephemeral PostgreSQL 16 service.
On a fresh explicit loopback `smartpro_test` setup, run
`python scripts/ci_course_direct_correction.py --prc`. It refuses to overwrite an
existing synthetic template. There are no hosted traffic, deployment or paid
service steps. Existing `frontend/workflow.test.mjs` had a stale `Faculty Reference`
label expectation; it now matches the existing `Faculty directory` UI.

## Remaining decisions and release conditions

1. Who appoints, replaces and ends PRC membership, and what effective scope applies?
2. Who records a collective outcome and what evidence represents that decision?
   Coordinator management alone and ordinary Faculty reading do not answer this.
3. Who authorizes entry-gate activation, with what legacy-project preflight?
4. Recover the original faculty development document/November 14 discussion before
   implementing panel-specific powers, final-report approval or HOD closure gates.

These are the unresolved portions. Previously finalized departmental authority,
correction rules, guide/evaluator overlap and ordinary workflows are not reopened.
No invented quorum or institutional defaults fill these gaps.

No merge, push, reviewer-branch change, live migration, deployment, hosted test,
live academic record change, paid service, free-trial credit or TinyFish use was
performed for this increment. Gate activation and committee writing remain absent,
so do not install this candidate expecting a usable end-to-end PRC decision flow.
Future deployment requires a separate approved promotion, preflight and recovery
rehearsal. Reverting application changes must preserve any recorded evidence;
do not use destructive down migrations to erase PRC history.

## Actual local verification addendum

- **292 backend cases verified:** 287 passed in the full `pytest backend/tests`
  run. Five existing recovery/preflight cases required a `smartpro_test_…` database
  name and PostgreSQL client binaries; all five passed after correcting that local
  test configuration. These are 292 distinct cases, not a claim of one pristine run.
- **50 course/PRC cases verified across disposable per-case databases:** the full
  initial 48-case run passed 44. Its two technical-role denial failures and two
  missing-browser/runtime failures were corrected and rerun successfully. Eight
  final PRC SQL/API contracts passed; the additional older-unused-PDF rejection and
  PRC browser cases bring the unique course-suite total to 50. Earlier failures
  remain in ignored local logs; they are not omitted from this record.
- **8 frontend test entries passed:** seven PRC presentation/Guide-gate tests and
  the existing workflow suite. Changed ES modules passed syntax checks; changed
  Python passed Ruff F/E9 and the diff passed whitespace checks.
- **Actual local browser verification passed:** PRC offering navigation, scoped
  progress, rejection/history, selected evidence, reload, 390px reflow and no Guide
  allocation form before approval; the existing Guide/Coordinator/Student direct
  correction and HTTPS reviewer stage-evidence journeys also passed.

The browser check caught missing `prc.js` asset registration, now fixed. The
existing HTTPS test helper stalled module downloads by doing TLS handshakes on
the accept loop. Handshakes now run per worker and Windows cleanup ends its own
process tree. These are local test-helper changes, not reviewer deployment edits.
An existing synthetic-identity denial surfaced as HTTP 503; it now maps SQL
permission denial to HTTP 403 without granting any academic responsibility. The
two previously failing role-isolation tests pass. No institutional identity
provider or reviewer sign-in policy was replaced.

All databases used here were on a newly initialized, loopback-only PostgreSQL 16
instance under this workspace. Existing local development databases, Neon,
reviewer staging and private hosted documents were not modified. No GitHub CI
run, hosted acceptance or production readiness is claimed from these local checks.
