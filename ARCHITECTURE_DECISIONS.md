# Architecture assumptions used for validation

- Preserve the modular monolith and the unified migration-defined PostgreSQL
  model. The FastAPI package is only a replaceable contract harness; domain
  operations and persistence are separate from HTTP handlers.
- **NestJS versus Django remains undecided.** Hosting, production identity
  provider, deployment and storage provider are not selected here.
- Synthetic local identities and UUID aliases exist only in an explicitly
  enabled demo mode. A trusted authentication context is required outside
  these tests; no user-provided header constitutes production authentication.
- The synopsis test policy uses one currently assigned faculty GUIDE or
  REVIEWER with an active FACULTY department role. This preserves the
  supplied one-reviewer demonstration and is not a departmental quorum rule.
- Academic publication/correction in tests uses an explicitly authorized
  synthetic ACADEMIC_ADMIN. TECH_ADMIN alone is never grading authority.
  Departmental correction authority remains undecided.
- Publication tests use a named **single_evaluator_sum test calculation**
  only when exactly one finalized source assessment is explicitly selected.
  No institutional multi-evaluator aggregation is inferred or implemented.
  Unknown or multiple-source policies must fail closed.
- A roster freeze records memberships effective at the explicit freeze
  instant. No global ban on membership in multiple teams or on multiple
  guides is introduced. Retrospective eligibility exceptions need a separate
  approved amendment policy.
- Final submission item sets, finalized assessment identity/source scores,
  approved configuration and published releases are immutable through
  ordinary write paths. Corrections append new release versions and an
  authorization/audit reason; prior evidence remains readable.
- Database transactions serialize conflicting operations on their common
  parent rows. READ COMMITTED plus row locks and uniqueness protects the
  tested workflow; callers must handle conflicts/deadlocks. This is not a
  general serializability claim.
- Files are staged and verified outside the academic submission transaction.
  Verified bytes are never renamed as part of the DB commit; deterministic
  storage identities make failed completion safely retryable. Automatic
  stale-orphan reconciliation remains future operational work.
  The local test verifier is not malware scanning or production file storage.
- Outbox leases use ownership tokens and expiry. Database recording and
  idempotent local processing do not imply exactly-once external delivery.
- `btree_gist` exclusion applies only to overlapping history for the same
  student in the same team. Different-team membership and multiple guides
  remain permitted. Explicitly authorized retrospective exceptions are pending.
- The tested runtime login has no superuser/database/role-creation privileges;
  migration credentials are kept separate. Scoped read/write rules are in
  services and constraints; a production RLS strategy remains undecided.
- Publication correction tests are reissues of the unchanged immutable marks.
  An institutional process for amending source marks is not implemented.
