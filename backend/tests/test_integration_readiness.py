"""Cumulative integration probes: delayed admission, legacy upgrade and recovery."""
# Imported pytest fixtures are intentionally re-used as test parameters.
# ruff: noqa: F811
import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from django.db import close_old_connections

from test_staff_api import (  # noqa: F401 - fixtures share the established synthetic upgrade
    staff_api, project_api, membership_api, api, active, prepared,
    post, payload, url, grant, HOD, DEPT, A, ROOT, execute_file, register, team, command,
)
from test_team_api import create, publish
from test_project_api import configure
from rest_framework.test import APIClient


@pytest.mark.parametrize('expires', ['window', 'role'])
def test_team_creation_rechecks_time_after_offering_lock(api, expires):
    _, state = api
    db, oid = state['db'], state['idt_offering']
    publish(db, oid)
    # Use the database clock, not the Python host clock. The thread must reach
    # its offering lock while eligible, then remain blocked beyond the deadline.
    if expires == 'window':
        db.execute("UPDATE student_offering_windows SET visible_until=clock_timestamp()+interval '2 seconds' WHERE offering_id=%s", (oid,))
    else:
        db.execute("UPDATE department_role_assignments SET valid_until=clock_timestamp()+interval '2 seconds' WHERE user_id=%s AND role_code='STUDENT'", (A,))
    started = threading.Event()
    backend_pid = []

    def delayed():
        with psycopg.connect(os.environ['DATABASE_URL']) as app:
            app.execute('SET ROLE smartpro_runtime')
            app.execute("SET lock_timeout='8s'")
            backend_pid.append(app.info.backend_pid)
            started.set()
            try:
                app.execute('SELECT smartpro_create_student_team(%s,%s,%s,%s,%s)',
                            (A, oid, 'Delayed team', 'expiry-probe', 'a'*64))
            except psycopg.Error as exc:
                return exc.sqlstate
            return 'COMMITTED'

    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.transaction():
            db.execute('SELECT id FROM curriculum_offerings WHERE id=%s FOR UPDATE', (oid,))
            future = pool.submit(delayed)
            assert started.wait(3)
            deadline = time.monotonic()+3
            while time.monotonic()<deadline:
                row = db.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s', (backend_pid[0],)).fetchone()
                if row and row['wait_event_type'] == 'Lock':
                    break
                time.sleep(.02)
            else:
                pytest.fail('admission did not reach a real lock wait')
            db.execute('SELECT pg_sleep(2.1)')
        assert future.result(timeout=8) == '42501'
    assert db.execute("SELECT count(*) AS n FROM teams WHERE name='Delayed team'").fetchone()['n'] == 0
    assert db.execute("SELECT count(*) AS n FROM idempotency_records WHERE key='expiry-probe'").fetchone()['n'] == 0


def test_existing_draft_evidence_is_latched_during_staff_upgrade(membership_api, monkeypatch):
    student, state = membership_api
    db = state['db']
    execute_file(db, ROOT/'proposals/curriculum/014_project_registration.sql')
    configure(db, state['societal'])
    monkeypatch.setenv('SMARTPRO_PROJECT_API', 'YES')
    result = register(student)
    assert result.status_code == 201
    project = result.json()['id']
    document = db.execute("INSERT INTO documents(project_id,document_type,label) VALUES(%s,'SYNOPSIS','Legacy draft') RETURNING id", (project,)).fetchone()['id']
    execute_file(db, ROOT/'proposals/curriculum/015_staff_administration.sql')
    db.execute('DELETE FROM documents WHERE id=%s', (document,))
    db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'HOD')", (HOD,DEPT))
    db.execute('INSERT INTO staff_department_controls(department_id,enabled,allow_title_corrections) VALUES(%s,true,true)', (DEPT,))
    grant(db,HOD,'CORRECT_PROJECT')
    monkeypatch.setenv('SMARTPRO_STAFF_API', 'YES')
    staff = APIClient()
    staff.credentials(HTTP_X_DEMO_USER='staff-policy')
    state['managed_project'] = project
    assert post(staff,state,'CORRECT_TITLE').status_code == 409
    assert db.execute('SELECT title FROM projects WHERE id=%s',(project,)).fetchone()['title'] == 'Useful project'


def catalog(db):
    return db.execute("""SELECT c.relname,c.relkind FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY 1,2""").fetchall()


@pytest.mark.parametrize('script', ['010_prepare.sql','010_activate.sql'])
def test_candidate_ten_without_baseline_has_no_partial_install(prepared, script):
    db = prepared['db']
    assert db.info.dbname.startswith('smartpro_test_')
    db.execute('DROP SCHEMA public CASCADE')
    db.execute('CREATE SCHEMA public')
    before = catalog(db)
    with pytest.raises(psycopg.Error):
        execute_file(db,ROOT/'proposals/curriculum'/script)
    db.execute('ROLLBACK')
    assert catalog(db) == before


@pytest.mark.parametrize('candidate', [11,12,13,14,15])
def test_candidate_missing_prerequisite_rolls_back(prepared, candidate):
    db = prepared['db']
    scripts = ['011_student_reads.sql','012_team_creation.sql','013_membership_commands.sql',
               '014_project_registration.sql','015_staff_administration.sql']
    if candidate>11:
        execute_file(db, ROOT/'proposals/curriculum/010_activate.sql')
    for script in scripts[:max(0,candidate-12)]:
        execute_file(db, ROOT/'proposals/curriculum'/script)
    before = catalog(db)
    with pytest.raises(psycopg.Error):
        execute_file(db, ROOT/'proposals/curriculum'/scripts[candidate-11])
    db.execute('ROLLBACK')
    assert catalog(db) == before


def test_prepare_requires_baseline_historical_guards(prepared):
    db = prepared['db']
    assert db.info.dbname.startswith('smartpro_test_')
    db.execute('DROP SCHEMA public CASCADE')
    db.execute('CREATE SCHEMA public')
    for script in sorted((ROOT/'database-v1.5/migrations').glob('*.sql')):
        if script.name[:3]<'009':
            execute_file(db,script)
    before = catalog(db)
    with pytest.raises(psycopg.Error):
        execute_file(db,ROOT/'proposals/curriculum/010_prepare.sql')
    db.execute('ROLLBACK')
    assert catalog(db) == before


def test_preflight_failure_repair_and_complete_install_preserve_legacy(prepared):
    db = prepared['db']
    tables = ['document_versions','submission_attempts','submission_items','approval_decisions',
              'assessments','result_releases','result_student_scores','review_roster_members']
    def historical():
        return [db.execute(f'SELECT to_jsonb(t) AS row FROM {t} t ORDER BY to_jsonb(t)::text').fetchall() for t in tables]
    before = historical()
    db.execute('UPDATE teams SET curriculum_offering_id=NULL')
    reports = db.execute((ROOT/'proposals/curriculum/preflight.sql').read_text())
    assert reports.fetchall()
    with pytest.raises(psycopg.errors.CheckViolation):
        execute_file(db, ROOT/'proposals/curriculum/010_activate.sql')
    db.execute('ROLLBACK')
    assert historical() == before
    assert db.execute("SELECT attnotnull FROM pg_attribute WHERE attrelid='teams'::regclass AND attname='curriculum_offering_id'").fetchone()['attnotnull'] is False
    db.execute('UPDATE teams SET curriculum_offering_id=%s',(prepared['societal'],))
    for script in ['010_activate.sql','011_student_reads.sql','012_team_creation.sql',
                   '013_membership_commands.sql','014_project_registration.sql','015_staff_administration.sql']:
        execute_file(db,ROOT/'proposals/curriculum'/script)
    assert historical() == before
    assert db.execute('SELECT count(*) AS n FROM staff_department_controls').fetchone()['n'] == 0
    assert db.execute('SELECT count(*) AS n FROM staff_permission_assignments').fetchone()['n'] == 0
    assert db.execute('SELECT count(*) AS n FROM student_offering_windows').fetchone()['n'] == 0
    assert db.execute('SELECT count(*) AS n FROM offering_membership_policies').fetchone()['n'] == 0
    assert db.execute('SELECT count(*) AS n FROM offering_project_registration_policies').fetchone()['n'] == 0


def test_student_staff_team_project_end_to_end(staff_api):
    staff,state = staff_api
    student,db,oid = state['student'],state['db'],state['idt_offering']
    assert post(staff,state,'PUBLICATION',target=oid).status_code == 200
    assert post(staff,state,'TEAM_POLICY',payload('TEAM_POLICY',state,revision=1),target=oid,key='team-policy').status_code == 200
    assert post(staff,state,'REGISTRATION',payload('REGISTRATION',state,revision=2),target=oid,key='registration-policy').status_code == 200
    assert str(oid) in {x['id'] for x in student.get('/api/v1/me/curriculum-offerings').json()['results']}
    created = create(student,oid,key='e2e-create')
    assert created.status_code == 201
    old_membership = created.json()['membershipId']
    registered = register(student,tid=created.json()['id'],code='E2E',key='e2e-project')
    assert registered.status_code == 201
    pid = registered.json()['id']
    assert pid in {x['id'] for x in staff.get(url('projects',state)).json()['results']}
    assert post(staff,state,'CORRECT_TITLE',target=pid,key='e2e-title').status_code == 200
    assert register(student,tid=created.json()['id'],code='E2E',key='e2e-project').json() == registered.json()
    target = team(db,oid)
    moved = command(student,'TRANSFER',old_membership,target=target,key='e2e-transfer')
    assert moved.status_code == 201, moved.content
    assert pid not in {x['id'] for x in student.get('/api/v1/me/projects').json()['results']}
    assert db.execute('SELECT response_body FROM student_project_registrations WHERE project_id=%s',(pid,)).fetchone()['response_body'] == registered.json()
    assert command(student,'LEAVE',moved.json()['membershipId'],key='e2e-leave').status_code == 200
    assert command(student,'JOIN',created.json()['id'],key='e2e-rejoin').status_code == 201
    assert pid in {x['id'] for x in student.get('/api/v1/me/projects').json()['results']}
    assert db.execute('SELECT left_at FROM team_memberships WHERE id=%s',(old_membership,)).fetchone()['left_at'] is not None
    close_old_connections()


@pytest.mark.parametrize('checkpoint', ['prepared','activated'])
def test_synthetic_candidate_backup_restore_and_resume(prepared, tmp_path, checkpoint):
    db = prepared['db']
    scripts = ['010_activate.sql','011_student_reads.sql','012_team_creation.sql',
               '013_membership_commands.sql','014_project_registration.sql','015_staff_administration.sql']
    if checkpoint == 'activated':
        for script in scripts:
            execute_file(db,ROOT/'proposals/curriculum'/script)
    def snapshot(conn):
        tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1").fetchall()
        return {r['tablename']: conn.execute(sql.SQL('SELECT to_jsonb(t) AS row FROM {} t ORDER BY to_jsonb(t)::text')
                .format(sql.Identifier(r['tablename']))).fetchall() for r in tables}
    before = snapshot(db)
    config = conninfo_to_dict(os.environ['DATABASE_ADMIN_URL'])
    assert os.environ.get('ALLOW_SMARTPRO_TEST_DB') == 'YES'
    assert config['dbname'].startswith('smartpro_test_')
    restored_name = config['dbname']+'_restore'
    assert len(restored_name)<=63
    binaries = ROOT/'.test-data/postgres/pgsql/bin'
    def binary(name):
        located = shutil.which(name)
        if located:
            return located
        local = binaries/(name+'.exe')
        assert local.is_file(), 'PostgreSQL client tools are required for the recovery check'
        return str(local)
    env = dict(os.environ,PGPASSWORD=config.get('password',''))
    args = ['--host',config['host'],'--port',config.get('port','5432'),'--username',config['user']]
    backup = tmp_path/'candidate.backup'
    subprocess.run([binary('pg_dump'),*args,'--format=custom','--file',str(backup),config['dbname']],
                   env=env,check=True,capture_output=True)
    with psycopg.connect(**dict(config,dbname='postgres'),autocommit=True) as owner:
        owner.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(restored_name)))
        owner.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(restored_name)))
        try:
            subprocess.run([binary('pg_restore'),*args,'--dbname',restored_name,'--exit-on-error','--single-transaction',str(backup)],
                           env=env,check=True,capture_output=True)
            with psycopg.connect(**dict(config,dbname=restored_name),autocommit=True,row_factory=dict_row) as recovered:
                assert snapshot(recovered) == before
                if checkpoint == 'prepared':
                    for script in scripts:
                        execute_file(recovered,ROOT/'proposals/curriculum'/script)
                assert recovered.execute("SELECT attnotnull FROM pg_attribute WHERE attrelid='team_memberships'::regclass AND attname='curriculum_offering_id'").fetchone()['attnotnull']
                assert recovered.execute('SELECT count(*) AS n FROM staff_permission_assignments').fetchone()['n'] == 0
        finally:
            owner.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(restored_name)))
