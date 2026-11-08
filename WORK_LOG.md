# SMART-PRO validation work log

## Initial audit — 3 November 2026, before implementation changes

Source: `SMARTPRO_Codex_Source (9).zip` (21 files); original extracted separately
under `work/smartpro-original`. SHA-256 inventory saved in evidence.

- Four ordered, explicitly transactional migrations: core, documents,
  evaluation, operations/guards. 36 tables, built-in UUID generation and
  PL/pgSQL; no external extensions declared. Existing scripts were never run
  on PostgreSQL according to all supplied documentation.
- SQL seed, one transaction of negative tests and smoke queries; limited
  lexical lint. Thirteen FastAPI/SQLite tests include a threaded submission
  race, but cannot establish PostgreSQL behavior.
- Seven HTTP paths: start upload, upload content, complete upload, submit,
  decide, read case, health. The API creates its own smaller SQLite schema,
  uses text demo identifiers, SQLite placeholders/BEGIN IMMEDIATE/rowid,
  and different column/table names from the PostgreSQL schema. Integration
  must use the migration model, not reproduce that second schema.
- `POSTGRES_SCHEMA_REVIEW.md` explicitly identifies submitted-item mutation,
  finalized-assessment configuration mutation, unchecked publication sources,
  freeze-time eligibility, approval authority, file verification, event
  processing, tenant access, draft-policy linkage and correction chains.
- Additional visible gaps: direct FINALIZED inserts bypass the UPDATE-only
  assessment trigger; approved scheme inserts bypass approval validation;
  generic score triggers may reject for a different reason than negative
  tests expect; release child INSERTs remain possible after publication;
  faculty role and assignment scope need separate authorization; outbox
  claims lack an owner token; file compensation excludes transaction commit
  failures. These are audit findings to reproduce with actual tests.
- No locally available Docker or PostgreSQL executable found. Inspecting
  supported portable PostgreSQL 16 binaries; no system installation/service
  changes planned. PostgreSQL execution is not yet claimed.

Retain the modular-monolith schema and temporary FastAPI harness. Backend
framework, institutional approval quorum, grading aggregation and correction
authority remain undecided. Narrow synthetic test policies will be labeled.

## Execution and corrections

- Original four migrations and seed: PostgreSQL 16.15 success. Original SQL
  constraint block fails at scoring-scope test because finalized-state guard
  fires first. Scope validation now precedes state validation; legacy draft
  tests use a separate open review and a properly assigned synthetic faculty.
- Three baseline probes actually changed submitted items, finalized timestamps
  and directly inserted approved schemes. Added immutable/sealing/approval
  guards address those demonstrated gaps.
- Original 13 SQLite tests passed after enabling loopback networking; an
  initial sandboxed run stalled in asyncio's internal socketpair and was
  interrupted. This was environment behavior, not a passing test.
- First PostgreSQL API run failed on authorization row-lock permissions.
  A fixed-search-path, narrow security-definer lookup avoids granting the
  synopsis role membership/role-edit rights. The retained 13 tests then passed.
- One added historical-membership test initially expected rejection of a
  departure **after** the freeze instant. That is valid history, so the test
  was corrected to attempt a departure before the freeze; no arbitrary
  restriction on legitimate later departures was introduced.
- Runtime tests use an actual non-superuser login distinct from the migration
  owner. Random local credentials are confined to `work/`, not deliverables.
- Additional probes reproduced premature review finalization, same-team
  overlapping membership intervals, and mutation of a submitter's membership
  history outside review rosters. Migration 009 closes these gaps without
  banning simultaneous membership in different teams or multiple guides.
- The populated upgrade test found SQLSTATE 55006 in migration 009: deferred
  attempt checks were pending before ALTER TABLE ENABLE TRIGGER. Explicitly
  validating the queued constraint before that DDL resolves it; the untouched
  v1.5 seed upgrades without changing historical source scores or identities.
