#!/usr/bin/env bash
set -euo pipefail
: "${DATABASE_URL:?Set DATABASE_URL to an EMPTY local/test PostgreSQL database.}"
if [[ "${ALLOW_SMARTPRO_TEST_DB:-}" != "YES" ]]; then
  echo 'Refusing to execute. Set ALLOW_SMARTPRO_TEST_DB=YES to confirm an EMPTY TEST database.' >&2
  exit 2
fi
command -v psql >/dev/null || { echo 'psql client is required' >&2; exit 2; }
cd "$(dirname "$0")"
for f in migrations/*.sql tests/001_seed.sql tests/002_constraints.sql tests/003_smoke_queries.sql; do
  echo "--> $f"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"
done
echo 'All database tests passed.'
