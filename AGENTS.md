# SMART-PRO engineering instructions

Current development is LOCAL ONLY on feature/finalized-academic-policies.
Do not contact GitHub, push, create PRs, merge, reset, clean or rebase. Preserve
backup/smart-pro-2026-11-04 and existing work. Verify locally before small commits.
The user's finalized-policy instruction supersedes earlier undecided product
rules; see docs/FINALIZED_ACADEMIC_POLICIES.md. Production activation stays blocked.
Academic policies are pinned per review. Append corrected evaluator/roster/result
versions; retain legacy scores/releases. Only the original active evaluator revises
its contribution; retrospective rosters need appointed coordinator authority and
historical membership plus STUDENT-role proof. Never auto-award missing marks.
Course-bound finalized-mark changes require authorization of the exact proposal by
an effective offering coordinator. Before overall release, the original evaluator
can apply their own correction when their current course coordinator appointment
includes correction responsibility. Stage release leaves ordinary synopsis
revisions open. Overall release closes ordinary document changes and keeps the
separate exceptional result-revision workflow.
Department Admins appoint offering coordinators. The HOD manages Admin terms.
Ordinary HOD succession requires the current HOD's voluntary resignation and an
eligible successor selected by a current Admin. Preserve earlier appointments.

The application uses Django-served HTML/CSS/native ES modules in frontend/.
Read docs/APPLICATION_CORRECTIONS.md and docs/REPOSITORY_STATUS.md first.
Normal startup is scripts/application.py serve: never seed or run candidates.
Legacy department_demo.py startup is archived; preserve its source/test databases.
Browser acceptance uses application.py test-workspace, a schema-only isolated DB
with test identities/authority but initially no academic records. User permits
010–015 only in disposable regressions. All candidates stay outside production.
025–028 make notes optional (never fabricate them), support Admin recording and
implementing externally communicated HOD instructions with explicit provenance,
retain immutable proposal descriptions, and separate faculty document reading from
synopsis decision authority. No compulsory request/approve/apply loop; legacy exact
approval APIs remain compatible. No institutional policy defaults or synthetic
approvals may enter normal application data. HOD and Admin remain distinct.
Same faculty may be separately assigned guide/evaluator; active departmental
FACULTY role plus authorized assignment suffices. Guide/evaluator alone may read
assigned work but needs explicit REVIEWER assignment for synopsis decisions.
036 records that explicit SYNOPSIS reviewer prospectively on authorized primary-guide
allocation; reassignment/end closes only the linked right. Independent reviewer
grants, pinned policy permissions and prior decisions remain. Never backfill authority
or infer approval rights for other configured documents.
Preserve scoped private PDFs, pinned policies, immutable history and old receipts.

Build from the existing Django/DRF and PostgreSQL modular monolith and frontend.
Inspect relevant local source and verified evidence before changing a
contract. Reuse validated components; deliver complete functional slices rather
than replacing working services with mocks or more planning.

- Preserve migrations 001–009 and historical academic evidence. Use reviewed
  forward migrations; candidate curriculum scripts remain outside automatic
  rollout until legacy mapping, preflight, backup and recovery are verified.
- Derive actor identity from trusted authentication, never a USN, Google Form or
  client-supplied actor/scope. Demo authentication requires both explicit switches
  and must fail closed outside demo. Real users require verified production login.
- Enforce department, semester, applicable cycle, effective roles and account
  status on the backend. Separate student scope, delegated routine staff commands
  and departmental policy authority. TECH_ADMIN alone grants no academic power.
- Model invariants with database constraints. Preserve temporal memberships,
  guide history, frozen review evidence, policy versions and published results.
  Never silently rewrite finalized academic records or invent institutional rules.
- Use explicit application services, transactional persistence, deterministic
  lock ordering, safe retries and idempotent audited mutations. Keep runtime DB
  privileges narrow; keep credentials and sensitive records out of logs.
- Membership commands lock student scope before affected teams in UUID order;
  keep team revision writes and temporal exclusion guards. Retry the entire
  transaction on 40001/40P01 and reauthorize; never retry only a stale savepoint.
  Use configured versioned department policies, not hardcoded team sizes.
- Project registration must use the current membership and explicitly approved
  offering/class window. Keep private registration receipts; never trust legacy
  writable idempotency rows or invent project-count/title/leadership restrictions.
- Staff authority needs an explicit grant tied to the exact effective role record;
  no faculty/guide/HOD/TECH_ADMIN role implies powers. Preserve strongest authority
  locks, history revision writes and policy CAS. Initial title correction must
  remain disabled by default and closed once academic activity has started.
- Bound queries, connections and timeouts; add useful structured failure logs.
  Prefer simple modules and measured indexing over speculative infrastructure.
- Test each slice's success, denial and failure cases and relevant concurrency;
  run focused checks then affected regressions. Inspect failures and verify CI on
  the exact PR head. Never claim unexecuted verification.
- Use focused branches, meaningful commits and reviewable dependent PRs. Do not
  merge main, deploy, alter real academic records or ratify institutional policy
  without authorization. Conventional reversible decisions need no repeated ask.
- Keep docs/REPOSITORY_STATUS.md authoritative and concise. Clearly distinguish
  implemented behavior, product direction and unratified institutional policy.
- For stack integration follow docs/INTEGRATION_READINESS.md. Preserve ancestry,
  verify checks after each base change, and never assume saved protections enforce.
- Before real deployment require load/security checks, backup/restore and crash
  recovery tests, monitoring, production identity and deployment hardening.

Read docs/ACADEMIC_WORKFLOW_AND_GUIDE_POLICY.md on its PR #3 branch when relevant:
one active primary guide with reassignment history; guide/evaluator overlap is
permitted by the latest user clarification (superseding earlier independence text);
configurable review stages and versioned schemes; TEAM/INDIVIDUAL/COMBINED scores.
AI guide allocation is future work. Minimize redundant exploration, abstractions,
output and repeated tests, without reducing essential quality checks.
