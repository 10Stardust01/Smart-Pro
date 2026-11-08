# Institutional readiness

Local assessment on 7 November 2026, with follow-up verification from `d01d22b`. The evidence covers
synthetic identities, records and files in isolated PostgreSQL 16 databases.
Production activation remains blocked.

| Area | Status | Evidence and limit |
| --- | --- | --- |
| HOD result history | Verified | The HOD opened the original and corrected stage marks, 76.00 and 80.00, in the browser. A second isolated workspace showed both overall release versions and the approved revision. Course contracts cover scoped result access. |
| Faculty appointment and project responsibilities | Verified in isolation | Application requests exercised the Admin recording an approved faculty grant and the HOD reassigning and ending a project guide appointment. The same faculty client gained and lost project access on subsequent requests. Admin could not end the guide assignment. An unrelated review and a changed department identifier were rejected. A separate finalized assessment and its published history stayed available to authorized readers. A short appointment reached its approved end naturally. The same client lost Faculty access and retained its separate Student role. |
| Departmental faculty detail management, amendment, termination and reinstatement | Authority confirmed; implementation pending | Product owner confirmed **department Admin** may edit other non-HOD faculty details, not only appointment end dates, and may amend, terminate and reinstate appointments (9 November 2026). **HOD details are excluded from Admin editing.** Existing application has no complete implementation. Preserve appointment/academic history and current authorizations; do not require additional approval. Whether reinstatement restores prior project-specific assignments remains undecided. |
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
- The current application uses a demo header, a synthetic identity map and a
  browser session-storage alias. It issues no production credentials or cookies
  and has no production session, CSRF or identity provider integration.

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
| Registrar and HOD | Confirm who provisions accounts, approved source exports, identity matching evidence, eligibility for non-faculty Admins, the behavior of project-specific assignments after a faculty reinstatement, and the exceptional HOD succession approver. Department Admin authority over faculty appointment amendment, termination and reinstatement is already a product decision, not an open question. Set per-offering rubrics, deadlines and publication delegates through approved configuration. |
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
