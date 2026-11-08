"""Reproducible clean-room validation; explicit isolated test databases only."""
import argparse
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from db_setup import reset_test_database

ROOT = Path(__file__).resolve().parent


def recreate_database():
    if os.environ.get('ALLOW_SMARTPRO_TEST_DB') != 'YES':
        raise RuntimeError('Explicit ALLOW_SMARTPRO_TEST_DB=YES required')
    cfg = conninfo_to_dict(os.environ['DATABASE_ADMIN_URL'])
    name = cfg.get('dbname', '')
    if not name.startswith(('smartpro_test', 'smartpro_validation')):
        raise RuntimeError('Refusing to destroy a non-test database')
    cfg['dbname'] = 'postgres'
    with psycopg.connect(**cfg, autocommit=True) as db:
        if not db.execute('SHOW server_version_num').fetchone()[0].startswith('16'):
            raise RuntimeError('PostgreSQL 16 required')
        db.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))
        db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    print('Recreated isolated database:', name, flush=True)


def inventory():
    with psycopg.connect(os.environ['DATABASE_ADMIN_URL'], autocommit=True, row_factory=dict_row) as db:
        return {
            'version': db.execute('SELECT version() AS version').fetchone()['version'],
            'extensions': db.execute('SELECT extname,extversion FROM pg_extension ORDER BY extname').fetchall(),
            'tables': db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall(),
            'constraints': db.execute("SELECT conname,contype,convalidated,pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE connamespace='public'::regnamespace ORDER BY conname").fetchall(),
            'triggers': db.execute("SELECT event_object_table,trigger_name,event_manipulation,action_statement FROM information_schema.triggers WHERE trigger_schema='public' ORDER BY 1,2,3").fetchall(),
            'indexes': db.execute("SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY 1,2").fetchall(),
            'functions': db.execute("SELECT proname,prosecdef,proconfig FROM pg_proc WHERE pronamespace='public'::regnamespace ORDER BY proname").fetchall(),
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--recreate', action='store_true')
    parser.add_argument('--label', default='cleanroom')
    args = parser.parse_args()
    if not args.label.replace('-', '').replace('_', '').isalnum():
        raise ValueError('Invalid evidence label')
    out = ROOT / 'evidence'
    out.mkdir(exist_ok=True)
    steps = []
    def run(name, command):
        start = time.perf_counter()
        result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out / f'{args.label}-{name}.log').write_text(result.stdout, encoding='utf-8')
        print(result.stdout, flush=True)
        steps.append({'stage': name, 'command': command, 'exit_code': result.returncode, 'seconds': time.perf_counter()-start})
        return result.returncode
    if args.recreate:
        recreate_database()
    failed = run('migrations-and-sql', [sys.executable, 'db_setup.py', '--legacy-tests', '--create-test-login'])
    if not failed:
        failed |= run('pytest', [sys.executable, '-m', 'pytest', 'tests', 'workflow-poc/tests', '-q',
                                f'--junitxml={out / (args.label + ".xml")}', '-p', 'no:cacheprovider', '-s'])
        failed |= run('lint', [sys.executable, '-m', 'ruff', 'check', '.', '--select', 'F,E9', '--no-cache'])
        failed |= run('sql-static', [sys.executable, 'database-v1.5/tests/static_lint.py'])
        # Explicit syntax pass without writing bytecode into deliverables.
        paths = [p for p in ROOT.rglob('*.py') if '__pycache__' not in p.parts]
        for path in paths:
            ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        steps.append({'stage': 'python-ast', 'files': len(paths), 'exit_code': 0})
        if not failed:
            reset_test_database()
            (out / f'{args.label}-schema-inventory.json').write_text(json.dumps(inventory(), indent=2, default=str), encoding='utf-8')
    summary = {'steps': steps, 'status': 'FAILED' if failed else 'PASSED'}
    xml = out / f'{args.label}.xml'
    if xml.exists():
        suites = ET.parse(xml).getroot().findall('testsuite')
        summary['tests'] = {k: sum(int(x.attrib.get(k, 0)) for x in suites) for k in ['tests', 'failures', 'errors', 'skipped']}
        summary['tests']['passed'] = summary['tests']['tests']-summary['tests']['failures']-summary['tests']['errors']-summary['tests']['skipped']
    (out / f'{args.label}-summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
