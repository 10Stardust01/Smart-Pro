# Student project proposals — current candidates 022/027 contract

An upgraded application accepts the following authenticated request:

```json
{"offeringId":"<UUID>","teamId":"<UUID>","title":"Project title","description":"Proposed work and outcomes"}
```

Description is immutable initial evidence, up to 10,000 characters. The current UI
requires it; existing three-field clients remain compatible. Changed-description
retries return 409 and never rewrite prior evidence.

The backend derives the eligible department/semester/cycle, approved applicable
MINI/MAJOR class and current membership. It generates an opaque `P-` plus SHA-256
reference from the authenticated actor and private retry key; this is a technical
unique reference, not an invented institutional numbering policy. Student-supplied
codes/classes are rejected. Multiple projects and shared titles remain permitted.

`GET /api/v1/curriculum-offerings/{id}/proposal` returns class and explicit
synopsis requirement/window capabilities. Unconfigured or closed proposals fail
closed; an approved no-document disposition is explicit. Both department workflow
controls and project/curriculum API gates are required. Successful retries return
the same record, reauthorize scope and do not create extra academic evidence.

The UI connects title/description/team/PDF review and confirmation to the existing private
upload and case-submission APIs with stable retry keys. This is a recoverable
staged operation: a failed file/submission step retains a draft; it does not claim
atomic success across database and filesystem. Exact role, forward SQL, results
and remaining boundaries are in [application corrections](APPLICATION_CORRECTIONS.md).

## Historical candidate 014 / pre-022 schema contract

The remainder describes the preserved underlying registration service and old
schema compatibility. It is not the student input contract of the upgraded app.


Depends on the reviewed #2 -> #4 -> #5 -> #6 -> #7 -> #8 stack. Candidate SQL
remains owner-run and outside automatic migrations; 001–013 are unchanged.

## API contract

POST `/api/v1/projects` accepts exactly:

```json
{"teamId":"<UUID>","projectType":"MAJOR","projectCode":"CSE-EXAMPLE","title":"Project title","description":"Proposed work and outcomes"}
```

`projectType` is MINI or MAJOR, independent of curriculum type. Code and title are
trimmed, nonblank, limited operationally to 120/500 characters. The code is required
by the existing project contract and retains the existing case-sensitive,
department-wide uniqueness constraint. Titles need not be unique. There is no
team leader, guide approval or project-count limit. Multiple projects can share
a team and offering, including concurrent registrations with distinct codes.

Trusted authentication and `Idempotency-Key` (the established 1–128 character
format) are required. Identity, department, semester, cycle and policy IDs are
derived from backend records; clients cannot supply them. Success returns 201;
the same actor/key and normalized input returns the identical body with 200.
Changed input with the same key or an existing department project code returns 409.

GET `/api/v1/me/projects?cursor=<UUID>` returns `{results,nextCursor}`, at most
50 projects ordered by UUID, for the student's currently eligible teams only.
It works after registration closes or a policy retires. Legacy projects retain
their existing policy and have a null `registrationPolicyVersionId`; no historical
policy/window is fabricated. Loss of current membership removes read/replay
authority. Current teammates can see team projects, including ones another member
registered. No roster, USN or original registrant identity is exposed.

Both responses include `id`, `teamId`, `offeringId`, `cycleId`, `projectType`,
`projectCode`, `title`, `policyVersionId`, `registrationPolicyVersionId`, `createdAt`.
Successful responses are `Cache-Control: no-store`. Pages reflect current scope.
400: invalid fields/cursor/key; 401: missing/disabled authentication; 403: invalid
current membership/scope or unavailable policy/window; 409: conflict/retry
exhaustion; 503: rollout/database/commit failure; 405: unsupported method.

## Approved policy and rollout

Reuse existing `project_policy_versions`: a currently APPROVED row must explicitly
contain `policy_data.studentRegistration = {"enabled":true}`. Other academic-policy
keys are unaffected. Extra keys within `studentRegistration` (for example a
project-count rule) are unsupported and fail closed, never silently ignored.
If institutional registration rules are unknown or require additional checks,
leave registration unbound until those rules have been approved and implemented.

Owner provisioning creates immutable `project_registration_policy_versions` with
the exact offering, department, cycle, MINI/MAJOR class, approved academic policy,
version number and `[opens_at,closes_at)` window. An explicitly selected
`offering_project_registration_policies` binding activates one version per
offering/class. Composite FKs prevent mismatched department/cycle/class/policy.
Publishing/replacing/removing a binding appends an old/new configuration audit
event with the database provisioning principal. Staff publication commands and
human authority attribution remain a separate feature.

The registration window is separate from team-formation visibility and membership
policy windows: existing teams may register projects after team creation closes.
Cycle dates never implicitly grant registration. A future cycle requires its own
explicitly approved offering binding and an open registration window. Retiring
the academic policy blocks new registrations. Historical policies/windows and
receipts remain unchanged; still-authorized committed retries remain replayable.

Apply 014 only after the reviewed synthetic 010–013 upgrade and runtime boundaries.
Default configuration is empty and closed. Set `SMARTPRO_CURRICULUM_API=YES` and
`SMARTPRO_PROJECT_API=YES` only after staged verification. The team/membership HTTP
gates are independent. Production login remains disabled pending a verified
provider; demo authentication still needs both existing explicit switches.

## Security, transactions and integration risks

The command locks/writes the student profile revision, then locks account/role,
offering, policy binding/version, team and current membership. This matches #8's
profile-before-team hierarchy. Team SHARE locks conflict with membership revision
writes; original membership evidence is locked and time bounds are rechecked
after waiting. Stale REPEATABLE READ snapshots abort. Different current members
may register different projects concurrently; existing department code uniqueness
arbitrates conflicting codes. Django retries whole 40001/40P01 transactions at
most three times with rollback and reauthorization, never a stale savepoint.

The SQL command independently matches the receipt's original team and canonical
input values; a supplied digest cannot authorize replay through a different team.

Project + private immutable receipt + audit commit together. Receipts use a new
restricted table because the legacy shared idempotency table is directly writable
by the synopsis runtime; registration must not trust forged legacy replay rows.
No new runtime table DML or direct receipt/policy reads are granted. Composite
receipt FKs pin the original team, cycle, academic/window policy and membership.
A new history guard prevents backdating membership endings across a registration.
Existing submissions, frozen review rosters and finalized results are untouched.

Definer functions have fixed trusted search paths, qualified tables and revoked
PUBLIC execution. Actor UUIDs remain trusted-server capabilities, not RLS. Existing
legacy synopsis read/write risks are unchanged and still block production use.
Real-data upgrade/recovery, production grants/authentication, policy ratification
and deployment hardening remain separate gates. Tests run real HTTP/restricted
PostgreSQL transactions, including both membership-race orders, expiry during a
lock wait, deferred commit failure and the integrated create/transfer/register flow.
