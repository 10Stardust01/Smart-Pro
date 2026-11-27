# Reviewer promotion — approved PRC foundation

Authorized by the owner’s request to deploy on the existing reviewer link.

- Service: `smartpro-reviewer-25775915` on the existing Render Free plan.
- URL: https://smartpro-reviewer-25775915.onrender.com
- Deployment branch remains `deployment/reviewer-staging`; auto-deploy remains off.
- Base: `6b1ff0869de40881d213530516565f147e1ee55a`.
- Runtime source: tested `e466dbf`, with serialized-role compatibility fix
  `18cc58ac9905ee4960ed655388699ed21a0857c8`.
- Only runtime files, additive candidate 066 and scope/promotion notes are promoted.
  Main, deployment settings, reviewer authentication, storage and worker/thread
  configuration are not replaced or merged wholesale.

## Database rehearsal and release scope

The existing isolated validation branch `br-lucky-rain-b3ufq1ql` was inspected
before use: it had no PRC tables or writer. Candidate 066 was then installed
atomically with bounded lock/statement timeouts. Counts and full-row digests of
14 academic/evidence tables matched the pre-deployment reviewer inventory.
Coordinator scoped PRC reads succeeded. Gate and decision tables remained empty;
runtime INSERT permissions were false and no committee-writing function existed.

The same additive migration is the only required schema addition. No offering
is activated, no PRC member appointed and no outcome recorded. Prior projects,
PDF metadata and bytes, marks, assignments, appointments and history remain.
An app rollback can use the previous source while retaining the empty additive
schema; never erase academic evidence through a destructive down migration.

## Verification basis

The feature’s local verification covered 292 backend cases, 50 course/PRC cases
across isolated runs and 8 frontend entries, including real local browser
journeys. Promotion runtime files were compared byte-for-byte with that feature
source, with the subsequent compatibility fix checked for both list and serialized
role choices. Python/JavaScript syntax checks passed on the promotion source.

The deployment handoff records the resulting deploy ID, live commit, HTTP checks
and post-migration evidence fingerprints after the release. This source note does
not claim hosted acceptance before those checks complete.
