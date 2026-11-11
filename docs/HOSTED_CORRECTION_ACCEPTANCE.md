# SMART-PRO — hosted published-result correction acceptance

**Status:** harness implemented, awaiting an explicitly dispatched and verified real
HTTPS run. Passing static CI alone is NOT hosted workflow acceptance.

## Why a separate fixture

The one pre-existing reviewer offering `8b40a6e1-419d-43c8-b625-279f82713b02`
has a version-1 academic framework with `allowFinalCorrections=false`.
The original already published project
`67b0acd3-914f-4063-97db-8b8a75359104` pins that historical
framework and must retain its original result and stage evidence.
Do not update that original framework or republish the original result.

## Controlled bounded test

Manual GitHub Actions workflow:
`.github/workflows/hosted-published-correction.yml`.

Required approval: `RUN_SYNTHETIC_PUBLISHED_CORRECTION`, selected branch
`main`. It uses the already provisioned private
`SMARTPRO_HOSTED_TEST_ACCOUNTS` Actions secret. Never put passwords
or tokens into workflow inputs, logs, documentation or Git commits.

The runner preflights the original published project first, then
creates a **separate, uniquely named synthetic curriculum type and offering**,
records a clearly labeled synthetic-only instruction using the existing
synthetic Admin account, appoints the current synthetic Coordinator, and
activates the new offering. The synthetic HOD records a **new approved
versioned framework** enabling exceptional final corrections, and the
Coordinator pins a plan to it. The existing framework remains unchanged.

It then creates **one** synthetic team and project, assigns the synthetic
Guide, creates and finalizes an evaluation stage, publishes that stage
and the overall result, requests an exact corrected overall mark through
the signed-in Guide, and approves it through the signed-in Coordinator.
The signed-in Student must see **both** the original and successor
overall-result versions, the Coordinator must see unchanged published
stage source IDs, and Student approval attempts must be forbidden.
The runner verifies the original legacy published result remains
unchanged at the end. No automatic approvals, extra HOD decision for
the correction itself, or independent-approver requirement is added.
The HOD's framework configuration is distinct from the Coordinator
decision on an individual correction.

All new synthetic fixtures and audit events remain stored for
traceability (they are never silently deleted). The test deliberately
makes **no** production identity, faculty policy or capacity claim.
It runs against the same existing Render Free reviewer application,
not a cloned application, with no upgrade or paid browser integration.

The test must **fail closed** on an unexpected response and must not
retry uncertain writes with new idempotency keys. Failure can leave
a partially created *synthetic* offering/team/project; report the
recorded fixture instead of inventing a pass or cleaning up immutable
records.

## Acceptance and evidence

The release-gate item may be closed for the bounded hosted correction
only after the actual workflow finishes successfully and the corresponding
Neon read-only check verifies original/new result versions, their
supersession, unchanged stage sources, Guide request, Coordinator
decision and original published project. A signed-in HTTPS script
is distinct from manual GUI accessibility or institutional acceptance.

If the workflow fails at a known stage, fix the narrow defect with a
reviewed commit, preserve all test/audit evidence, and rerun using the
same synthetic-only approval procedure. Do not change established
department academic decisions to make a test pass.
