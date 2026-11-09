# Course Management

An offering starts paused. Activation requires an effective course coordinator
with an active departmental faculty role. An HOD can appoint multiple coordinators
with distinct responsibilities. Admin can record a communicated HOD instruction
with provenance. Renewal, changed responsibilities and revocation append versions.
Student access depends on a currently effective appointment. Replace a sole
coordinator before revoking their appointment on an active offering.

Course Management shows assigned offerings and brings together their requirements,
review plans, assignments, submissions, deadlines, results and history. A coordinator
applies exact approved requirement versions and schedules stages within approved bounds.
The HOD, or Admin recording HOD instructions, establishes the framework. Each stage
pins its rubric, marking mode, quorum, aggregation, window and overall weight.
Single-stage results retain rubric marks. Weighted results normalize each stage
against its rubric maximum before applying its weight and the approved final scale
and precision. Required or positively weighted stages need published marks.

The application reuses team registration, private PDF storage, document decisions,
academic reviews, evaluator assignments, frozen rosters and release history.
Assigning a stage includes the active primary guide as an evaluator. Handover
retains prior evaluation evidence. The authorized primary guide may reopen an
approved synopsis before overall publication. Stage publication leaves the ordinary
document workflow open. Overall publication closes ordinary document changes.
Ordinary pre-overall-publication finalized-mark corrections retain their existing
evaluator/Coordinator authorization rules. **Finalized product decision (not
faculty-ratified):** after overall publication, the assigned Guide requests a
specific correction directly to a student's overall result with a reason.
The responsible Coordinator approves or rejects it, even when the Guide and
Coordinator are the same person. Approval appends a corrected overall version
without editing or recalculating completed stage results. Both original and
corrected overall versions, exact change, decision and audit history remain.
Candidate 059 prepares this direct workflow; do not deploy before isolated tests.

The deadline worker checks approved obligations and creates deduplicated in-app
warnings. A completed obligation stops showing as active, and an authorized date
change supersedes earlier warnings. Notification history stays available.
External delivery has no configured channel. Real departmental frameworks,
requirements, reviewers, windows and reminder timing must be approved explicitly.

## Local verification

Run from the repository root with the existing local virtual environment and
synthetic PostgreSQL test cluster. This creates a separate schema-only browser
workspace with test identities and prints its manifest path.

```powershell
.venv\Scripts\python.exe scripts\application.py test-workspace --port 8003
```

Open [the local workspace](http://127.0.0.1:8003/). To resume an existing isolated
workspace, pass its printed manifest to `serve --test-manifest`. The launcher
starts the in-app notification worker every 60 seconds for a course-enabled
workspace. Normal `serve` uses an explicitly provisioned database and performs
no setup or migrations.

Browser verification used separate single-stage and multi-stage offerings. It
covered scoped appointments, an attempted sole-coordinator revocation, assignment
and publication by the coordinator, actual student PDFs, guide review and marks,
an overdue synopsis revision and deadline extension, and final result history.
The weighted result was 81.00 from 60.00 at 25% and 88.00 at 75%. The single
assessment retained 76.00 and its independently authorized revision to 80.00.
Phone-width verification covered Results and page overflow. A full mobile replay
and broader deployment-scale notification performance tests remain outstanding.

Candidates 037–042 are owner-run and were installed in isolated test databases.
Production activation remains blocked pending deployment controls, production
identity, migration preflight and approval of actual academic configuration.
