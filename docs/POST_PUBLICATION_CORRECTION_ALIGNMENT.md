# Direct overall-result correction — finalized product direction

> **Latest hosted reviewer checkpoint — 10 November 2026 (not institutional production):**
> Neon Free staging **main** now contains migrations **059–063**, with 061 → 062 → 063 installed as separate atomic transactions. Existing Render Free reviewer service manually deployed source commit **`0419358dc5a3c87d5ef5290909b7cbc00e59fb40`** ([PR #12](https://github.com/10Stardust01/Smart-Pro/pull/12)). All published-result, stage-result, audit and READY-file metadata digests remained unchanged. Permissioned Coordinator/Admin reads succeeded and unauthorized Student/Faculty reads were denied. The original pre-059 and new pre-061 recovery branches remain.
>
> **Still outstanding:** actual private PDF byte/hash restoration, independently verified paired database+file recovery, full authenticated hosted Guide → Coordinator → Student/Faculty browser acceptance, peak-load tests and institutional approval. PR #12 passed **five** checks; its sixth correction-browser check was **cancelled during Chromium installation at the 12-minute timeout**, so do not claim 6/6. No paid feature/trial was used. [Release evidence and open gates](https://github.com/10Stardust01/Smart-Pro/issues/4).


> **Updated 10 November 2026:** reviewed GitHub main includes candidates
> **059–063**; the signed-HTTPS Guide → Coordinator → Student correction flow
> passed on disposable PostgreSQL. Neon **main** has 059/060 only, whereas
> the existing Neon **validation branch** successfully installed 061 → 062 →
> 063 without changing published releases, audit rows or file metadata.
> Render reviewer staging remains at `319e3ebc` (Free, auto-deploy off).
> Earlier 059/060 upgrade descriptions below are **historical**, not current
> execution instructions. **Never reapply 059/060** on these installed targets;
> hosted migration must first pass paired private-PDF/database recovery.
> See [validation evidence](NEON_061_063_VALIDATION_20261110.md) and
> [release gate #4](https://github.com/10Stardust01/Smart-Pro/issues/4).

SMART-PRO remains a project lifecycle and academic evaluation platform, not a
faculty HR application.

After an overall result is published, its **currently assigned Project Guide**
can propose an exact corrected **overall mark for a student** with a reason.
The responsible offering **Coordinator** approves or rejects the specific
request, even if the Coordinator is the Guide, requester or original evaluator.
No HOD, independent approver, extra authorization or separate apply action.

Approval appends a new `course_final_results` version in the SAME transaction.
Previous results and the existing published review-stage scores stay immutable.
The correction's exact old/new mark, student, reason, actor, approval, preceding
result ID and successor version remain in the existing request,
authorization/application, result and audit records. The recorded stage
sources are copied unchanged as provenance; the new overall result is an
**authorized exceptional correction**, not represented as a new calculation
of unchanged stage marks. Declining a request does not alter the result.

Candidate `059_published_correction_authority.sql` on the review branch replaces
the previous proposed stage-recalculation 059; candidates 001–058 and live Neon
are untouched. Backend `REQUEST_FINAL_REVISION` now carries project ID,
expected published version, student ID, new overall mark and reason.
`AUTHORIZE_FINAL_REVISION` records the Coordinator decision and, if approved,
immediately issues the corrected result. Previously exposed exceptional stage
API aliases and `APPLY_FINAL_REVISION` are rejected.

A Guide sees the correction form from their Project work page; the Coordinator
sees pending decisions under course Results. UI access is supported by server
authorization and exact current role/assignment checks.

**Status: isolated acceptance passed, not deployed.** [GitHub CI run 42549200764](https://github.com/10Stardust01/Smart-Pro/actions/runs/42549200764)
installed candidate 059 on disposable PostgreSQL 16, exercised direct request,
rejection, same-person approval, idempotency and stale/forbidden operations,
and launched the **real Django application and frontend in Chromium** with
its own isolated database. The Guide submitted through Project work, the
Coordinator approved from Course Management, and the Student saw both the
original and new overall result versions. Regression checks confirmed the
original stage/source evidence was unchanged. This is not a mocked-API UI test.
The existing Render reviewer deployment, live Neon data, and original release
records have **not** been modified. Hosted reviewer session testing, backup
restore rehearsal and explicit deployment authorization remain separate gates.
No new infrastructure, paid plan, or trial was used.

Other project decisions stand: configurable/pinned review stages and rubrics,
scoped Guide/evaluator responsibilities, prior version history and minimal
Admin account/access controls. No student marks-flagging feature or invented
approval role has been added.

## Guide requests from already-corrected stage evidence

A Guide may also request a revised overall release based on **already corrected** complete published stage evidence. The request pins the new stage sources and calculated totals. The same responsible Coordinator decides it, including when also the Guide/evaluator. Approval appends an overall version only if the pinned stage evidence still matches. This path never edits stage marks or invents an evaluator authorization. No-change requests are rejected.

**Verified in isolated PostgreSQL/API regression:** [CI run 42561282815](https://github.com/10Stardust01/Smart-Pro/actions/runs/42561282815) at `c0564cc` passed the correction contracts and real Django/Chromium direct-correction acceptance. The stage-evidence contract asserts a previously corrected stage release is pinned, the Coordinator publishes its matching source IDs and results, the prior overall release is immutable, no-change attempts are rejected, and direct overall mark overrides are not misidentified as changed stage evidence. This mode's separate frontend form has not yet had an independent browser click-through test. All checks used a disposable synthetic database; there has been no hosted migration or live data change.

## Existing Neon staging upgrade safety — 9 November 2026

The `smartpro_staging` Neon main branch already contains the **original 059**
direct correction functions; `smartpro_guide_final_corrections` and the
`course_final_revision_requests.reason` column are present. The main branch
**does not** yet contain the later `STAGE_EVIDENCE_OVERALL_CORRECTION` function
body. Therefore a new `060_published_stage_evidence_rerelease.sql` forward
upgrade is required. Do NOT re-run 059 in place. The existing same-project
recovery branches include `smartpro-pre-059-rollback-20261109` and
`smartpro-059-validation-20261109`; preserve both. Treat the main branch
as live and do not replace existing data or copy an older backup over it.

Candidate 059 in repository is restored to its original already-installed form.
Candidate 060 replaces only the reviewed `smartpro_course_final_revision`
function body (same signature and privileges). Run it first on the existing
validation branch; verify original result versions, audit history, the mode
marker and deployed code compatibility. Recheck free-tier and service identity
before updating the live main branch. A failed preflight must stop release.

## 061 read-model alignment for stage-evidence requests

The real HTTPS staging-auth browser regression uncovered that 060 successfully
created an authorized stage-evidence request but the old 059 read projections
only included DIRECT_AUTHORIZED_OVERALL_CORRECTION, leaving the Guide unaware
of the pending request and the Coordinator without the decision row. Forward-
only candidate 061 changes **only** the two scoped read functions to include
both exceptional types and the exact request mode; it does not change academic
policy, decision authority, released marks, or original stage evidence. This
is covered by a PostgreSQL API visibility regression and an actual HTTPS,
signed-session, Chromium Guide → Coordinator → Student acceptance test against
a disposable synthetic database.
