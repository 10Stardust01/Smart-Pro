# SMART-PRO provisional runtime write boundary

This is a **synthetic PostgreSQL test-role policy** stacked on PR #5. It
does not change historical migrations 001–009, upgrade a real database, or
constitute production authorization. Candidate
`proposals/security/runtime_write_boundary.sql` is owner-applied after the
read boundary. The scripts are intentionally not auto-applied to real data.

## What has been verified

The original test provisioner granted `SELECT ON ALL TABLES`, as well as
overly broad `INSERT, UPDATE` rights. The previous read-boundary change
removed the blanket read grant and exposed a scoped synopsis idempotency
lookup. This change replaces the remaining write grants with a minimal
**current synopsis workflow** set.

| Table / operation | App runtime privilege |
| --- | --- |
| file_assets, document_versions, submission_items | INSERT |
| approval_decisions, audit_events, outbox_events | INSERT |
| idempotency_records, upload_sessions, submission_attempts | INSERT |
| upload_sessions | UPDATE(status, sha256, size_bytes, document_version_id, completed_at) |
| submission_cases | UPDATE(state, row_version) |
| submission_attempts | UPDATE(sealed_at, attempt_state) |
| documents | Existing SELECT; **no INSERT or UPDATE(label)** |
| notification_deliveries | **No INSERT or UPDATE** |
| outbox_events, idempotency_records, file_assets | **No UPDATE** |
| other academic, team, identity and grading tables | No direct DML |

The worker-style `smartpro_claim_outbox`, `smartpro_ack_outbox` and
`smartpro_retry_outbox` are not invoked by the authenticated synopsis
HTTP application. They must use a separately reviewed worker identity if
implemented as real background jobs; do **not** restore worker writes to
the student-facing runtime role simply for convenience.

The existing synopsis upload-completion service also needed exclusive
document-row locking for atomic document-version numbering. We replaced its
direct `SELECT ... FOR UPDATE` (which implicitly requires a document UPDATE
grant) with `smartpro_synopsis_lock_document(document_id,actor_id)`: a
SECURITY DEFINER function that checks current project-student authority and
locks the same row in one statement. Direct document UPDATE and unscoped
row locking remain denied to `smartpro_runtime`.

The synopsis submission service also requires an exclusive lock on the
verified file asset until the submission commits. We now obtain it through
`smartpro_synopsis_locked_version(version_id,project_id,actor_id)`, which
checks effective project membership and returns only the version metadata
needed by the application. The runtime role cannot directly lock or update
the underlying file-asset rows. Both the document lock and file snapshot
have negative unauthorized-role tests and concurrency regressions.

PR #7's review fix takes `FOR UPDATE` immediately, matching the submission-item
trigger's requirement and avoiding SHARE-to-UPDATE upgrade races. Multi-document
submissions acquire these locks in UUID order. See [stack review](STACK_REVIEW.md).

The baseline `smartpro_guard_submitted_file()` trigger also takes an
exclusive row lock on the verified file asset when a submission item is
inserted. The candidate hardening script changes **only that existing
trigger function's execution security**, not its validation logic, to
SECURITY DEFINER with a fixed trusted search path. This keeps its READY
check and atomic locking intact without granting document/file UPDATE to
the runtime role. A regression test checks the function configuration.

The narrow `smartpro_create_student_team` function in candidate 012 is
SECURITY DEFINER and still manages its inserts atomically under the DB owner.
The runtime role does **not** need direct team or team-membership INSERT.

The SQL privilege script uses a transaction and can be reapplied by its
owner. An explicit `REVOKE` removes historical direct grants on tables in
`public`, then exact required grants are restored. A production rollout
must first inventory *actual* grants, role inheritance, PostgreSQL ownership,
`PUBLIC` grants, other services, and worker identities. Test the full
deployment's grant change and rollback/recovery on a staging copy before
applying it to a real academic database.

## Important limits

- This is **a narrower runtime permission policy**, not complete SQL
  authorization. The trusted backend still supplies actor identifiers to
  privileged functions, and some legacy writes are direct. A compromised
  application DB credential can still misuse its allowed INSERTs/UPDATEs.
  Before real student use, encapsulate sensitive legacy mutations behind
  vetted, actor-checked commands or an equally strong independently
  enforced boundary; review the remaining function EXECUTE grants.
- The prototype FastAPI harness and Django adapter use synthetic demo
  authentication only. A USN or a form response is never authentication.
- PostgreSQL tests prove denied writes, correct column-level grants, and
  that previously implemented synopsis/team flows still pass. They do
  not prove the safety of an unknown production grants configuration.
- This does not ratify academic policy or settle the 4 preexisting
  faculty/institutional policy skips.

See `db_setup.py` for synthetic-only install order and
`workflow-poc/tests/test_additional.py` for privilege assertions.
