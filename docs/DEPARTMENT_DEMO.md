# Archived development fixture milestone

This document records an earlier test-fixture milestone, not current product design.
The old setup/serve launcher is disabled. Do not run its historical commands or
copy fixture approvals into an operating database. Existing data remains preserved.
Use [current application launch and verification](APPLICATION_CORRECTIONS.md).

# SMART-PRO local departmental demonstration

Local-only continuation from `78364cb` on `feature/finalized-academic-policies`.
No GitHub, remote CI, deployment or real academic data is involved.
For the latest corrections, verified scope and unmet application requirements,
see [application corrections](APPLICATION_CORRECTIONS.md), including the role matrix,
managed proposal contract, verified workflows and remaining institutional boundaries.

## Frontend audit and implementation

The entire tracked repository at the milestone contained no frontend, React/
TypeScript package, HTML templates, or student/admin/faculty screens. The existing
FastAPI harness is a synopsis test service, not a frontend. Django already exposed
profile/offering reads, teams/memberships, registration, staff configuration and
versioned academic-policy/result commands.

The demonstration adds a Django-served HTML/CSS/native ES-module interface in
`frontend/`. It requires no npm install, CDN, external fonts or frontend build
server. This is a deliberate small implementation where no prior UI existed.
Existing endpoints remain the authority for teams, transfers, project registration,
department policy versions, publication, corrections and result history.

Backend pieces are implemented without parallel academic models:

- Candidate 018: review assignment, complete draft marks, faculty finalization.
  See [initial evaluation contract](INITIAL_EVALUATIONS_API.md).
- Candidate 019: HOD-authorized offering instructions, separate Admin execution,
  private persistent synopsis uploads/previews/downloads, versioned submissions,
  assigned faculty feedback/revisions/approval and coordinator/HOD oversight.
  See [document submission contract](DOCUMENT_SUBMISSION_API.md).
- Demo-only `/api/v1/demo/workspace`: scoped identity, discovery, assigned review
  context and audit metadata. Students do not receive faculty context merely
  because they have an unrelated FACULTY role. Department disablement and all demo
  feature gates are enforced.
- Demo-only POST `/api/v1/demo/enrollment`: empty body, self-confirmation from a
  trusted synthetic admission. Actor, home department, semester and USN cannot be
  supplied by a client. Repeat confirmation is idempotent.

Screens cover student overview/enrollment, team creation/discovery/join/leave/
transfer, registration/progress, admin configuration/assignment/publication,
faculty draft/final/corrected marks, personal result history and scoped audits.
Responsive navigation and forms are tested at desktop and mobile widths. Errors,
empty states, loading, stale revisions, identity switching and retry keys are
handled. Record text is escaped before display; assets use a self-only CSP.

## Start on this machine

From `C:\TwoDrive\Smart-Pro`, using the existing virtual environment and local
PostgreSQL binaries/configuration:

```powershell
.venv\Scripts\python.exe scripts/portable_postgres.py --bin-dir .test-data/postgres/pgsql/bin --data-dir .test-data/pg-memberships --action start
.venv\Scripts\python.exe scripts/department_demo.py setup
.venv\Scripts\python.exe scripts/department_demo.py serve
```

Open **http://127.0.0.1:8000**. Optional `serve --port 8001` changes the port.
Stop the web server with Ctrl+C in its launching terminal.

Setup clones the already-reviewed synthetic `smartpro_test_academic_audit` database
into `smartpro_test_demo_department`. It does **not execute candidates 010–015**,
drop/reset the source, or overwrite prior academic records. Only new candidate
018–024 and demo-only reads are installed/refreshed in the clone. The source must already have
reviewed 010–017; a bare or production database is rejected. `--source-db` accepts
only an explicitly named preprovisioned `smartpro_test_academic_*` source.

Setup is repeatable and preserves the live demo's activity/results. It never has a
reset switch. New fixture configuration is visibly synthetic: CSE/ECE capstone
offerings, explicit windows, advisory membership policy, the existing reviewed
synthetic rubric, an appointed coordinator, and a starter project/review. These
are demonstration records, not ratified institutional defaults. Only the setup
process uses owner credentials; the web child removes the owner DSN and uses the
restricted runtime login. Secrets stay in the ignored local environment file.

The launcher binds loopback only and explicitly enables demo/auth/service gates.
Assets/intake/discovery also require a `smartpro_test_demo_*` database; production
authentication still rejects all demo headers. Technical administrators gain no
academic authority.

## Suggested walkthrough

For the document MVP, use **Submissions & reviews**: HOD authorizes an exact
offering instruction and names **Demo Department Admin**; that separate Admin
configures it. Student selects the configured offering in Teams/My projects,
registers a project, uploads a real PDF and submits its version. HOD/coordinator
assigns a synopsis reviewer. Assigned faculty previews/downloads it and requests
changes; student reads feedback and uploads/submits a revision; faculty approves
when explicitly enabled. Coordinator/HOD sees both versions and all feedback.

This browser journey is preserved as **MVP-SYNOPSIS-01 / Accessible Learning
Research Portal**, under Interdisciplinary Design Thinking, with two PDFs/two
attempts: REQUEST_CHANGES then APPROVED. Earlier demo projects/results remain.
Choose a different project to exercise new submissions. Installed local
`pdfinfo`/`pdftoppm` binaries must remain on PATH for PDF validation/preview.

1. **Student A**: create/join a capstone team and register a project. **Student B**
   starts in Campus Innovators with a starter project. Transfers/leaves preserve
   historical memberships and academic evidence.
2. **Head of department**: inspect projects, configure windows/team/academic policy
   versions, and assign an applicable review to one or more eligible faculty.
3. **Assigned faculty**: save the full rubric, then finalize. **HOD/coordinator**
   publishes when the pinned quorum is met. **Student** sees only personal totals.
4. **Assigned faculty**: submit a direct correction; result versions retain the
   previous total. Open activity details to inspect the structured audit evidence.
5. **New student** uses a separate pending Electronics admission (`student-next`).
   Confirmation reveals only its home offering. Confirmation remains verified on
   subsequent visits; it is not reset to simulate a fresh enrollment.
6. **Electronics faculty/student** do not see CSE reviews. **Technical administrator**
   sees an explicit restricted-access screen.

Browser verification created Aster Robotics / Assistive Robotics for Campus Access,
published 86.00 and corrected it to 88.00. Both versions remain in the persistent
demo. Earlier tested enrollment history is also retained. The pending incoming
admission is separate, so the user can still exercise confirmation firsthand.

## Verification

Latest document increment: full backend **281 passed**; document workflow **17
passed**, including clean/missing-prerequisite migration checks and actual PDF
rendering; legacy database/synopsis/curriculum **136 passed, four existing baseline
skips, one existing deprecation warning**; **eight demo contracts** and **six unit
tests** passed again. Syntax, Ruff F/E9 and whitespace checks pass.
The earlier milestone's 14 Django compatibility checks remain historical evidence.
No remote result is claimed.

An initial backend run had 276 passes/five failures because its disposable DB name
did not satisfy the integration suite's `smartpro_test_` prefix check. The final
full run used a fresh, correctly named DB and passed all 281; assertions were kept.

```powershell
.venv\Scripts\python.exe scripts/test_department_demo.py
.venv\Scripts\python.exe scripts/test_document_workflow.py
```

This executes **eight** role/intake/department-disablement/privacy/end-to-end
contracts in a freshly named disposable clone of the demo, then removes only that
clone. Persistent demo/source records are untouched. The older regression harness
was run only in disposable synthetic databases under the user's explicit exception
allowing candidate 010–015 execution **for isolated regression fixtures only**.
Browser checks covered the actual login → team → project → assignment → scoring →
publication → correction → student result flow, enrollment, technical-role denial,
versioned settings, and 390px responsive layout without horizontal overflow.
Local screenshots/XML evidence remain ignored under `.test-data/demo-*`.

## Remaining boundaries

This is a functional departmental demonstration, not production activation.
Production login/intake, actual policy ratification/configuration, full legacy SQL
encapsulation, deployment/load/storage/recovery validation and a portable approved
real-data upgrade remain blocked. A preprovisioned reviewed synthetic database is
required for setup on another machine. Guide allocation and synopsis REVIEWER
assignment are separate, audited operations; a guide may also evaluate.
Report/presentation/source-code uploads, retrospective reopening/deadline
exceptions, notifications and large-department pagination remain separate work.
Admin requests, HOD approves and Admin applies project/team/review-plan setup.
The UI provides no arbitrary owner/bootstrap grant interface. Existing authority
provenance and historical academic evidence remain protected.


## Current local walkthrough

The prepared database persists all previous examples plus Applied Research Studio,
Research Access Lab and Accessible Field Research Notebook. The latter contains two
private PDF versions, requested-change/approval feedback and result versions 86/88.

```powershell
cd C:\TwoDrive\Smart-Pro
.venv\Scripts\python.exe scripts/department_demo.py serve
```

Open http://127.0.0.1:8000/. Setup is already complete on this machine; `serve`
never seeds or migrates. If additive synthetic setup needs refreshing, run the
explicit `setup` command first; it never executes 010–015 or resets history.

Test accounts: Nisha Reddy (Admin), Meera Iyer (choose HOD or Admin), Arjun Mehta
(Student), Anika Rao (Faculty), Dev Menon (choose Coordinator or Faculty), Rhea
Nair (foreign-department Student). Kiran Shah has genuine Student and Faculty
appointments; select the intended responsibility explicitly. Technical access alone
stays academically restricted. No passwords, real users or production login.

Admin: Academic setup → request exact values. HOD: Academic setup → review and
confirm authorization. Original Admin: apply. HOD: Submissions → authorize offering
using approved plan/team policy and explicit windows. Named Admin: Offerings →
configure. Student: Teams → select offering/create or join; My projects → title,
team confirmation, PDF, review, confirm. Faculty: assigned project → private PDF,
feedback/decision; student may revise when requested. HOD/Coordinator oversee the
same records. Evaluation uses applicable approved review choices; only Faculty
context scores/corrects its assigned assessments. Published versions remain visible.
