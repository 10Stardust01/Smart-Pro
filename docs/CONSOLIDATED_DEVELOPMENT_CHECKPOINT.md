# SMART-PRO — consolidated development checkpoint

**10 November 2026 (IST).** This is a source-code consolidation checkpoint, **not** authorization to migrate Neon main, deploy Render, or activate real academic records. Historical notes remain preserved, but outdated deployment assertions do not override the current verified state.

## Current project and lineage

SMART-PRO is a **Django / Django REST Framework, PostgreSQL 16 and role-specific frontend** application. Student, Faculty Guide/Evaluator, offering Coordinator, HOD and Admin workspaces and milestones A–E remain part of one modular-monolith codebase. The old proof-of-concept statement that Django versus NestJS is undecided is historical, not a present architectural choice.

GitHub compare on 10 November showed `main` was **65 commits behind** the tested review head `9f1f0a0a4f60bdc9247b4ed2cb97ca6f73d9085e`, **zero commits divergent**. Those 65 commits contain the Render reviewer staging support, Milestone E frontend refinements and reviewed candidates 059, 060, 061. Consolidation must merge the full ancestry, not just copy the most recent SQL file. This is the latest state **verified on GitHub**; any unpushed Windows working-copy changes remain unknown.

## Latest agreed product decisions (not necessarily faculty-ratified)

- Retain completed student registration/team/project/document workflows, private versions and feedback; Guide synopsis approval and reassignment history; flexible stage/evaluator responsibility and rubric configuration; Student and Faculty scoring/results, Coordinator queues, HOD oversight and Admin intake/authority. Preserve existing approved role scoping and academic evidence.
- Department-configured stage count, labels, evaluator responsibilities, marking scheme, quorum and publication are versioned and pinned. Do not hardcode two minor/major reviews or silently change historical review rules.
- HOD governs Admin appointments; Admin appoints offering Coordinators and may manage non-HOD faculty account details/appointments within the owner-approved scope. Last-Coordinator and normal HOD succession safeguards remain. Faculty reinstatement must **not** automatically restore historic project assignments without a separately approved decision.
- **Before overall publication**, existing stage-score correction authority applies, including explicitly authorized Coordinator contribution corrections. **After overall publication**, the assigned Project Guide may request (a) an exact corrected overall student mark or (b) a new overall release using **already corrected complete stage evidence**. Only the offering Coordinator approves/rejects; the same person may act as Guide, requester, evaluator and Coordinator. No mandatory extra approver, HOD escalation, independent approval or separate apply operation. Approval appends an immutable overall-result version without overwriting original stage scores, published release or audit. No student in-app mark-flag feature is added.
- Faculty reference and CSV/XLSX imports are separate from authoritative identity and appointment data; official matching must be verified and audited. Avoid arbitrary permanent dataset caps; existing paginated queues and intake remain. **Two inherited 100-record exceptional-correction read limits are unresolved**, tracked in [issue #3](https://github.com/10Stardust01/Smart-Pro/issues/3).

## Verified source versus hosted rollout

| Surface | Verified status as of 10 November 2026 | Required next step |
| --- | --- | --- |
| GitHub development | Reviewed through 061, full HTTPS synthetic correction browser test, hosted read-only smoke fix; five CI workflows green at `9f1f0a0a` | Consolidate complete ancestry into main; keep review history |
| Render reviewer | `smartpro-reviewer-25775915`, Free Docker Singapore; auto-deploy off; `deployment/reviewer-staging` live SHA `319e3ebc1368745fcc7f2afe61d47a7bb202335a` | Explicit controlled deployment and authenticated hosted acceptance |
| Neon `smartpro_staging` main | Original direct correction **059 present**, stage-evidence extension **060 present**, Guide/Coordinator read-projection **061 absent** | Preserve rows and perform versioned 061 preflight/recovery before approved release |
| Neon validation | Existing `smartpro-059-validation-20261109` also has 059/060 but lacks 061 | Apply *only 061* after separately authorized validation-branch change; preserve recovery branches |
| Real institutional use | Not approved; reviewer sessions use synthetic identities | Official account/identity mapping, private file recovery, privacy, accessibility, department sign-off |

Read-only Neon sampling showed **1 overall result version, 1 stage version, 0 correction requests and 67 audit rows** on each checked branch; this is **not** a complete DB/PDF recovery proof. Preserve `smartpro-pre-059-rollback-20261109` and `smartpro-059-validation-20261109`. **Never re-run 059 or 060 on those installed environments** or restore an old snapshot over live records. See [issue #4](https://github.com/10Stardust01/Smart-Pro/issues/4) for forward-only staging/recovery gates.

## Verification and remaining work

At review head `9f1f0a0a`, GitHub Actions reported five successes: PostgreSQL schema, Django compatibility, curriculum membership, Student API, and actual Django/Chromium published-result correction. The latter passed Guide → Coordinator → Student direct and signed-HTTPS stage-evidence journeys against disposable PostgreSQL, plus public hosted liveness/readiness, login/CSRF, anonymous access denial and frontend asset smoke. **Public anonymous smoke is not authenticated hosted correction acceptance**. Earlier A–E and measured load evidence remain scoped to their reported fixtures; see [requirements register](REQUIREMENTS_COMPLETION_REGISTER.md), [repository status](REPOSITORY_STATUS.md), and [capacity baseline](CAPACITY_BASELINE.md).

Open technical work: [scalable correction discovery #3](https://github.com/10Stardust01/Smart-Pro/issues/3), [controlled 061 release plus paired database/PDF recovery #4](https://github.com/10Stardust01/Smart-Pro/issues/4), limited non-HOD faculty account administration, multi-department deadline/concurrency testing and accessibility. External gates: institution-selected production identity, verified faculty/student mapping, approved academic settings, privacy/retention, storage recovery and named HOD emergency succession operator.

**Decision precedence:** latest explicit owner-approved direction → matching reviewed behavior and test evidence → this checkpoint and requirements register → historical prototype assumptions. Never declare feature completeness beyond its verified environment. Merging source into main does **not** deploy to Render, migrate Neon or authorize institutional use.
