"""Exercise logical PostgreSQL and PDF recovery for a named browser test workspace."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import psycopg
from psycopg import sql

from department_demo import ROOT, settings


def fingerprint(db):
    tables = db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
    rows = sql.SQL(
        "SELECT count(*), md5(coalesce(string_agg(to_jsonb(r)::text, chr(10)"
        " ORDER BY to_jsonb(r)::text), '')) FROM public.{} r"
    )
    return {name: db.execute(rows.format(sql.Identifier(name))).fetchone() for (name,) in tables}


def restore(manifest_path):
    root = (ROOT / '.test-data').resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    source = manifest['database']
    storage = Path(manifest['storage']).resolve()
    if (manifest_path.resolve().parent != root
            or manifest['purpose'] != 'ISOLATED_BROWSER_ACCEPTANCE'
            or not source.startswith('smartpro_test_demo_acceptance_')
            or not source.replace('_', '').isalnum()
            or storage != root / source):
        raise ValueError('Expected an isolated browser acceptance manifest and its local storage')

    target = 'smartpro_test_demo_acceptance_restore_' + uuid4().hex[:8]
    output = root / target
    output.mkdir()
    _, owner, _ = settings(root / 'pg-memberships.env.json')
    binaries = root / 'postgres' / 'pgsql' / 'bin'
    environment = dict(os.environ, PGPASSWORD=owner['password'])
    connection_args = ['-h', owner['host'], '-p', str(owner['port']), '-U', owner['user']]
    archive = output / 'workspace.backup'
    with psycopg.connect(**dict(owner, dbname=source)) as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        snapshot = db.execute('SELECT pg_export_snapshot()').fetchone()[0]
        expected = fingerprint(db)
        files = db.execute(
            "SELECT storage_key,sha256,size_bytes FROM file_assets WHERE upload_status='READY' ORDER BY storage_key"
        ).fetchall()
        subprocess.run([str(binaries / 'pg_dump.exe'), *connection_args, '--snapshot', snapshot,
                        '-Fc', '-f', str(archive), source], env=environment, check=True, timeout=120)
        source_files = (storage / 'files').resolve()
        if source_files != storage / 'files':
            raise ValueError('Unexpected symbolic link at source PDF directory')
        target_files = output / 'files'
        target_files.mkdir()
        for key, digest, size in files:
            path = source_files / key
            if path.resolve().parent != source_files or path.is_symlink() or not path.is_file():
                raise ValueError('Invalid or missing stored PDF in the isolated backup source')
            content = path.read_bytes()
            if len(content) != size or hashlib.sha256(content).hexdigest() != digest.strip():
                raise ValueError('Stored PDF does not match its recorded size and digest')
            restored = target_files / path.name
            with restored.open('xb') as stream:
                stream.write(content)
            if hashlib.sha256(restored.read_bytes()).hexdigest() != digest.strip():
                raise ValueError('Restored PDF does not match its recorded digest')

    with psycopg.connect(**dict(owner, dbname='postgres'), autocommit=True) as db:
        db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(target)))
    subprocess.run([str(binaries / 'pg_restore.exe'), *connection_args, '--exit-on-error',
                    '--single-transaction', '-d', target, str(archive)], env=environment, check=True, timeout=120)
    with psycopg.connect(**dict(owner, dbname=target)) as db:
        if fingerprint(db) != expected:
            raise ValueError('Restored public table fingerprints differ from the backup snapshot')
    output.with_suffix('.json').write_text(json.dumps({
        'database': target, 'purpose': 'ISOLATED_BROWSER_ACCEPTANCE', 'storage': str(output)
    }, indent=2), encoding='utf-8')
    print(f'{target}: matched {len(expected)} public tables and {len(files)} PDFs')
    for table in ('document_versions', 'assessments', 'academic_result_versions', 'course_final_results', 'audit_events'):
        print(f'{table}: {expected[table][0]}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    restore(parser.parse_args().manifest)
