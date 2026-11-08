# Synopsis workflow contract harness

This temporary FastAPI harness now uses the **same PostgreSQL schema as the
ordered migrations**, through `domain.py`. It does not create a second SQLite
model. NestJS versus Django remains undecided.

Start with the [package setup](../README.md). After provisioning the isolated
PostgreSQL 16 test database, run from the package root:

```powershell
python db_setup.py --seed api_seed.sql --create-test-login
python workflow-poc/app.py
```

The API listens on 127.0.0.1:8765. `/docs` and `openapi.json` describe the actual
seven paths. Demo aliases: `case-1`, `synopsis-1`, `synopsis-2`; demo identities:
`student-a`, `student-b`, `faculty-a`, `faculty-other`, `student-outsider`,
`tech-admin`. `SMARTPRO_DEMO_AUTH=YES` enables those insecure test-only headers;
they are not production authentication.

The original sequence remains: start upload → PUT bounded PDF-signature test
bytes → complete/verify → submit attempt → assigned faculty requests changes
→ upload and complete revision → resubmit → approve. `expectedCaseVersion`
and `Idempotency-Key` retain their original contract. Completion can also be
retried safely after a transaction commit failure. History includes exact
document-version IDs for each attempt.

Run all validation with `python validate.py --recreate`. The 13 original
workflow cases are retained and use PostgreSQL placeholders/dictionary rows
and semantic attempt ordering instead of SQLite's `rowid`. Additional API
tests cover distinct-faculty races, duplicate retries, upload completion,
revoked permissions, SQL-injection-shaped data and commit recovery.

`POSTGRES_SCHEMA_REVIEW.md` preserves the supplied historical static review.
The current results, fixed issues and remaining policy/security limits are in
`../DATABASE_VALIDATION_REPORT.md`. Original sources and the earlier SQLite
results remain in `../evidence/SMARTPRO.original.zip`.

No production authentication, malware scanner, object-storage provider or
external notification service is configured. The PDF-signature verifier is
an explicit local test implementation behind a verifier interface.
