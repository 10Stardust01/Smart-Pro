# SMART-PRO — controlled real-HTTPS PDF upload performance diagnostics

## Why this exists

The real hosted academic-write tests passed but used **617-byte PDFs**:
- [2 clients](https://github.com/10Stardust01/Smart-Pro/actions/runs/42857100933): max 6.995 s.
- [4 clients](https://github.com/10Stardust01/Smart-Pro/actions/runs/42858473656): max 1.626 s.

The earlier display called each maximum a p95. With only 2 or 4
observations, that is not a useful performance statistic. These runs
establish specific race-condition correctness, not realistic throughput.

Render CPU/memory samples for these minutes had no obvious sustained
spike. Render HTTP latency and request-count metrics returned no data.
Neither is evidence for the origin of the 6.995-second delay.

## Opt-in upload stage timings

The upload handler logs a single sanitized diagnostic line on each
**successful** upload only if the Render setting
SMARTPRO_UPLOAD_TIMINGS is set to YES. Otherwise it does not log this
data. Measured phases:

- parse_ms — request multipart parsing and in-handler buffering.
- pdf_verify_ms — PDF validation and external pdfinfo subprocess.
- prepare_sql_ms — authorized PREPARE database command.
- start_sql_ms — authorized START_UPLOAD database command.
- storage_ms — immutable storage publication.
- complete_sql_ms — authorized COMPLETE_UPLOAD database command.
- handler_ms — total handler time, excluding HTTP edge and middleware.

Records also show byte size and whether private backend is S3 or
filesystem, **never** actor IDs, passwords, cookies, document contents,
project IDs, filenames, or storage keys.

## Manual diagnostic workflow

The separate GitHub Actions workflow
.github/workflows/hosted-upload-latency.yml requires manual dispatch,
the existing private GitHub Actions secret
SMARTPRO_HOSTED_TEST_ACCOUNTS, and approval phrase
RUN_SYNTHETIC_HOSTED_WRITES.

It creates one new clearly labeled synthetic project in the verified
synthetic offering and Student team. It uses separate signed-in Student
sessions, genuine HTTPS multipart PDF uploads, and private read-back
with SHA-256 comparisons for **every** result.

Choose 2 or 4 concurrent clients, 3 or 5 repeated upload waves, and
approximately 64, 256 or 1024 KiB per PDF. Bounded maximum per run:
20 permanent, immutable synthetic PDFs and 20 MiB of bytes. There are
no retries, no deletes, no schedule, and no automatic load increase.
This is a diagnostic sample, not a production capacity test.

The default suggested first run is 2 clients, 5 rounds, 256 KiB;
the second run may use 4 clients if the first is healthy. These tests
make persistent audit and storage records: never run on real coursework
or leave synthetic fixtures unlabelled. Existing approved academic
policies, roles, and published results remain untouched.

## Deployment procedure and safeguards

1. Ensure the PR is green and merge it into main. This does not itself
   update the hosted Render reviewer app: it tracks the
   deployment/reviewer-staging branch, with auto-deploy disabled.
2. Promote the reviewed diagnostics into the dedicated staging branch
   through the controlled GitHub process. Deploy explicitly to the
   existing Render Free instance, without changing plans or touching
   real coursework. Verify the HTTPS readiness endpoint.
3. Optionally add just SMARTPRO_UPLOAD_TIMINGS=YES to Render Environment,
   merging with existing variables. Never replace the environment list.
4. Run the manual diagnostic workflow from main using the known
   synthetic UUID defaults. Never put secrets into workflow inputs.
5. Examine each round's raw client timings and checksums and the
   matching Render stage-timing lines. If no timing line appears,
   don't pretend stage attribution is available.
6. Correlate client versus handler timing. HTTP edge, session auth,
   middleware and connection establishment are NOT included in
   the handler measurements. Sampled CPU does not rule out spikes.
7. Only optimize a bottleneck if the measurements warrant it.
   Keep PDF validation, permissions and immutable write semantics.
   After any change, rerun the same parameters and report both sets.
8. Remove the optional timing flag after the investigation.
   Keep all completed synthetic audit records; don't delete original
   reviewer accounts. Stay on existing free plans without paid
   features, trials, metered credits, or uncontrolled requests.

For each sample report actual size, sample count, median, descriptive
nearest-rank p50/p95, maximum, error count, and deployment version.
Even 10–20 samples are insufficient for reliable production p95
claims. Real departmental capacity testing is a separate milestone.
