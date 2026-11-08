# Sprint 1: teams, projects and authorized faculty changes

Work is ordered by dependencies and completion criteria, with no fixed duration.
Five developer responsibilities are proposed. Current deliverable is
the initial adapter scaffold and plan, not completed team-write functionality.
Keep the validated harness and SQL contracts as regression oracles.

## Ownership and sequence

| Owner | Prerequisites and contracts | Implementation | Acceptance and review |
|---|---|---|---|
| Developer 1 | Django configuration, identity boundary, OpenAPI conventions | Trusted-principal interface, scoped authorization and SQL connection ownership; production provider stays disabled until selected | Missing/disabled identity and cross-department denial tests; review Developer 2 |
| Developer 2 | Team/project write design and forward migration 010 proposal | Create team/project, join/leave, delegated membership edits, guide reassignment, audit and idempotency | Concurrent joins/edits, narrow runtime rights, frozen history unchanged; review Developer 3 |
| Developer 3 | Preserve synopsis error/response contracts | Adapt seven existing routes incrementally with serializers, file-verifier/storage ports and same service transactions | Run revision/approval contract suite against adapter; no quorum policy invention; review Developer 1 |
| Developer 4 | Student screens against agreed API schema | Create/join team, register project, overview, membership and policy warnings | Real API integration, loading/conflict/denial states; review Developer 5 |
| Developer 5 | Faculty/Admin permission-aware screens and test matrix | Delegated team and guide edits, current/historical roster views and audit reasons | End-to-end acceptance, CI evidence, independent PR review; review Developer 4 |

Contract gate: agreed endpoint DTOs, error envelope, effective-date policy, team
delegation model and migration review. Begin independent UI components and read
queries while migration/permission work is reviewed. Do not block all work on
unconfirmed marking or approval policies.

Complete each slice as soon as its acceptance criteria pass; no calendar wait or
fixed deadline applies. Prioritize the complete team/project/delegated-edit flow.
Other synopsis routes may follow incrementally without delaying that flow.
Before write implementation, agree the delegation model for shared teams,
stale-version request fields, atomic guide replacement, and policy-setting routes.

## Module boundaries

`identity` verifies a principal; `academics` resolves cycles/policies/delegation;
`teams` owns effective memberships; `projects` owns registration/assignments;
`synopsis` wraps the retained service; `audit`/`outbox` stay in the command's DB
transaction. Add Django apps as each slice lands. Current smartpro package is a
small compatibility adapter only. ORM reads may use unmanaged models; command
repositories retain explicit SQL when composite guards or lock order matter.

## Proposed API contract to implement

All routes under `/api/v1`, trusted authentication required. List endpoints must
filter by scope before serialization; object checks alone do not protect lists.

| Method/path | Input / behavior | Authorization |
|---|---|---|
| POST /teams | cycleId, name; return id and guideline warnings | Current student and department setting permitting formation |
| POST /teams/{id}/memberships | studentId; server chooses effective timestamp | Self-join under configured policy or explicit delegated team manager |
| POST /memberships/{id}/end | reason; preserve old interval | Self-leave if permitted or explicit delegated team manager |
| POST /projects | teamId, projectType, approved policyVersionId, projectCode, title | Authorized current member and approved scoped policy |
| POST /projects/{id}/guide-assignments | facultyUserId, reason | Coordinator/HOD or explicit effective project/team delegation |
| POST /guide-assignments/{id}/end | reason; append replacement assignment separately or atomically | Same scope; preserve historical decision attribution |
| GET /me/projects | Current authorized project summaries | Current student/faculty or explicitly scoped academic administrator |
| GET /projects/{id}/history | Historical memberships, assignments, audit | Explicit project read permission; no broad directory exposure |

Mutation requests carry Idempotency-Key. Return 201 for new resources, 200 for
matching retries, 401 for missing identity, 403 for denied scope, 409 for stale
version/conflicting retries, 422 for invalid state. Preserve the existing synopsis
response contract when migrating it; its stored idempotent response status is 201.
For membership concurrency, lock the team row; project row_version alone does
not serialize changes to a shared team. Use deterministic team/project lock order.
Guide reassignment closes only the selected assignment and creates a new interval;
it does not impose a global single-guide constraint. Record reason, actor and
affected identities atomically with each change.

## Forward migration 010 design gate

Do not write new policy into 001–009. Add validated department/cycle/team/project
delegations for MANAGE_TEAM, ASSIGN_GUIDE and EDIT_TEAM_POLICY as distinct actions.
Coordinator/HOD role or delegation must be effective and account ACTIVE. Avoid
giving the request role unrestricted UPDATE on memberships/roles; prefer narrow
fixed-search-path SQL functions or an equivalently reviewed least-privilege design.
Support team-size guideline warnings and configurable exception behavior without
hardcoding a numeric minimum/maximum. Policy changes create versions, and their
effective scope must be explicit. Faculty cannot edit department policy merely
because they can adjust a team's membership.

## Definition of done

1. Synthetic student authenticates through the explicit demo adapter, creates or
   joins a permitted team, registers a project and sees real persisted data.
2. Authorized faculty changes a member or guide within delegated scope. Unrelated
   faculty, students editing others, disabled users, expired delegations and
   TECH_ADMIN relying only on that role are rejected.
3. Team-size guidelines are configurable; warning/exception behavior follows the
   configured policy, and routine edits need no mandatory HOD approval.
4. Review 1 roster, submitted versions, decisions and released marks remain
   unchanged after prospective membership/guide edits. Retroactive edits that
   falsify history fail. Multi-team and multi-guide positive cases remain valid.
5. Concurrent changes/idempotency do not duplicate memberships or lose audit
   events. New runtime privileges are proven narrow with negative DB tests.
6. Existing PostgreSQL suite stays green with its four documented policy skips;
   Django adapter CI passes on the PR head; another developer reviews the PR.

## Decisions needed when their feature is reached

Institutional identity provider before real login; synopsis approver/quorum before
official approval; review stages and rubrics before official evaluation; aggregation
and amendment authority before publishing actual marks; storage/malware scanning,
backups and deployment ownership before departmental hosting. None is silently
filled by a synthetic test fixture. No production deployment is in Sprint 1 scope.
