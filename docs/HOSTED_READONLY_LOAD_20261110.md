# SMART-PRO — actual hosted read-only concurrency evidence

**Date:** 10 November 2026. **Target:** the existing Render Free reviewer site,
`https://smartpro-reviewer-25775915.onrender.com`, against the deployed
`deployment/reviewer-staging` application. **No academic data writes, login
attempts or private credentials** were used.

## Real HTTPS tests

A one-off, internet-connected GitHub Actions runner executed
`scripts/hosted_readonly_ramp.py` **against the deployed URL**, not an isolated
Django test client or a database mock. The runner used Python standard-library
HTTPS, disabled redirect following, did not retry failed wave requests, and
stopped on unexpected responses, timeout, or wave p95 greater than 5 seconds
(10 seconds in the initial smaller run).

| Run | GitHub Actions evidence | Warm-up | Clients ramped | Total GETs | Expected responses | Errors |
|---|---|---:|---|---:|---:|---:|
| Initial | [42772993504](https://github.com/10Stardust01/Smart-Pro/actions/runs/42772993504) | 3 | 1, 2, 4, 8 | 33 | 33 | 0 |
| Extended | [42773414993](https://github.com/10Stardust01/Smart-Pro/actions/runs/42773414993) | 3 | 1, 2, 4, 8, 16, 32 | 129 | 129 | 0 |

**Extended-run response times (actual HTTP, rounded ms):**

| Clients | Successful GETs | P50 | P95 | Max |
|---:|---:|---:|---:|---:|
| 1 | 2/2 | 338 ms | 338 ms | 338 ms |
| 2 | 4/4 | 323 ms | 894 ms | 894 ms |
| 4 | 8/8 | 327 ms | 817 ms | 817 ms |
| 8 | 16/16 | 350 ms | 455 ms | 455 ms |
| 16 | 32/32 | 407 ms | 926 ms | 929 ms |
| 32 | 64/64 | 530 ms | 1,349 ms | 1,381 ms |

All three warm-up GETs returned 200 (liveness, DB-backed readiness, correction
frontend JS). Live waves requested the reviewer login page (200), DB-backed
readiness (200), and an unauthenticated workspace (expected 401), as applicable.
No unexpected status, 429, 5xx or network timeout was observed. Render application
logs independently recorded these requests with
`SMARTPRO-bounded-readonly-staging-check/20261110` as User-Agent.

The **initial cold start** caused one warm-up GET to take about 15,011 ms, then
the site completed the initial and extended warmed ramps. This cost must be
considered separately from warm-request latency on Render Free.

Render Free instance at the time advertised **0.15 CPU and approximately
512 MiB memory**. Observed Render 30-second time-series samples around the
second run showed about 71 MB memory (not a real peak-memory measurement);
we do not infer available peak capacity or a production SLA from those samples.

## Scope and deliberately open gates

- **Verified:** actual hosted, read-only traffic handled up to 32 short-lived
  concurrent anonymous clients with zero unexpected responses in these two
  short ramp tests. Access boundary returned 401 without a session.
- **Not verified:** authenticated Student/Guide/Evaluator/Coordinator/HOD/Admin
  browser journeys, PDF submissions/downloads, concurrent academic writes,
  distinct sustained users, deadline spikes, deep query workloads, tail
  response times under a longer soak, realistic project volumes, accessible
  rich UI with assistive technologies, private PDF byte restore or institutional
  policy sign-off.
- The validated live service and Neon database were **not modified by this
  read-only harness**. It does not create synthetic projects or edit marks.
- This is a **bounded exploratory hosted baseline**, not formal peak capacity
  certification. Higher load should be planned using reversible synthetic
  data and an isolated environment before a carefully supervised hosted
  verification.
- No TinyFish paid browser minutes, paid infrastructure, free trial, or paid
  scaling were used. The two GitHub Actions runs were short-lived; no schedule
  or automatic recurring load test was installed.

**Reproduction:** `.github/workflows/hosted-readonly-ramp.yml` is manually
dispatchable on the default branch. It has **no push or schedule trigger**; authorized maintainers must
start it manually in GitHub Actions. It does not run on normal commits. No user secrets required. The source is
`scripts/hosted_readonly_ramp.py`.
