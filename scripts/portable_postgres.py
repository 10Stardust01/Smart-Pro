"""Optional Windows binary setup: no system install/service and loopback only."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bin-dir', required=True, type=Path)
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--port', type=int, default=55439)
    parser.add_argument('--action', choices=['start', 'stop', 'status'], default='status')
    args = parser.parse_args()
    binaries, data = args.bin_dir.resolve(), args.data_dir.resolve()
    pgctl = binaries / 'pg_ctl.exe'
    if args.action != 'start':
        return subprocess.run([str(pgctl), '-D', str(data), args.action]).returncode
    data.parent.mkdir(parents=True, exist_ok=True)
    settings_path = data.with_suffix('.env.json')
    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
        from psycopg.conninfo import conninfo_to_dict
        owner = conninfo_to_dict(settings['DATABASE_ADMIN_URL'])
    else:
        if (data / 'PG_VERSION').exists():
            raise RuntimeError('Existing cluster needs its original environment file; refusing to invent credentials')
        owner = dict(host='127.0.0.1', port=args.port, user='smartpro_owner', password=secrets.token_hex(24), dbname='smartpro_test')
        app = dict(owner, user='smartpro_api', password=secrets.token_hex(24))
        settings = dict(DATABASE_ADMIN_URL=make_conninfo(**owner), DATABASE_URL=make_conninfo(**app),
                        ALLOW_SMARTPRO_TEST_DB='YES', SMARTPRO_DEMO_AUTH='YES', SMARTPRO_DB_ROLE='smartpro_runtime',
                        SMARTPRO_DATA_DIR=str(data.parent / 'smartpro-files'))
    env = os.environ.copy()
    env['PGPASSWORD'] = owner['password']
    if not (data / 'PG_VERSION').exists():
        with tempfile.NamedTemporaryFile(mode='w', dir=data.parent, delete=False, encoding='utf-8') as pw:
            pw.write(owner['password'])
            pwpath = Path(pw.name)
        try:
            subprocess.run([str(binaries / 'initdb.exe'), '-D', str(data), '-U', owner['user'],
                            '--pwfile='+str(pwpath), '-A', 'scram-sha-256', '--encoding=UTF8', '--locale=C'], env=env, check=True)
        finally:
            pwpath.unlink(missing_ok=True)
    status = subprocess.run([str(pgctl), '-D', str(data), 'status'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if status.returncode:
        subprocess.run([str(pgctl), '-D', str(data), '-l', str(data.parent / 'smartpro-postgres.log'),
                        '-o', f'-h 127.0.0.1 -p {owner["port"]}', '-w', 'start'], env=env, check=True)
    admin = dict(owner, dbname='postgres')
    with psycopg.connect(**admin, autocommit=True) as db:
        if not db.execute('SHOW server_version_num').fetchone()[0].startswith('16'):
            raise RuntimeError('PostgreSQL 16 required')
        if not db.execute('SELECT 1 FROM pg_database WHERE datname=%s', (owner['dbname'],)).fetchone():
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(owner['dbname'])))
    settings_path.write_text(json.dumps(settings, indent=2), encoding='utf-8')
    print('Local environment file (contains secrets; keep outside source control):', settings_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
