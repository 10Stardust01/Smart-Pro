## 10 November 2026 — forward-only 061–063 Neon Free validation completed

The existing Neon validation branch now contains candidates 059–063. Only
061, 062 and 063 were added, in separate atomic transactions; Neon main and
Render remained unchanged at 059/060. Published overall/stage versions, audit
rows and READY file metadata were unchanged, and scoped Coordinator/Admin reads
succeeded. Function ownership, fixed search paths and grants were inspected.
This does **not** prove recoverability of the three underlying private PDFs.
[Detailed evidence and remaining hosted release gates](NEON_061_063_VALIDATION_20261110.md).

## Candidate 063: non-HOD Faculty role and departmental details (10 Nov 2026)

Candidate 063 (PR #7) introduces only Department Admin authority over other
non-HOD Faculty records, with departmental display name/designation/contact
email metadata independent of global account identity, an audited Faculty term
amend/end/reinstate action, stale-revision conflicts and retry-safe receipts.
This does **not** alter historic project evaluations, published result versions,
student records, global logins or HOD/independent authority. An appointment with
active project/Coordinator responsibilities is not ended until existing
assignment workflows resolve those responsibilities; reinstatement does not
silently restore them. Isolated SQL/API validation is not hosted acceptance.
Neon main/validation currently have 059/060, not 061–063. **PR #7 is merged**
into main at `57881021` after six passing CI checks. No deployment, migration
or institutional activation was authorized.

## Correction pagination candidate 062 (10 November 2026)

The new 062 source adds two role-scoped read functions: one selected Guide
project and one offering's exceptional correction request pages, 25 per page.
An anchor timestamp keeps newly submitted requests from shifting existing
pages. Existing Guide project-work listing was already paginated, so the
correction form no longer depends on the legacy 100-project correction list.
The old 061 API shape remains for compatibility but the new UI uses 062.
Isolated PostgreSQL contracts exercised 126 correction requests, 126 additional
Guide projects, role restrictions, and original release preservation.
[PR #6](https://github.com/10Stardust01/Smart-Pro/pull/6) contains the tested
code; this has **not** been installed in Neon or deployed to Render. The
existing staged database has 059/060, and must receive 061 before 062 through
a controlled forward-only migration with paired database/PDF recovery checks.

# Source consolidation and hosted state (10 November 2026)

[Consolidated development checkpoint](CONSOLIDATED_DEVELOPMENT_CHECKPOINT.md)
is the current summary of the reviewed 059–061 source, accepted product decisions,
Milestones A–E and remaining gaps. Render Free reviewer staging is live at
`319e3ebc`. Connected Neon main and validation have **059 and 060**, but **not 061**.
Historical deployment SHAs and old 'not deployed' claims below remain dated
provenance, **not current hosted-state assertions**. No hosted migration or academic
record mutation is implied by source consolidation.

## 10 November 2026 — non-destructive correction CI audit

The preserved review branch `review/live-staging-audit-20261109` at
`de623bc2` completed both real Django/PostgreSQL browser corrections:
the direct-overall-mark flow and the signed HTTPS reviewer
Guide → Coordinator → Student stage-evidence re-release flow. The
PostgreSQL, Django compatibility, curriculum and student API workflows
also passed. The direct-correction GitHub Actions job nevertheless finished
red because its **last, separately scoped read-only hosted smoke** failed
while comparing an HTTP 302 redirect: converting Python's case-insensitive
`HTTPMessage` to a regular dictionary made `headers.get('Location')`
return `None` when the header used different capitalization.

The isolated fix is on `fix/hosted-smoke-register-20261110`: keep the
original `HTTPMessage` for case-insensitive header access and add a
no-network regression in `scripts/test_hosted_public_smoke.py`.
The regression test has been added but has not yet been independently
executed in GitHub CI. Do not infer that the rest of the live hosted smoke
passed: its later CSRF, anonymous-authority and frontend-asset checks
were not reached in the failed run.

**No academic SQL/migration code, correction policies, actor assignments,
staging database rows, hosted deployment or PDF artifacts were changed by
this audit.** The review branch remains ahead of the deployment branch.
Candidates 060 then 061 must be preflighted in the existing Neon validation
environment, and explicitly authorized separately before live migration
or deployment. Preserve 059, original releases, recovery branches and the
current Render staging service.

## 9 November 2026 — safe live schema alignment

The current Neon staging branch has the already-applied direct correction
candidate 059; the reviewed stage-evidence expansion needs forward migration
060. Existing before-059 recovery and 059 validation branches are retained.
Candidate 060 replaces only `smartpro_course_final_revision` with the
reviewed dual-mode function. Do not reapply 059 or overwrite published data.
Render Free is configured for `deployment/reviewer-staging`, auto deploy off.
Any live promotion must use a fast-forward branch update and explicit Render
deploy; database checks and live smoke tests must be recorded separately.

# SMART-PRO implementation status

## 9 November 2026 — correction workflow branch verified, not deployed

The reviewer staging deployment currently **live on Render Free** is `c20e15b`
(verified by Render's deploy list), matching GitHub
`deployment/reviewer-staging`. Auto-deploy remains off.
No change from this review work was deployed.

On the isolated review branch at `c0564cc`, the assigned Guide can either
propose a corrected published overall mark or request an overall re-release
from **already corrected, complete stage evidence**. A current offering
Coordinator approves/rejects even when Guide, requester, or evaluator;
no extra HOD/independent authorization is introduced. The initial release
and all original review evidence remain available. [Correction CI](https://github.com/10Stardust01/Smart-Pro/actions/runs/42561282815)
passed disposable PostgreSQL 16, direct and stage-evidence contracts,
backend syntax and the real Django/Chromium Guide→Coordinator→Student
journey. The stage-evidence form itself has not had a separate browser click
test. This does not constitute hosted or institutional acceptance.

The requirements register separates code-verified results from remaining
institutional decisions, hosting recovery, account-access work and accessibility.


## 9 November 2026 — hosted snapshot and product-policy reconciliation

Render Free already hosts the reviewer service from `deployment/reviewer-staging`
(commit `0d5281e`); Neon reports a `free_v3` PostgreSQL 16 project with a
populated staging database. This corrects older local-only/deployment-pending
statements below; it is **not** production or institutional sign-off.
Draft PR #1 prepares the finalized **direct Guide-to-Coordinator overall-result
correction**, without reopening or recalculating any review stage. Candidate
059, the role-specific forms and regression tests are **not deployed**.
The [isolated PostgreSQL 16 / real-Django Chromium CI](https://github.com/10Stardust01/Smart-Pro/actions/runs/42549200764)
passed Guide submission, same-person Coordinator approval, Student access to
both overall result versions, and non-mutation of recorded review-stage marks.
The browser exercised actual frontend, backend, and a disposable database,
not the hosted Render instance. Approval is a single atomic decision that
appends a new result version, preserving its predecessor and audit. See [requirements register](REQUIREMENTS_COMPLETION_REGISTER.md).

Original results and the current live deployment have not been modified.


Updated 8 November 2026 (Asia/Kolkata). Authoritative current status; historical
reports/evidence retain their original meaning. No main merge or deployment.

## Local-only continuation

### Capacity baseline

See [measured capacity and reproduction steps](CAPACITY_BASELINE.md) for the
disposable 100- and 500-project runs. Candidate 058 fixes the observed
stage assignment/publication lock inversion and was aligned with
`smartpro_dev` after a verified restore rehearsal. The hardening follow-up
compares bounded Django connection reuse and verifies retry after a lost receipt.

### Local navigation performance

Measured in Chrome at 390 px against `smartpro_dev` on port 8021 using
existing synthetic records. Each pair is the first and second pass in a
fresh browser session; the first Student sign-in includes session discovery.
Times are click to usable content (milliseconds), with API request counts:

| Journey | Before | After | Requests before → after |
| --- | ---: | ---: | --- |
| Student sign-in | 1432 / 879 | 1066 / 570 | 8 / 7 → 7 / 6 |
| Faculty sign-in | 481 / 467 | 465 / 483 | 2 → 2 |
| Coordinator sign-in | 1063 / 1067 | 784 / 999 | 4 → 4 |
| Coordinator offering | 1041 / 1057 | 953 / 813 | 4 → 4 |
| Admin operations | 1602 / 1671 | 551 / 559 | 9 → 6 |
| HOD governance | 2431 / 2662 | 958 / 1068 | 8 → 6 |
| HOD candidate search | 2475 / 2668 | 180 / 251 | 8 → 1 |
| Clear candidate search | 2459 / 2426 | 254 / 240 | 8 → 1 |

Independent panels now load together after workspace authorization. Setup
and proposal data load on the views that use them, and appointment search
and paging refresh only the authorized candidate list. Chrome opened the
Coordinator evaluation queue in 1,096 ms and reached page two in 1,116 ms
after overlapping the scoped detail and queue requests. The development
candidate list fit on one page. No schema or academic data changes were needed.

The unused HOD assignment read took 990 ms in the first Chrome trace.
Separate Django request profiling measured 877–899 ms in the handler,
including 876–897 ms across three SQL executes. Setup took 131–171 ms
across 9–10 executes; PostgreSQL connection setup was 40–55 ms across
samples. Warm browser scripting, layout and style work were only a few
milliseconds on the slow governance paths. Seven alternating workspace
requests had median HTTP times of 220 ms on the normal server and 227 ms
on a temporary server without auto-reload or a second notification worker.
That sample does not indicate an auto-reload penalty. The assignment read
still runs on Setup, and the Coordinator path still needs fresh workspace
and offering scope checks.

### Milestone E frontend

The [frontend design rules](FRONTEND_DESIGN.md) define the shared palette,
type, navigation, surfaces and controls. Student and Faculty overviews
surface the next relevant entry point. Coordinator queues keep dense,
scrollable tables and textual publication status. Admin imports show
file selection, column mapping and review. HOD governance separates
oversight actions, offerings that need attention and appointment history.

Chrome exercised all five roles on synthetic development records at
1440, 820 and 390 pixels. The checked screens fit the viewport. The checks
covered keyboard focus, a scrollable evaluation table, Student result reload,
Coordinator queue Back and Forward, Admin record history and offering edit
controls, and HOD appointment history. A synthetic CSV preview exercised all
three Admin import steps. The 105-project fixture rendered 25 queue entries
on its first page. Chrome measured 383 ms for that loopback queue request. The overview renders at most three project
cards with access to the full listing. The frontend workflow suite passed.

Final E acceptance used a disposable synthetic PostgreSQL workspace. Chrome
verified persisted offering edits, CSV import and its receipt, a second
synopsis attempt with the first retained, rubric draft and finalization,
stage and overall publication, and HOD replacement of the Admin. The Student
saw the released total of 40.00 and ordinary revision upload was closed.
The existing PostgreSQL contract also confirmed ordinary corrections close
after overall publication.

The browser checks covered keyboard confirmation, Escape and restored focus,
labeled controls, the 390 px layout, and a backend CSV row error that
prevented apply. Sampled text contrast was at least 6.15:1 and the input
boundary was 3.54:1 against white. These were focused accessibility checks.
Six existing PostgreSQL contracts and the frontend workflow suite passed.
The acceptance change updates evidence documentation.

### Milestone D.1 departmental records

The [requirements completion register](REQUIREMENTS_COMPLETION_REGISTER.md)
tracks verification and outstanding work across milestones. Candidate 051 was
rehearsed on `smartpro_test_dev_restore_ee397a8e` and then installed only on
the confirmed loopback `smartpro_dev` database. All 100 public table row
fingerprints and the stored PDF matched the backup. The pre-existing database
routines and constraints were preserved.

Candidates 052–056 add scoped directory search, bounded multipart CSV and
single-sheet XLSX imports, import outcomes and audited reconciliation, and
paged offerings, Coordinator versions and department leadership history.
Operational faculty links require an explicitly verified account. A matching
display name is a review hint. The BIT CSE public reference remains separate.

Chrome verified the student directory and reload, CSV creation, XLSX update and
unchanged retry, duplicate row reporting, a possible faculty match and an
explicit verified link, the BIT CSE reference, and HOD Admin
replacement and succession, offering page 9 of 205, and Coordinator version 1
on page 2 of 26. Loopback HTTP median for page 9 was 164.26 ms across ten
requests. A 3,500-row XLSX preview took 818 ms and apply took 511 ms. These are
synthetic single-machine measurements. In the same 205-offering fixture,
three Coordinator catalog reads per variant had medians of 4,777.72 ms
before the prefilter and 270.14 ms after it. The returned offering was the same.

The final course and authority run passed 28 tests, the document run passed
57, and the frontend workflow suite passed. The course suite covers competing
Admin replacement, concurrent Coordinator removal, exact import retries,
overlapping import previews and refusal to link a second faculty reference to
the same account. Admin and HOD read-only smoke checks passed on the aligned
development database.

D.1 closes with candidate 057. Admin record detail uses an opaque operational
UUID and retains search and page across Back, Forward and reload. It shows
linked import provenance, configured profile or access changes, and audited
reconciliation. Scoped candidate search covers Admin/HOD appointment pickers.
Chrome selected faculty candidate 304 on page 9 of 205.

Candidate 057 records proposals, verified associations, rejections and
revocations for the locally enabled faculty reference. It uses the directory
profile reference, existing operational account UUID, and a separately supplied
institutional source and identifier. The current verification evidence is
synthetic. Sign-in and appointment authority use the existing identity and
authorization services. Real BIT mappings and the approved production resolver
remain institutional dependencies.

The owner rehearsed 052–056 on `smartpro_test_dev_restore_ba566dcd`, then 057 on
`smartpro_test_dev_restore_16fc198e`. Both sequences were installed on the
confirmed `smartpro_dev` target. All 100 existing table row fingerprints and
the stored PDF matched, and the new crosswalk table started empty.

### Milestone D departmental workspaces

Department Operations connects offering settings, Coordinator appointments,
and records intake. Department Governance surfaces effective Admin terms,
succession and offering oversight. The same command services enforce academic
authority and append history. The Admin offering view surfaces missing
Coordinator coverage and preserves the specific last-Coordinator conflict.

Candidate 051 adds department-scoped intake search and batch history with
25-row pages, exact counts and import attribution. The staff intake endpoint
supports GET with `kind`, `page` and `batchPage`. Search uses read-only
POST `LIST` so names and references stay out of request URLs. Setup accepts
`intake=metadata` to avoid carrying the legacy records and batches. CSV import
and reconciliation keep the existing authorization and transaction contract.
The import receipt identifies the batch but does not break out created and
updated rows. Other legacy setup and course listings keep their existing limits.

Chrome exercised CSV preview, mapping, application and history, offering
creation and activation, Coordinator appointment and rejected final removal,
Admin replacement and revocation, and voluntary HOD resignation and successor
appointment. Back, Forward and reload preserved the selected offering. The HOD
offering overview fit at 390 px and showed visible keyboard focus.

The PostgreSQL regression runs passed 25 course and authority tests and 57
document tests. The frontend workflow suite passed. A same-key concurrent
HTTP import returned two successful responses for one batch and one record.
With 5,000 synthetic records, ten direct PostgreSQL reads per case had medians
of 8.38 ms for the first 25-row page and 5.89 ms for an exact-reference search.
The performance rows were rolled back. These timings exclude HTTP overhead.

### Main development database alignment

`smartpro_dev` is the persistent loopback development workspace, provisioned
from the reviewed schema without archive data. Candidates 048–057 are
installed. The local launcher selects it explicitly with
`scripts/application.py serve-development`. See
[deployment and recovery](DEPLOYMENT_AND_RECOVERY.md).

A private dump and file snapshot restored into
`smartpro_test_dev_restore_c1a42d08`. All 100 public tables matched by
count and row digest. The restored schema matched 578 constraints and
368 routines, and the saved PDF matched its recorded SHA-256 digest.
The verified snapshot contained one complete synthetic submission and
evaluation lifecycle and 105 synthetic projects for pagination coverage.

### Milestone C.1

The in-app document consumers use paginated offering or department project
discovery, selected-project evidence, or configuration-only reads for Admin.
The original endpoint response remains available to older integrations.
Candidate 050 supplies the bounded document path. No new SQL candidate is
required for this closeout.

On the same scaled disposable database, the legacy Coordinator read took
7,594 ms and serialized 56.3 kB for 50 projects. Five reads of the offering
listing and selected evidence had medians of 15 ms and 47 ms respectively.
The listing returned 25 projects with an exact count and serialized 5.4 kB.
Selected evidence returned one project with its authorized history.

The loopback test database and archived demo are separate from a provisioned
development target. No normal `DATABASE_URL` selected a target during this
work. The procedure for inspecting and aligning one, including backups of
both PostgreSQL and private files, is in
[deployment and recovery](DEPLOYMENT_AND_RECOVERY.md).

The local mixed load fixture completed two 48-request waves with 25 workers,
including simultaneous same-key PDF upload and submission retries. Median
latencies were 640 and 671 ms, with p95 of 1,969 and 1,953 ms. The final case
retained one version and one authorized approval. These waves exercised a
different workload from Milestone C's 50-worker read test.

### Milestone C

Student and Faculty **Project work** uses candidate 050 for searchable
25-project pages and loads complete evidence only for the selected project.
The selected work view, project, assessment, search and page travel in the
URL. Existing upload, submission, review and marking commands still authorize
every write. Candidate 050 follows 049 and is owner-run in existing workspaces.

On the same disposable 1,003-project database the legacy Coordinator document
projection took 8,093 ms and returned 50 projects. The new Coordinator listing
had a median of 31 ms across five direct PostgreSQL reads, returned 25 projects
with the full count, and serialized about 5.3 kB. Repeated project-level scope
checks in the old department read were identified in the PostgreSQL timeout
context. The new listing checks Coordinator access per offering and does not
serialize document histories on list requests. The legacy compatibility
response remains for older consumers and is outside these timing results.

Local mixed HTTP read waves used 25 and 50 workers and completed 50 and 100
requests respectively without errors. Median/p95 were 1,250/1,875 ms and
1,039/4,172 ms at 17.5 and 20.9 requests per second. The fixture reused
synthetic identities. This measures local development service behavior,
including requests for workspace, membership, listing and scoped evidence.
It does not establish production capacity.

Browser acceptance preserved two synopsis versions and both review attempts
through a change request and approval. INDIVIDUAL and COMBINED browser
marking and publication produced Student totals of 23.00 and 58.00.

### Milestone B stabilization

Candidate 049 follows 048 and gives the evaluation queue 25-project database
pages, offering-wide project/team search and status filters. The URL retains
the filters and page when opening or returning from an assessment. Project
evidence opens by project ID with a fresh offering authorization check.

Overall publication closes ordinary requests, authorizations and applications.
Where pinned policy permits exceptional changes, the original evaluator
proposes exceptional stage evidence against the current overall release.
The existing independent authorization and exceptional overall revision
procedure still apply. Earlier releases remain in history.

Local queue measurements on disposable PostgreSQL used five sequential HTTP
reads per size, at 50, 200, 500 and 1,000 unassigned synthetic projects.
Median response times were 277, 258, 310 and 298 ms. Each 25-project page
was about 25.6 kB. A targeted title search took 227–255 ms. Twelve reads
with four workers at 1,000 projects completed in at most 961 ms each.
This measured the queue endpoint with mostly unassigned work, before the
final selected-project evidence change. It does not measure production
capacity or a full offering with finalized marks for every stage.

The queue query counts matching projects and selects a page in PostgreSQL
before calculating stage summaries. Published stages use their retained
source count. Other legacy department-wide document views remain separate
from the scoped evidence path and need their own scale verification.

### Connected course evaluation workspace (Milestone B)

Coordinator Course Management now includes **Project evaluation**. Candidate
048 adds the scoped queue and publication preflight. The disposable browser
launcher installs it when creating a fresh acceptance workspace; ordinary
startup does not apply it. Older workspaces need an owner to apply candidate
048 after the existing course candidates before the queue is available.

The queue reuses the existing guide, stage, evaluation, correction and
publication commands. Evaluator writes carry the user's existing Faculty
responsibility and remain subject to server-side ownership checks. The
Coordinator workspace stays open during these actions. Readiness is a
snapshot; every publication command rechecks current evidence and authority.
The queue displays the first 100 projects per offering.

### BIT main-CSE Faculty Reference (7 November)

An opt-in, read-only reference is available in the isolated localhost workspace:
`scripts/application.py serve --test-manifest <path> --faculty-reference`.
Admin and HOD see the reference in their department overview; Coordinator sees it
only within an assigned offering. The API checks the selected role and current
department or offering authorization. Student and Faculty cannot access it.

The 2026-11-07 snapshot reconciles all 11 earlier records (CSV and Excel agree)
with 36 names from the supplied BIT audit. Nine records have individual IRINS
matches in that audit; the reported IRINS count of 39 remains unresolved. BIT
titles are displayed with conflicting or earlier evidence labeled. Missing
expertise stays unknown. The snapshot verifies neither current employment nor
identity, grants no permissions, and requires no schema or record changes.

### Finalized departmental authority (7 November)

Candidates 044–047 add versioned coordinator-owned corrections before overall
release, Admin-managed course appointments, HOD-led Admin replacement, voluntary
HOD succession and departmental CSV intake. The synthetic browser verified an
official student import, coordinator appointment, Admin replacement and HOD
succession. The production identity, exceptional succession and deployment gates
are recorded in the [readiness register](INSTITUTIONAL_READINESS.md).

### Readiness follow-up (7 November)

Candidate 043 closes public execution grants on six owner-privileged functions.
The isolated application verified faculty grant, expiry and project assignment
changes on the same client. Early termination and amendment of a departmental
faculty appointment still require an approved authority model. See the
[readiness register](INSTITUTIONAL_READINESS.md) and
[department checklist](DEPARTMENT_REVIEW_CHECKLIST.md).

### Institutional readiness (7 November)

HOD stage and overall history passed in the isolated browser. The new faculty
appointment regression checks assignment scope and loss of access on the same
client after the departmental role ends. A fresh schema installed through 042.
The logical restore matched 98 public tables and both stored PDFs. See the
[readiness register](INSTITUTIONAL_READINESS.md) for verification limits and
production activation gates.

### Functional and accessibility acceptance (7 November)

A fresh isolated browser workspace exercised coordinator appointments, offering
creation and activation, eligibility updates, project registration and PDF review
through single-stage and weighted publication. It also exercised an independently
authorized mark correction with both release versions visible. The acceptance
fixes restore offering editing, separate mark saving from finalization, manage
keyboard focus in dialogs, and repair authorized stage result reads. Sampled
desktop and phone-width keyboard checks covered all five roles.

### Role dashboard UX (7 November)

Course Management is the main entry point for coordinator submissions and results.
Admin can open offering creation and configuration history as needed. HOD oversight
links directly to Course Management. Faculty see saved finalized marks before
opening the correction form. Finalization and publication have explicit confirmation.
The five dashboards were checked in the isolated browser workspace at desktop and
phone widths. The 10 PostgreSQL course contracts and frontend workflow checks passed.

### Course coordination, assessment and reminders (7 November)

Owner-run candidates 037–042 add effective, offering-scoped coordinator appointments;
pinned course frameworks and plans; single-stage and weighted multi-stage assessment;
default primary-guide evaluation; exact authorized mark and overall-result corrections;
post-approval synopsis revisions; and versioned deadlines with in-app reminders.
New offerings start paused and need an effective coordinator before activation.
Course Management brings the existing document, guide and assessment services
together for each offering. Overall publication closes ordinary synopsis and
document changes while retaining previous files, decisions and marks.

Verified in isolated PostgreSQL: 10 course contracts, 53 lifecycle/document
contracts, 8 compatibility contracts and 281 existing backend tests. The isolated
browser journey exercised HOD and instructed Admin appointments, coordinator scope,
student registration and PDF revisions, guide approval and evaluation, staged
and overall release, and independently authorized corrections. The Results page
also passed a phone-width overflow check. The normal application database was
preserved. See [Course Management](COURSE_MANAGEMENT.md) for startup, verification
scope and remaining production work.

### Management lifecycle milestone (6 November)

Commit `ba07e03` extends checkpoint `464c16f` with forward candidates 030–035. Admin can
revise offering availability/settings, cycle dates and approved policy versions;
HOD/coordinator can end assignments, revoke delegated responsibilities, replace
unfinished evaluators and inspect frozen-roster history. Students can revise
initial proposal details before document submission/evaluation, with old versions
retained, and open authorized projects across offerings through Project history.

Community Project eligibility is fixed by an audited unused-offering correction
from semester `3` to the student's actual `SEM-3`, retaining the offering ID. Browser
selection and registration visibility are verified without a scope bypass.

Named document requirements reuse the private PDF/version/case infrastructure.
Admin records actual HOD instructions, including optional/required status, windows,
revision/review permissions and eligible reviewers. Changes append policy versions;
existing cases retain pinned rules and earlier feedback. Synopsis is explicitly
configurable, not automatically mandatory. No additional institutional document
name or approval chain is seeded. Evaluator withdrawal retains drafts; finalized
contributions require an applicable separate review round.

Verified locally: 50 PostgreSQL/file/lifecycle contracts, 281 backend regressions,
8 compatibility contracts, JS assertions/syntax, Ruff and Django system checks.
Suites overlap and are reported separately. One run was interrupted by a local
machine pause/statement timeout; the full contract rerun passed. Browser verified
Community eligibility, configurable PDF upload → feedback → revision → reviewer
reassignment → approval, evaluator replacement → finalization → publication,
proposal-only registration/edit/history and mobile rendering. Synthetic browser
records live only in isolated acceptance workspaces; original user records remain.

An existing Community project is pinned to a policy without an applicable review
rubric. Evaluation stays blocked until an authorized compatible review plan exists;
no retrospective policy switch or invented rubric was applied. Production identity,
legacy rollout, storage/security/recovery validation and institutional configuration
remain prerequisites to production.

### Primary-guide synopsis responsibility (separate increment)

Forward candidate 036 records a private immutable link from each authorized new
primary-guide allocation to an explicit SYNOPSIS REVIEWER assignment. The existing
HOD/explicitly delegated coordinator guide API is reused. Guide reassignment/end
closes only linked rights; independent reviewer assignments and all prior decisions
remain. Configured approval/revision rules still apply; other document types gain
no automatic guide approval. Installation grants no historical guide rights and
creates no requirement or institutional approval. An existing guide can be saved
again through the authorized allocation command to record the new responsibility.

Verified: 53 PostgreSQL/file/lifecycle contracts (including same-key concurrency,
competing guide replacements, rollback/retry, private helper/grant denials,
independent reviewer configuration and retained approvals), 8 compatibility tests,
frontend assertions/syntax, Ruff and Django checks. The earlier 281-test backend
regression checkpoint remains recorded separately. Browser verified student actual
synopsis upload → HOD guide allocation → guide private preview and configured formal
approval, with no additional reviewer command. Original acceptance academic hashes
are checked before/after isolated candidate installation. No production rollout.

### Definitive application correction (historical checkpoint)

Backend/security/startup commit: `36bbbd4`.

Normal startup no longer seeds or serves archived fixtures. Admin can record and
implement HOD-approved external instructions with explicit provenance, without a
compulsory in-app approval loop. Human notes are optional across routine commands;
auto-audit and permissions remain. Managed proposals retain immutable descriptions;
guide/evaluator document reading is separate from formal synopsis-review authority.
Fresh HOD dashboards no longer rely on old fixture staff grants. Candidate 025–028
are isolated-test-only; 001–024 and historical records are unchanged.

Verified: 281 backend tests, 40 PostgreSQL/file/configuration contracts, 8 existing
compatibility tests, native-JS assertions/syntax, Ruff, Django. These suites overlap
behavior and are reported separately. Fresh isolated browser setup → Admin offering
→ student proposal/PDF → faculty feedback/revision/approval → coordinator history
→ publication/direct blank-note correction 86.00 → 88.00 passed. HOD appointment and
revocation without notes and desktop/mobile rendering passed. No remote CI.

Use [current report and launch instructions](APPLICATION_CORRECTIONS.md).
Remaining: production identity/bootstrap and deployment validation, approved
program/cohort contracts, wider document types, complete retrospective-roster and
routine-delegation screens, large-department paging. Full institutional MVP and
production readiness are not claimed. Earlier milestones below are historical.

### Coherent application / authorized configuration increment

Managed offering-derived proposals now connect team confirmation, title, actual PDF,
review confirmation and submission. Explicit responsibility switching is enforced
on API commands and private reads. Admin can author exact project/team policies,
review plans and trusted existing-account eligibility/access updates for HOD
approval and original-Admin application. Guide allocation is independent of
reviewer/evaluator assignment; the same qualified faculty may hold both.

Backend commit `7085e22`. Additive owner-run candidates **022–024** follow 021; 001–021 files and all previous
academic evidence are preserved. Operation grants are finite/scoped; guide intervals
cannot overlap; stale/planning/finalized-state guards and post-wait reauthorization
apply. Production activation remains blocked.

Verified: **281 backend**, **35 PostgreSQL/file/setup**, **8 demo** tests;
frontend assertions/syntax, Ruff and Django checks. Browser verified new academic
configuration → offering → student team/proposal/PDF → private faculty retrieval,
feedback/revision/approval → HOD/coordinator history → original/corrected results
**86.00 → 88.00**. Fresh department setup through corrected results passes real API
verification without demo catalogs. See [current correction report](APPLICATION_CORRECTIONS.md)
for role matrix, exact verification evidence and browser/API scope distinctions.

Remaining: production identity/bootstrap, approved program/cohort extensions,
additional document/stage workflows, complete retrospective-roster/delegation UI,
large-department navigation and production storage/security/recovery validation.
The implemented synopsis/evaluation demonstration is not full institutional onboarding.

### Synopsis document MVP

Candidate 019 connects actual private PDF upload, authenticated page preview and
download, versioned submission attempts, faculty feedback/revision/approval and
coordinator/HOD oversight. Existing academic/document tables and services are
reused. HOD authorizes immutable offering instructions; a separate, explicitly
named ACADEMIC_ADMIN executes them. Admin and TECH_ADMIN gain no independent
academic authority or document access. Requirement policies are pinned per case.
The student selects any eligible offering and its configured registration class.
Backend increment: local commit `a98ffdb`. No earlier migration file was changed.

The actual browser journey is preserved as MVP-SYNOPSIS-01: HOD → Admin → student
registration/PDF upload → faculty file retrieval/changes request → student revision
→ faculty approval → coordinator/HOD retained history. See
[document contract](DOCUMENT_SUBMISSION_API.md) and [local demo](DEPARTMENT_DEMO.md).
User-authorized faculty approval is explicit per requirement, not automatic.
Production remains blocked; report uploads, retrospective synopsis reopening,
guide allocation and large-department paging are separate functional gaps.

Latest local verification: **281 backend passed**, **17 real-file/PostgreSQL
document contracts passed**, **136 legacy/synopsis/curriculum passed** with four
existing skips/one warning. Eight existing demo contracts and six unit tests also
passed again. Document tests include atomic candidate installation, missing
prerequisites, exact Admin authority, private retrieval/rendering, revised
history, disabled approval/controls, failed storage, rollback/retry and concurrency.
The initial regression run's five DB-name isolation failures were corrected by
using a fresh `smartpro_test_` database; no assertions were weakened. Final results
are in ignored `.test-data/documents-backend-final.xml`,
`documents-legacy-final.xml` and `document-final.log`.

### Departmental demonstration

The milestone now has a working Django-served responsive frontend (native ES
modules/CSS; no previous frontend existed). Student enrollment confirmation,
team creation/join/transfer/leave, registration/progress, department configuration,
review assignment, draft scoring/finalization, publication, direct corrections,
personal result history and scoped audit views are connected to real APIs.

Backend increment `b7def69` adds candidate 018 and demo-only intake/discovery.
Candidate 018 reuses existing rubrics, assignments, receipts, policy binding and
publication logic. All 001–017 source files remain unchanged. The live database
is a persistent clone of a reviewed synthetic DB; demo setup does not execute
010–015 or reset source records. The explicit user exception permits the existing
010–015 fixtures only in disposable regression databases.

Executed locally: **278 backend cases**, **21 final initial-evaluation cases**
(overlapping, three added later), **136 legacy/database/synopsis/curriculum cases**
with four existing skips/one warning, **eight isolated-clone demo contracts**, six
unit tests and all 14 Django compatibility checks. Ruff, JavaScript syntax, SQL
static and whitespace checks passed. Browser verification covered the complete
student→faculty→published/corrected results flow (86.00→88.00, both preserved),
department enrollment, restricted technical-admin access, policy versioning and
390px responsive layout without horizontal overflow.

Launch/walkthrough/audit/limits: [departmental demo](DEPARTMENT_DEMO.md). The
loopback app is at `http://127.0.0.1:8000`; identities are explicitly synthetic.
No GitHub operations, remote CI, production access or real academic changes.

GitHub access is suspended. Work continues locally on
`feature/finalized-academic-policies`; backup `backup/smart-pro-2026-11-04` remains
at `6eb58f0`, whose verified tree is `42f1bd70413d3da2001026590bcac5d5c2320f5d`.
Historical GitHub/CI information below is not newly queried. No pushes, PRs,
merges, resets, cleans, rebases or production activation are permitted.

Candidate 016 adds explicit HOD mandates, audited coordinator appointment and
routine faculty delegation, plus immutable department quorum/aggregation policies.
Governance defaults disabled; owner bootstrap remains distinct from academic
authority. User-authorized product rules and local contracts are in
[finalized policies](FINALIZED_ACADEMIC_POLICIES.md).
Candidate 017 implements review-pinned policies, scoped result/context reads,
direct original-evaluator corrections and coordinator-authorized retrospective
roster revisions. Evaluations/results append immutable versions; original rubrics,
marks, frozen rosters and releases are retained. Historical membership AND STUDENT
role evidence is pinned and protected against later invalidation. Missing proof
fails closed; added students receive no automatic marks. Governance uses explicit
configured quorum and MEAN/MIN/MAX/WEIGHTED_MEAN capabilities, with no institutional
default. Runtime cannot directly write the new authority or academic records.

Initial local commit `6111589` passed 19 governance and 60 staff cases. Final focused
verification passed 47 academic cases; the legacy database/synopsis/curriculum run
passed 136 with four baseline placeholders skipped and one existing warning. Six
unit tests, all 14 Django compatibility checks, Ruff F/E9 and SQL static checks
passed. Detailed local artifacts are ignored under `.test-data/academic-*.xml`.
The full backend run passed 258 cases; the final 47-case focused run overlaps it
and includes two later-added migration/eligibility probes. Final governance audit
verification passed 20 cases. These are executed local counts, not remote CI.
No new skip or remote verification is claimed. Migrations 001–009 and candidates
010–015 remain unchanged from `6eb58f0`.

## Verified stack and integration boundary

Main remains `193c09535c620c722bd356d88db8582fc1b60621`. Migrations 001–009 are
unchanged. The cumulative [integration review](INTEGRATION_READINESS.md) adds
targeted pre-release corrections to candidates 010 prepare, 012 and 015 on #10; other
candidates are unchanged. Actual stack dependencies, reviews and CI were queried.

| PR | Dependency and functionality |
| --- | --- |
| [#2](https://github.com/divyanshuacharya0990-lab/SMART-PRO/pull/2), `df9d4af` | Base main; staged 010 identity, curriculum and temporal integrity |
| [#4](https://github.com/divyanshuacharya0990-lab/SMART-PRO/pull/4), `adc1c20` | Base #2; profile/offering reads |
| [#5](https://github.com/divyanshuacharya0990-lab/SMART-PRO/pull/5), `1bd703c` | Base #4; team creation/discovery and restricted reads |
| [#6](https://github.com/divyanshuacharya0990-lab/SMART-PRO/pull/6), `212c543` | Base #5; synopsis write-grant hardening |
| [#7](https://github.com/divyanshuacharya0990-lab/SMART-PRO/pull/7), `aaf9c3f` | Base #6; verified synopsis file-lock upgrade fix |
| [#8](https://github.com/divyanshuacharya0990-lab/SMART-PRO/pull/8), `8cbb517` | Base #7; audited membership commands and versioned size policies |
| [#9](https://github.com/divyanshuacharya0990-lab/SMART-PRO/pull/9), `ed807ca` | Base #8; candidate 014 registration and current-student project reads |
| [#10](https://github.com/divyanshuacharya0990-lab/SMART-PRO/pull/10) | Base #9; candidate 015 explicit staff authority, policy administration and safe initial-title corrections |
| [#3](https://github.com/divyanshuacharya0990-lab/SMART-PRO/pull/3), `da38203` | Independent policy documentation on main |

All PRs remain draft. [Prior review](STACK_REVIEW.md) and the
[registration contract](PROJECT_REGISTRATION_API.md) record cumulative risks:
reuse approved academic policies and scope FKs, preserve profile-before-team lock
ordering, pin original membership/policy evidence, and keep registration receipts
private rather than trusting the legacy writable idempotency table. No independent
human approval or production certification is claimed.

## Integration review

Candidate 010 prepare now requires baseline 009's historical guards before any
change. Candidate 012 rejects role/window expiry after an offering lock wait;
candidate 015 latches academic evidence already present at installation. All
four probes failed before the fixes. Review tests also exercise prerequisite
rollback, preflight failure/repair, full ordered installation, combined staff/
student/team/project workflow and exact logical backup/restore at both prepared
and activated checkpoints. Runtime privilege inventory confirms the documented
legacy shared-service risks; no new direct authority/receipt DML is granted.

All implementation PRs have no submitted reviews. Main's branch API reports
`protected:false`; saved check metadata is not proof of enforcement. Protection
inspection is denied and rulesets are plan-restricted. Follow the report's manual
merge gates and preserve ancestry. Source integration remains separate from SQL
activation; no merge/deployment/real-data change was performed.

## Latest execution evidence

Entry #10 `8defb98`: all four workflows passed (198 API, 39 curriculum,
97 database/synopsis with four policy skips, six unit tests and Django probe).
This integration review reran the full local suites: **212 API cases passed**,
then **all 15 final review probes passed** (overlapping cases; the last prerequisite
probe was added after broad collection). Curriculum **39 passed**; database/
synopsis **97 passed, four existing skips, one existing warning**; six unit tests,
all 14 compatibility checks, Ruff F/E9, SQL static checks and diff whitespace passed.
Logical backup/restore succeeded at prepared and activated checkpoints. Final CI
must collect **213 API cases**. Exact corrected-head CI links/results are maintained
in [PR #10](https://github.com/divyanshuacharya0990-lab/SMART-PRO/pull/10).

## Reviewed baseline functionality and next dependency

[Registration](PROJECT_REGISTRATION_API.md) uses current trusted membership and
exact offering/class policy windows; atomic project/receipt/audit persistence;
bounded full-transaction retries; multiple projects per team; private scoped reads;
and immutable registration eligibility history. No title uniqueness, leadership,
guide approval or project-count limits were invented. Unsupported registration
rules fail closed. Existing project tables and approved academic policies are reused.

[Staff administration](STAFF_ADMIN_API.md) adds exact-role effective grants,
disabled-by-default departmental controls, versioned policy publication, scoped
project discovery and explicitly enabled initial-title correction. Technical
authority/evidence revisions close stale-snapshot races; academic activity latches
corrections closed. No guide, scoring, AI or historical-amendment authority is added.
Registration regressions now install 015 so they exercise the cumulative upgrade.

Ordinary evaluator assignment/draft-scoring and student/staff demo interfaces are
now connected. Before real-user activation, approve actual department policy values,
authority bootstrap/holders, production identity/intake, full legacy sensitive-write
encapsulation, real-data upgrade/backup/recovery, storage/scanning, deployment
hardening and institutional configuration. The four historical baseline policy
placeholders concern quorum, aggregation, amendments and retrospective eligibility;
these product capabilities now have explicit candidate 016–017 tests rather than
being silently activated in the unchanged 001–009 test-only publication contract.
All candidate rollouts remain synthetic-only and owner-run until separately approved.
Remote publication is suspended. Never assume previously saved main review settings
provide enforcement under the account plan.
