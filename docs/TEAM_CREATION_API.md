# Student team creation and eligible discovery (candidate 012)

**Status:** Implemented as a reviewable backend slice on a stacked PR. This is
not a production deployment or approved institutional team-size policy.
Depends on PR #4 (student API/011), which depends on PR #2 (010). Original
migrations 001–009 remain untouched.

## Authenticated HTTP contract

- `POST /api/v1/teams`: JSON `{"offeringId":"<UUID>","name":"Team name"}`
  and required `Idempotency-Key` (1–128 characters: letters, numbers,
  `.`, `_`, `:`, `-`; starts with alphanumeric). Responds **201** with
  `{id,name,offeringId,membershipId}`. Same actor/key/same normalized request
  returns the identical body with **200**, and never emits a second team/audit.
  Reusing a key for different input returns **409**.
- `GET /api/v1/curriculum-offerings/{offeringId}/teams?cursor=<UUID>`:
  returns `{results:[{id,name,offeringId,memberCount}],nextCursor}`.
  At most 50 teams per page, UUID-ordered. A page is current-state data;
  concurrent team/membership changes can affect subsequent pages. No USNs,
  student names or rosters are exposed.
- Responses use `Cache-Control: no-store`. Neither endpoint accepts an
  acting user/department/semester/cycle from the client. Any unknown POST
  field is rejected. Both are protected by trusted student authentication.

## Eligibility and integrity

The student's ACTIVE account, currently effective STUDENT department role
and verified student profile are required. The requested offering must match
the student's department and semester and have an explicitly published
visibility window. Creating a team additionally requires that the department
has set `student_team_creation_enabled=true`. Discovery may remain visible
while creation is disabled.

Creation inserts **team + creator's membership + audit event + completed
idempotency record in one PostgreSQL transaction**, inside a restricted
SECURITY DEFINER function. The existing 010 membership-scope trigger and
one-active-team-per-offering exclusion constraint continue to guard races.
A conflicting second team creation rolls back entirely, returning 409. The
idempotency reservation and row locks serialize matching retries; a
previously committed response remains replayable after a visibility window
closes, provided the actor is still authorized as a student.

**No student team creation without automatic creator membership.**
This does not implement joining someone else's team, team discovery opt-out,
team-size policies, faculty delegation or transfer yet. Those require a
separate policy/configuration and write-service slice; do not hardcode sizes
or incorrectly treat the creation flag as a universal joining rule.

The app role `smartpro_runtime` may call these narrowly scoped SQL
functions and **cannot directly insert teams** or read the new 010/011
student-profile/offering-window tables. Its original broad SELECT grant has
now been replaced in **synthetic test provisioning** with an audited baseline
allowlist in `proposals/security/runtime_read_boundary.sql`. That owner-run
script also revokes previously issued blanket SELECT, denies direct reads of
legacy users, team memberships, teams, grades, audit and idempotency records,
and exposes a scoped replay lookup for the older synopsis service.

This is a **specific read-privilege fix**, not proof of complete database
least privilege. The existing synopsis service retains direct SELECT on the
limited legacy tables it needs, and its existing legacy write grants are not
reworked in this slice. Production role provision, all remaining write
privileges, and direct SQL capabilities must be independently reviewed
against the deployed configuration before actual student use.

As with student 011 functions, SQL `actor_id` is a **trusted-server
capability**, not RLS or authentication: runtime DB credentials must remain
server-side, and production requires a verified principal provider.

## Installing/testing the candidate

1. Apply reviewed 010 prepare/map/activate, then 011 student reads in an
   isolated PostgreSQL 16 database.
2. As migration owner, apply `proposals/curriculum/012_team_creation.sql`.
   It rejects a missing/prepare-only prerequisite. It is NOT in automatic
   migrations or safe to apply to unknown real academic records.
3. Publish explicit `student_offering_windows` and turn on
   `student_team_creation_enabled` for permitted offerings.
4. Set `SMARTPRO_CURRICULUM_API=YES` and `SMARTPRO_TEAM_API=YES`. For
   synthetic testing ONLY, `SMARTPRO_ENV=demo` and
   `SMARTPRO_DEMO_AUTH=YES` enable `X-Demo-User: student-a`.
5. Run `python -m pytest backend/tests -q` with the isolated postgres
   test URLs from the student API CI workflow, and verify the full PR-head CI.

This feature does not select a production login, perform real-data migration,
or create admin-facing publication/formation configuration commands. It does
not imply that pilot or production readiness has been achieved.
