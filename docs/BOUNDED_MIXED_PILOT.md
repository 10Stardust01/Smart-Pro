# Bounded real-hosted mixed-role academic pilot (manual only)

**Status: PREPARED, NOT YET RUN.** There is no claim of a measured result until a real GitHub Actions run is explicitly started and its logs are examined.

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
