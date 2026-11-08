# SMART-PRO database validation and integration report

**Executive verdict: CONDITIONAL PASS — ready for the next controlled engineering milestone, not departmental deployment.**

Validation date: **3 November 2026**. Actual server: **PostgreSQL 16.15, compiled by Visual C++ build 1944, 64-bit** on Windows, bound to **127.0.0.1:55439**, with a workspace-only cluster and SCRAM credentials. Docker was unavailable; no system service was installed. Python **3.12.14**, psycopg **3.3.7**, FastAPI **0.162.0**, pytest **9.2.0**. Dependency installation and `pip check` succeeded; exact versions and artifact metadata are saved.

## Initial repository findings

Inspected all **21 files** in the supplied ZIP before implementation, including all four migrations, seeds, constraint/smoke SQL, lexical lint, both READMEs, compose/CI, all API code/tests, OpenAPI, prior result files and `POSTGRES_SCHEMA_REVIEW.md`. The original has **36 tables**, four transactional but previously unexecuted migrations, and a separate smaller SQLite schema in the HTTP harness. Documentation accurately disclosed that only SQLite/static checks had run. The supplied nested GitHub workflow would not be discovered at the package root.

Real baseline execution established:

- All **four original migrations and seed** executed successfully on PostgreSQL 16.15. There was no original migration syntax failure.
- The original SQL constraint block **failed**: a finalized-assessment guard raised SQLSTATE **23514** before the test's expected scoring-scope foreign-key error. Further SQL probes actually deleted a submitted item, changed a finalized assessment timestamp, and inserted an already-approved scheme without approval validation. Those probes rolled back.
- The original **13 SQLite workflow tests passed** in this runtime. A preliminary sandboxed invocation stalled in asyncio's loopback socketpair and was interrupted; it is not counted as a passing execution. The successful baseline used authorized local networking.
- The review's other issues were confirmed in implementation: insertable release children after publication, mutable scoring configuration, insufficient frozen-time membership checks, missing source-result verification, draft policy linkage, and no usable worker ownership protocol.

## Significant corrections

**Migrations 001–004 remain byte-for-byte unchanged**; SHA-256 comparisons are in `evidence/change-inventory.json`. Five executable forward migrations preserve the approved model:

| Migration | Correction and reason |
|---|---|
| 005 | Immutable attempt identity and sealed, nonempty item sets; exact ready-file checks; immutable finalized assessment identity; approved-scheme insert bypass blocked; finite score/maximum checks; explicit faculty scope and freeze-time eligibility. Scope errors are validated before finalized-state locks. |
| 006 | Explicit department-scoped academic grants; complete frozen-roster result releases; finalized exact-review sources and reproducible totals/breakdowns; append-only release/source/score sets; sequential correction chains with reasons; publication audit/outbox recording. |
| 007 | Upload sessions in the migration schema; verified version/asset matching; outbox claim tokens, expiries, stale-owner fencing, retries, backoff and dead-letter transitions. |
| 008 | Narrow fixed-search-path authorization lookup/row locks; preserves a restricted runtime role without granting membership or role edits. |
| 009 | `btree_gist` overlap exclusion for the **same user in the same team**; submitter membership snapshots; premature review finalization and historical definition/document changes blocked. Multiple teams and multiple guides remain permitted and positively tested. |

`btree_gist` is the one added extension requirement. Cross-table rules use composite foreign keys/uniqueness where possible and transactional guards where necessary; no cross-table subquery was placed in an ordinary CHECK.

The FastAPI adapter now delegates to framework-independent PostgreSQL domain operations and uses the migration tables. SQLite DDL, placeholders, locking and `rowid` assumptions were removed. All seven HTTP paths and the intended revision workflow remain. Demo aliases stay opt-in at the boundary; stored/returned identities are real UUIDs, so the old literal demo `caseId` is now its UUID. Error responses share a documented `detail.code`/`detail.message` envelope, including validation errors. OpenAPI is regenerated from the delivered adapter.

Uploads use deterministic stable object identities, bounded input and a **test-only** size/PDF-signature verifier. Completion verifies before the short persistence transaction; bytes are not renamed as part of its commit. A real deferred-trigger COMMIT failure rolls back file/version/audit rows, retains the upload's bytes and UPLOADED state, and permits a successful retry. Missing/changed verified objects are rejected at submission. This is not a malware scanner, production storage protocol or automatic orphan reconciler.

## What actually ran

The final **acceptance** command destroyed and recreated only `smartpro_validation`, applied **all 9 migrations**, loaded synthetic seed data, ran the retained SQL contracts, executed the full suite, ran Ruff and SQL lexical checks, then restored a clean seeded schema and recorded its catalog inventory: **38 tables**.

| Suite | Passed | Skipped | Failed/errors |
|---|---:|---:|---:|
| test_database | 61 | 4 | 0 |
| test_additional | 17 | 0 | 0 |
| test_workflow | 13 | 0 | 0 |
| **Total** | **91** | **4** | **0** |

**95 collected tests** include all 13 original API cases, 17 added API cases, and 65 database cases. Separately, the retained SQL block emitted **18 PASS notices**, and smoke queries succeeded. These SQL assertions are not double-counted as pytest cases. Final pytest wall time was approximately **92.2 seconds**. All recorded acceptance stage exit codes are **0**. Ruff's selected Pyflakes/syntax checks, Python AST parsing, SQL lexical consistency and dependency checks passed; lexical checks are not presented as server execution.

Positive/negative coverage includes all three marking modes; correct synthetic totals **86 and 82**; cross-project/cycle/department/review rejection; duplicate version rejection; pending upload rejection; frozen references and memberships; unauthorized faculty/technical-admin rejection; invalid marking scopes; missing, negative, NaN and over-maximum marks; finalized sources/configuration; result source totals; correction reissues; atomic audit/outbox/idempotency; and runtime privilege separation.

**Ten concurrency scenarios** use real overlapping transactions or parallel HTTP requests: submission contention; same-key identical and different-payload retries; same- and distinct-faculty conflicting decisions; same-upload completion; parallel document version allocation; score update versus finalization; rubric child insertion versus approval; and worker claim contention. Direct database races record distinct `pg_backend_pid()` values in `acceptance-pytest.log`.

Under **READ COMMITTED**, parent row locks serialize case operations/version checks, document version numbering, score finalization and scheme approval. Worker claims use `FOR UPDATE SKIP LOCKED`; ownership tokens plus lease expiry prevent stale acknowledgements. Unique/composite constraints provide additional rejection guarantees. This establishes the tested interleavings, not general serializability or exhaustive race freedom; callers must handle conflict/deadlock errors and retry appropriately.

## Real failures and their resolutions

- **Original SQL test failed** as described above. Scope checks were corrected; draft scoring fixtures now use an open review and a faculty-role holder, rather than creating new assessments on a published review. No negative assertion was deleted or changed to accept corruption.
- **Initial integrated API run: 13 failures, SQLSTATE 42501.** PostgreSQL requires update privileges for row locking. A narrowly scoped security-definer lookup with fixed safe search path resolved this without granting identity/membership writes. Final API runs use an actual non-superuser login distinct from the migration owner.
- **One new test expectation was wrong:** a membership departure just after freeze is valid history. The test now attempts a pre-freeze departure; legitimate later departures remain allowed.
- **An added auth-order test failed (404 versus 401).** Authentication now precedes demo identifier resolution. Validation errors were also normalized and independently tested.
- **Three edge probes failed** before migration 009: overlapping same-team membership, submitter-history mutation and premature review finalization. All pass after remediation.
- **Populated forward upgrade failed with SQLSTATE 55006:** PostgreSQL refused ALTER TABLE while deferred attempt events were pending. Migration 009 now drains/validates that constraint queue before reenabling its trigger. The corrected upgrade passed, followed by the final clean-room rerun. The original failure log is preserved.
- One non-failing dependency warning remains: this Starlette version deprecates the httpx-based TestClient in favor of httpx2. The locked tested stack works; future dependency updates need regression testing.

## Upgrade verification and historical evidence

`scripts/test_upgrade.py` creates a **separate** `smartpro_test_upgrade` database, executes the untouched four migrations and seed from `SMARTPRO.original.zip`, then applies 005–009. It succeeded and compared documents, finalized assessments, decisions, releases and student results before/after: existing selected values were unchanged. Historical attempts acquire seals and matching membership references; a deletion probe is rejected.

This is a real forward-upgrade test **only for the supplied synthetic v1.5 state**, not an arbitrary production migration certification. Existing invalid READY assets, overlapping periods or incompatible claimed outbox rows can fail rather than be silently repaired. Legacy release grant IDs remain null: new authority records were deliberately not fabricated for historical decisions. Data preflight and approved operator remediation remain necessary for other installations.

## Security, audit and reliability limits

The synopsis runtime login cannot create databases/roles, mutate academic grants, edit memberships/roles, or truncate evidence. All external values are bound parameters; table/identifier choices are controlled. Tests cover direct-object scope checks, revoked membership/reviewer access and injection-shaped comments. Authorization locks protect the checked role/membership records during the transaction. Evidence tables reject ordinary mutation; privileged schema owners/superusers can still bypass database guards via DDL, so this is not tamper-proof external audit storage.

Audit/outbox records commit with academic operations. Claims, lease reclaim, stale-token rejection, retries, dead-letter handling and local receipt deduplication were executed. **No external notifications were sent** and no exactly-once external delivery is claimed. Retrying a provider-side effect after a crash still needs provider idempotency/reconciliation. Automatic file-orphan cleanup, operational retry scheduling and production monitoring remain future work.

Remaining priorities:

1. **Before real-user deployment:** choose/configure trusted production authentication, faculty-approved authorization policy, secure file validation/storage, operational backups/restore and audit controls. Demo headers are explicitly insecure and disabled unless opted in. A production grading API/service account is not implemented.
2. **Faculty-policy blockers (4 explicit skips):** approval quorum/authority; multi-evaluator aggregation; source-mark amendment/correction authority; retrospective membership/attendance exceptions. Assigned-but-unstarted evaluator completion rules also need policy. Technical administration alone grants no academic authority.
3. **Publication scope:** the named `single_evaluator_sum` policy is labeled `exampleOnly=true` and requires one finalized source. Unknown/multiple finalized-source methods are rejected. The authorized correction test appends a reasoned release **with unchanged immutable source marks**; it is not an implementation of institutional mark amendment.
4. **Operational/tenant limits:** service-layer project scoping is tested; RLS, a complete role-management/audit service, production privacy review, performance/load tests, backup/restore drills, crash testing and deployment infrastructure are not validated. The trusted application DB account can read the schema; end users must never receive SQL credentials.

**Not executed:** GitHub-hosted CI, Docker Compose, Linux runtime, the optional Bash wrapper, real SSO/scanning/object storage, external delivery, institutional multi-evaluator calculations and production recovery/performance tests. CI is **configured but unverified**; the tested setup was native Windows PostgreSQL. The portable setup helper's status path was checked; initial server bootstrap used the recorded equivalent native initdb/pg_ctl commands.

## Deliverables and reproduction

The corrected source package contains ordered migrations, PostgreSQL tests, integrated domain/HTTP harness, synthetic fixtures, outbox/publication test services, locked dependencies, Docker configuration, the root CI workflow, updated OpenAPI, this report, architecture decisions and evidence. Exact changed/new file inventory is in `evidence/change-inventory.json`; original source ZIP/hashes and intermediate failures remain available. Local random credentials, Python environments and PostgreSQL data/binaries are excluded from the deliverable archive.

From the extracted package root, after loading the explicit test environment described in `README.md`:

```powershell
python -m pip install -r requirements-lock.txt
python validate.py --recreate --label local
python scripts/test_upgrade.py
python db_setup.py --seed api_seed.sql --create-test-login
python workflow-poc/app.py
```

`README.md` provides full PowerShell/Bash environment commands and Docker/native server startup. Never use the reset runner against real records. The temporary server is stopped after evidence capture; databases are retained locally for inspection/restart.

**Next milestone:** faculty-policy decisions and a narrowly scoped production-identity/file-verification integration, followed by the grading/publication slice once its aggregation/amendment policy is approved. Keep NestJS versus Django undecided until that separate framework review. This work establishes an executed prototype foundation, not production readiness.
