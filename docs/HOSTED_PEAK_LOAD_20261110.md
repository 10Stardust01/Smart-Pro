# SMART-PRO actual hosted Render Free stress ramp — 10 November 2026

**The actual publicly hosted reviewer application was exercised, not a local
Django test client or a simulated database.** The test targeted
\`https://smartpro-reviewer-25775915.onrender.com\` running Render Free
reviewer commit \`0419358dc5\` with Neon staging main through migration 063.

**Source and evidence:** \`scripts/hosted_peak_ramp.py\`;
[GitHub Actions run 42776567147](https://github.com/10Stardust01/Smart-Pro/actions/runs/42776567147).
This is deliberately reported as **HALTED_SLOW_P95_AT_300**; the runner exited
nonzero because the configured 10-second p95 gate was crossed. It was **not**
a request failure.

## Observed real HTTP results

| Concurrent short-lived clients | Expected/total responses | P50 | P95 | P99 | Maximum |
|---:|---:|---:|---:|---:|---:|
| 50 | 100/100 | 1,602 ms | 2,653 ms | 2,803 ms | 2,803 ms |
| 100 | 200/200 | 1,918 ms | 5,807 ms | 6,082 ms | 6,533 ms |
| 200 | 400/400 | 3,752 ms | 8,904 ms | 9,379 ms | 10,193 ms |
| 300 | 600/600 | 8,671 ms | **13,891 ms** | 15,059 ms | 16,267 ms |

Three preliminary warm-up requests also succeeded; one took **15,351 ms**
during service cold start. **1,303/1,303** requests returned their expected
statuses, including authorized public login rendering (200), SQL-backed
readiness (200) and anonymous session access rejection (401). No unexpected
HTTP status, 429, 5xx or timeout was recorded in the runner result.

The runner used only HTTPS **GET**, one instance on the existing Render Free
service, a hard maximum of 1,303 requests and 300 concurrently scheduled
clients, and no paid browser, trial, paid upgrade or automatic autoscaling.
It stopped escalating after the 300-client p95 exceeded 10 seconds; no
requests were sent above that level. No project, grade, file, term or
appointment was edited.

**Independent telemetry:**
- Render metrics near the peak reported CPU usage of about **0.189 CPU**
  against a reported Free limit of **0.15 CPU** (time-averaged samples are
  not a precise measure of instantaneous throttling), and memory around
  **77 MB** against a roughly **512 MB** limit. This indicates CPU/queueing
  as a more plausible immediate source of contention than memory, but
  does not establish a root cause by itself.
- A Render application-log query covering this window found **no matching**
  status-429, 5xx, traceback or out-of-memory entries. Server-side logs for
  the test use User-Agent \`SMARTPRO-owned-staging-peak-ramp/20261110\`.
- The post-test Neon staging database still contained 1 overall-result
  version, 1 stage-result version, 3 READY file records and 69 audit events.
  Published-result and READY-file metadata digests matched pre-test values.
  The load harness itself did not create audit records.

## Interpretation

This is useful evidence that the **actual Render Free reviewer service**
handled a 200-client short-lived anonymous/SQL-readiness burst under the
chosen p95 ≤10-second test threshold; it reached **13.89 seconds p95 at
300**. It is **not a throughput rating of 200 or 300 authenticated active
academic users**, nor a sustained capacity SLA. Each synthetic client
performed only two GETs sequentially, including the readiness endpoint.
Network contention on the GitHub Actions runner also contributes to
end-to-end timing.

**Still separate**: authenticated hosted Student/Guide/Coordinator/HOD/Admin
journeys, simultaneous document upload, evaluation and publication writes,
realistic large project data, multi-minute soak, PDF byte-level restore,
and complete accessibility/institutional review.

The follow-on **workflow is manual-only** (\`workflow_dispatch\`) and cannot
accidentally re-run a stress test on every GitHub push. If re-used,
choose bounds and monitor the actual environment; do not treat the existing
run's maximum as universally safe on all tiers.
