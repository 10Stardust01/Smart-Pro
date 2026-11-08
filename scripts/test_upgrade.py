"""Execute untouched v1.5 ZIP SQL, then forward migrations; synthetic test DB only."""
import json
import os
from pathlib import Path
import sys
import zipfile

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from db_setup import execute_file


def main():
    if os.environ.get('ALLOW_SMARTPRO_TEST_DB') != 'YES':
        raise RuntimeError('Explicit test flag required')
    cfg = conninfo_to_dict(os.environ['DATABASE_ADMIN_URL'])
    cfg['dbname'] = 'postgres'
    name = 'smartpro_test_upgrade'
    with psycopg.connect(**cfg, autocommit=True) as db:
        db.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))
        db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    cfg['dbname'] = name
    queries = {
        'documents': 'SELECT id,project_id,document_id,version_no,file_asset_id,uploaded_by FROM document_versions ORDER BY id',
        'assessments': 'SELECT id,review_id,scheme_mode_id,evaluator_assignment_id,state,finalized_at FROM assessments ORDER BY id',
        'releases': 'SELECT id,review_id,release_no,calculation_snapshot,released_by,released_at,supersedes_id FROM result_releases ORDER BY id',
        'results': 'SELECT * FROM result_student_scores ORDER BY release_id,roster_member_id',
        'decisions': 'SELECT id,attempt_id,project_id,reviewer_user_id,decision,comment,decided_at FROM approval_decisions ORDER BY id',
    }
    with psycopg.connect(**cfg, autocommit=True, row_factory=dict_row) as db:
        with zipfile.ZipFile(ROOT / 'evidence/SMARTPRO.original.zip') as source:
            paths = sorted(x for x in source.namelist() if '/migrations/' in x and x.endswith('.sql'))
            paths.append('database-v1.5/tests/001_seed.sql')
            for path in paths:
                db.execute(source.read(path).decode('utf-8'), prepare=False)
                print('PASS ORIGINAL SQL', path, flush=True)
        before = {k: db.execute(q).fetchall() for k, q in queries.items()}
        applied = []
        for path in sorted((ROOT / 'database-v1.5/migrations').glob('*.sql')):
            if path.name[:3] > '004':
                execute_file(db, path)
                applied.append(path.name)
        after = {k: db.execute(q).fetchall() for k, q in queries.items()}
        assert before == after, 'Historical identities, scores or attribution changed'
        assert db.execute('SELECT count(*) AS n FROM submission_attempts WHERE sealed_at IS NULL OR submitted_membership_id IS NULL').fetchone()['n'] == 0
        try:
            db.execute('DELETE FROM submission_items')
        except psycopg.errors.CheckViolation:
            pass
        else:
            raise AssertionError('Upgraded historical items remain mutable')
        result = {
            'status': 'PASSED', 'version': db.execute('SELECT version() AS v').fetchone()['v'],
            'database': name, 'forward_migrations': applied, 'historical_queries_unchanged': list(queries),
            'legacy_release_grants_not_fabricated': db.execute('SELECT count(*) AS n FROM result_releases WHERE authorization_grant_id IS NULL').fetchone()['n'],
            'scope': 'Supplied synthetic v1.5 schema/seed only; no production upgrade claim',
        }
    (ROOT / 'evidence/upgrade-summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
