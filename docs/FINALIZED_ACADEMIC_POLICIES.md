# Finalized academic-policy implementation (historical local baseline)

**Later user-approved product decision (pending faculty ratification):** After an
overall result has been published, the assigned Project Guide may request a
specific correction. The offering's responsible Coordinator may approve or
reject it even if the same person is the Guide, was an evaluator, or made the
request. There is no independent-person, second-approver or mandatory HOD
escalation. Original and corrected published result versions, exact change,
reason and audit evidence must remain. The historical independent-authorization
passages below describe the *older* course implementation; they do not override
the later exceptional-only decision. Ordinary pre-publication correction rules
are not changed by this decision. Candidate 059 on the review branch prepares
this alignment and remains unapplied to the live deployment pending tests.

The user's continuation instruction authorizes implementing configurable quorum,
aggregation, original-evaluator mark corrections, coordinator retrospective roster
corrections, and the HOD → coordinator → delegated faculty authority chain.
This supersedes earlier statements that these product behaviors are undecided.
No actual department values are approved or activated by the implementation.

For course-bound evaluations under candidates 037–042, the newer course policy
requires independent offering-coordinator authorization of the original
evaluator's exact proposed change. Earlier records and release versions are
retained. See [Course Management](COURSE_MANAGEMENT.md).

Owner-run candidate 016 follows 015. Governance settings and explicit mandates
for existing HOD role records default disabled/empty. TECH_ADMIN has no authority
to create these records through the API. A database owner remains a trusted
bootstrap operator; PostgreSQL cannot prevent its superuser changing database data.

All routes below are authenticated POSTs under
`/api/v1/academic/departments/{departmentId}`, gated by `SMARTPRO_ACADEMIC_API=YES`
and explicit enabled departmental configuration. Production identity still fails
closed. Each command requires `Idempotency-Key`, `expectedRevision` (department
governance revision, initially zero), and an optional `reason` (maximum 500 chars; omitted/blank accepted after 025).
Success is 200, including replay; stale revisions/key conflicts return 409,
authority/disabled configuration 403, invalid input 400, disabled API/database 503.
All documented fields except the optional note are required; identity always comes from authentication.

| Suffix | Additional fields / authority |
| --- | --- |
| `/coordinators` | `userId`, timezone-aware finite `validUntil`; explicitly mandated HOD appoints active departmental faculty |
| `/coordinators/revoke` | `mandateId`; appointing HOD mandate revokes coordinator and its issued routine grants |
| `/delegations` | `roleAssignmentId`, `permission`, nullable `projectId`, aware `validUntil`; effective appointed coordinator delegates READ_POLICIES, READ_PROJECTS or CORRECT_PROJECT to exact effective faculty role |
| `/delegations/revoke` | `grantId`; coordinator revokes its own delegation |
| `/policies` | `evaluatorQuorum`, `aggregation`, `evaluatorWeights`; mandated HOD appends immutable policy version in the role-aware application (the legacy SQL capability also permits appointed coordinators) |

Supported aggregation capabilities are MEAN, MIN, MAX, and WEIGHTED_MEAN. None is
a default institutional formula. Nonweighted policies require empty weights;
weighted policies require explicit positive decimal weights keyed by evaluator
user UUID. Actual review applicability, quorum satisfaction and exact weight
coverage must be validated at publication. No SUM strategy that silently expands
the rubric maximum is introduced. Decimal arithmetic/rounding is documented with
the result implementation.

Appointments and policies serialize on the departmental governance revision.
Receipts/audit commit atomically; retries reauthorize and repeat the whole
transaction. Audit captures actor, authority provenance, old/new input and reason.
Owner bootstrap changes identify the database principal separately. Existing
015 staff grants retain their provenance; newly delegated grants also require
the live coordinator/HOD chain, enabled governance and active accounts. Revocation,
expiry or disabling source authority removes their usability. Ordinary faculty,
guides and technical administrators cannot independently grant academic power.

Only synthetic local testing is authorized. Existing migrations 001–009 and
candidates 010–015 remain unchanged in this implementation. No cloud/GitHub
operation, production migration, deployment or real-user activation is permitted.

## Review policies, revised evaluations and results

Owner-run candidate 017 follows 016. It adds immutable extension records linked to
existing reviews, assessments, evaluator assignments, membership evidence and
approved rubric criteria. It does not reopen finalized assessments or change
legacy result releases. Their source rows, scores, attribution and histories remain
unchanged. New result versions retain the legacy release ID where applicable.
Candidates are single-install scripts, not rerunnable upgrade tooling. Rebuild
isolated synthetic databases from the final candidates or design a reviewed
forward repair for an earlier draft; never clear real records to reapply them.

Routes below use `/reviews/{reviewId}` beneath the same departmental prefix.
POSTs require an idempotency key and `expectedReviewRevision`, initially zero
before binding. This counter is separate from the department governance revision.

| Method / suffix | Additional fields and semantics |
| --- | --- |
| POST `/policy` | `policyId`, `reason`; mandated HOD/appointed coordinator pins an immutable policy and snapshots the original frozen roster. No silent rebinding. |
| POST `/roster` | `membershipIds`, `reason`; appointed coordinator supplies the complete corrected, nonempty roster. Membership must belong to the project's team and cover the review freeze time, with an effective historical STUDENT role in that department. No fabricated membership or role is created. |
| POST `/evaluations` | `assessmentId`, `scores`, `reason`; only the original evaluator with an ACTIVE account/effective departmental FACULTY role may append a corrected version of its finalized assessment. Reason may be empty: automatic structured old/new audit is mandatory. No coordinator approval/grant is required for this command. |
| POST `/publish` | `reason`; mandated HOD/appointed coordinator publishes only when configured quorum and current-roster score completeness are satisfied. |
| GET `/results?afterVersion=0` | Up to 50 immutable result versions, with `nextAfterVersion`. Mandated staff see scoped full sources; original evaluators see their own source details and review context/rubric. Students see only their own historical totals and no evaluator source scores. Foreign principals are denied. |
| GET department `/policies` | Mandated HOD/coordinator reads governance revision and up to 50 latest policies/appointments. |

Each `scores` item has exactly `criterionId` (mode-criterion UUID), `studentId`
(null for TEAM criteria, student UUID for STUDENT criteria), and `marks` (finite,
nonnegative decimal, at most two decimal places). Every applicable criterion and
every corrected-roster student must be covered exactly once, within the frozen
rubric maximum. TEAM, INDIVIDUAL and COMBINED use existing mode-criterion scopes.

`DECIMAL_TOTAL_V1` sums TEAM plus individual criterion marks per student/evaluator,
then applies the pinned strategy over **all finalized evaluators**. Quorum is the
minimum finalized evaluator count; it does not imply selecting a favorable subset.
WEIGHTED_MEAN requires exact coverage of those evaluators using positive weights
keyed by canonical evaluator UUID. Arithmetic is PostgreSQL numeric, rounding only
the final aggregate to two decimals (half values round away from zero). Sources,
policy, roster, calculation version, actor and predecessor are retained per result.

Corrections automatically publish a successor when a legacy/new publication exists
and the current roster's evaluations are complete. Otherwise corrected evaluations
remain pending, with `resultVersionId:null`; no marks are auto-awarded to an added
student. A roster correction never changes a prior roster or released total. Each
finalized evaluator must supply complete marks for a changed roster before its
revised result can publish. After publication, any original evaluator can directly
correct its own contribution again; other evaluators' contributions remain pinned.

Result/evaluation/roster records and command receipts are private and immutable.
The review revision serializes competing updates; stale requests fail 409 and may
refresh/retry with a fresh key, while exact retries retain their original receipt.
Audit failure, deferred commit failure or a denied operation rolls back the entire
command. New role/membership revision writes reject stale snapshots that could
otherwise backdate evidence. Configured policy behavior is implemented; actual
department quorum, strategy, weights, authority holders and applicable reviews
still require explicit institutional configuration before real use.


## Confirmed application clarifications (5 November 2026)

Evaluator eligibility is an active department FACULTY role plus an authorized
project-specific evaluator assignment. A second HOD faculty-appointment model is
not required. A primary guide may also evaluate the project; guide, document
reviewer and evaluator assignments remain separate. Display names and STUDENT
roles never establish faculty eligibility. Multi-role users explicitly select
Faculty to score/correct, HOD to authorize policy and Admin to execute approved
configuration. Candidates 022–024 and the current API enforce this separation;
no existing published contribution or academic history is rewritten.
