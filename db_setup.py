"""Migration/test provisioning only; not called by HTTP request handlers."""
import os
from pathlib import Path
import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent
DB_ROOT = ROOT / 'database-v1.5'

def admin_connect():
    db = psycopg.connect(os.environ['DATABASE_ADMIN_URL'], autocommit=True)
    db.add_notice_handler(lambda diag: print(f'SQL NOTICE {diag.message_primary}', flush=True))
    return db

def execute_file(db, path):
    # psql-only ON_ERROR_STOP directive has no SQL semantics; psycopg raises errors.
    source = '\n'.join(line for line in Path(path).read_text(encoding='utf-8').splitlines()
                       if not line.startswith('\\'))
    try:
        db.execute(source, prepare=False)
        print(f'PASS SQL {Path(path).name}', flush=True)
    except psycopg.Error as exc:
        print(f'FAIL SQL {Path(path).name} sqlstate={exc.sqlstate}: {exc}', flush=True)
        raise

def grant_runtime(db):
    db.execute("DO $$ BEGIN IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='smartpro_runtime') THEN CREATE ROLE smartpro_runtime NOLOGIN; END IF; END $$")
    db.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
    db.execute('GRANT USAGE ON SCHEMA public TO smartpro_runtime')
    # Never grant blanket SELECT to the application role. Current synopsis
    # reads are enumerated in the reviewed owner-run security script below.
    db.execute('GRANT EXECUTE ON FUNCTION smartpro_project_permission(uuid,uuid,text) TO smartpro_runtime')
    # Owner-run reviewable policies are the single authority for runtime
    # grants. Provision only after schema and synthetic fixtures are installed.
    execute_file(db, ROOT / 'proposals' / 'security' / 'runtime_read_boundary.sql')
    execute_file(db, ROOT / 'proposals' / 'security' / 'runtime_write_boundary.sql')


def create_test_login():
    from psycopg.conninfo import conninfo_to_dict
    settings = conninfo_to_dict(os.environ['DATABASE_URL'])
    username, password = settings.get('user'), settings.get('password')
    if os.environ.get('ALLOW_SMARTPRO_TEST_DB') != 'YES' or username != 'smartpro_api' or not password:
        raise RuntimeError('Explicit synthetic smartpro_api login configuration required')
    with admin_connect() as db:
        if not db.info.dbname.startswith(('smartpro_test', 'smartpro_validation')):
            raise RuntimeError('Test login provisioning limited to isolated test databases')
        old = db.execute('SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=%s', (username,)).fetchone()
        if old and any(old):
            raise RuntimeError('Existing application login has unsafe administrative privileges')
        if not old:
            db.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT').format(sql.Identifier(username), sql.Literal(password)))
        db.execute(sql.SQL('GRANT smartpro_runtime TO {}').format(sql.Identifier(username)))

def reset_test_database(seed='001_seed.sql'):
    if os.environ.get('ALLOW_SMARTPRO_TEST_DB') != 'YES':
        raise RuntimeError('Test reset requires ALLOW_SMARTPRO_TEST_DB=YES')
    with admin_connect() as db:
        info = db.info
        if not info.dbname.startswith(('smartpro_test', 'smartpro_validation')):
            raise RuntimeError('Refusing reset outside explicitly named isolated test database')
        if db.execute('SHOW server_version_num').fetchone()[0][:2] != '16':
            raise RuntimeError('This validation targets PostgreSQL 16')
        db.execute('DROP SCHEMA public CASCADE')
        db.execute('CREATE SCHEMA public')
        for path in sorted((DB_ROOT / 'migrations').glob('*.sql')):
            execute_file(db, path)
        if seed:
            execute_file(db, DB_ROOT / 'tests' / seed)
        grant_runtime(db)

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', default='001_seed.sql')
    parser.add_argument('--legacy-tests', action='store_true')
    parser.add_argument('--create-test-login', action='store_true')
    args = parser.parse_args()
    reset_test_database(args.seed)
    if args.create_test_login:
        create_test_login()
    if args.legacy_tests:
        with admin_connect() as db:
            execute_file(db, DB_ROOT / 'tests/002_constraints.sql')
            execute_file(db, DB_ROOT / 'tests/003_smoke_queries.sql')
