# SmartPro Teams UI and finalized workflow reconciliation

## Verified reviewer state

Render service `smartpro-reviewer-25775915`, in the owner-confirmed Smart-Pro
workspace, reports live deploy `dep-dc4rplkipgvc738o5h00` at source
`12f282b83ada650d6ff019cb7456870fe47f71b6`. It follows
`deployment/reviewer-staging`, with automatic deployment off. Main remains
`0cf98f9926ce73b903ac6986d0c9025323965362`.

Read-only HTTP checks returned 200 for `/demo-assets/app.js` and
`/demo-assets/prc.js`. The served app still contains the Membership policy card;
the PRC asset contains the read-only PRC activities view. The app asset is served
with `Cache-Control: no-store`. No authenticated session or live academic record
was changed during these checks.

The earlier explanation that development changes simply had not reached reviewer
staging is now incomplete. The PRC foundation was promoted, but it did not change
the Teams screen. Its progress views appear in Course Management and project
evidence, and its candidate gate is offering-specific. The promotion note records
empty activation/decision tables; this inspection did not query live database rows.
Do not infer a browser cache problem or a complete PRC workflow from a live deploy.

## Change in this branch

Remove only the generic Membership policy panel below Create a team. Preserve
Current membership, Available teams, Create a team, join/leave/transfer actions,
confirmation and server error handling. Membership APIs and SQL are unchanged.
Configured policy, eligibility, capacity, temporal membership history, locking,
transaction retries and authorization remain enforced by the existing backend.
This UI removal needs no database migration.

The frontend workflow check also had an outdated expected label, Faculty Reference;
it now checks the existing Faculty directory label without changing that interface.

## Finalized requirements versus implemented behavior

The latest explicit user clarifications in Analyze SmartPro Repo supersede narrower
wording in the earlier foundation notes. These are finalized requirements, not
open product questions:

| Finalized requirement | Inspected reviewer source | Remaining implementation |
| --- | --- | --- |
| PRC approval gates the entire academic project lifecycle after registration, synopsis submission and PRC responses | Candidate 066 guards Guide insertion/reassignment for explicitly gated offerings; it does not guard every downstream academic operation | Enforce the approved gate across development/progress writes, reviews, assessment, presentation, final report, final evaluation and closure paths, with scoped regression tests |
| PRC Reject requires a fresh synopsis; Request Modification permits revision; preserve all history | Candidate 066 preserves distinct outcomes and denies reuse of synopsis versions preceding a rejection | A usable authorized committee decision/resubmission journey is still incomplete |
| Coordinator manages PRC activities within the assigned offering | Offering-scoped progress reads and project evidence exist | Management commands need the previously unresolved authority for committee appointment and collective outcome recording; management alone does not establish those powers |
| Coordinator allocates up to two teams per Guide | Existing assignment commands do not implement this two-team allocation cap | Add transactional capacity enforcement and concurrent-allocation coverage |
| An eligible PRC-approved third team approaches a Guide; Guide accepts or declines without Coordinator approval | No third-team request/accept/decline journey in this source | Add the student request and direct Guide decision services and UI, with scope, eligibility, history and retry checks |
| Maximum three teams per Guide | No corresponding three-team limit in the inspected assignment path | Serialize capacity checks across allocation and acceptance so concurrent requests cannot exceed three |

The three-team rule and direct Guide acceptance do not need to be re-approved.
Team creation/joining, initial project registration and synopsis submission must
remain available before PRC approval. Otherwise the gate would create a circular
dependency. PRC responses, including revision or fresh synopsis submission, also
remain available before approval. The user explicitly reconfirmed this ordering.
The earlier local foundation and deployed reviewer foundation are partial work;
their verification counts do not prove the later, broader requirements.

## Preserved boundaries

This branch does not invent committee appointment authority, quorum, voting rules,
collective-decision recording authority, or a scope for counting Guide load that
the retrieved decision does not specify. It does not convert generic Faculty
synopsis approval into PRC approval. Existing historical assignments and evidence
remain intact. Synthetic acceptance data seen in the screenshot is a separate
reviewer-data issue; hiding or deleting it here would obscure that issue.

No merge, reviewer-branch update, deployment, migration, gate activation or live
academic write is part of this change. The card remains visible on the existing
reviewer URL until this UI change is deliberately promoted and deployed.

## Verification of this increment

- Existing frontend workflow suite passes after fixing the stale directory-label
  expectation. The deployed branch does not contain the separate feature branch's
  PRC test file; no PRC test run is claimed here.
- The actual Teams renderer was exercised locally in four states: no membership,
  existing membership, no eligible offering, and enrollment required. The card is
  absent; Create, Leave, team-list and enrollment behavior remain present as
  applicable. This is renderer verification, not authenticated browser acceptance.
- The application module passes JavaScript syntax checks and the diff passes
  whitespace checks. Backend and candidate SQL files are byte-for-byte unchanged.
- The initial remote publication attempt was rejected by automatic approval
  review. The user subsequently authorized proceeding after reviewing the patch
  and reconfirming pre-PRC team/project/synopsis access. Publication is limited to
  a separate review branch; no merge or deployment is included.
