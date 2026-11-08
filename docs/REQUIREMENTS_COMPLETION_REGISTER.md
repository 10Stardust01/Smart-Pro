# SMART-PRO requirements completion register

This register tracks approved behavior and the evidence available at each checkpoint.
Verified means an applicable test or browser workflow passed. Historical evidence
is identified by commit and remains valid for the scope it covered. Change a row
when its behavior, verification evidence or assigned milestone changes.

| Requirement | Status | Evidence | Remaining gap | Priority | Assigned milestone |
| --- | --- | --- | --- | --- | --- |
| Students see eligible offerings, join teams and register projects in scope. | Verified | Course and document workflow suites; student project work in `52924d7`. | | High | C |
| Offering activation requires an effective Coordinator and protects the last effective appointment. | Verified | `scripts/test_course_workflow.py`, activation and concurrent last-removal tests; D browser at `bc6695d`. | | Critical | D |
| Admins configure approved offering settings and preserve changes. | Verified | D browser created and activated an offering; document suite verifies lifecycle and history. | | High | D |
| Guides review authorized submissions, request a revision and approve when policy allows. | Verified | C browser executed submit, request changes, resubmit and approve; document contracts preserve both attempts. | | High | C |
| Evaluators can enter and finalize assigned TEAM, INDIVIDUAL and COMBINED marks. | Verified | B and C browser evidence at `88ff737` and `52924d7`; individual and combined course regression. | | Critical | C |
| Coordinators work within offering context, see assessment progress and exercise authorized publication and correction operations. | Verified | A context at `0589f47`; B queue at `88ff737`; candidate 049 and course lifecycle contracts. | | Critical | B |
| Overall release closes ordinary edits; exceptional revisions retain earlier evidence. | Verified | Candidate 049; course correction, publication race and exceptional overall revision tests; C.1 reliability. | | Critical | C.1 |
| Document versions, feedback and academic decisions retain their history and use scoped private retrieval. | Verified | C browser and C.1 document, storage and restore tests at `ecb0d6e` and `1a5cb15`. | | Critical | C.1 |
| Admins appoint Coordinators; HOD can replace an Admin; successor HOD requires vacancy. | Verified | D browser and course authority contracts at `bc6695d`. | Competing Admin replacements and HOD succession are covered by the D.1 course regression. | Critical | D.1 |
| Admins search and open scoped departmental student and faculty records and inspect history. | Verified | Candidates 052 and 057; Chrome search, Back, Forward, and refresh; scoped profile and import/reconciliation evidence. | | High | D.1 |
| Accepted BIT CSE faculty reference can be viewed without granting authority. | Verified | Scoped reference and local opt-in at `77d0904`; course reference authorization test. | | High | D.1 |
| Technical faculty crosswalk links roster references and operational account UUIDs using auditable institutional evidence. | Verified | Candidate 057; Chrome synthetic proposal and verification; concurrent duplicate claim, revocation, replay and scoped access contracts. | | High | D.1 |
| BIT supplies authoritative employee identifiers and approves the institutional account mapping process. | Pending | The institution has yet to approve the mapping. D.1 fixtures are synthetic. | Approved identity evidence, actual account linkage, and production resolver integration. | Critical | Institutional onboarding |
| Official imports preview, validate, apply and preserve provenance and identity history. | Verified | Candidate 053, Chrome CSV/XLSX, 1,100-row regression and 3,500-row HTTP test. | | High | D.1 |
| Admin and HOD offering and appointment discovery covers the full scoped dataset. | Verified | Candidates 054–057; Chrome page 9 of 205 offerings and candidate 304 on page 9 of 205; attributed histories and concurrency tests. | | High | D.1 |
| Shared role navigation and responsive workflow surfaces. | Verified | Milestone E Chrome journeys across all five roles at 1440, 820 and 390 px, with scoped history, result reload and keyboard checks. | Formal accessibility conformance audit remains outside the verified checks. | High | E |
| Milestone E preserves the critical write workflows across all five roles. | Verified | Disposable Chrome acceptance covered offering edit, CSV apply and receipt, rubric save and finalization, stage and overall publication, Student PDF revision, and Admin replacement history. Six focused PostgreSQL contracts and the frontend suite passed. | Targeted accessibility checks only. | Critical | E |
| Course and project discovery stays bounded and scalable. | Verified | Candidate 049 queue, candidate 050 document pages and C.1 performance evidence in repository status. | Deployment-specific capacity and query verification. | High | Deployment readiness |
| Concurrent academic workflows retain submissions, marks and published evidence. | Verified | [Capacity baseline](CAPACITY_BASELINE.md): upload burst, shared-team contention, committed-response loss and two-stage evaluation. Candidate 058 aligned with local development after a restore rehearsal. | Verify deadline boundaries and transport interruption under load on the intended runtime. | Critical | Deployment readiness |
| Establish a measured mixed-role and deadline capacity envelope. | Partial | [Capacity baseline](CAPACITY_BASELINE.md): 100/500-project fixtures, controlled connection reuse comparison, traced admission and recovery, import overlap. | Longer multi-department soak, dense historical data, independent generator, deployment hardware and agreed arrival targets. | High | Deployment readiness |
| Permissions are scope-bound and synthetic authentication is isolated. | Verified | Existing role, cross-offering and revoked-session contracts; development identity safeguards in `1a5cb15`. | Production identity resolver and institutional provisioning. | Critical | Deployment readiness |
| Development database restore and migration preserve academic evidence. | Verified | Owner rehearsed candidates 052–057 on fresh restores and aligned `smartpro_dev`; existing table fingerprints and stored PDF matched. | Production-specific backup, restore and rollout authorization. | Critical | Deployment readiness |
| Production sign-in, retention, emergency HOD succession and institutional onboarding are authorized and validated. | Blocked | Institutional decision register and deployment runbook. | Requires institutional decisions and verification in the approved environment. | Critical | Deployment readiness |
| Automatic guide allocation and COE integration remain outside current scope. | Intentionally deferred | Existing academic policy and milestone scope. | | Low | Future approved milestone |

See [repository status](REPOSITORY_STATUS.md), [institutional readiness](INSTITUTIONAL_READINESS.md)
and [deployment and recovery](DEPLOYMENT_AND_RECOVERY.md) for evidence and boundaries.
