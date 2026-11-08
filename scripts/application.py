"""Serve SMART-PRO without seeding; separately create an isolated browser test workspace."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from department_demo import ROOT, TARGET, DEVELOPMENT, CSE, settings, install_documents

DEVELOPMENT_ROOT = ROOT / '.local-data'


def create_workspace(*, development=False):
    """Copy schema only. Never copy academic data or reset an existing database."""
    _, owner, app = settings(ROOT / '.test-data/pg-memberships.env.json')
    name = DEVELOPMENT if development else 'smartpro_test_demo_acceptance_' + uuid4().hex[:12]
    workspace_root = DEVELOPMENT_ROOT if development else ROOT / '.test-data'
    manifest = workspace_root / (name + '.json')
    if manifest.exists() or (workspace_root / name).exists():
        raise RuntimeError('Workspace manifest or storage already exists; provisioning never overwrites it')
    binaries = ROOT / '.test-data/postgres/pgsql/bin'
    child = dict(os.environ, PGPASSWORD=owner['password'])
    args = ['-h', owner['host'], '-p', str(owner['port']), '-U', owner['user']]
    dump = subprocess.run([str(binaries/'pg_dump.exe'), *args, '--schema-only', '--no-owner', TARGET],
                          env=child, capture_output=True, check=True).stdout
    # The dump includes no INSERT/COPY data, approved policy, assignment or result.
    with psycopg.connect(**dict(owner, dbname='postgres'), autocommit=True) as db:
        db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    restored = subprocess.run([str(binaries/'psql.exe'), *args, '-d', name, '-v', 'ON_ERROR_STOP=1'],
                             input=dump, env=child, capture_output=True)
    if restored.returncode:
        raise RuntimeError('Schema restore failed; isolated database retained for inspection')
    return initialize_workspace(owner, name, manifest, development=development)


def initialize_workspace(owner, name, manifest, *, development):
    with psycopg.connect(**dict(owner, dbname=name), autocommit=True, row_factory=dict_row) as db:
        if development:
            existing = db.execute("SELECT (SELECT count(*) FROM public.departments) AS departments,"
                                  " (SELECT count(*) FROM public.projects) AS projects,"
                                  " to_regprocedure('public.smartpro_course_evaluation_queue(uuid,uuid,text)') IS NOT NULL AS installed").fetchone()
            if any(existing.values()):
                raise RuntimeError('Development initialization requires an unused schema-only database')
        install_documents(db,new_development=development)
        from db_setup import execute_file
        for candidate in ['037_course_coordination.sql','038_course_assessment_lifecycle.sql',
                          '039_course_deadlines_notifications.sql','040_course_integration.sql',
                          '041_course_scope_guards.sql','042_course_authorized_operations.sql',
                          '043_runtime_function_grants.sql','044_coordinator_own_corrections.sql','045_admin_course_appointments.sql','046_department_leadership.sql','047_department_intake.sql','048_course_evaluation_queue.sql','049_paginated_evaluation_queue.sql','050_document_project_pages.sql','051_department_intake_pages.sql','052_department_directory.sql','053_department_import_outcomes.sql','054_department_offering_pages.sql','055_leadership_history_pages.sql','056_coordinator_catalog_scope_prefilter.sql','057_department_identity_navigation.sql']:
            execute_file(db,ROOT/'proposals/curriculum'/candidate)
        if development:
            execute_file(db,ROOT/'proposals/development/persona_labels.sql')
        with db.transaction():
            db.execute("INSERT INTO departments(id,code,name) VALUES(%s,'CSE','Computer Science and Engineering')", (CSE,))
            for suffix, label, role in [(1,'Arjun Mehta','STUDENT'), (3,'Anika Rao','FACULTY'),
                                        (4,'Meera Iyer','HOD'), (8,'Dev Menon','FACULTY'),
                                        (12,'Nisha Reddy','ACADEMIC_ADMIN')]:
                uid = f'00000000-0000-4000-8000-{suffix:012d}'
                db.execute('INSERT INTO users(id,display_name,email) VALUES(%s,%s,%s)',
                           (uid,label,f'acceptance-{suffix}@example.invalid'))
                rid = db.execute('INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,%s) RETURNING id',
                                 (uid,CSE,role)).fetchone()['id']
                if role == 'HOD':
                    db.execute('INSERT INTO academic_hod_mandates(department_id,role_assignment_id,user_id,enabled) VALUES(%s,%s,%s,true)', (CSE,rid,uid))
                    db.execute("INSERT INTO academic_action_grants(user_id,department_id,action_code) VALUES(%s,%s,'APPROVE_SCHEME')", (uid,CSE))
            db.execute('INSERT INTO academic_governance_settings(department_id,enabled) VALUES(%s,true)', (CSE,))
            db.execute('INSERT INTO staff_department_controls(department_id,enabled) VALUES(%s,true)', (CSE,))
            counts = db.execute('SELECT (SELECT count(*) FROM curriculum_offerings) offerings,(SELECT count(*) FROM projects) projects,(SELECT count(*) FROM project_policy_versions) policies,(SELECT count(*) FROM faculty_assignments) assignments').fetchone()
            if any(counts.values()):
                raise RuntimeError('Fresh acceptance workspace must contain no academic records')
    storage = manifest.parent / name
    storage.mkdir(parents=True,exist_ok=False)
    with manifest.open('x',encoding='utf-8') as stream:
        json.dump({'database':name,'purpose':'PERSISTENT_LOCAL_DEVELOPMENT' if development else 'ISOLATED_BROWSER_ACCEPTANCE',
                   'storage':str(storage)},stream,indent=2)
    print('Created workspace:', name, flush=True)
    print('Manifest:', manifest, flush=True)
    return manifest


def create_test_workspace():
    return create_workspace()


def serve(port, manifest=None, faculty_reference=False, *, development=False):
    env = dict(os.environ, SMARTPRO_UI='YES', PYTHONPATH=str(ROOT/'backend'), DJANGO_SETTINGS_MODULE='smartpro.settings')
    env.pop('DATABASE_ADMIN_URL', None)
    env['SMARTPRO_FACULTY_REFERENCE']='NO'
    env['SMARTPRO_LOCAL_DEVELOPMENT']='NO'
    env['DJANGO_SECRET_KEY'] = env.get('DJANGO_SECRET_KEY') or secrets.token_hex(32)
    if manifest:
        record = json.loads(manifest.read_text(encoding='utf-8'))
        if development:
            if (record.get('purpose') != 'PERSISTENT_LOCAL_DEVELOPMENT' or record['database'] != DEVELOPMENT
                or Path(record['storage']).resolve() != (DEVELOPMENT_ROOT/DEVELOPMENT).resolve()):
                raise RuntimeError('The dedicated local development manifest is required')
            if env.get('SMARTPRO_DEPLOYMENT','development') != 'development':
                raise RuntimeError('Local development sign-in requires development settings')
            env['SMARTPRO_LOCAL_DEVELOPMENT']='YES'
        elif record.get('purpose') != 'ISOLATED_BROWSER_ACCEPTANCE' or not record['database'].startswith('smartpro_test_demo_acceptance_'):
            raise RuntimeError('An explicit isolated browser-test manifest is required')
        _, owner, app = settings(ROOT/'.test-data/pg-memberships.env.json')
        if app.get('host') not in ('127.0.0.1','localhost') or app['host'] != owner.get('host') or app.get('port') != owner.get('port'):
            raise RuntimeError('Runtime and owner configuration must point to the same loopback cluster')
        env.update(DATABASE_URL=make_conninfo(**dict(app,dbname=record['database'])), SMARTPRO_ENV='demo',
                   SMARTPRO_DEMO_AUTH='YES', SMARTPRO_DEPARTMENT_DEMO='YES',SMARTPRO_DATA_DIR=record['storage'])
        for gate in ['CURRICULUM','TEAM','MEMBERSHIP','PROJECT','STAFF','ACADEMIC','DOCUMENT']:
            env['SMARTPRO_'+gate+'_API']='YES'
        # Read-only capability discovery keeps older isolated workspaces usable.
        # Serving never upgrades their schema or fabricates coordinator appointments.
        with psycopg.connect(**dict(app,dbname=record['database'])) as db:
            course_ready=db.execute("SELECT to_regprocedure('public.smartpro_course_auxiliary(uuid,uuid,text,jsonb,text)') IS NOT NULL").fetchone()[0]
            if development:
                signatures = [
                    'public.smartpro_course_evaluation_queue(uuid,uuid,text)',
                    'public.smartpro_course_evaluation_queue(uuid,uuid,text,text,text,integer)',
                    'public.smartpro_document_project_page(uuid,uuid,text,text,integer,uuid)',
                ]
                if not course_ready or not db.execute(
                    'SELECT NOT EXISTS (SELECT FROM unnest(%s::text[]) s WHERE to_regprocedure(s) IS NULL)',
                    (signatures,),
                ).fetchone()[0]:
                    raise RuntimeError('Development database requires reviewed candidates 048–050')
            if faculty_reference:
                leadership_ready=db.execute("SELECT to_regprocedure('public.smartpro_department_leadership(uuid,uuid,text)') IS NOT NULL").fetchone()[0]
                if not course_ready or not leadership_ready:
                    raise RuntimeError('Faculty Reference requires a current isolated test workspace')
                env['SMARTPRO_FACULTY_REFERENCE']='YES'
        env['SMARTPRO_COURSE_API']='YES' if course_ready else 'NO'
    else:
        # Normal startup never creates data, migrations, identities or approvals.
        env.update(SMARTPRO_ENV='local',SMARTPRO_DEMO_AUTH='NO',SMARTPRO_DEPARTMENT_DEMO='NO')
        if not env.get('DATABASE_URL'):
            raise RuntimeError('Supply DATABASE_URL for your provisioned application; startup never seeds a database')
    worker=None
    if env.get('SMARTPRO_COURSE_API')=='YES' and env.get('SMARTPRO_ACADEMIC_API')=='YES':
        worker=subprocess.Popen([sys.executable,'-m','django','course_notifications','--interval','60'],env=env,cwd=ROOT)
    try:
        command = [sys.executable, '-m', 'django', 'runserver', f'127.0.0.1:{port}']
        if not development:
            command.append('--noreload')
        return subprocess.run(command, env=env, cwd=ROOT).returncode
    finally:
        if worker is not None:
            worker.terminate()
            try:worker.wait(timeout=10)
            except subprocess.TimeoutExpired:worker.kill();worker.wait()



if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['serve','test-workspace','init-development','serve-development'])
    parser.add_argument('--test-manifest',type=Path)
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--faculty-reference',action='store_true',help='Enable Faculty Reference in an isolated test workspace')
    args=parser.parse_args()
    if args.action in ('init-development','serve-development') and args.test_manifest:
        parser.error('Development uses its dedicated manifest')
    if args.faculty_reference and (args.action=='init-development' or args.action=='serve' and not args.test_manifest):
        parser.error('--faculty-reference requires a local workspace')
    if args.action=='init-development':
        create_workspace(development=True)
        raise SystemExit(0)
    development=args.action=='serve-development'
    manifest=(DEVELOPMENT_ROOT/f'{DEVELOPMENT}.json' if development else
              create_workspace() if args.action=='test-workspace' else args.test_manifest)
    raise SystemExit(serve(args.port,manifest,args.faculty_reference,development=development))
