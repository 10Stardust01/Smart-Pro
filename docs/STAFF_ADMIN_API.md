# Departmental staff administration — candidate 015

Stacked on PR #9, after reviewed 010–014 and the runtime security boundaries.
No main merge, deployment, real-data upgrade or institutional ratification is
implied. Earlier migrations/candidates and academic result records are unchanged.

## Explicit authority and rollout

`staff_department_controls` starts disabled; title corrections also default false.
Owner provisioning must explicitly enable the department after approved testing.
An ACTIVE user needs a current `staff_permission_assignments` row tied by composite
FK to an exact effective `department_role_assignments` record for that same user,
department and required role. There are no seeded grants or role-based defaults.
Replacing a role record does not revive old grants. Ordinary faculty, project
guides, students, ACADEMIC_ADMIN and TECH_ADMIN have no implicit staff powers.

| Permission | Eligible explicitly assigned role / scope |
| --- | --- |
| READ_POLICIES | HOD, COORDINATOR or FACULTY; department scope |
| MANAGE_OFFERINGS | HOD or COORDINATOR; department scope |
| MANAGE_TEAM_POLICY | HOD or COORDINATOR; department scope |
| MANAGE_REGISTRATION_POLICY | HOD or COORDINATOR; department scope |
| READ_PROJECTS, CORRECT_PROJECT | HOD, COORDINATOR or FACULTY; department or explicit project scope |

Assignments have effective dates, a required provisioning reason and optional
granting-user reference. Owner changes to controls/grants/associated role dates
append configuration audit events with old/new state and database principal.
This is bootstrap evidence, not a claim that a database principal authenticates
a human academic authority. Assignment/approval rules remain owner-configured,
disabled until ratified; this slice cannot grant, approve or delegate authority
through HTTP. Faculty cannot be assigned departmental policy-write permissions.

Identity/scope are immutable on grants. End them prospectively or set `revoked=true`
(also cancels future assignments); reopening requires a new row. Grant/role dates
cannot invalidate recorded commands, and department revisions cannot be reset.
Authenticated commands record the actual staff actor, permission/role grant,
effective scope/time, reason and old/new state. No client-supplied actor or role
is accepted. SQL actor UUIDs remain trusted-server capabilities, not RLS.

Install owner-run `015_staff_administration.sql` in an isolated reviewed upgrade
after 014. Configure approved controls/grants, then enable `SMARTPRO_STAFF_API=YES`.
The student rollout gates are independent. Demo authentication still requires
both explicit existing switches; production identity remains unconfigured.

## HTTP contract

All paths start `/api/v1/staff/departments/{departmentId}`:

| Method/path | Purpose |
| --- | --- |
| GET `/policies?cursor=<UUID>` | Up to 50 existing offerings, publication/team/registration state, department revision |
| GET `/projects?cursor=<UUID>` | Up to 50 authorized projects, row versions and academic-activity indicator |
| POST `/offerings/{offeringId}/publication` | Replace visibility window and team-creation flag |
| POST `/offerings/{offeringId}/team-policy` | Create/bind a new immutable team-policy version |
| POST `/offerings/{offeringId}/registration-policy` | Create/bind a window for an existing approved registration policy, or disable it |
| POST `/projects/{projectId}/title` | Explicitly delegated, optimistic-versioned correction of initial metadata only |

GET pages return `{departmentId,results,nextCursor}`; policy reads also return
`revision`. UUID order is stable for a snapshot; concurrent changes can affect
later pages. Project-scoped READ_PROJECTS assignments filter the query before
serialization; they never expose the departmental directory. No rosters or USNs
are returned. Policy state includes scheduled windows, visibility, policy version
IDs, MINI/MAJOR registration classes, parent approval state and registration status.

POSTs require `Idempotency-Key` with the established 1–128 character format and
exactly the documented fields. Every body requires a trimmed, nonblank `reason`
up to 500 characters. Policy bodies require `expectedRevision` from GET `/policies`.
They replace configuration atomically; stale revisions return 409 rather than
silently overwriting another operator. Title bodies use `expectedProjectVersion`.

| Command | Additional required body fields |
| --- | --- |
| publication | `visibleFrom`, `visibleUntil`, `teamCreationEnabled` |
| team-policy | `allowJoin`, `allowLeave`, `allowTransfer`, `minimumMembers`, `maximumMembers`, `sizeMode` |
| registration-policy | `projectType`, `policyVersionId`, `opensAt`, `closesAt` |
| title | `expectedProjectVersion`, `title` (1–500 characters); no department revision |

Timestamps require explicit ISO timezones and normalize to UTC. Publication times
are both null to unpublish, or an ordered `[from,until)` window. Size bounds may
be null; minimum cannot exceed maximum; sizeMode is ADVISORY or ENFORCED. The
creation flag is separate from join/leave/transfer permissions. Registration is
MINI/MAJOR independently of curriculum type; parent policies must already be
APPROVED with the supported studentRegistration rule from 014. Set policyVersionId,
opensAt and closesAt all null to disable a class binding. Staff cannot invent or
approve additional academic rules through these routes.

Successful commands return 200 `{departmentId,action,targetId,revision,state}`.
Matching actor/key/target/canonical-body retries return the original result without
extra versions/audits. Changed input with the same key returns 409. Current authority
and enablement are checked even for replay. The result is the command's snapshot;
GET again for current configuration. Responses are `no-store`.
400: invalid fields/times/key; 401: missing/disabled authentication; 403: scope,
authority or disabled department/correction; 409: stale/conflicting/protected state
or retry exhaustion; 503: disabled HTTP rollout or database/commit failure; 405:
unsupported method. Database messages and SQL are sanitized.

## Corrections, concurrency and history

Only project title is correctable, and only when explicitly enabled/delegated
before documents, submission cases, reviews, assignments or milestones exist.
Academic-activity latching also prevents deleting a draft from reopening editing.
Code, team, cycle, classification, policies, membership history, submissions,
reviewed/finalized assessments and published results cannot be changed here.
Initial registration receipts remain immutable; student reads show current title,
while retries preserve the original registration response.

Commands lock actor, exact authority grant/role, department controls, then offering
or project resources. Highest authority locks are taken first, expiry is rechecked
after waits, and real grant/role revision writes invalidate stale history snapshots.
Policy changes use a department CAS revision. Project corrections use row_version;
academic activity stamps a separate project revision to reject stale snapshots.
Existing student locks and constraints continue to apply. No guide allocation,
review scoring, AI or retrospective academic-amendment workflow is introduced.

Mutation, immutable private receipt and authenticated audit commit together.
Neither shared legacy idempotency rows nor raw client authority are trusted. Whole
40001/40P01 transactions retry at most three times with rollback/reauthorization;
outer transaction savepoints are not blindly retried. Runtime receives only three
scoped entry functions, no new direct table DML or private authority/receipt reads.
Legacy shared-runtime and synopsis privilege risks still require production review.
