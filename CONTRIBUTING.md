# Review workflow

The imported validated prototype is on `main`. Work on short feature branches and
open pull requests. Require one independent developer review, resolve comments,
and wait for `postgres-validation` and `django-compatibility` on the current head.
The PR author cannot supply their own independent approval. No reviewer identities
or collaborators have been invented or granted access.

A classic `main` branch rule was saved on 3 November 2026: one approval, stale
approval dismissal, required up-to-date `postgres-validation`, conversation
resolution and administrator inclusion; force pushes/deletions remain disabled.
**GitHub explicitly reports that this rule is NOT ENFORCED on this private
repository under the current account plan.** Until the owner enables an eligible
plan, these are team procedures, not a technical merge barrier. No plan purchase,
organization transfer or visibility change is authorized or performed here.
Add `django-compatibility` to the saved required-check list after its first run.

Keep SQL migrations 001–009 immutable. Any future schema change needs a numbered
forward migration, SQL contracts, rollback/forward-fix discussion and historical
data preflight. Do not enable ORM schema synchronization or use Django migrate
to recreate academic tables. Do not use migration credentials in request handlers.

Run the root validator in an isolated PostgreSQL 16 database. Four skipped
institutional-policy cases remain open decisions, not successful behavior tests.
Run the Django probe separately: both runners reset their named synthetic database.
Never execute them concurrently against the same database.
