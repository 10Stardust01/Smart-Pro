# SMART-PRO — consolidated development checkpoint

> **Latest hosted reviewer checkpoint — 10 November 2026 (not institutional production):**
> Neon Free staging **main** now contains migrations **059–063**, with 061 → 062 → 063 installed as separate atomic transactions. Existing Render Free reviewer service manually deployed source commit **`0419358dc5a3c87d5ef5290909b7cbc00e59fb40`** ([PR #12](https://github.com/10Stardust01/Smart-Pro/pull/12)). All published-result, stage-result, audit and READY-file metadata digests remained unchanged. Permissioned Coordinator/Admin reads succeeded and unauthorized Student/Faculty reads were denied. The original pre-059 and new pre-061 recovery branches remain.
>
> **Still outstanding:** actual private PDF byte/hash restoration, independently verified paired database+file recovery, full authenticated hosted Guide → Coordinator → Student/Faculty browser acceptance, peak-load tests and institutional approval. PR #12 passed **five** checks; its sixth correction-browser check was **cancelled during Chromium installation at the 12-minute timeout**, so do not claim 6/6. No paid feature/trial was used. [Release evidence and open gates](https://github.com/10Stardust01/Smart-Pro/issues/4).


**10 November 2026 (IST).** This is a source-code consolidation checkpoint, **not** authorization to migrate Neon main, deploy Render, or activate real academic records. Historical notes remain preserved, but outdated deployment assertions do not override the current verified state.

## Current project and lineage

SMART-PRO is a **Django / Django REST Framework, PostgreSQL 16 and role-specific frontend** application. Student, Faculty Guide/Evaluator, offering Coordinator, HOD and Admin workspaces and milestones A–E remain part of one modular-monolith codebase. The old proof-of-concept statement that Django versus NestJS is undecided is historical, not a present architectural choice.

GitHub compare on 10 November showed `main` was **65 commits behind** the tested review head `9f1f0a0a4f60bdc9247b4ed2cb97ca6f73d9085e`, **zero commits divergent**. Those 65 commits contain the Render reviewer staging support, Milestone E frontend refinements and reviewed candidates 059, 060, 061, followed by verified forward-only 062 correction paging and candidate 063 scoped non-HOD Faculty management. Consolidation must merge the full ancestry, not just copy the most recent SQL file. This is the latest state **verified on GitHub**; any unpushed Windows working-copy changes remain unknown.

## Latest agreed product decisions (not necessarily faculty-ratified)

- Retain completed student registration/team/project/document workflows, private versions and feedback; Guide synopsis approval and reassignment history; flexible stage/evaluator responsibility and rubric configuration; Student and Faculty scoring/results, Coordinator queues, HOD oversight and Admin intake/authority. Preserve existing approved role scoping and academic evidence.
- Department-configured stage count, labels, evaluator responsibilities, marking scheme, quorum and publication are versioned and pinned. Do not hardcode two minor/major reviews or silently change historical review rules.
- HOD governs Admin appointments; Admin appoints offering Coordinators and may manage non-HOD faculty account details/appointments within the owner-approved scope. Last-Coordinator and normal HOD succession safeguards remain. Faculty reinstatement must **not** automatically restore historic project assignments without a separately approved decision.
- **Before overall publication**, existing stage-score correction authority applies, including explicitly authorized Coordinator contribution corrections. **After overall publication**, the assigned Project Guide may request (a) an exact corrected overall student mark or (b) a new overall release using **already corrected complete stage evidence**. Only the offering Coordinator approves/rejects; the same person may act as Guide, requester, evaluator and Coordinator. No mandatory extra approver, HOD escalation, independent approval or separate apply operation. Approval appends an immutable overall-result version without overwriting original stage scores, published release or audit. No student in-app mark-flag feature is added.
- Faculty reference and CSV/XLSX imports are separate from authoritative identity and appointment data; official matching must be verified and audited. Avoid arbitrary permanent dataset caps; existing paginated queues and intake remain. **Candidate 062 now supplies scoped 25-row exceptional-correction pages**, tested with 126 requests and 126 extra Guide projects in [PR #6](https://github.com/10Stardust01/Smart-Pro/pull/6). The older 061 all-project compatibility response remains unchanged; larger concurrent load and hosted acceptance remain open.

## Verified source versus hosted rollout

| Surface | Verified status as of 10 November 2026 | Required next step |
| --- | --- | --- |
| GitHub development | Milestones A–E and candidates **059–063** consolidated in `main` (`57881021`, merged PRs #5–#7); 063 adds scoped non-HOD Faculty details and audited term management | Six of six PR #7 checks passed; source merge does not authorize Neon migration or Render deployment |
| Render reviewer | `smartpro-reviewer-25775915`, Free Docker Singapore; auto-deploy off; `deployment/reviewer-staging` live SHA `319e3ebc1368745fcc7f2afe61d47a7bb202335a` | Explicit controlled deployment and authenticated hosted acceptance |
| Neon `smartpro_staging` main | Original direct correction **059 present**, stage-evidence extension **060 present**, Guide/Coordinator read-projection **061 absent** | Preserve rows and perform versioned 061 preflight/recovery before approved release |
| Neon validation | Existing `smartpro-059-validation-20261109` now has 059–063, with 061 → 062 → 063 applied atomically and published-result/audit metadata unchanged | Schema rehearsal **completed**. Hosted paired database/private PDF restore and live release still open ([evidence](NEON_061_063_VALIDATION_20261110.md)) |
| Real institutional use | Not approved; reviewer sessions use synthetic identities | Official account/identity mapping, private file recovery, privacy, accessibility, department sign-off |

Read-only Neon sampling showed **1 overall result version, 1 stage version, 0 correction requests and 67 audit rows** on each checked branch; this is **not** a complete DB/PDF recovery proof. Preserve `smartpro-pre-059-rollback-20261109` and `smartpro-059-validation-20261109`. **Never re-run 059 or 060 on those installed environments** or restore an old snapshot over live records. See [issue #4](https://github.com/10Stardust01/Smart-Pro/issues/4) for forward-only staging/recovery gates.

## Verification and remaining work

At review head `9f1f0a0a`, GitHub Actions reported five successes: PostgreSQL schema, Django compatibility, curriculum membership, Student API, and actual Django/Chromium published-result correction. The latter passed Guide → Coordinator → Student direct and signed-HTTPS stage-evidence journeys against disposable PostgreSQL, plus public hosted liveness/readiness, login/CSRF, anonymous access denial and frontend asset smoke. **Public anonymous smoke is not authenticated hosted correction acceptance**. Earlier A–E and measured load evidence remain scoped to their reported fixtures; see [requirements register](REQUIREMENTS_COMPLETION_REGISTER.md), [repository status](REPOSITORY_STATUS.md), and [capacity baseline](CAPACITY_BASELINE.md).

Open technical work: hosted acceptance for [paginated correction discovery #3](https://github.com/10Stardust01/Smart-Pro/issues/3), [controlled 061 release plus paired database/PDF recovery #4](https://github.com/10Stardust01/Smart-Pro/issues/4), hosted Faculty account acceptance and approved rules for resolving active project assignments at Faculty termination/reinstatement, multi-department deadline/concurrency testing and accessibility. External gates: institution-selected production identity, verified faculty/student mapping, approved academic settings, privacy/retention, storage recovery and named HOD emergency succession operator.

**Decision precedence:** latest explicit owner-approved direction → matching reviewed behavior and test evidence → this checkpoint and requirements register → historical prototype assumptions. Never declare feature completeness beyond its verified environment. Merging source into main does **not** deploy to Render, migrate Neon or authorize institutional use.
