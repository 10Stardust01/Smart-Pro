# Initial review assignment and evaluator-owned draft marks

Candidate `018_initial_evaluations.sql` follows 017. It adds one restricted
SECURITY DEFINER command, no direct runtime score-table grants and no changes to
001–017. Local synthetic use only; production rollout remains blocked.

Authenticated POST routes under `/api/v1/academic/departments/{departmentId}`:

| Suffix | Exact body fields |
| --- | --- |
| `/reviews` | `projectId`, `schemeVersionId`, `schemeModeId`, `policyId`, `facultyIds`, `reason` |
| `/assessments/{assessmentId}/draft` | `expectedAssessmentVersion`, `scores`, `reason` |
| `/assessments/{assessmentId}/finalize` | `expectedAssessmentVersion`, `reason` |

All require `Idempotency-Key`, enabled academic service/governance and a nonblank
reason up to 500 characters. Success/replay is 200; denial 403, stale state or
incompatible configuration 409, invalid input 400, unavailable service/database 503.
Identity comes only from authentication. Exact retries reauthorize and return the
same receipt; different bodies under the same key conflict.

Only a mandated HOD/appointed coordinator can assign a review. Project department,
cycle, active rubric, allowed mode, project policy and immutable academic policy
must agree. Distinct effective departmental faculty must satisfy configured quorum
and exact weights where applicable. The current eligible team roster is frozen,
assignments and DRAFT assessments are created, and the existing 017 command pins
the policy. Disabled/unverified team members cause failure rather than silent
omission. No new review labels, rubric maxima or institutional rules are assumed.

Only each assessment's original active departmental faculty evaluator can save or
finalize it. Scores use the same `{criterionId, studentId, marks}` contract as
017: exact full criterion/roster coverage, TEAM student null, finite nonnegative
decimal marks up to two places, within the approved criterion maximum. Saving
advances `assessmentVersion`; finalization validates completeness and locks the
original assessment. Once all assigned assessments are finalized, the base review
advances to FINALIZED. Existing 017 handles quorum publication and append-only
corrections; the new API does not duplicate publication or correction logic.

Commands lock department/review/assessment scope, retain original records, audit
actor/authority/old/new input, commit receipts atomically and reuse the established
bounded whole-transaction retries. Concurrent draft saves conflict on version;
same-key concurrent assignments create one review. No owner credentials are used
by HTTP handlers.
