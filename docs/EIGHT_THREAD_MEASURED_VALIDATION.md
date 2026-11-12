# One controlled eight-thread staging measurement — acceptance record

**State: PREPARED, NOT EXECUTED.** Do not merge this marker until the reviewer staging deployment is Live with `SMARTPRO_GUNICORN_THREADS=8`, using the bounded 4/6/8 allowlist from PR #55 and reviewer-staging PR #56. There is still just one worker on Render Free. The test must use only the **eight existing independent synthetic Student actor IDs and projects**, exactly two prior documents/attempts per project; no duplicate teams or projects.

## Baseline, four request threads

[Hosted test #43195738956](https://github.com/10Stardust01/Smart-Pro/actions/runs/43195738956) passed 8 Guide REQUEST_CHANGES, 8 fresh 128KiB uploads with matching downloaded SHA-256, 8 independent resubmissions and 480/480 authenticated reads, with read p95 **1.882s**. Per-tier read p95 at 8/16/24 sessions was **0.891/1.330/1.963s**. Concurrent upload p95 **5.641s** missed the unchanged **5.000s** goal. Server upload traces showed S3 write substeps spanning **65.8–3572.7ms**, whereas PDF validation was **246.4–402.4ms** and finalize SQL **10.4–101.2ms**. The service ran one Gunicorn worker with four request threads.

## Post-tuning acceptance

With eight request threads, the same harness preflights precisely two original submissions and its assigned Faculty Guide in eight existing synthetic projects, performs a legitimate Guide REQUEST_CHANGES, then a *third* document version upload and submission. The 8 concurrent 128KiB uploads, private SHA-256 checks and 480 paced reads in 8/16/24-session tiers are the exact functional targets. It retains upload p95 **≤5.000s**, submission p95 **≤3.000s**, and pooled read p95 **≤2.000s**, with zero HTTP/role errors. It logs actual individual upload wall times and server substep timings. Even if successful it is not a campus-wide hundred-student load test: it has only eight distinct Student actors and up to 24 sessions.

Stop on unexpected case state, missing Guide authority, non-200, >5s repeated reads, or performance breach. Do **not** relax thresholds or silently relaunch just to obtain a pass. Afterward, disable staging-only aliases and timing diagnostics and restore four Gunicorn threads unless eight-thread metrics justify a separately reviewed retained setting. Original project history remains immutable and auditable; no paid services/trials or free-plan upgrades.
