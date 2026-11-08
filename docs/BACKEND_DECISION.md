# Backend decision: Django + Django REST Framework

Decision date: 3 November 2026. Recommendation: Django 5.2 LTS + DRF for a modular
monolith, retaining the SQL-owned PostgreSQL schema and explicit service layer.
This is an engineering recommendation, not faculty approval or deployment approval.
The tested versions are Django 5.2.18 and DRF 3.16.1, pinned in backend/requirements.txt.

## Evidence and comparison

The actual schema has 38 tables, not just teams and a synopsis status column.
Migrations 001–009 define UUID identities, composite ownership foreign keys,
partial uniqueness, JSONB policy versions, NUMERIC marks, deferred commit guards,
btree_gist temporal exclusion, historical rosters, scoped grants and an outbox.
The domain service already uses psycopg transactions, parent-row locks and a
restricted runtime login. The HTTP adapter is temporary FastAPI.

| Actual concern | NestJS | Django + DRF | Integration choice |
|---|---|---|---|
| SQL-owned schema / composite ownership FKs | Compatible with explicit SQL repositories; ORM synchronization must remain off | Compatible with unmanaged mappings and psycopg; inspectdb output requires review | Preserve all SQL guards; neither ORM recreates the schema |
| Composite PK child tables (submission_items, score/release children) | TypeORM supports composite identity, but multi-column relations still need explicit mapping/tests | Django 5.2 CompositePrimaryKey supports identity; relational fields/admin support is limited | Keep score/submission writes in explicit services; no fabricated single-column id |
| Existing synopsis behavior | Requires a TypeScript port of domain.py, error semantics, byte handling and lock ordering | Reuses the Python domain operations with a new HTTP adapter | Lower immediate reimplementation risk for Django |
| Temporal membership and faculty scope | Guards can reject routes; SQL/service checks still needed inside transactions | DRF authentication/permissions plus scoped queries; DB/service checks still needed | Effective role, enabled user and project assignment must all hold |
| Immutable submissions/results | Generic CRUD/admin would expose invalid operations | Generic CRUD/admin would expose invalid operations | Explicit submit, decide, seal and append-correction commands only |
| Academic administration | Custom interfaces or selected admin integration | Built-in admin is useful for suitable reference data; not unrestricted academic editing | Add narrowly scoped service-backed staff screens after permission design |
| Transactions / workers | QueryRunner or explicit client; retain same transaction for all mutations; SKIP LOCKED worker pattern | Existing psycopg transactions can remain; Django atomic does not wrap a separate psycopg connection | One connection owns each command; no split audit/outbox commits |
| React integration / five developers | Shared TypeScript types and explicit Nest modules are useful | Generate client types from agreed OpenAPI; split Django apps by domain | No requirement for frontend and backend to share a language |
| Auth identity | Requires trusted integration and subject mapping | Django auth exists but current users table is not Django's auth schema | Do not replace existing users or equate staff/superuser with academic grants |

The Django probe executes against PostgreSQL 16 with all nine migrations. It
checks UUID reads, an actual composite-key row lookup, restricted current/session
roles, a student and assigned-faculty case read, unrelated-faculty rejection,
missing-identity rejection and production rejection of demo headers. Catalog
constraints/indexes, columns, trigger definitions and function definitions are
compared before and after each phase, without a reset between snapshots. Generated
inspectdb output is retained as evidence, not adopted as authoritative models.

See evidence/django-compatibility.json and evidence/django-inspectdb.txt for actual
results. This is a focused Django compatibility probe; a runnable NestJS port and
head-to-head throughput benchmark were not performed. NestJS compatibility is a
source/schema/documentation assessment. No performance or developer-skill claims
are inferred. If the team has materially stronger TypeScript backend experience,
that can change the staffing tradeoff, but does not change the SQL contract.

## Requirements retained and missing work identified

- Preserve MINI/MAJOR projects; versioned policies; TEAM, INDIVIDUAL and COMBINED
  marking modes; immutable formal evidence and historical rosters.
- Team size remains configurable guidance. Coordinator/HOD sets department policy;
  delegated faculty may edit only their authorized scope. No global one-team or
  one-guide restriction is added. Multiple teams/guides are already positive cases.
- **Faculty membership/guide editing is not implemented by migration 008.** Its
  permission function only handles student/reviewer synopsis operations. The
  runtime role cannot write teams, projects, memberships or assignments. Sprint 1
  must add a separately reviewed forward migration for scoped team-management
  delegation and narrowly privileged commands; existing academic_action_grants
  allow only APPROVE_SCHEME/PUBLISH_RESULTS/CORRECT_RESULTS.
- Do not reuse reviewer authority as team-edit authority. A team can be linked
  from multiple projects; membership changes must check all affected project scopes
  (or a delegated team scope) and lock common parents in deterministic order.
- Policy JSONB can hold a versioned guideline shape, but current approved policy
  documents are immutable. Define when an update applies to current teams versus
  future projects; do not silently rebind historical projects.
- Single-reviewer synopsis approval and single_evaluator_sum are synthetic test
  policies. Institutional quorum, aggregation, grade amendments and retrospective
  membership exceptions remain unresolved. Four skipped tests expose these gaps.
- Student/Admin dashboards remain required; faculty/guide is a candidate third
  interface, not a newly finalized institutional role hierarchy.

## Production and demo identity

The added scaffold accepts synthetic X-Demo-User only when BOTH SMARTPRO_ENV=demo
and SMARTPRO_DEMO_AUTH=YES. All protected requests otherwise fail closed.
Production must replace that authentication class with a verified institutional
identity adapter (issuer/audience/signature/expiry/subject validation, or an
approved server session flow). Map trusted subjects to existing users, check
ACTIVE status and effective department/project grants. No default passwords,
public demo login, user-selected roles or TECH_ADMIN grading rights are introduced.
No production provider, secure object store or hosting configuration is selected.

## Primary references checked

- Django legacy database integration: https://docs.djangoproject.com/en/5.2/howto/legacy-databases/
- Django composite keys and admin/relationship limitations: https://docs.djangoproject.com/en/5.2/topics/composite-primary-key/
- DRF list/create/object permission limitations: https://www.django-rest-framework.org/api-guide/permissions/
- NestJS database integration and transactions: https://docs.nestjs.com/techniques/database
- NestJS guards: https://docs.nestjs.com/guards
- TypeORM composite primary columns: https://typeorm.io/docs/entity/entities/

Recommendation follows from preserved Python services and the administration
domain, with explicit allowance for ORM limitations. No automatic Django admin
or generic ViewSet is treated as an academic authorization solution.
