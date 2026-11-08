# PostgreSQL schema: original v1.5 plus tested forward hardening

The first four migrations are preserved byte-for-byte from the supplied ZIP.
Five subsequent migrations harden their integrity without replacing the
approved domain model:

1. `001_core.sql` — identity, academic context, policies, teams and projects.
2. `002_documents.sql` — files, versions, cases, attempts and decisions.
3. `003_evaluation.sql` — schemes/modes, frozen rosters, marks and releases.
4. `004_operations_and_guards.sql` — audit/outbox/idempotency and initial guards.
5. `005_integrity_hardening.sql` — submission seals, scoring/configuration
   immutability, faculty scope, freeze-time eligibility and finite scores.
6. `006_publication_contract.sql` — explicit academic grants, complete,
   reproducible test-policy releases and append-only correction chains.
7. `007_upload_and_delivery.sql` — upload persistence and outbox claim tokens,
   acknowledgements, retry backoff and dead-letter transition.
8. `008_runtime_authorization.sql` — restricted, fixed-search-path authority
   lookup without granting identity/membership edits to the API role.
9. `009_temporal_and_review_history.sql` — `btree_gist`, same-student/same-team
   overlap exclusion, submitter snapshots and historical review/document guards.

PostgreSQL **16** is the validated target. `btree_gist` must be installed by a
migration-capable owner; it is part of standard PostgreSQL distributions.
Do not run academic HTTP requests using the migration owner credentials.

Follow [the root setup](../README.md). The authoritative full runner is
`python validate.py --recreate`, from the package root with explicit test
environment variables. It recreates only named isolated test databases,
applies all migrations, seeds, runs the retained SQL contracts, tests the
API/concurrency behavior and runs static checks. `run-tests.sh` is an optional
SQL-only runner for an empty database and requires Bash plus `psql`.

Both clean creation and a forward upgrade from the **provided synthetic v1.5
schema/seed** were executed. See `../evidence/upgrade-summary.json`. Existing
unverified READY assets, overlapping memberships or inconsistent historical
data may cause a real database upgrade to fail; no metadata is fabricated to
make such rows pass. Explicit new academic grants are not retroactively
invented for historical releases.

The root `.github/workflows/postgres-validation.yml` is the configured CI
workflow. The nested workflow shipped in the original source is retained as
historical configuration, not the active package entry point.

The test publication method remains explicitly `single_evaluator_sum` with
`exampleOnly=true`; multiple-evaluator aggregation is rejected until a policy
is configured. No institutional grading or correction policy is inferred.
See `../ARCHITECTURE_DECISIONS.md` and `../DATABASE_VALIDATION_REPORT.md`.
