> **12 November 2026 current verification (supersedes historical hosted pending statements):** Actual Render Free reviewer is LIVE at `deployment/reviewer-staging` commit `915a6546`; auto-deploy is OFF. Hosted synthetic direct overall correction, graphical Guide/Coordinator/Student correction, corrected stage-evidence overall re-release, signed Faculty-access revocation and Guide reassignment, deployed text contrast remediation, and five-role keyboard skip-link verification all PASSED within their defined test scopes. Institutionally approved production remains separate. See README and the leading current requirements register.
>
> **Real-system recovery drill — PARTIAL, not independent restore acceptance:** An isolated Neon copy `smartpro-realdata-paired-recovery-audit-20261112` was created from actual reviewer `main` without changing the original default branch or Render. Source and isolated copy matched 124 projects, 8 overall-result rows, 412 audit events, 39 READY file metadata entries and manifest digest `87301ea007cf0f4961d0ddb283405e7f`; their private buckets matched 39/39 keys/sizes totaling 8,701,217 bytes. This is branch-copy consistency, NOT independent retrieval/re-hashing of original PDF bytes or independent backup-and-restore of database plus original private files. Previous snapshot inspection branch contained no private bucket. A paired independent restore remains OPEN. Do not restore snapshots against live reviewer staging.
>
> **Open scale and accessibility evidence:** Isolated real-data correction database-function samples were 67.88 ms (HOD) and 12.585 ms (Guide) but only 4 correction requests exist; live large-volume/colliding-write acceptance is OPEN. Eight different-project PDF uploads passed (8/8, p95 2.903 s), while eight sessions targeting one project exceeded the 10 s stopping threshold (p95 10.972 s; 2 HTTP 200 and 6 HTTP 409). Ten seconds is NOT the desired user-experience target: provisional p95 engineering objectives for review are ~1 s ordinary reads, ~2 s typical writes, ~3–5 s small PDFs, subject to real workload validation. Automated axe on 10 screens and five-role keyboard skip-link smoke passed; human screen-reader, comprehensive form keyboard/focus tests and accessible PDF evaluation remain OPEN. Institutional identity/account mapping is deferred at owner direction pending approved institution decisions. No paid resources, uncontrolled GitHub Action load or new academic policy was introduced.
>
# Institutional readiness

> **Current 11 November 2026 hosted acceptance addendum (supersedes the older deployment/correction status below):** GitHub `main` `902b1a2` includes merged [PR #27](https://github.com/10Stardust01/Smart-Pro/pull/27) and [PR #28](https://github.com/10Stardust01/Smart-Pro/pull/28); reviewer source `deployment/reviewer-staging` is `f315bd2`. Read-only Neon staging inspection confirms migration-065 overall-correction alignment and the separately enforced stage-mark restriction. [Signed HTTPS five-role synthetic direct-overall correction #43034757343](https://github.com/10Stardust01/Smart-Pro/actions/runs/43034757343) **passed**, retaining prior result/stage evidence. **Still open:** hosted stage-evidence re-release variant, graphical signed-in click-through, Admin faculty access handover, paired database+original private-PDF fresh-destination recovery, sustained authenticated peak/deadline performance, accessibility and institutional sign-off. Older lines below are historical, **not** current migration instructions; never reapply 059–065. No production identity or policy approval implied.
>

> **Current verified reviewer-staging update — 11 November 2026 (supersedes historical status below):** Neon staging has reviewed migrations **059–064** (not institutional production). Render Free reviewer service is **live** at commit `37de1d9`, deployment `dep-dbpl7sgu01pc73dmfmhg` (auto-deploy off). [All five signed HTTPS synthetic roles passed](https://github.com/10Stardust01/Smart-Pro/actions/runs/42856225094); [two-client real HTTPS academic write races passed](https://github.com/10Stardust01/Smart-Pro/actions/runs/42857100933); [four-client private PDF upload + SHA-256 verification passed](https://github.com/10Stardust01/Smart-Pro/actions/runs/42858473656). A separate [10-upload 256 KiB diagnostic](https://github.com/10Stardust01/Smart-Pro/actions/runs/42864693940) passed after [S3 connection reuse PR #23](https://github.com/10Stardust01/Smart-Pro/pull/23), with median 0.980 s and first wave as slow as 3.481 s; **not** a sustained capacity SLA. Temporary upload timing logs have been disabled. See the [authoritative requirements register](REQUIREMENTS_COMPLETION_REGISTER.md) for exact scope.
>
> **Still open:** Hosted **Guide → Coordinator → Student** correction on a dedicated correction-enabled synthetic project; signed-in Admin → Coordinator academic faculty access handover; sustained authenticated/deadline capacity; independently verified **paired database + private S3 object backup and fresh-destination restore** (test PDF read-back is not this); accessibility and institutional production sign-off. **Do not reapply already installed migrations 059–064.** Historical statements below using Render `0419358d`/`27a598e` or pre-064 migration levels describe older checkpoints only and are not current deployment guidance.

> **Latest hosted reviewer checkpoint — 10 November 2026 (not institutional production):**
> Neon Free staging **main** now contains migrations **059–063**, with 061 → 062 → 063 installed as separate atomic transactions. Existing Render Free reviewer service manually deployed source commit **`0419358dc5a3c87d5ef5290909b7cbc00e59fb40`** ([PR #12](https://github.com/10Stardust01/Smart-Pro/pull/12)). All published-result, stage-result, audit and READY-file metadata digests remained unchanged. Permissioned Coordinator/Admin reads succeeded and unauthorized Student/Faculty reads were denied. The original pre-059 and new pre-061 recovery branches remain.
>
> **Still outstanding:** actual private PDF byte/hash restoration, independently verified paired database+file recovery, full authenticated hosted Guide → Coordinator → Student/Faculty browser acceptance, peak-load tests and institutional approval. PR #12 passed **five** checks; its sixth correction-browser check was **cancelled during Chromium installation at the 12-minute timeout**, so do not claim 6/6. No paid feature/trial was used. [Release evidence and open gates](https://github.com/10Stardust01/Smart-Pro/issues/4).


> **10 November 2026 staging clarification:** Render reviewer staging has
> signed, CSRF-protected **synthetic reviewer sessions**, not approved production
> authentication. Statements below about local demo-header identity describe
> historical local testing. Neon main contains 059/060 only; the existing
> Neon validation branch now has 061–063, without a hosted rollout or paired
> private-file recovery.
> See [consolidated checkpoint](CONSOLIDATED_DEVELOPMENT_CHECKPOINT.md).

Local assessment on 7 November 2026, with follow-up verification from `d01d22b`. The evidence covers
synthetic identities, records and files in isolated PostgreSQL 16 databases.
Production activation remains blocked.

| Area | Status | Evidence and limit |
| --- | --- | --- |
| HOD result history | Verified | The HOD opened the original and corrected stage marks, 76.00 and 80.00, in the browser. A second isolated workspace showed both overall release versions and the approved revision. Course contracts cover scoped result access. |
| Faculty appointment and project responsibilities | Verified in isolation | Application requests exercised the Admin recording an approved faculty grant and the HOD reassigning and ending a project guide appointment. The same faculty client gained and lost project access on subsequent requests. Admin could not end the guide assignment. An unrelated review and a changed department identifier were rejected. A separate finalized assessment and its published history stayed available to authorized readers. A short appointment reached its approved end naturally. The same client lost Faculty access and retained its separate Student role. |
| Departmental faculty detail management, amendment, termination and reinstatement | **Verified in isolated API/SQL; not hosted-accepted** | Candidate 063 adds Admin-only departmental profile fields, temporal Faculty appointment amendment/termination/new-term reinstatement, idempotency and before/after audit. Denies HOD edits and unrelated roles. Protects existing Guide and offering appointments from unapproved automatic termination/reinstatement. Existing project-specific assignments must first be resolved with authorized assignment actions. The profile does not modify global sign-in credentials or identity-provider state. [PR #7](https://github.com/10Stardust01/Smart-Pro/pull/7). |
| Accessibility | Partially verified | Browser samples across all five roles covered Tab, visible focus, Enter and Space, named controls, validation, disclosures and published-result semantics. The recorded rubric table now exposes its stage name and column headers. The PDF dialog exposes the original download and restores focus on Escape. The raster preview cannot expose PDF text and untagged source PDFs may still require an accessible alternative. Windows Narrator is present, but the available browser controls cannot operate it or verify spoken output or table traversal. |
| Identity and role security | Partially verified | Local header-selected identities are gated to demo mode and a loopback test database. Effective roles are checked on each request. Database functions also enforce assignment, department and academic authority. The runtime audit and grant correction below cover the local role layout. |
| Migration and transaction checks | Verified in isolation | A seeded schema installed 001–009, the runtime boundary, 010 preparation and preflight, and candidates through 047 in order. The chain preserved sampled legacy document versions, marks, result releases, scores and approval evidence. The separate acceptance restore installed 043–047 with both uploaded files and result history already present. Real legacy mappings and deployment-volume compatibility remain open. |
| Database and PDF restore | Verified in isolation | An exported database snapshot and the matching immutable PDFs restored to a new workspace. All 98 public table fingerprints and both PDFs matched, including three assessments, four stage result versions, two overall releases and 104 audit records. On the restored copy, HOD download returned 200, Admin download 403, corruption 503 and the repaired copy 200. |
| Operational recovery | Partially verified | The restore uses a single restore transaction. Regressions exercise command failure and retry. Bounded private PDF reads now log availability, size or digest failures without paths or credentials. Physical crash recovery, point-in-time recovery, load and monitoring drills remain untested. |
| Production activation | Blocked | The institution must assign the owners and make the decisions below. The current adapter rejects real login. |

## Confirmed behavior

- The HOD governs academic policy, oversees the department and manages Admin
  appointments. Admin manages authorized operations and course coordinator
  appointments directly. Course coordinators act within their effective offering
  appointments, including while the HOD seat is vacant.
- Student access follows verified enrollment, current membership and approved
  offering settings. The primary guide participates in evaluation by default.
  Assessments pin approved plans. Ordinary evaluators need specific coordinator
  authorization for finalized changes. Before overall release, a coordinator with
  correction responsibility can submit their own finalized correction from the
  Faculty workspace and apply it immediately. Previous versions and the actor
  remain in history. Exceptional overall revisions use the separate published
  result workflow.
- The **local development mode** uses gated synthetic identities, demo headers
  and a browser alias. **Hosted reviewer staging** uses signed synthetic sessions
  with CSRF protection instead. Neither mode provisions institutionally verified
  accounts or constitutes an approved production identity integration.

## Department leadership

The HOD can appoint an Admin, replace one atomically, end a term, or explicitly
increase capacity above the default of one. New leadership selections use
active departmental faculty accounts. The outgoing Admin loses operational
access on subsequent requests and earlier actions retain their attribution.

A current HOD can resign in Academic setup. The end of the term is recorded in
a private command receipt and audit history. A current Admin can appoint an
eligible successor only after that resignation. The database rejects overlapping
HOD terms for the department. The normal flow preserves existing course and
Admin appointments. Legacy department-wide delegations can still depend on
their original mandate and require migration review if the institution uses them.
An upgrade that finds overlapping HOD terms requires approved data repair before
adding the constraint.

First-HOD bootstrap is an owner-only database operation on a department with no
prior HOD term. It requires an existing active departmental faculty identity
and an institutional verification reference. Production requires a verified
operator and approved identity mapping before invoking it. The normal successor
command requires a voluntary resignation, so an unavailable HOD requires a
separately approved institutional recovery procedure.

For an exceptional vacancy, the designated institutional approver must verify
why the current term needs to end, the affected department, the proposed
successor and the identity of the operator. The operator must record the
authorization reference, preserve the old term and verify that other current
appointments still work after the change. Account recovery remains a separate
identity-provider process. This procedure requires approval before any
exceptional operator command can be enabled.

## Department records

Admin can preview a UTF-8 CSV export, map its columns, see row conflicts and
import with provenance. Excel records can use CSV export. Corrective batches
retain previous batch evidence. Imported records stage separately from accounts
and grant no appointments. An Admin can link a record to a verified existing
account. An official student record can update section only when the linked
profile already has the same department, USN and semester. Semester or USN
conflicts require review through the existing eligibility workflow.

Downloaded Google Forms responses can enter the separate unverified student
intake channel. Linking a response records the checked match and leaves the
academic profile and permissions unchanged. Live Forms connectivity remains
subject to institutional permission, configuration and retention rules.

## PostgreSQL privilege model

The owner installs the schema and migrations. The application login inherits the
non-login `smartpro_runtime` role, which Django selects explicitly for each
connection. The isolated catalog showed that the login has no superuser, database
creation, role creation, replication or row-security bypass attribute. The runtime
can create temporary objects. Public schema creation and database creation
privileges are denied. The role has no direct table or column access to
departmental role appointments, stage result versions or overall result versions.

Candidate `043` removes default `PUBLIC` execution from six owner-privileged
functions. The runtime keeps explicit access to the initial evaluation, role
documents and role workspace entry points. Three trigger functions keep their
existing trigger use and lose direct execution grants. The fresh schema and
application course suite verified the change. An ACL regression checks that
there are zero publicly executable owner-privileged functions in the audited
public schema.

The older synopsis path still requires direct reads on nine tables and direct
inserts on nine tables. The write surface includes upload, submission, review,
audit, outbox and idempotency records. Direct updates are limited to five upload
session fields, two submission case fields and two attempt fields. No table-level
update, delete, truncate, references or trigger grant was observed. A runtime
credential can bypass HTTP authorization by calling entry points directly with
actor identifiers. The runtime must be held by the trusted service. Legacy write
encapsulation and verification of the deployed role inventory remain technical
activation work.

## Technical work that can proceed

- Encapsulate the remaining legacy writes and add direct runtime denial tests.
  Repeat the effective privilege audit with the actual deployment roles.
- Prepare versioned deployment checks for timeouts, TLS, secrets injection,
  private document storage and PDF parser isolation. Keep request logging free
  of document bytes, credentials and sensitive data. Validate alerts against
  scoped failure logs and test handling of incomplete uploads and storage loss.
- Rehearse backups with the actual selected storage and database services.
  Verify interruption, recovery time, data loss bounds and restore integrity.
  Repeat assistive technology testing with the supported browser and reader
  combinations, including form errors, table headers and uploaded documents.

## Institutional decisions and activation gates

| Decision owner to designate | Decision or approval needed |
| --- | --- |
| Identity and security owner | Select the provider and approved protocol. Define immutable provider identity to internal account mapping, onboarding, deactivation and session invalidation. Require verified credentials, account status checks and a documented CSRF model if cookies authenticate requests. Set session timeouts, credential handling and secret rotation. |
| Registrar and HOD | Confirm who provisions accounts, approved source exports, identity matching evidence, eligibility for non-faculty Admins, the explicit authorized reassignment process after a Faculty reinstatement (no automatic duty restoration), and the exceptional HOD succession approver. Department Admin authority over faculty appointment amendment, termination and reinstatement is already a product decision, not an open question. Set per-offering rubrics, deadlines and publication delegates through approved configuration. |
| Infrastructure and recovery owner | Select hosting and private file storage, approve network and TLS boundaries, inventory legacy DB grants and mappings, and set recovery objectives, backup retention and restore responsibilities. Sign off after a deployment-shaped restore drill. |
| Records and accessibility owners | Define privacy access, retention, removal and incident procedures for student records, PDFs and audit evidence. Set acceptance criteria for accessible documents and supported assistive technology. |
| Department operations owner | Choose approved notification channels, recipients and monitoring ownership. In-app reminders are implemented. Any external delivery needs an approved channel and delivery evidence. |

The activation gate includes verified production authentication, approved account
lifecycle authority, restricted deployment privileges, validated migration
preflight, approved privacy and recovery procedures, and signed institutional
acceptance. The synthetic backup drill supports local evidence only.

To repeat the logical restore from the repository root, pass an isolated browser
manifest to `scripts/verify_isolated_restore.py`. It creates a new disposable
database and storage directory and retains the archive for inspection. Use the
local virtual environment and start the existing loopback test cluster first.

The [department review checklist](DEPARTMENT_REVIEW_CHECKLIST.md) lists the
actions faculty and the HOD can review with the named institutional owners.
