# Curriculum-scoped student teams: proposed migration 010

## Confirmed requirements

Students can create teams. Identify each student by a unique VTU USN linked to
the existing immutable users.id UUID. Student details are name, section, semester,
department and USN; no additional student fields are required for this slice.
The same student cannot have overlapping
team memberships within the same curriculum offering. A student may belong to
a Societal Project team and an Interdisciplinary Design Thinking (IDT) team in
the same semester. Departments configure which curricula they offer.

**Student visibility and eligibility:** a signed-in student should see only the
curriculum offerings published for their **own department and current semester**
within the applicable academic cycle. Students must not be shown a directory of
other departments' offerings or other semester offerings. The backend must derive
the student's identity from trusted authentication; no client-provided department,
semester, USN or alternate user ID can broaden these results.

**Joining is separately protected:** guessing or submitting another offering's ID
must not bypass these restrictions. Candidate activation 010 adds a database
guard for **new** team memberships: the student's current profile department
and semester must match the target offering. The application service must also
check the configured enrollment cycle, whether team formation/joining is open,
and the authenticated student's actual permission. Authorized staff can manage
offerings in their own department under separately scoped permissions; staff
visibility is not the student-facing listing.

**Future extensibility:** if cross-department eligibility becomes an approved
requirement, use explicit, auditable eligibility/enrollment grants, not blanket
student access to all offerings or an unvalidated manual offering ID. Historical
memberships continue to reference the original offering and student UUID. A
subsequent student profile/semester update must not retroactively relabel past
memberships, reviews or marks. Profile department/semester edits are rejected while incompatible unended or
future-ending memberships exist. An authorized command must end those intervals
first, then change the profile in the same transaction; ended history stays intact.
Reopening or extending an ended interval rechecks current eligibility.

A curriculum offering is uniquely identified by department + academic cycle +
semester key + curriculum type. A chosen project title is not a curriculum type.
MINI/MAJOR remains the existing project classification and is not repurposed.
One team belongs to one offering; multiple projects may share that team within
the offering. Different curricula require separate teams, even for the same roster.
Two duplicate offering rows cannot bypass the rule.

## Data model and integrity

- Student name uses the existing users.display_name field. student_profiles adds
  section, semester_key, department_id and USN, without duplicating the name.
  The proposal makes the existing users.email optional, retaining existing email
  values and checks on supplied addresses; student registration needs no extra
  email field and no placeholder address is manufactured.
  USN is the college-wide unique student identifier, stored uppercase and trimmed
  with an ordinary uniqueness constraint. No external USN lookup or guessed VTU
  format validation is required. Knowing a USN does not establish authentication.
  Section, semester and department describe the current student profile; editing
  these fields does not relabel an old team, offering or frozen academic record.
- curriculum_types supplies stable codes and editable display labels.
- curriculum_offerings binds a type to a department, cycle and semester.
  No universal semester allocation is assumed. A formation flag allows departments
  to configure student team creation; it does not grant faculty management rights.
- teams gains curriculum_offering_id, with a composite FK proving that department
  and cycle match the offering.
- team_memberships carries the same offering through a composite team FK and
  references student_profiles. A GiST exclusion constraint rejects overlapping
  intervals for the same student UUID and offering, including concurrent joins.
  An INSERT/interval-extension guard compares current student department and
  semester to the offering. It writes a private profile revision token to serialize
  membership admission with profile edits, including stale REPEATABLE READ and
  SERIALIZABLE snapshots (retry the whole transaction on SQLSTATE 40001);
  its absence of an authenticated user context means the **service must**
  additionally enforce actor identity and authorized cycle. Historical
  memberships inserted before activation are not rewritten by this guard.
- Stable student UUIDs keep membership and academic history intact when an
  authorized identity correction changes a USN. Identity corrections must be
  audited and must not reassign another student's USN or merge accounts silently.
- Offering scope, team scope, curriculum codes and student UUID bindings cannot
  be relabeled to evade the membership restriction after activation.

Existing historical guards remain enabled. Transfers close the previous interval
and create a new membership in one transaction; they do not move an old membership
row. Adjacent intervals are valid; overlapping or backdated conflicting intervals
are rejected. Review rosters, submission identity and released results stay intact.
This is the minimum temporal rule needed for the agreed active-membership rule;
no additional team-size, guide-count or cross-curriculum restriction is introduced.

## Staged migration proposal

The SQL in proposals/curriculum is deliberately outside database-v1.5/migrations.
It is executable contract evidence for a proposed 010, not an automatically enabled
schema change or completed team-management feature. Migrations 001-009 are unchanged.

1. Stop application writers and take a verified backup/snapshot.
2. Apply 010_prepare.sql as migration owner.
3. Import student details (name, section, semester, department and unique USN)
   and reviewed curriculum offerings.
   Explicitly map every old team, including historical teams, to its true offering.
   Do not infer semester/category from project titles, fabricate USNs, or silently
   assign every old team to one category.
4. Run preflight.sql. Resolve missing identities, missing mappings, incompatible unended/future
   memberships and overlapping memberships with the academic owner. Conflicting history is an activation
   blocker, not permission to alter past records.
5. Apply 010_activate.sql. Its preconditions and constraints reject invalid mappings
   and roll back the activation transaction. Keep writers stopped if it fails.
6. Verify schema/data and deploy matching services before resuming team writers.

Preparation alone leaves nullable classification fields and is not a supported
application state. It must not be exposed to team writers. Activation makes the
fields mandatory, validates the composite bindings and installs the exclusion.
Both scripts must be reviewed together; they are not a migration runner yet.
Promotion to the numbered migrations directory requires a tested fixture/upgrade
strategy. Original supplied fixture files will remain preserved as evidence.

Preparation failure rolls back its transaction. Failed activation rolls back
activation only, retaining explicit preparation/mapping for diagnosis. Before any
new application writes, a verified pre-change backup is the recovery source.
After new academic records exist, use a reviewed forward fix; do not drop historical
constraints or delete membership evidence as a rollback shortcut.

## Next implementation gates

1. Review this schema contract and legacy mapping/preflight design.
2. Define scoped MANAGE_TEAM / ASSIGN_GUIDE / EDIT_TEAM_POLICY delegation and its
   effect on shared teams; do not equate reviewer authority with team management.
3. Implement service commands: an authenticated student can list **only their own
   department/semester offerings for the authorized cycle**, create permitted
   teams and join themselves. Listing must be server-scoped, not a client-side
   filter of an all-department response. They cannot add arbitrary students,
   choose another actor, provision profiles, configure offerings or grant delegation.
4. Use trusted principal UUIDs. USN lookup resolves a target UUID only in authorized
   flows and must avoid unrestricted student-directory exposure.
5. Require effective scoped roles and ACTIVE accounts; check offering formation
   settings. Use idempotency, deterministic locks, and atomic audit/outbox records.
6. Implement authorized transfer and guide reassignment, then real student/faculty
   screens. Handle exclusion conflicts as 409 rather than silently switching teams.

No HTTP write endpoint, runtime write grant, production login, USN import UI or
faculty delegation is enabled by this proposal. Department staff identity and
USN corrections require separately reviewed commands. Work advances by dependencies
and acceptance evidence, without fixed duration or calendar deadlines.

## Reproducible acceptance evidence

The curriculum-contracts workflow applies preserved migrations 001-009 and their
synthetic fixtures, then explicitly maps synthetic profiles/offerings and activates
the candidate schema. Tests cover same-semester Societal+IDT membership, denial of
two teams in one offering, concurrent competing joins, transfer history, identity
correction, offering boundaries, null/spoofed bindings, failed legacy preflight,
complete student detail fields, and unchanged frozen academic evidence. Baseline PostgreSQL and Django workflows
run independently on their own databases.

## Technical review

See [the completed review](CURRICULUM_REVIEW.md) for verified defects, validation
and the separate conditions for merging the inert proposal and activating it.
