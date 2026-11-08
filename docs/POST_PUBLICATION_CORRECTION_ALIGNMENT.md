# Post-publication correction alignment — 9 November 2026

## Decision authority and scope

The user-approved (not faculty-ratified) product decision is specific:
the **currently assigned Project Guide** may submit a correction request to
a project result **after overall result publication**. The responsible,
currently appointed offering **Coordinator** can approve or reject it even
if the Coordinator evaluated the marks, requested it, or is the Guide.
No independent authorizer, extra HOD, committee or self-approval ban is
added. The exact requested change, request reason, authority, previous
published result, revised result, and audit evidence must be retained.

Ordinary pre-overall-publication corrections are **not** silently changed.
Department review configurations, stage/evaluator responsibilities, rubrics,
marking mode, quorum, weights and publication rights remain versioned and
must continue to be respected. Do not give Admins or students grading powers.

## Confirmed repository discrepancy

Existing candidate 038/042 SQL and frontend reject original-requester or
panel-member authorization for exceptional published corrections as well
as ordinary ones. Installed Neon staging routines still contain those
restrictions. The reviewer-staging branch is live at `0d5281e`.

## Prepared, not installed

The isolated forward migration
`proposals/curriculum/059_published_correction_authority.sql`:

1. Permits a current Coordinator with correction responsibility to decide
   an **exceptional** stage change despite being the evaluator/requester.
   Ordinary stage-correction authorization remains unchanged.
2. Permits the same Coordinator to authorize an exceptional overall revision
   despite participating or having originated the request.
3. Permits the current assigned Guide, with a live Faculty responsibility,
   to request an exact revised overall release **after its supporting stage
   evidence is updated**. The calculation still uses pinned framework
   sources, not arbitrary total override.
4. Permits the approving Coordinator, if independently authorized to
   publish by the pinned framework and current appointment, to apply that
   exact overall request. Previous releases remain immutable.

Existing version checks, request records, authorization rows, calculated
snapshot equality, immutable result append and transaction/audit rules remain.
No new tables, default academic settings, HOD approval or student flags are
introduced. Existing historic migration candidates 001–058 are unchanged.

## Acceptance checks before any staging change

- Disposable PostgreSQL 16 install through 059; no live database writes.
- Same Guide/evaluator/Coordinator requests, authorizes and applies an
  exceptional stage and overall correction. Original result preserved.
- Guide and Coordinator are different: Guide requests exact overall change;
  appointed Coordinator approves and publishes.
- Ordinary prepublication self-authorization remains blocked.
- Forged/expired guide, foreign offering, unappointed coordinator,
  stale result version, changed stage scores, declined decision and replay
  remain denied or idempotent as applicable.
- Browser tests of authorization panels, reviewer session, role switching,
  stage history and overall result history. Queue permission and final revision
  authorizer projection are included in candidate 059; the Guide-only frontend
  request entry point remains to be verified.
- Verify live storage and DB backups together before any eventual migration.

## Genuine remaining question

**Does the Guide need to be able to request new criterion marks/overall
student totals *before* the underlying evaluator's stage result has been
corrected, or only request the release of already corrected, verified
stage evidence?** Existing course calculations forbid inventing new marks
outside approved rubric/evaluator evidence. Candidate 059 keeps that
constraint; a direct score-proposal interface needs an explicit product
decision so it cannot silently bypass approved academic evaluation.

## Other readiness gaps

The register links historical evidence; most older `Verified` rows are
verified in synthetic local tests, not the current Render/Neon combination.
Live free-tier hosting exists, but institutional onboarding/identity,
faculty appointment amendment authority, provider-specific backup/recovery,
PDF isolation, screen-reader verification, formal capacity acceptance and
academic-rule ratification remain separate gates. Do not activate real
student/academic records or use paid/trial services.
