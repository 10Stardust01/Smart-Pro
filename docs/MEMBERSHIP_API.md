# Student membership commands — candidate 013

Stacked after PRs #2 -> #4 -> #5 -> #6 -> #7. No automatic or real-data upgrade.
Preserve migrations 001–009 and reviewed 010 mapping/preflight/activation gates.

## Contract

All routes require trusted authentication, an ACTIVE account and an effective
STUDENT role in the verified profile department. Demo users remain synthetic-only;
USNs, client actor IDs and Google Forms do not authenticate anyone.

| Route | JSON body | Success |
| --- | --- | --- |
| GET `/api/v1/me/memberships?cursor=<UUID>` | none | 200, own current scoped memberships only |
| POST `/api/v1/teams/{teamId}/memberships` | `{}` | 201, new membership |
| POST `/api/v1/memberships/{membershipId}/end` | optional `reason` | 200, ended interval |
| POST `/api/v1/memberships/{membershipId}/transfer` | `targetTeamId`, optional `reason` | 201, replacement membership |

POSTs require `Idempotency-Key` with the existing team API's 1–128 character
format. Unknown fields, client timestamps/identities and malformed input fail 400.
Matching retries return the original body with 200; a changed canonical request
using the same actor/action/key fails 409. Retries recheck current actor/scope but
may replay a committed result after windows close or membership ends. `reason`
is optional, trimmed and at most 500 characters, and is stored in the audit event.

Command responses contain `action`, `offeringId`, `teamId`, `membershipId`,
`previousMembershipId`, `effectiveAt`, `policyVersionId` and `warnings`. Own-membership
reads return `{results,nextCursor}`, at most 50 UUID-ordered rows containing `id`,
`teamId`, `teamName`, `offeringId`, `cycleId`, `joinedAt`, `scheduledEndAt`. They
include current memberships behind closed admission windows so a permitted leave
remains usable; they expose no other student's identity or roster. Pages reflect
current state. All successful responses are `no-store`.

Scope/disabled policy/foreign membership failures return 403; current-state,
capacity, exclusion and conflicting key failures return 409. Disabled rollout or
database/commit failure returns sanitized 503. Unauthenticated requests return
401; unsupported methods return 405. No staff transfer authority is implied.

## Explicit departmental policy

As migration owner, install 013 after activated 010, 011, 012 and the reviewed
runtime security boundaries. It creates immutable `team_membership_policy_versions`
and offering-specific `offering_membership_policies` bindings with composite
department/cycle FKs. No default institutional sizes or self-service permissions
are invented: JOIN/LEAVE/TRANSFER require a configured binding and an explicitly
enabled operation. Policy flags default false, sizes are nullable, and
`size_mode` must explicitly choose `ADVISORY` or `ENFORCED`.

JOIN/TRANSFER require the target offering to match the student's current department
and semester and to have an open server-published visibility window. Its exact
offering/cycle is the bound scope; a client cannot authorize a future cycle.
Transfers stay within the same offering and academic cycle. Creation permission
is separate: `student_team_creation_enabled` does not authorize joining.
LEAVE requires ownership, current profile scope and policy permission, and remains
possible after admission closes. An absent binding fails closed.

ENFORCED maximum blocks admissions and ENFORCED minimum blocks departures that
would leave too few currently active members. Minimum is not a prerequisite for creating
or growing an initial team. ADVISORY mode records below/above-limit warnings in
the response/audit. Future scheduled memberships reserve maximum capacity conservatively;
past/ended members do not. Existing records are never rewritten to fit a new policy.
Configured maxima also protect creator enrollment through the existing 012 command.

Policy versions cannot be updated/deleted; changing policy means a new version.
Binding changes automatically append an audit event with old/new binding and the
database provisioning principal. Each student command preserves its policy version.
Only reviewed owner provisioning exists here; a delegated staff publication UI/API
and human actor attribution for staff commands are separate work. Runtime cannot
read or mutate policy tables directly. Enable `SMARTPRO_MEMBERSHIP_API=YES` along
with both existing student/team rollout gates only after staged verification.

## Transaction and concurrency boundary

Commands lock profile -> account/role -> idempotency -> offering/policy/window ->
affected teams in UUID order -> membership rows. They recheck time eligibility
after waiting. Team revision writes serialize capacity across different students
and invalidate stale REPEATABLE READ/SERIALIZABLE snapshots. The shared capacity
trigger covers 012 and scheduled owner admissions as well. Existing exclusion/FK
and historical eligibility triggers remain authoritative.

A transfer ends its old interval and appends a new identity at the same server
instant. It never moves a membership row or rewrites rosters/submissions/results.
Membership, audit and replay record commit together; any failure rolls back all
effects. The Django service owns the whole transaction and retries 40001/40P01
at most three times with reauthorization, never just a savepoint inside an outer
transaction. Exhaustion returns a retryable 409 using the same key. Lock/statement
timeouts remain bounded. Runtime SQL actor parameters still rely on the trusted
server, and the previously documented legacy synopsis direct-write risks remain.

Regression tests run real HTTP and restricted-role SQL against PostgreSQL 16:
permission/scope denial, policies, identical/conflicting retries, parallel final
place joins, same-offering races, opposite transfers, stale snapshots, historical
evidence, scheduled reservations, deferred commit failure and transaction retry.
