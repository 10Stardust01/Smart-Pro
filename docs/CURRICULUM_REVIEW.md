# PR #2 technical review — 4 November 2026

## Scope and decision

Reviewed the current repository at ab06105e2c09f97c38f1dde289ecae3e0c64b2bc:
candidate prepare/activate/preflight SQL, curriculum tests, baseline migrations
001–009, runtime grants, synopsis services and the Django identity adapter.

The proposal can be considered for merge as an inert, staged schema contract
after the corrected-head checks pass. It is not ready to activate in a deployed
application. The scripts remain outside the automatic migration directory.
No baseline migration, existing fixture or main branch is changed by these fixes.

## Verified defects fixed

1. **High: profile scope changes left incompatible memberships active.**
   Both department and semester could change while an unended membership still
   belonged to the original offering. The former history test actually used an
   active membership. The profile guard now requires incompatible unended or
   future-ending intervals to be ended first. Ended history and frozen evidence
   remain unchanged. A future joined_at is also protected, preventing scheduled
   enrollment from becoming incompatible.
2. **High: UPDATE bypassed the INSERT-only eligibility guard.**
   After ending a membership and changing semester, setting left_at back to NULL
   revived out-of-scope enrollment. Extensions/reopenings now recheck scope.
   Shortening/closing an interval remains available for authorized transitions,
   subject to the existing historical-evidence guards.
3. **High: legacy activation accepted incompatible current memberships.**
   Preflight and activation now reject incompatible unended/future intervals,
   while allowing ended history to differ from the current profile. Activation
   failure rolls back all classification/constraint changes in its transaction.
4. **Concurrency requirement addressed in the fix.**
   A profile lock alone would not make an older REPEATABLE READ snapshot see a
   committed membership insert. Admissions/extensions write a private profile
   revision token. A concurrent profile edit therefore either sees the admission
   under READ COMMITTED or fails with 40001 under stronger isolation. The caller
   must retry the entire transaction, then reauthorize. Both write orderings,
   stale snapshots and live row-lock contention are regression-tested.

The four original-behavior probes (department, semester, reopening, legacy
activation) all failed against the original SQL before applying the fix.

## Integrity and migration assessment

- Prepare makes email optional without removing supplied-email validation or
  uniqueness. UUID identity is stable; canonical USN uniqueness is structural
  identity integrity, not authentication or proof of ownership.
- The nullable prepare state is explicitly unsupported for application writers.
  Writers must remain stopped throughout prepare, reviewed mapping, preflight
  and activation. This is an operational precondition, not a database-enforced
  maintenance switch. Use a verified backup before starting.
- Every historical team requires an explicit offering mapping; every historical
  member requires a verified profile. Do not infer curriculum from project titles
  or assign arbitrary USNs. If one legacy team actually represents multiple
  curricula, a reviewed migration plan is needed; one offering ID cannot encode
  that mixed history correctly.
- Composite foreign keys enforce team department/cycle/offering agreement and
  membership/team/offering agreement. NOT NULL activation prevents nullable
  composite-FK bypass. Immutable identity triggers prevent reparenting.
- The GiST exclusion covers all intervals per student/offering, including
  backdating and concurrent competing joins. Adjacent intervals are permitted.
  Existing roster/submitter history triggers remain enabled. Frozen evidence is
  checked before/after activation and transfers.
- Activation holds exclusive locks on the affected tables and is transactional.
  Preflight is diagnostic; it is not a substitute for activation constraints or
  stopping all writers. Failure leaves the prepared/mapped state for diagnosis.
- New trigger functions use fixed search paths, schema-qualified table reads and
  revoked PUBLIC execution. No runtime table privileges or callable write API
  are added. The revision write is internal to the admission trigger.
- Batch commands should lock students in deterministic UUID order and retry
  40001/40P01. The constraints protect integrity even when a transaction aborts;
  deadlock avoidance and error-to-HTTP mapping belong to the future service.

## Visibility, identity and cycle boundaries

The visible_offerings test helper is an owner-executed SQL example filtering by
profile department, semester and a supplied cycle. It is not a deployed endpoint,
RLS policy, trusted-principal resolver or proof that cycle choice is authorized.
An owner can query the entire catalogue; staff and migration access must not be
mistaken for the student-facing visibility policy. Runtime has no SELECT on the
new profiles/offerings and no team/membership write grant; denial is tested.

Existing shared runtime credentials are a service capability, not per-student DB
identity. Baseline SELECT grants and actor-parameter permission helpers rely on a
trusted server. Do not expose that connection to students or claim RLS isolation.
USN/request-body user IDs must never select the acting principal. Django's current
identity adapter is synthetic demo-only and fails closed outside that mode.

The database scope guard proves department/semester compatibility. It deliberately
does not select an authorized cycle, require ACTIVE/effective student roles, enforce
registration windows, or interpret the formation flag as permission. The schema
allows distinct same-department cycles, including future cycles. Cycle dates alone
do not identify one authorized registration cycle when cycles overlap or future
registration opens early. These checks need an explicit server policy shared by
listing and joining, derived from the trusted principal and institutional cycle
configuration. Direct-ID joins must use that same policy.

These are rollout blockers, not newly introduced public endpoint vulnerabilities:
the proposal exposes no student offering/join endpoint and grants no runtime access.
Before activation, implement and test authenticated listing/self-join, account and
department-role eligibility, authorized cycle/window/formation policy, scoped staff
delegation, atomic audit/idempotency and error handling. Also test the real deployed
upgrade/fixture path and compatibility with the activated schema; current baseline
Django/PostgreSQL CI still validates 001–009, not a finished 010 application upgrade.

## Future cross-department support

Keep default eligibility limited to the student's own department and semester.
The offering/type/team separation remains extensible. A future change must define
explicit auditable eligibility grants and update both visibility and admission
policy plus these profile-transition guards. Do not remove the guard or expose a
global catalogue as an extensibility shortcut. The current migration grants no
cross-department eligibility.

## Validation

Updated-head CI and local test results are reported in PR #2's description.
The regression suite includes the original contracts plus scope transitions,
legacy mismatch detection, ended-history preservation, stale snapshots at all
three supported isolation levels, live contention in both orderings and runtime
access denial. Baseline migrations 001–009 are unchanged.
