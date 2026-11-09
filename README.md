# SMART-PRO — Project lifecycle and academic evaluation platform

SMART-PRO is a Django / Django REST Framework and PostgreSQL application for
departmental project registration, teams, guide assignments, document revision
and approval, configurable evaluation, results, and academic history. The
frontend contains role-specific workspaces for Student, Faculty, Coordinator,
HOD, and Admin.

**Current source and decisions:** [Consolidated development checkpoint](docs/CONSOLIDATED_DEVELOPMENT_CHECKPOINT.md). GitHub integration and live Render/Neon deployment are different steps.

## Existing reviewer staging deployment

- **Application:** [SMART-PRO reviewer staging](https://smartpro-reviewer-25775915.onrender.com)
- **Hosting:** Render **Free** web service (Docker, Singapore).
- **Database:** existing SMART-PRO PostgreSQL 16 project on Neon **Free**.
- **Source:** `deployment/reviewer-staging`; deployment verified at
  commit `319e3ebc1368745fcc7f2afe61d47a7bb202335a` (verified in connected Render, 10 November 2026).
  Automatic Render deployment is off; newer development commits have not been promoted.
- **Access:** staging-only authenticated reviewer sessions, backed by effective
  database roles. Use **synthetic academic identities and records only**; do not
  use the site for live institutional approvals or marks.

The application is **already deployed**, but a live web service is not the same
as production/institutional sign-off. See
[repository status](docs/REPOSITORY_STATUS.md),
[department review checklist](docs/DEPARTMENT_REVIEW_CHECKLIST.md), and
[deployment and recovery](docs/DEPLOYMENT_AND_RECOVERY.md) for verification and
remaining requirements.

**Hosting restriction:** continue only with genuine ongoing free plans. Do not
upgrade to paid resources, activate free trials or trial credits, consume Railway
trial credits, or add charge-incurring services. Verify the relevant plan and
limits before every infrastructure change. Keep the existing live service,
database, and immutable academic history intact.

**Correction alignment:** reviewed source includes 059, 060, 061, forward-only 062 correction paging and
candidate 063 Admin-scoped non-HOD Faculty management (PR #7), but Neon
**main** staging still has **059/060 only**, while the existing Neon validation
branch has successfully installed **061–063** in an isolated rehearsal.
The **hosted** request-visibility change remains unapplied on Neon main.
Do not re-run 059 or 060, or mistake a code merge for a hosted release. See
[post-publication correction alignment](docs/POST_PUBLICATION_CORRECTION_ALIGNMENT.md)
and [release gate #4](https://github.com/10Stardust01/Smart-Pro/issues/4).

## Historic PostgreSQL prototype reproduction

The commands and inventory below are preserved as **historical validation
context**, not instructions to configure, overwrite or redeploy the current
Render/Neon staging service. Never run `--recreate` against a live database.
The original local synopsis harness remains available for regression testing;
use isolated synthetic test databases and private test files only.

## Reproduce with PostgreSQL 16

Python 3.12 is the tested interpreter. From this package root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
docker compose -f database-v1.5/compose.yaml up -d
Get-Content .env.example | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
    }
}
.\.venv\Scripts\python.exe validate.py --recreate --label local
```

`--recreate` **destroys only the explicitly named isolated test database**.
Both the affirmative test flag and a `smartpro_test*` / `smartpro_validation*`
database name are required. Never point this runner at real academic records.
The administrative DSN is used only for migrations/test fixtures; the API uses
a separate non-superuser `smartpro_api` login and `smartpro_runtime` privileges.

On Bash/Linux, use `python3 -m venv .venv`, activate it, install the lock file,
then `set -a; . ./.env.example; set +a` and `python validate.py --recreate`.
The root GitHub workflow executes that Python validation runner. CI and Docker
Compose were configured but **not executed in this Windows session**; the
actual recorded server was portable PostgreSQL 16.15.

### Native Windows alternative (used for actual server execution)

Get PostgreSQL 16 Windows binary archives from the
[official EDB binary download page](https://www.enterprisedb.com/download-postgresql-binaries).
The exact tested download URL, size and SHA-256 are in
`evidence/postgres-binary-source.json`. Extract `pgsql/bin`, `pgsql/lib` and
`pgsql/share` together. No Windows service installation is necessary.

```powershell
$python = '.\.venv\Scripts\python.exe'
& $python scripts/portable_postgres.py --bin-dir C:/path/to/pgsql/bin --data-dir C:/path/to/private-test/pgdata --action start
$settings = Get-Content C:/path/to/private-test/pgdata.env.json -Raw | ConvertFrom-Json
$settings.PSObject.Properties | ForEach-Object {
    [Environment]::SetEnvironmentVariable($_.Name, [string]$_.Value, 'Process')
}
& $python validate.py --recreate --label native
& $python scripts/portable_postgres.py --bin-dir C:/path/to/pgsql/bin --data-dir C:/path/to/private-test/pgdata --action stop
```

Choose a new private test directory **outside the source tree**. Random local
credentials remain in its environment file. The server listens only on
127.0.0.1, default port 55439, and uses SCRAM authentication. The archive does
not bundle PostgreSQL binaries, data directories or local credentials.

## Manual API demonstration

After setting the test environment and provisioning PostgreSQL as above:

```powershell
.\.venv\Scripts\python.exe db_setup.py --seed api_seed.sql --create-test-login
.\.venv\Scripts\python.exe workflow-poc/app.py
```

This resets the isolated test schema and creates the original synthetic
workflow fixtures. The server binds only to 127.0.0.1:8765. Use `/docs` or the
updated `workflow-poc/openapi.json`. `SMARTPRO_DEMO_AUTH=YES` explicitly enables
insecure test-only `X-Demo-User` identities and aliases `case-1`, `synopsis-1`,
etc. No production identity adapter is configured; with the flag off, protected
routes reject requests. Never expose demo authentication to real users.

The original upload → submit → request changes → upload revision → resubmit →
approve sequence and response fields remain. History now includes exact
document-version IDs. Upload verification is a bounded-size/PDF-signature
**test verifier**, not a PDF security assessment or malware scan.

## Layout / validation scope

- `database-v1.5/migrations/001`–`004`: original SQL, unchanged.
- `005`–`009`: forward integrity, publication, upload/outbox, scoped runtime
  authorization, temporal and historical guards; `btree_gist` is required.
- `db_setup.py`: explicit isolated migration/seed runner and runtime grants.
- `workflow-poc/domain.py`: framework-independent synopsis transactions.
- `academic_services.py`: named single-evaluator **test policy** publication,
  ownership-token outbox leases/retries, local notification deduplication.
- `tests/` and `workflow-poc/tests/`: actual PostgreSQL, API and concurrency
  tests. Four institutional-policy cases are explicitly skipped.
- `validate.py`: clean-room runner, exit codes, JUnit XML and schema inventory.
- `evidence/`: baseline failures and final executed results; source ZIP and
  source hashes preserve the supplied implementation.
- `.github/workflows/postgres-validation.yml`: root CI workflow, configured
  but unverified on GitHub. The supplied nested workflow is historical.

The SQL-only legacy runner remains available as
`bash database-v1.5/run-tests.sh` for an **empty** isolated PostgreSQL 16 database;
it now discovers every ordered migration. The full Python runner also executes
API/concurrency tests and lint and is authoritative for this validation.

Academic quorum, grade-amendment authority, retrospective membership exceptions
and multi-evaluator aggregation are not invented. Publication reissue tests
retain the same immutable source marks and append a release with a reason;
they do not implement an institutional mark-amendment process. External
notifications, production storage/authentication, backups, performance, RLS,
and departmental deployment remain outside the verified prototype.
