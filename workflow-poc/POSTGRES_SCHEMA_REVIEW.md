# Targeted review of the PostgreSQL v1.5 database prototype

> Historical review supplied in the original ZIP, preserved below. The executed
> remediation and remaining limits are documented in `../DATABASE_VALIDATION_REPORT.md`.

This is a **static review**, not a migration execution report. Items below must be addressed before department deployment and, where they affect integrity, before the first full PostgreSQL-backed API prototype.

## Verified offline

- The bundled migrations contain 36 declared tables and four migration files.
- Existing structural lint reports 35 explicitly declared composite foreign-key targets with corresponding declared unique/primary keys.
- This verifies neither SQL parseability nor correct runtime behavior.

## Concrete gaps to close

1. **Submission-item immutability after submission.** The existing `submission_items` table accepts UPDATE/DELETE and additional INSERTs after a formal attempt. Although `document_versions` is immutable, a reviewed submission can potentially have its referenced set of files altered. Adopt a draft/finalized attempt protocol or an append-only submitted-item model, with server and SQL checks. The API harness protects existing submitted items from update/delete but does not establish the PostgreSQL equivalent.
2. **Finalized assessment record protection.** `smartpro_finalize_assessment` stops a finalized assessment being changed *back to DRAFT* but does not yet prohibit all meaningful updates to `evaluator_assignment_id`, `review_id`, or `scheme_mode_id` while retaining `FINALIZED`. Add a guard that freezes the scoring identity and finalization timestamp after finalization; allow only explicitly audited correction flows.
3. **Score publication isn't verified from source marks.** The schema permits inserting `result_releases` and student result rows without a trusted publication service proving all roster members are included and results reproduce finalized assessment values. Build the transaction and its tests; do not claim SQL alone proves result correctness.
4. **Review roster eligibility time.** The snapshot currently links an existing team-membership record but does not establish that membership was effective at the review's freeze time. This requires an approved attendance/transfer policy and transactional validation.
5. **Reviewer authority and quorum.** A foreign key to `users` does not prove reviewer assignment or required approval quorum. The production service must enforce approved policy and role-scoped permission checks.
6. **File state and private storage.** `file_assets` holds metadata; the schema cannot alone guarantee malware scanning, object presence, cryptographic verification, access policies, or cross-system recovery.
7. **Event processing.** The outbox schema needs a worker protocol for claim/reclaim, retry backoff, dead-letter handling, and idempotent recipient delivery.
8. **Tenant-safe row access.** Composite keys prevent certain cross-project links but don't replace department/project-scoped read authorization or evaluated database-row security policy.
9. **Approved project policy linkage.** The FK checks policy identity/scope but does not itself forbid a newly created project referencing a DRAFT policy version.
10. **Versioned result correction.** SQL protects existing release rows but the release-creation operation must enforce valid `supersedes` chains, appropriate authority and consistent calculation snapshots.

## Migration strategy recommendation

Do not quietly patch an unvalidated prototype into a production migration series. First run all four migrations and the bundled tests in an isolated PostgreSQL 15+/16 test database, record failures, then add a separately versioned hardening migration and tests. For new projects that have not been deployed, the migrations may then be consolidated before the first approved release.
