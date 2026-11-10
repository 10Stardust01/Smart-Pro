> **Latest hosted reviewer checkpoint — 10 November 2026 (not institutional production):**
> Neon Free staging **main** now contains migrations **059–063**, with 061 → 062 → 063 installed as separate atomic transactions. Existing Render Free reviewer service manually deployed source commit **`0419358dc5a3c87d5ef5290909b7cbc00e59fb40`** ([PR #12](https://github.com/10Stardust01/Smart-Pro/pull/12)). All published-result, stage-result, audit and READY-file metadata digests remained unchanged. Permissioned Coordinator/Admin reads succeeded and unauthorized Student/Faculty reads were denied. The original pre-059 and new pre-061 recovery branches remain.
>
> **Still outstanding:** actual private PDF byte/hash restoration, independently verified paired database+file recovery, full authenticated hosted Guide → Coordinator → Student/Faculty browser acceptance, peak-load tests and institutional approval. PR #12 passed **five** checks; its sixth correction-browser check was **cancelled during Chromium installation at the 12-minute timeout**, so do not claim 6/6. No paid feature/trial was used. [Release evidence and open gates](https://github.com/10Stardust01/Smart-Pro/issues/4).

**Do not rerun 059–063** on Neon main or validation. The pre-061 branch preserves the pre-upgrade checkpoint but has not passed independent private-PDF recovery; it is unprotected due to the Neon Free plan protection limit.

> **Validation rehearsal completed (10 Nov 2026), not hosted acceptance:**
> existing Neon validation now contains **059–063**, with 061, 062 and 063
> installed atomically in order. Neon **main** and Render remain unchanged at
> 059/060. Do **not** rerun 059 or 060. The actual private PDF bytes still
> require a paired backup and fresh-destination restore before any live main
> migration. See [validation evidence](NEON_061_063_VALIDATION_20261110.md)
> and [release gate #4](https://github.com/10Stardust01/Smart-Pro/issues/4).

# SMART-PRO deployment and recovery

## Free-only hosted PDF recovery verification

Before approving a hosted Neon database migration, independently retrieve the
actual private `smartpro-documents` object **bytes** from the appropriate
branch into a private directory on a trusted machine. Never paste or commit S3
credentials or presigned GET links into GitHub issues, source, Actions logs, or
a public artifact.

Export a local manifest from the corresponding database's
`file_assets` READY entries with the fields `key` (the database
`storage_key`), `size_bytes`, and `sha256` under an `objects` array.
The manifest must represent the **same database checkpoint** as the files.
Run this standard-library-only offline checker to confirm all files and then
perform an independent local copy:

```powershell
python scripts/verify_hosted_pdf_recovery.py .\recovery_manifest.json .\private-pdfs .\private-pdfs-recovered
```

A passing output includes `PASS_LOCAL_FILE_RESTORE_ONLY` in the
`private-pdfs-recovered/verification_receipt.json` receipt. Failure leaves
the release blocked. A local copy validates byte-level recoverability but does
**not** prove that Neon private S3 storage can be restored to another bucket,
that a hosted app can authenticate and download the recovered objects, or that
a full database dump was restored. Those gates must be separately executed and
recorded. Retain the original pre-059, pre-061 and validation branches without
deleting or overwriting academic history.



Use a reviewed local commit and an explicitly provisioned PostgreSQL database.
Development uses the Django launcher on loopback. Tests use disposable
databases and private temporary storage. Staging and production use
`smartpro.wsgi:application` through an approved WSGI server and TLS gateway.
Start the existing course notification command as a separate supervised
process only when that feature is enabled.

## Main local development workspace

The persistent local database is `smartpro_dev` on the reviewed loopback
PostgreSQL cluster. Its manifest is `.local-data/smartpro_dev.json` and its
private storage is `.local-data/smartpro_dev/`. Both are ignored by Git.
The launcher reads the loopback connection configuration from the existing
ignored `.test-data/pg-memberships.env.json`, uses the runtime login for
serving, and selects `smartpro_dev` explicitly. It does not substitute the
test database, archived demo, or an inherited `DATABASE_URL`.

From the repository root on Windows:

```powershell
# One-time provisioning only when smartpro_dev does not exist.
& .venv/Scripts/python.exe scripts/application.py init-development

# Normal local startup with the dedicated database.
& .venv/Scripts/python.exe scripts/application.py serve-development --port 8021 --faculty-reference
```

The loopback development launcher reloads Django when Python files change.
If an older process still serves port 8021 after switching checkouts, stop
that process and start the command above from the current checkout. The
frontend assets are read from disk, so an old Python process can serve
newer JavaScript and reject requests introduced after it started.


Provisioning copies the reviewed archive schema without its rows, installs the
remaining candidate chain in order, and creates five synthetic local personas
with departmental roles. It refuses an existing database, manifest or storage
directory. If an installation is interrupted, retain the incomplete database
and verify which candidates ran before making any owner changes. Startup
requires 048–050 and never runs migrations. Local personas require the
explicit development launcher, loopback requests and development settings.
The development-only persona lookup is scoped to the five seeded accounts.
Keep institutional identities and records out of this workspace.

`test-workspace` and `serve --test-manifest` continue to use their own
disposable database names and test storage. Hosted environments continue
to use explicit runtime credentials and the approved identity resolver.

For local recovery, stop writers before pairing a custom-format PostgreSQL
dump with a private file snapshot. Restore into a new database and compare
table counts and row digests, constraints, routines and the stored PDF
digests before selecting a restored instance. Keep the bundle private.

| Setting | Hosted requirement |
| --- | --- |
| SMARTPRO_DEPLOYMENT | staging or production |
| DJANGO_SECRET_KEY | Long random secret from the approved secret store |
| SMARTPRO_ALLOWED_HOSTS | Explicit comma-separated hostnames |
| SMARTPRO_CSRF_TRUSTED_ORIGINS | Explicit HTTPS origins if the deployment requires them |
| SMARTPRO_TRUST_TLS_PROXY | YES only when the gateway removes client-provided forwarding headers and sets its own |
| SMARTPRO_HSTS_SECONDS | Start at zero and enable after verifying HTTPS for the approved host |
| DATABASE_URL | Restricted runtime login, managed TLS settings and no owner credentials |
| SMARTPRO_DB_CONN_MAX_AGE | Defaults to zero. Set only after reviewing the WSGI worker and PostgreSQL connection budgets |
| SMARTPRO_DATA_DIR | Absolute private path when documents are enabled. Restrict filesystem permissions to the service user |
| SMARTPRO_IDENTITY_RESOLVER | Approved importable callable that verifies each request and returns the institution-mapped application UUID |

Set the application feature gates explicitly. Set a gateway body limit suitable
for the enabled APIs, including 2 MiB PDF uploads and multipart overhead.
The application retains its per-file bound and one-file limit. Use a private
filesystem with atomic hard links and keep temporary staging and final objects
on the same filesystem. Do not expose the storage directory as static files.

The identity adapter accepts an explicit Bearer credential. The resolver owns
issuer and audience validation, token expiry and revocation. The approved
identity integration must supply browser sign-in and session termination.
Account provisioning and institutional
profile-to-identity mapping require institutional approval. The application
recomputes effective academic roles from PostgreSQL on each authenticated
request. A requested responsibility can only narrow those roles. Public
directory data does not participate in authentication. Hosted settings reject
the synthetic adapter and require an explicit resolver.

Use HTTPS for `/health/live` and `/health/ready` behind the hosted gateway.
Liveness checks the process. Readiness checks database access, function
signatures for the enabled course and document APIs, and the configured
storage directory. Probes return status without database details.

## Provisional capacity settings

The local [hardening comparison](CAPACITY_BASELINE.md#hardening-follow-up)
supports a starting **test profile** of one process, 12 synchronous
threads, a bounded admission limit (48 in the tested Uvicorn h11 adapter)
and `SMARTPRO_DB_CONN_MAX_AGE=60` with Django health checks. Enable
connection reuse only on a threaded WSGI runtime where threads are reused
and the response iterable is closed. The local development launcher and
hosted defaults were not changed. The benchmark uses Uvicorn's buffered
WSGI bridge; validate the intended server and proxy before deployment.

- Budget at least one PostgreSQL connection per live worker thread, plus
  background and maintenance connections. Leave at least 30% headroom and
  explicit operator reserve; with 100 configured connections, treat 70 as
  an early warning, not an allocation target. Alert on sustained thread
  saturation, rising admission 503s, lock waits and latency. A second app
  process doubles its thread connection budget and cannot remove
  database-level academic lock contention.
- Retain the tested 5 s connect, 5 s lock and 10 s statement limits during
  evaluation. Set a bounded ingress deadline with room for valid uploads
  and database failure handling. Start with at most four simultaneous
  uploads per instance as an **unverified** ingress setting and retain
  the configured document-size checks. Rehearse body buffering, slow
  clients, interrupted requests and actual deadline boundaries before
  approving the cap. Avoid an unbounded request queue.
- Return a clear temporary overload response; at a selected proxy,
  consider a short `Retry-After`. For an uncertain academic write,
  check project or assessment history and retry the **same** payload and
  idempotency key. For a PDF, keep the same file and browser tab. Do not
  automatically retry denied or stale operations, or create a new key
  merely because the success receipt was lost.

## Owner-run schema alignment

Identify the intended database using a named owner connection and
`SELECT current_database(), inet_server_addr(), inet_server_port()`. Compare
the current schema with the reviewed candidate inventory. Do not infer the
development target from a test fixture, an archived demo or the currently
selected database in a GUI. Candidate 048 depends on the preceding course
chain. Candidate 049 depends on 048 and changes correction guards. Candidate
050 depends on 049 and changes scoped document reads. Candidate 051 depends
on 047 and adds the bounded departmental intake and batch-history reads. It is
installed on newly provisioned isolated workspaces. Align existing development
databases through the owner-run procedure before using records search.
Candidates 052–057 extend the department directory, import and history paths.
They were exercised in disposable PostgreSQL workspaces. Install them in order
through a separately reviewed owner-run change. Multipart intake uses
`SMARTPRO_INTAKE_FILE_BYTES` (2 MiB default), with separate decoded/expanded
data limits. Set an approved gateway upload limit before enabling intake.


1. Quiesce writes. Record project, release and document counts and versions,
   and take a PostgreSQL custom-format dump using the owner connection. Capture
   the matching private storage snapshot. Keep both copies access restricted.
2. Restore the dump and files to a separately named test destination. Check
   integrity, candidate dependencies, runtime grants and historical counts.
3. Apply the missing reviewed candidates in order to the restored copy first
   with `psql -X -v ON_ERROR_STOP=1 -f <candidate-file>`. Test the role-scoped
   workflows, readiness, stored file hashes and earlier releases.
4. Repeat on the explicitly identified development target only after the
   restored copy passes. Keep the original backup. Recheck the same invariants
   before reopening writes.

A failed transaction must be investigated before retrying. For a recovery
that requires restoring data, restore to a new destination, compare DB and
storage consistency, and obtain approval before switching traffic. Preserve
the failed database for investigation. Do not reverse immutable academic
history by editing releases or audit records.

Monitor request latency and errors, DB sessions and timeouts, notification
worker lag, private storage capacity, and counts of unfinished upload
sessions. Upload completion publishes an immutable object before marking the
version ready. A failed completion leaves a retryable object. Avoid deleting
such objects based on age alone. Compare against the upload session and
database evidence during supervised recovery.
