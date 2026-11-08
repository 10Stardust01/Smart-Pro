# Cumulative integration review — 4 November 2026

Reviewed main `193c095` through PR #10 `8defb98`, current SQL/services/tests,
actual PR metadata, reviews, effective synthetic grants and CI. This review
adds three focused corrections to #10; it creates no additional feature branch.
No merge, deployment, real academic data or institutional approval is authorized.

## Assessment and findings

The cumulative backend is suitable for **inert source integration after the
corrected #10 checks and explicit merge authorization**, with manual review gates
below. It is not suitable for real-user activation. No uncorrected public API
authorization bypass was found within the reviewed synthetic/trusted-server scope.
This is an independent code-and-execution pass, not independent human approval.

| Severity / disposition | Finding |
| --- | --- |
| High, corrected in #10 | Candidate 010 preparation accepted baseline 001–008 without 009's historical guards. A real older-schema probe reproduced this; preparation now requires the 009 guard functions before any change. |
| High, corrected in #10 | Candidate 012 used statement-start time after an offering lock wait. Both role expiry and visibility expiry still admitted a team. Reproduced with two real lock-wait probes; recheck effective time before admission and stamp the new membership with that time. |
| High, corrected in #10 | Candidate 015 latched only future evidence inserts. Removing a draft that existed before installation reopened title correction. Reproduced through the staff API; installation now latches existing evidence before releasing its project lock. |
| Integration gate | All eight implementation PRs are draft, with no submitted reviews. Exact-head CI succeeded before this review; corrected-head results are linked in #10. Obtain explicit authorization and a human review before integration. |
| Integration gate | Branch API reports `protected:false`, despite saved postgres/Django check metadata. Protection inspection returns 403 (integration access); rulesets return 403 requiring Pro/public. Enforcement is unverified; a human must enforce all checks manually or verify supported protections. Do not change visibility or subscription automatically. |
| Real-user activation blocker | Demo identities are header-selected synthetic principals behind two gates. Production rejects them. A verified identity provider/account mapping and deployment security are still required. |
| Real-user activation blocker | Shared runtime is a trusted-service capability, not per-user SQL/RLS. Legacy synopsis SELECTs and direct inserts/column updates remain; audit/idempotency/outbox inserts can be forged with stolen DB credentials. New registration/staff receipts and authority tables are private. Encapsulate sensitive legacy commands and inventory deployed role inheritance before real use. |
| Rollout blocker | Synthetic logical recovery is tested; unknown real legacy mappings, mixed-curriculum teams, grants, data volumes, storage and crash/PITR recovery are not certified. |
| Deferred | Guide allocation, evaluator policy, institutional grading/release/amendment rules, production load/monitoring/storage scanning and connected UI are separate work. No speculative implementation added. |

## Verified behavior and execution

| Executed locally in isolated PostgreSQL 16 databases | Result |
| --- | --- |
| Full API suite plus initial 14 review probes | 212 passed |
| Final review probes, including missing baseline 009 | 15 passed (overlaps preceding row) |
| Curriculum contracts | 39 passed |
| Database/synopsis regressions | 97 passed, four existing institutional skips, one existing deprecation warning |
| Django unit tests / compatibility probe | Six passed / all 14 checks passed |
| Ruff F/E9, SQL static checks, diff whitespace | Passed |

Corrected-head CI must collect **213 API cases**, including all 15 review probes.
Exact commit and workflow links/results are maintained in PR #10; older green CI
is not approval of these corrections. Both corrections' expiry probes and the
legacy-evidence probe, plus the baseline prerequisite probe, failed before fixes.

- Trusted-principal profile/offering reads, team creation/discovery, join/leave/
  same-offering transfer, multiple project registrations per team and scoped reads.
- Exact-role, effective departmental staff delegation; publication windows,
  immutable team-policy versions, approved registration bindings, project discovery
  and explicitly enabled initial-title correction. No implicit faculty/guide/HOD/
  TECH_ADMIN powers. Unknown registration rules fail closed.
- Atomic command/audit/receipt persistence; policy/project optimistic revisions,
  capacity serialization, temporal exclusion, bounded whole-transaction retries,
  revocation/expiry checks and immutable membership/registration/academic evidence.
- Full local regression results and final CI are recorded in #10 and the status
  document. Additional review probes cover real expiry lock waits, legacy evidence,
  prerequisite rollback, failed preflight/repair, full 010–015 install and a combined
  staff publication → team creation → registration → correction → transfer → leave
  → rejoin workflow. Original registration receipts survive title correction and
  membership changes; current student visibility follows current membership.
- `pg_dump`/`pg_restore` at both prepared and activated checkpoints compares every
  public table's restored rows exactly, then resumes prepared installation through
  015. This checks synthetic logical recovery, not real-data crash recovery/PITR.
- Fresh installation leaves publication windows, membership/registration bindings,
  staff controls and grants empty. Runtime cannot configure them directly. HTTP
  gates, departmental enablement and correction enablement have negative tests.
  Application environment switches are server controls, not SQL authorization;
  authenticated actor arguments must never come from a client or direct DB access.

## SQL rollout and recovery boundary

Keep application writers stopped for the entire owner-run operation. Validate
backup restoration and actual grants first. Apply unchanged baseline 001–009,
then reviewed runtime read boundary followed by runtime write boundary. Prepare
010, explicitly map every historical team and verify every member profile, run
all preflight result sets, then activate 010. Apply 011 → corrected 012 → 013 →
014 → corrected 015. These remain candidates outside automatic migrations.

Missing prerequisites abort their candidate transaction without partial catalog
changes. Preflight reports do not themselves prevent activation: activation
independently rejects unmapped teams, missing profiles, incompatible current/
scheduled memberships and overlapping historical intervals. Roll back a failed
transaction, diagnose/repair only approved mappings, rerun preflight and retry.
Do not truncate evidence, disable triggers, invent USNs or rewrite membership
intervals to make a migration pass. When mapping is unsafe, restore the verified
backup in isolation; do not attempt destructive down-migrations over new evidence.
The corrections change only unreleased candidates 010 prepare/012/015; 001–009 are untouched.
An already provisioned synthetic DB must be rebuilt from the corrected candidates
or receive a separately reviewed forward repair; rerunning CREATE scripts is not
an upgrade mechanism. Source merge never activates any SQL or policy.

## Exact integration sequence (after authorization)

1. Freeze new feature work; pin all reviewed heads. Keep every API rollout switch
   disabled and prohibit candidate activation throughout source integration.
2. Merge **#2 → #4 → #5 → #6 → #7 → #8 → #9 → #10**, using merge commits to preserve
   ancestry. Keep dependency branches until their children are retargeted. Avoid
   squash/rebase unless the entire remaining stack is deliberately reconstructed.
3. After each predecessor merge, retarget its immediate child to current main,
   merge current main into that child if needed, and run checks on the resulting
   exact head/merge result. Resolve conflicts by preserving both contracts; do not
   blindly take one side. Require refreshed review after any material change.
4. Required jobs at every step: `postgres-validation`, `django-compatibility`,
   `curriculum-contracts`, and from #4 onward `student-api`. Verify current main
   checks after each merge before proceeding. A missing/stale/skipped/failed check
   is not success; base retargeting alone may not trigger all workflows, so ensure
   a new synchronized commit or explicit dispatch/run is actually checked.
5. At #10 require the full cumulative API suite including this review's 15 probes,
   all existing regressions, compatibility, privilege/static checks and both
   synthetic backup/restore checkpoints. Rerun on final main after integration.
6. #3 is independent documentation. Review/merge separately only while its explicit
   unratified/not-implemented labels remain; it must never activate academic rules.

The intermediate #5 team path lacks the expiry correction until corrected #10;
#6/#7 add required legacy grant/lock hardening. Do not enable partial-stack features.

## Before connected frontend implementation

Synthetic UI work can start from the consolidated, checked main and existing API
contracts. Confirm the frontend source location (no tracked React package is in
this checkout), endpoint origin/proxy, principal/profile bootstrap, stable error
handling, UUID cursors, idempotency-key persistence and revision-conflict refresh.
Staff UI must not infer rights from a role label or expose an owner/grant/policy-
approval path that the backend does not provide. It must handle 403/409/503 safely.

Before connecting real accounts: settle verified login/account linkage and intake,
ratify who provisions/revokes effective staff grants and departmental enablement,
approve applicable windows/team-size modes/registration policy versions, and pass
deployment/SQL-security/staging recovery gates. Historical amendments, quorum,
aggregation, retrospective eligibility and primary-guide rules remain unratified
and outside this interface slice. Keep official grading/release flows disabled.
