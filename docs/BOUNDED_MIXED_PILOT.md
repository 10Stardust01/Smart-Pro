# Bounded real-hosted mixed-role academic pilot (manual only)

**Status: COMPLETED — bounded hosted mixed-role pilot PASSED 12 November 2026.** [Manual GitHub Actions run #43132925649](https://github.com/10Stardust01/Smart-Pro/actions/runs/43132925649), using the existing Render Free reviewer and synthetic Student/Faculty/Coordinator identities, passed with no paid services or new trials. Cold-start readiness succeeded; this startup latency is excluded from operation metrics. Signed workspace probes: **27/27 HTTP 200** (9 per role), pooled p95 **0.944s**, maximum **1.197s**. Concurrent two-client write p95: ~256KiB private PDFs **3.735s**, competing Student submissions **0.419s**, Faculty draft marks **0.324s**, Faculty finalization **0.336s**, Coordinator stage publication **0.393s**. All five write waves met provisional goals and expected conflict handling; private downloaded PDF SHA-256 matched upload. Read-only Neon verified exactly one new synthetic project, two READY files, one submitted attempt, one FINALIZED assessment, one stage result version and one ACADEMIC_PUBLISH audit event; the count of pre-existing overall final-result versions remained at eight. This **passes this specific low-concurrency mixed-workload profile only**; it is not evidence of distinct-user, sustained, high-volume deadline capacity, larger historical correction paging, complete private-PDF recovery, or human accessibility approval. **Do not rerun this passing pilot** without a newly defined separate diagnostic goal.

### Historical failed cold-start attempt and corrected startup probe

**Status: FIRST MANUAL RUN HALTED BEFORE WRITES; FIXED COLD-START PROBE PENDING RE-EXECUTION.** [GitHub Actions run #43089522963](https://github.com/10Stardust01/Smart-Pro/actions/runs/43089522963) completed with failure on 12 November 2026: offline preflight passed, then the first 10-second `/health/ready` probe raised `ReadTimeout`. Render's own Gunicorn startup logs show the server starting at 19:41:42 UTC, two seconds after the timeout at 19:41:40 UTC. Neon readback after that run matched its pre-run 124 projects, 8 overall-result versions, 39 READY file records and 412 audit events. **No synthetic project or academic write was created by this failed run**, and no performance result may be inferred from it.

The updated harness makes up to **three** read-only startup probes, each with a **30-second** maximum and **two** possible five-second delays; expected temporary 502/503/504 statuses are retried only during startup. An unexpected HTTP status fails closed. The startup allowance is **not included in academic write/read latency metrics**, and existing 1.5s/3s/5s provisional goals, two-writer wave caps, 45 observer GET cap and stop-on-error rules are unchanged. **Only a new manual run can verify this code**; no automatic replay is scheduled.


## Scope and safeguards

- Test target is the **actual owned SMART-PRO Render Free reviewer** and existing Neon Free reviewer database. No fake endpoint, dedicated trial service, cloud upgrade, paid tools, TinyFish, proxy, or additional outside accounts are used.
- Uses the existing private GitHub Actions secret `SMARTPRO_HOSTED_TEST_ACCOUNTS` and **three existing synthetic role identities** (Student, Faculty, Coordinator). They are **not** distinct real students. No credentials are printed or copied to repository files.
- Workflow is manual-only, no schedule, no retry or load ramp. Fixed synthetic department/offering/team/faculty IDs, exact manual approval phrase, TLS verification, no custom host inputs, read-only GitHub token, and shared concurrency lock with other synthetic hosted write workflows.
- Creates **one explicitly marked new synthetic project** under an existing verified synthetic Student team. Its audit records and PDF evidence remain permanent; no existing academic project, result, policy, team membership or faculty authority is deleted or altered.
- Reuses the proven academic-write harness to test two ~256 KiB simultaneous private-PDF uploads with downloaded SHA-256 verification; two competing Student submissions (expect HTTP 200/409); two concurrent Faculty draft saves (200/409); two Faculty finalizations (200/409); and two competing Coordinator stage publications (200/409), followed by exact-once released-result verification.
- Adds up to **45 additional signed GETs** across Student, Faculty and Coordinator sessions while the write harness runs; **three concurrent read requests at most**, no retries. Existing writer harness runs only two competing writers per wave. This is one **small mixed-workload pilot** and *not* an institutional peak-load, distinct-student, high-volume historical paging or sustained-capacity certification.
- Reports per-operation observed p95 (two writes means p95 is effectively the slower request), read role p95, 5xx/conflicts, and integrity. Provisional objectives: read p95 <=1.5s, typical write-wave p95 <=3s, ~256KiB PDF upload-wave p95 <=5s. The existing harness also stops on a 10-second safety ceiling; that ceiling is **not** the normal performance goal. A run with correct records but slow responses is reported as a performance failure, not falsely as total success.
- Never change Render deployment, Neon default branch, GitHub billing/permissions, or institutional roles.

## One-time manual run

1. Open the repository **Actions** tab; select **SMART-PRO bounded mixed-role academic pilot (manual, Free)**.
2. Select **Run workflow**, keep branch `main`, and enter approval `RUN_ONE_BOUNDED_MIXED_PILOT`.
3. Run **once**. No need to paste any passwords, credentials, or other UUIDs.
4. Check logs for `PILOT_FUNCTIONAL_PASS`, `PILOT_READS`, five `PILOT_WRITE_PHASE` entries, and either `PASS_BOUNDED_MIXED_PILOT` or `PILOT_PERFORMANCE_GAP`. A red workflow can be an observed latency breach; inspect the phases before interpreting it as data corruption.

**If the five waves do not finish, stop.** Do not rerun without diagnosing whether the synthetic team, stage settings, authentication, or HTTP status behavior has changed. No automatic retries or load increases.

## What this does not complete

It does not replace a realistic multi-identity peak-deadline exercise, a high-volume corrections pagination fixture, human screen-reader acceptance, or independently restored original private-PDF bytes. Keep those separate and do not claim closure from this pilot.
