# PR stack technical review — 4 November 2026

Reviewed current main `193c095` and the current heads of #2 (`df9d4af`), #4
(`adc1c20`), #5 (`1bd703c`) and #6 (`212c543`), including the source, grants,
triggers, migrations and test contracts. #3 (`da38203`) is prospective policy
documentation, not deployed constraints. Directly queried the latest PR-head CI:
all existing workflows succeeded. The dependency order is #2 -> #4 -> #5 -> #6;
#3 remains independent. No merge is authorized.

## Confirmed finding and targeted fix

**Synopsis file-lock upgrade race:** #6's locked-version capability acquired
`FOR SHARE` on a file, but the existing submitted-file trigger later requested
`FOR UPDATE` on the same row. Two independently locked submission cases sharing
a version could both validate under SHARE and deadlock upgrading their locks.
The focused local PostgreSQL probe failed on #6: a second validator returned
while the first still held its lock. Take UPDATE at initial validation instead,
and acquire version/file locks in UUID order across multi-document submissions.
This preserves the existing trigger and runtime privilege restrictions; it does
not restore direct file UPDATE grants or modify migrations 001–009.

## Security and integrity assessment

- 010 uses composite scope FKs, temporal exclusion, immutable identity guards
  and a real profile revision write to reject stale admission/profile snapshots.
  Its reviewed mapping, stopped-writer prepare/preflight/activate procedure remains
  mandatory. No automatic legacy upgrade or real-data recovery is verified.
- 011 derives profile/offering reads from ACTIVE account and effective student
  role; UUID cursors never broaden department/semester/publication scope. SQL
  actor parameters are trusted-server capabilities, not authentication or RLS.
- 012 locks profile, identity/role, idempotency and offering scope before atomic
  team/member/audit creation. Same-key retries are checked against normalized
  request digests; temporal exclusion prevents duplicate offering memberships.
  New membership commands must also serialize distinct students on team capacity;
  a student lock alone cannot enforce a team-size limit.
- Definer paths put pg_catalog first and pg_temp last, sensitive reads are schema
  qualified, PUBLIC execution is revoked, and runtime has no direct identity,
  roster, team or grade writes. #5 removes blanket reads; #6 removes broad writes
  and the separately granted legacy UPDATE(label) column privilege.
- Remaining synopsis direct reads/inserts are a documented trusted-service
  boundary, not protection against stolen DB credentials. In particular legacy
  INSERT on audit/idempotency tables is not actor-authenticated SQL. Complete
  sensitive-command encapsulation and real production grant/inheritance inventory
  remain required before admitting real users. This review does not claim those
  known gaps are newly solved or grant arbitrary faculty powers.
- The existing shared runtime and explicitly gated demo adapter do not establish
  production authentication. Historical review rosters, submission identity,
  criterion scores and published results must remain frozen during prospective
  membership changes. Institutional grading/guide decisions in #3 are unratified.

This is a fresh code-and-execution review, not independent human approval or a
production-readiness certification. Verification results and PR links belong in
the authoritative REPOSITORY_STATUS.md and PR descriptions.
