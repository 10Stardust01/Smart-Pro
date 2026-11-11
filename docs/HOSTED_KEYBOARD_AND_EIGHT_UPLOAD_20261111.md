# SMART-PRO — 11 November 2026 live reviewer keyboard and write-load evidence

## Five-role keyboard smoke: PASSED within a bounded scope

[GitHub Actions run #43066865472](https://github.com/10Stardust01/Smart-Pro/actions/runs/43066865472) used signed Chromium sessions in the actual Render Free reviewer site as Student, Faculty, Coordinator, HOD and Admin.

All five roles passed keyboard Tab access to the skip-to-main link, visible focus outline, Enter navigation to the main anchor and continuation of Tab focus into main content. The test made no academic writes. It checks only these keyboard mechanics; **it is not an actual human screen-reader examination, full form-error focus audit, screen-reader/PDF tagging assessment or institutional WCAG certification**.

## Bounded eight-client private PDF load: FAILED threshold and contention observed

[GitHub Actions run #43066015323](https://github.com/10Stardust01/Smart-Pro/actions/runs/43066015323) created one explicitly synthetic project under the existing reviewer staging course and attempted **eight simultaneous approximately 256 KiB private PDF uploads** from eight signed sessions of **the same** synthetic Student. The test's defined 10-second p95 stopping gate was breached: **p95 = 10.972 s** (max 10.972 s). The harness stopped immediately without progressing into its Student SUBMIT, Faculty draft/finalize or Coordinator publication races; it did not retry or auto-escalate concurrency.

Independent Render application logs for the exact wave show **two HTTP 200 successful uploads and six HTTP 409 conflicts**, zero recorded 5xx uploads. Read-only Neon verification found **two document versions** on that isolated test project, 31 READY file-asset rows across the staging environment at that checkpoint, and the original historical published project still at one overall release. A 409 can be a legitimate optimistic-concurrency defense; these observations do **not** demonstrate lost marks, corrupted files or that eight *independent* students uploading to *distinct* projects would have the same outcomes.

Time-aligned Render sampled metrics recorded CPU about 0.079 CPU at 17:14:00Z (reported Free limit 0.15) and memory roughly 111 MB by 17:14:30Z (limit about 537 MB). Such sparse samples cannot rule out short bursts, storage/network stalls, database locks or runner-side contention, so no definitive bottleneck root cause is claimed. Prior bounded tests with four simultaneous synthetic private PDF uploads passed; neither test establishes institutional peak capacity.

**Disposition:** The tested **same-project eight-session burst FAILS the 10-second p95 gate** and produces six explicit 409 responses. Leave representative sustained authenticated mixed-write/deadline capacity **OPEN**. Before fixing behavior or setting an SLA, agree on realistic numbers of distinct concurrent students, per-project document semantics and acceptance percentile. Do not silently relax conflict rules, change academic policy or purchase/activate paid infrastructure to claim success.

## Recovery still unverified

Current Neon object-storage metadata previously matched 29 READY source database assets to 29 keys/sizes, but a snapshot-created inspection branch contained no original private PDF objects. The original Neon staging branch was restored as default after an unexpected snapshot routing change, with historical data preserved. A new presigned GET from original private storage was attempted from the current container and failed on DNS resolution of the Neon private-storage hostname; **no original private object byte was retrieved or independently restored in that attempt**. Therefore, do not claim paired database/private PDF restore, a tested backup RPO/RTO or a verified full object recovery. Do not repeat snapshot restore on the active branch.

No paid services, free trials, academic policy, historical released marks or Render deployment configuration were changed by these checks.
