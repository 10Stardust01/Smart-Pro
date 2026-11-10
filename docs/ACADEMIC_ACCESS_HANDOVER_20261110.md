# SMART-PRO academic access and assignment handover

**Owner-approved product decision: 10 November 2026.** This is academic
project management, **not** an employee HR/job-desk feature. No institutional
production authorization is implied.

When an authorized Department Admin ends another non-HOD Faculty member's
SMART-PRO **application** Faculty term, access ends immediately even if that
person is the only Coordinator, or has unfinished project Guide or Evaluator
duties. Session expiry or ordinary logout is **not** a Faculty role revocation.

Academic evidence (existing student submissions, versions, evaluations,
finalized scores, released results, authorship, and audit history) is immutable
and retained. Current Guide/reviewer intervals close prospectively; active
evaluator responsibility is withdrawn without deleting old scores; affected
offering Coordinator appointment versions remain historical and no longer
authorize commands. An offering with no effective Coordinator is flagged by
the existing Admin/HOD offering coverage view. Coordinator-only operations
stay denied until an authorized Admin appointment. Ordinary voluntary last-
Coordinator removal remains protected.

The offering Coordinator uses existing authorized project/Guide/evaluator
reassignment commands. Department Admin appoints replacement offering
Coordinators. No replacement is selected automatically. The Coordinator
evaluation queue shows when there is a recorded Faculty access handover on
a project; its history warning is not a claim that the replacement is still
outstanding. Restoring a new Faculty term never silently restores a previously
ended Guide/evaluator/Coordinator assignment; it requires explicit new
academic authorization. A fresh Faculty term itself needs no additional HOD
approval chain.

## Status and boundaries

Candidate [064](../proposals/curriculum/064_academic_access_handover.sql)
proposes the immediate TERMINATE mechanism on a **disposable development
database first**, with role-, history- and same-key retry contracts.
An Admin-scheduled future **AMEND_TERM** shortening continues to require
prospective coverage resolution; scheduled automatic cutovers are not claimed.
No live staging schema or private PDF data is changed by opening the PR.

Before a production rollout, verify actual authenticated UI/browser changes,
racing academic writes and role revocation, future term expiry behavior,
independent database/private-object restore, and the existing release gates.
Do not reapply the already-installed candidate 063.
