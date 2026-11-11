# SMART-PRO — Project lifecycle and academic evaluation platform

> **11 November 2026 — five-role hosted keyboard smoke passed; eight-upload peak gate failed:** [Signed Chromium keyboard #43066865472](https://github.com/10Stardust01/Smart-Pro/actions/runs/43066865472) **PASSED for all five roles** on skip-link focus, visible outline, main anchor and continued Tab navigation; this is not a human screen-reader or PDF audit. A bounded real HTTPS eight-session/same-synthetic-Student 256 KiB private PDF upload burst [#43066015323](https://github.com/10Stardust01/Smart-Pro/actions/runs/43066015323) **FAILED its p95 ≤10s gate at 10.972s**, with **2 HTTP 200 / 6 HTTP 409** uploads in independently checked Render app logs. The test stopped before submission/marking/publication races. The 409s are explicit conflicts, not evidence of lost marks; this is not eight independent students/projects. Original historical result remained one version. **Representative sustained mixed-write/deadline load remains OPEN.** A direct private Neon presigned GET from this runtime failed to resolve the storage host, so no independent paired original-PDF-byte/database restore is claimed. [Detailed evidence](docs/HOSTED_KEYBOARD_AND_EIGHT_UPLOAD_20261111.md).
>
> **11 November 2026 — genuine stage-evidence correction and overall re-release PASSED on hosted HTTPS:** In a new synthetic-only correction-enabled offering, the assigned evaluator used the actual signed HTTP `REQUEST_CORRECTION` → Coordinator `AUTHORIZE_CORRECTION` → evaluator `APPLY_CORRECTION` path to publish changed stage evidence. A Guide then submitted `REQUEST_FINAL_REVISION` with `mode=STAGE_EVIDENCE`; the signed Coordinator approved the exact pending request, and the Student saw overall **v1 40.00 → v2 42.00** while both source hashes changed. [One-time completion run #43065220997](https://github.com/10Stardust01/Smart-Pro/actions/runs/43065220997) **PASSED**, with independent read-only Neon verification of both overall versions and the distinct stage-source digests. The original historical project remains v1 40.00 unchanged. The first workflow [#43064828444](https://github.com/10Stardust01/Smart-Pro/actions/runs/43064828444) stopped after successfully creating genuine corrected stage evidence and the pending Guide request because its test incorrectly expected a top-level `type` field in the Coordinator queue; **the same pending request was completed once**, without duplicating the correction or creating another project. All tests used the existing Render/Neon Free reviewer staging and synthetic identities, without changing historical academic policy. **This closes the bounded genuine hosted stage-evidence re-release gate**, not institutional policy ratification or recovery/peak-write/assistive-technology acceptance.
>
> **11 November 2026 — independently verified faculty handover and recovery-incident findings (latest status):** On real Render Free reviewer HTTPS, [one-time signed synthetic handover #43055424143](https://github.com/10Stardust01/Smart-Pro/actions/runs/43055424143) **PASSED**: Admin terminated an isolated temporary Faculty term on the existing synthetic Student identity; same signed session lost Faculty access but retained Student access; Coordinator explicitly appointed a different Faculty Guide to a *new synthetic project*. Independent Neon readback confirmed **2 append-only handover records, 2 successive Guide assignments, inactive temporary Faculty role, active Student role and zero published results** for that project. No established Faculty term was revoked. Two aborted earlier attempts had safely terminated temporary access; the final run passed. **Close the bounded hosted faculty access/Guide handover check**, not institutional staff authority approval.

> **Recovery warning — not an acceptance pass:** A Neon manual database snapshot restored through the connector unexpectedly swapped default branch and moved the application compute onto older snapshot state. The original branch and records were preserved; the original `br-solitary-cherry-b3lygsgt` was restored as default `main`, original compute hostname `ep-delicate-tooth-b3x8g5uu` remapped to it, and the snapshot left as a separate inspection branch. Verified original current **113 projects, 4 overall-result versions, 4 handover records and 29 READY file assets / 29 stored objects**. Independent [signed Render HTTPS routing audit #43056746567](https://github.com/10Stardust01/Smart-Pro/actions/runs/43056746567) **PASSED**: newly created post-snapshot synthetic project accessible, original historical final result v1 intact, terminated temporary Faculty not reactivated. Brief routing disruption *may* have occurred during the swap; its duration/impact was not measured. Crucially, **the older snapshot branch showed 0 private bucket objects versus 29 on the original**, proving that this database snapshot alone does NOT recover private PDFs. **Paired independent DB + original private PDF byte restore remains OPEN**, and snapshot restore must not be repeated against live staging. No policy/academic marks/payments/trials changed.

> **Hosted accessibility contrast fix LIVE and independently verified — 11 November 2026:** [Reviewer-staging PR #32](https://github.com/10Stardust01/Smart-Pro/pull/32) merged the one-line `frontend/styles.css` change (`.metric small` `#819094` → `#586b70`) to deployment branch commit **`ced07d6`**, leaving all academic policies, results and migrations unchanged. On the existing Render **Free** `Smart-Pro` workspace, manually triggered deploy **`dep-dbq8oe6gekts73eoqjdg`** reached **Live**; automatic deployments remain OFF. [Independent signed-in real-site Chromium/axe scan #43050757492](https://github.com/10Stardust01/Smart-Pro/actions/runs/43050757492) **PASSED without any CSS preview/override**: retrieved the actual served stylesheet, verified computed corrected foreground on Student/Faculty overview, and scanned **10 screens across five signed roles with zero automated WCAG 2.0/2.1 A/AA violations**. This closes the *specific hosted overview metric contrast remediation* gate. It **does not** establish complete WCAG conformance: manual assistive-technology/keyboard checks, accessible private PDFs, and institutional sign-off remain open. Earlier notes about unpromoted staging PR #32 below are historical snapshots.
>
> **Accessibility correction — source merged, hosted promotion pending (11 November 2026):** Baseline real signed-in reviewer [axe audit #43047014955](https://github.com/10Stardust01/Smart-Pro/actions/runs/43047014955) completed 10 screens for five roles and identified **six low-contrast helper text nodes** (three Student and three Faculty overview cards), with `#819094` on `#fffefa` at **3.27:1** rather than required **4.5:1**. The eight other audited screens had zero automated WCAG 2.0/2.1 A/AA violations. [PR #31](https://github.com/10Stardust01/Smart-Pro/pull/31) merged a narrowly scoped **source-only** CSS fix (`.metric small` → `#586b70`, approximately **5.55:1**) plus a static contrast regression at GitHub `main` **`40be1d5`**, with five current PR CI checks passing. [Browser-local preview #43047559954](https://github.com/10Stardust01/Smart-Pro/actions/runs/43047559954) passed **10/10 automated screens only with that exact CSS preview injected**; it is **not proof the hosted reviewer currently serves the fix**. [Draft reviewer-staging PR #32](https://github.com/10Stardust01/Smart-Pro/pull/32) is ready but **not merged or deployed** pending explicit owner confirmation of the Render `Smart-Pro` workspace and controlled promotion. Fresh real-hosted scan *without CSS injection*, assistive-technology/manual testing and accessible PDF review remain OPEN; no WCAG conformance certification is claimed.
>
> **Bounded actual hosted authenticated read-soak PASSED:** [run #43044346237](https://github.com/10Stardust01/Smart-Pro/actions/runs/43044346237) signed in all five synthetic roles and completed **300/300 read-only `/api/v1/workspace` responses** across **120 seconds** at an intended **2.5 GET/s**. Client timings: **p50 0.546s, p95 0.824s, p99 0.904s, max 1.000s**; no retries, file/mark/policy writes, paid browsers, upgrades or trials. This closes only the **bounded five-role authenticated read-soak check**. Sustained mixed academic writes at realistic deadlines, larger user loads, institutional throughput/SLA and sign-off remain **OPEN**.
>
> **New independent graphical browser acceptance — 11 November 2026:** [GitHub Actions run #43043955485](https://github.com/10Stardust01/Smart-Pro/actions/runs/43043955485) **PASSED** with actual signed-in Chromium Guide, Coordinator and Student screens on the existing correction-only synthetic project. The Guide requested overall **42.00**, Coordinator approved, and Student saw **40.00 v1 → 41.00 v2 → 42.00 v3**. Follow-up independent read-only Neon verification found **2** exact correction requests, **2** decisions, **2** applications, **4** correction audit events and identical stage-source digests across all three releases; the original historical project remains unchanged at version 1. This **closes the separate graphical direct-overall correction check**. The first attempt [#43042080326](https://github.com/10Stardust01/Smart-Pro/actions/runs/43042080326) failed in GitHub runner OS font installation before academic writes; the successful rerun avoided the inaccessible Ubuntu apt mirror. Both runners are isolated on their one-time test branch, not merged into `main`. Hosted stage-evidence re-release, signed Admin Faculty access handover, paired DB + original PDF restore, representative sustained mixed-write load, assistive-technology/accessibility and institutional approval remain open.
>
> **Current reviewer-staging acceptance — 11 November 2026 (not institutional production):**
> The approved exceptional post-publication Guide → Coordinator correction is now fixed, independently verified, and live. [PR #27](https://github.com/10Stardust01/Smart-Pro/pull/27) introduced forward-only **065** after existing 059–064, removing the unintended `allowFinalCorrections` veto from the **overall-result** correction write and Guide read paths. The original pinned framework keeps `allowFinalCorrections=false` for finalized **stage-mark** corrections, while the exceptional Guide request → responsible Coordinator decision remains available. Seven PR checks passed; Render Free reviewer staging deploy `dep-dbq78obrjlhs73cvo5gg` reached **Live** at source `f315bd2`, with Neon Free reviewer-staging main migration 065 installed. No existing academic policies, old published marks, stage scores, audit history or original private files were edited.
>
> **Actual hosted HTTPS workflow PASSED:** [GitHub Actions run #43034757343](https://github.com/10Stardust01/Smart-Pro/actions/runs/43034757343) exercised all **five signed-in synthetic roles** on the live reviewer service, creating a separate synthetic offering/project with a *pinned false stage-correction flag*. Assigned Guide requested a specific correction, Coordinator approved, unauthorized Student decision was rejected, and the Student saw preserved original overall mark **40.00** and successor **41.00** as versions **1 → 2**. Independent read-only Neon verification found exactly **one** request, **one** approved decision, **one** application, **two** correction audit events, and identical underlying published stage sources. The pre-existing historical project remains version **1** with its original result fingerprint unchanged. This acceptance execution used a **one-time push-triggered workflow on a separate test branch**, not a new workflow merged into `main`.
>
> **Still not institutional acceptance:** The hosted **stage-evidence re-release variant** has isolated-regression evidence but was not included in this direct-overall correction run; signed-in Admin faculty handover, independent paired database+private-PDF fresh-destination restore, sustained authenticated capacity, accessibility and institutional production sign-off remain open. Details: [requirements register](docs/REQUIREMENTS_COMPLETION_REGISTER.md) and [release gate #4](https://github.com/10Stardust01/Smart-Pro/issues/4). Historical snapshots elsewhere in this README describe the state on **10 November** and must not be used as current deployment instructions.

> **Historical checkpoint only — 10 November 2026 (superseded by the 11 November acceptance above):**
> Neon Free staging **main** now contains migrations **059–063**, with 061 → 062 → 063 installed as separate atomic transactions. Existing Render Free reviewer service manually deployed source commit **`0419358dc5a3c87d5ef5290909b7cbc00e59fb40`** ([PR #12](https://github.com/10Stardust01/Smart-Pro/pull/12)). All published-result, stage-result, audit and READY-file metadata digests remained unchanged. Permissioned Coordinator/Admin reads succeeded and unauthorized Student/Faculty reads were denied. The original pre-059 and new pre-061 recovery branches remain.
>
> **Still outstanding:** actual private PDF byte/hash restoration, independently verified paired database+file recovery, full authenticated hosted Guide → Coordinator → Student/Faculty browser acceptance, peak-load tests and institutional approval. PR #12 passed **five** checks; its sixth correction-browser check was **cancelled during Chromium installation at the 12-minute timeout**, so do not claim 6/6. No paid feature/trial was used. [Release evidence and open gates](https://github.com/10Stardust01/Smart-Pro/issues/4).


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
  commit `f315bd2abcf45e8412d50b02692893c5046317f6` (reviewer deployment `dep-dbq78obrjlhs73cvo5gg` verified **Live** 11 November 2026).
  Automatic Render deployment remains off; this is reviewer staging, not institutional production.
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

**Correction alignment:** Neon reviewer-staging main now has sequentially installed candidates **059–065**, including approved Faculty handover 063–064 and the scoped exceptional overall-result defect fix **065**. This is not a new academic policy: assigned Guide requests an exact post-publication correction and the offering Coordinator approves or rejects it, including when the same person performs both roles. Ordinary finalized-stage mark correction restrictions remain separate. The signed HTTPS direct-overall correction journey **passed** [run #43034757343](https://github.com/10Stardust01/Smart-Pro/actions/runs/43034757343), and the new synthetic history was verified independently in Neon. Never re-run installed candidates 059–065; use forward-only controlled migrations for future changes. See [post-publication correction alignment](docs/POST_PUBLICATION_CORRECTION_ALIGNMENT.md) and [release gate #4](https://github.com/10Stardust01/Smart-Pro/issues/4).

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
