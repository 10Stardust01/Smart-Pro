# Student profile and curriculum reads

Dependent on PR #2's reviewed curriculum schema. No automatic production upgrade
or production identity provider is introduced. Migrations 001–009 stay unchanged.

## HTTP contract

Authenticated GET `/api/v1/me/profile` returns `id`, `name`, `usn`, `section`,
`semester` and `department: {id, code, name}` for the trusted principal only.
GET `/api/v1/me/curriculum-offerings` returns `{results, nextCursor}`. Each result
contains `id`, `code`, `label`, `semester`, `cycle: {id, code}` and
`studentTeamCreationEnabled`. That flag describes configuration, not permission
to write teams. Requests cannot choose an acting user, department, semester or
cycle. Only `cursor` affects listing; it is a UUID lower bound, never a scope grant.
Pages contain at most 50 results in UUID order. Use the returned `nextCursor` as
`?cursor=...`; null means no more results. Pages reflect current eligibility and
publication state, so concurrent catalogue edits can change subsequent pages.

Both routes require an ACTIVE account, a student profile and a currently effective
STUDENT role in that profile's department. Offerings must match the current
department and semester and have an explicitly configured visibility window.
Visibility is half-open: `[visible_from, visible_until)`. Cycle dates do not
implicitly authorize a cycle. An administrator may intentionally publish early
registration for a future cycle; a client cannot request it into visibility.
No windows means an empty list. Responses use `Cache-Control: no-store`.

401: authentication missing/disabled; 403: no eligible student profile/role;
400: malformed cursor; 405: unsupported method; 503: rollout disabled or database
unavailable. Database failure responses contain no SQL, credentials or raw errors.

## Explicit staged rollout

1. Follow PR #2's stopped-writer, verified legacy mapping/preflight/activation
   procedure in an isolated database first. Never run on real records without
   approved backup, upgrade and recovery verification.
2. As migration owner, apply `proposals/curriculum/011_student_reads.sql` after
   successful 010 activation. It rejects the nullable prepare state and creates
   empty visibility configuration. It remains outside automatic migrations.
3. Provision reviewed `student_offering_windows` rows as migration owner for the
   approved offerings and dates. Runtime cannot read or mutate that configuration
   directly. Staff publication commands and their audit trail are a later slice;
   no end-user configuration path is claimed here.
4. Enable `SMARTPRO_CURRICULUM_API=YES` only after installing these capabilities.
   For synthetic development also set `SMARTPRO_ENV=demo` and
   `SMARTPRO_DEMO_AUTH=YES`; use `X-Demo-User: student-a` from the existing fixture.
   Production continues to fail closed until a trusted provider is implemented.

SQL SECURITY DEFINER functions expose only scoped reads to smartpro_runtime;
PUBLIC execution is revoked and search paths are fixed. Their UUID argument is
a trusted-server capability, not authentication or RLS. Database credentials must
never reach clients. Existing baseline runtime grants are unchanged; new profile,
offering and window tables remain inaccessible directly. No teams, memberships,
reviews, grades or history are written by these reads.

Run `python -m pytest backend/tests -q` with the same explicit isolated PostgreSQL
16 environment as the curriculum workflow and dependencies from
`backend/requirements.txt`. Tests use the activated synthetic upgrade, real HTTP
authentication and the restricted application login. The dedicated Student
curriculum API workflow runs these tests alongside all existing workflows.
