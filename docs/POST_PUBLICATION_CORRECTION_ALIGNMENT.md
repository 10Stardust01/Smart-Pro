# Direct overall-result correction — finalized product direction

SMART-PRO remains a project lifecycle and academic evaluation platform, not a
faculty HR application.

After an overall result is published, its **currently assigned Project Guide**
can propose an exact corrected **overall mark for a student** with a reason.
The responsible offering **Coordinator** approves or rejects the specific
request, even if the Coordinator is the Guide, requester or original evaluator.
No HOD, independent approver, extra authorization or separate apply action.

Approval appends a new `course_final_results` version in the SAME transaction.
Previous results and the existing published review-stage scores stay immutable.
The correction's exact old/new mark, student, reason, actor, approval, preceding
result ID and successor version remain in the existing request,
authorization/application, result and audit records. The recorded stage
sources are copied unchanged as provenance; the new overall result is an
**authorized exceptional correction**, not represented as a new calculation
of unchanged stage marks. Declining a request does not alter the result.

Candidate `059_published_correction_authority.sql` on the review branch replaces
the previous proposed stage-recalculation 059; candidates 001–058 and live Neon
are untouched. Backend `REQUEST_FINAL_REVISION` now carries project ID,
expected published version, student ID, new overall mark and reason.
`AUTHORIZE_FINAL_REVISION` records the Coordinator decision and, if approved,
immediately issues the corrected result. Previously exposed exceptional stage
API aliases and `APPLY_FINAL_REVISION` are rejected.

A Guide sees the correction form from their Project work page; the Coordinator
sees pending decisions under course Results. UI access is supported by server
authorization and exact current role/assignment checks.

**Status: code and targeted regression tests prepared only.** These changes
are not merged, not installed in Neon, not deployed on Render and not yet
tested against an isolated PostgreSQL database or in a full browser journey.
Run those checks before any staging rollout. No trial/paid services.

Other project decisions stand: configurable/pinned review stages and rubrics,
scoped Guide/evaluator responsibilities, prior version history and minimal
Admin account/access controls. No student marks-flagging feature or invented
approval role has been added.
