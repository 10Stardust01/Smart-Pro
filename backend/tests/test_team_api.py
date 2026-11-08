"""Real Django HTTP + PostgreSQL 16 contracts for student team commands."""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import django
import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartpro.settings')
os.environ.setdefault('DJANGO_SECRET_KEY', 'synthetic-team-tests-only')
django.setup()

from django.db import OperationalError, close_old_connections, connection
from rest_framework.test import APIClient
from unittest.mock import patch
from db_setup import execute_file
from proposals.curriculum.test_contracts import (  # noqa: F401
    A, DEPT, CYCLE, active, prepared, offering, team,
)

CREATE = '/api/v1/teams'
LIST = '/api/v1/curriculum-offerings/{}/teams'


@pytest.fixture
def api(active, monkeypatch):  # noqa: F811
    connection.close()
    db = active['db']
    execute_file(db, ROOT / 'proposals/curriculum/011_student_reads.sql')
    execute_file(db, ROOT / 'proposals/curriculum/012_team_creation.sql')
    monkeypatch.setenv('SMARTPRO_ENV', 'demo')
    monkeypatch.setenv('SMARTPRO_DEMO_AUTH', 'YES')
    monkeypatch.setenv('SMARTPRO_CURRICULUM_API', 'YES')
    monkeypatch.setenv('SMARTPRO_TEAM_API', 'YES')
    client = APIClient()
    client.credentials(HTTP_X_DEMO_USER='student-a')
    yield client, active
    connection.close()


def publish(db, oid, *, enabled=True):
    db.execute("""
        UPDATE curriculum_offerings
        SET student_team_creation_enabled=%s WHERE id=%s
    """, (enabled, oid))
    db.execute("""
        INSERT INTO student_offering_windows(offering_id,visible_from,visible_until)
        VALUES(%s,now()-interval '1 day',now()+interval '1 day')
    """, (oid,))


def create(client, oid, name='Student Team', key='team-test-key'):
    return client.post(
        CREATE, {'offeringId': str(oid), 'name': name},
        format='json', HTTP_IDEMPOTENCY_KEY=key,
    )


def test_create_team_is_atomic_audited_and_scoped(api):
    client, state = api
    db = state['db']
    oid = state['idt_offering']
    publish(db, oid)
    before = db.execute('SELECT COUNT(*) AS n FROM teams').fetchone()['n']
    response = create(client, oid)
    assert response.status_code == 201, response.content
    item = response.json()
    assert item['name'] == 'Student Team'
    assert item['offeringId'] == str(oid)
    assert response['Cache-Control'] == 'no-store'
    assert db.execute('SELECT COUNT(*) AS n FROM teams').fetchone()['n'] == before + 1
    membership = db.execute('SELECT team_id,user_id,curriculum_offering_id FROM team_memberships WHERE id=%s',
                            (item['membershipId'],)).fetchone()
    assert str(membership['team_id']) == item['id']
    assert str(membership['user_id']) == A
    assert membership['curriculum_offering_id'] == oid
    audit = db.execute("SELECT actor_id,action,metadata FROM audit_events WHERE target_id=%s", (item['id'],)).fetchone()
    assert str(audit['actor_id']) == A and audit['action'] == 'TEAM_CREATED'
    assert audit['metadata']['membershipId'] == item['membershipId']
    record = db.execute("SELECT state,response_status,response_body FROM idempotency_records WHERE actor_id=%s AND operation='STUDENT_CREATE_TEAM'",
                        (A,)).fetchone()
    assert record['state'] == 'COMPLETE' and record['response_status'] == 201
    assert record['response_body']['id'] == item['id']


def test_identical_retry_returns_same_team_without_extra_writes(api):
    client, state = api
    db = state['db']
    publish(db, state['idt_offering'])
    first = create(client, state['idt_offering'], name='  Robotics  ')
    second = create(client, state['idt_offering'], name='Robotics')
    assert first.status_code == 201 and second.status_code == 200
    assert first.json() == second.json()
    assert db.execute("SELECT COUNT(*) AS n FROM audit_events WHERE action='TEAM_CREATED'").fetchone()['n'] == 1


def test_reused_key_with_changed_payload_is_conflict(api):
    client, state = api
    db = state['db']
    publish(db, state['idt_offering'])
    assert create(client, state['idt_offering']).status_code == 201
    response = create(client, state['idt_offering'], name='Another name')
    assert response.status_code == 409
    assert db.execute("SELECT COUNT(*) AS n FROM audit_events WHERE action='TEAM_CREATED'").fetchone()['n'] == 1


def test_retry_after_publication_closes_still_returns_original_team(api):
    client, state = api
    db = state['db']
    publish(db, state['idt_offering'])
    first = create(client, state['idt_offering'])
    assert first.status_code == 201
    db.execute("UPDATE student_offering_windows SET visible_until=now()-interval '1 minute', visible_from=now()-interval '2 days' WHERE offering_id=%s",
               (state['idt_offering'],))
    retry = create(client, state['idt_offering'])
    assert retry.status_code == 200 and retry.json() == first.json()
    assert create(client, state['idt_offering'], key='new-key').status_code == 403


def test_duplicate_team_membership_rolls_back_command_and_audit(api):
    client, state = api
    db = state['db']
    publish(db, state['idt_offering'])
    assert create(client, state['idt_offering']).status_code == 201
    team_count = db.execute('SELECT COUNT(*) AS n FROM teams').fetchone()['n']
    result = create(client, state['idt_offering'], name='Second Team', key='another-key')
    assert result.status_code == 409
    assert db.execute('SELECT COUNT(*) AS n FROM teams').fetchone()['n'] == team_count
    assert db.execute("SELECT COUNT(*) AS n FROM audit_events WHERE action='TEAM_CREATED'").fetchone()['n'] == 1
    assert db.execute("SELECT COUNT(*) AS n FROM idempotency_records WHERE operation='STUDENT_CREATE_TEAM'").fetchone()['n'] == 1


@pytest.mark.parametrize('mode', ['hidden', 'creation-disabled', 'expired', 'other-semester', 'other-department'])
def test_creation_denied_without_eligible_offering(api, mode):
    client, state = api
    db = state['db']
    oid = state['idt_offering']
    if mode == 'hidden':
        pass
    elif mode == 'creation-disabled':
        publish(db, oid, enabled=False)
    elif mode == 'expired':
        publish(db, oid)
        db.execute("UPDATE student_offering_windows SET visible_from=now()-interval '3 days',visible_until=now()-interval '1 day' WHERE offering_id=%s", (oid,))
    elif mode == 'other-semester':
        oid = offering(db, state['sp'], semester='SYNTHETIC-SEM-4')
        publish(db, oid)
    else:
        dept = db.execute("INSERT INTO departments(code,name) VALUES('X-DEPT','Another Department') RETURNING id").fetchone()['id']
        cycle = db.execute("INSERT INTO academic_cycles(department_id,code,starts_on,ends_on) VALUES(%s,'SECOND','2026-01-01','2027-01-01') RETURNING id", (dept,)).fetchone()['id']
        oid = offering(db, state['sp'], department=dept, cycle=cycle)
        publish(db, oid)
    result = create(client, oid)
    assert result.status_code == 403
    assert db.execute("SELECT COUNT(*) AS n FROM audit_events WHERE action='TEAM_CREATED'").fetchone()['n'] == 0


@pytest.mark.parametrize('mode', ['disabled', 'expired-role', 'missing-profile'])
def test_create_rejects_ineligible_actor(api, mode):
    client, state = api
    db = state['db']
    publish(db, state['idt_offering'])
    if mode == 'disabled':
        db.execute("UPDATE users SET account_status='DISABLED' WHERE id=%s", (A,))
    elif mode == 'expired-role':
        db.execute("UPDATE department_role_assignments SET valid_until=now()-interval '1 day',valid_from=now()-interval '3 days' WHERE user_id=%s", (A,))
    else:
        client.credentials(HTTP_X_DEMO_USER='faculty-a')
    assert create(client, state['idt_offering']).status_code == 403


def test_validation_authentication_and_gates(api, monkeypatch):
    client, state = api
    oid = state['idt_offering']
    assert create(client, oid, key='bad key').status_code == 400
    assert create(client, oid, key='').status_code == 400
    assert create(client, oid, name='   ').status_code == 400
    assert create(client, oid, name='x'*121).status_code == 400
    assert client.post(CREATE, {'offeringId':str(oid),'name':'Good','userId':A},
                       format='json', HTTP_IDEMPOTENCY_KEY='valid').status_code == 400
    assert client.post(CREATE, ['invalid'], format='json', HTTP_IDEMPOTENCY_KEY='valid').status_code == 400
    client.credentials()
    assert create(client, oid).status_code == 401
    client.credentials(HTTP_X_DEMO_USER='student-a')
    monkeypatch.setenv('SMARTPRO_ENV', 'production')
    assert create(client, oid).status_code == 401
    monkeypatch.setenv('SMARTPRO_ENV', 'demo')
    monkeypatch.delenv('SMARTPRO_TEAM_API')
    assert create(client, oid).status_code == 503


def test_eligible_team_discovery_does_not_reveal_other_offerings(api):
    client, state = api
    db = state['db']
    publish(db, state['societal'], enabled=False)
    results = client.get(LIST.format(state['societal']))
    assert results.status_code == 200
    expected = {str(row['id']) for row in db.execute(
        'SELECT id FROM teams WHERE curriculum_offering_id=%s',
        (state['societal'],)).fetchall()}
    listed = {row['id']: row for row in results.json()['results']}
    assert set(listed) == expected
    actual_members = db.execute("""
        SELECT COUNT(*) AS n FROM team_memberships
        WHERE team_id=%s AND joined_at<=statement_timestamp()
          AND (left_at IS NULL OR statement_timestamp()<left_at)
    """, ('13000000-0000-4000-8000-000000000001',)).fetchone()['n']
    assert actual_members > 0
    assert listed['13000000-0000-4000-8000-000000000001']['memberCount'] == actual_members
    assert all(row['offeringId'] == str(state['societal']) for row in listed.values())
    assert 'usn' not in str(results.json()).lower()
    assert client.get(LIST.format(state['idt_offering'])).status_code == 403
    other_semester = offering(db, state['sp'], semester='SYNTHETIC-SEM-4')
    publish(db, other_semester)
    assert client.get(LIST.format(other_semester)).status_code == 403


def test_team_discovery_cursor_pagination(api):
    client, state = api
    db = state['db']
    publish(db, state['idt_offering'])
    ids = [str(team(db, state['idt_offering'])) for _ in range(51)]
    first = client.get(LIST.format(state['idt_offering'])).json()
    assert len(first['results']) == 50
    assert first['nextCursor'] == first['results'][-1]['id']
    second = client.get(LIST.format(state['idt_offering']), {'cursor':first['nextCursor']}).json()
    assert len(second['results']) == 1 and second['nextCursor'] is None
    assert [r['id'] for r in first['results']+second['results']] == sorted(ids)
    assert client.get(LIST.format(state['idt_offering']), {'cursor':'not-a-uuid'}).status_code == 400


def test_concurrent_same_key_creates_exactly_one_team(api):
    _, state = api
    db = state['db']
    publish(db, state['idt_offering'])
    oid = state['idt_offering']

    def worker(_):
        close_old_connections()
        try:
            client = APIClient()
            client.credentials(HTTP_X_DEMO_USER='student-a')
            response = create(client, oid, key='parallel-one')
            return response.status_code, response.json()
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, range(2)))
    assert sorted(x[0] for x in results) == [200, 201]
    assert results[0][1] == results[1][1]
    assert db.execute("SELECT COUNT(*) AS n FROM audit_events WHERE action='TEAM_CREATED'").fetchone()['n'] == 1


def test_concurrent_different_keys_do_not_create_two_memberships(api):
    _, state = api
    db = state['db']
    publish(db, state['idt_offering'])
    oid = state['idt_offering']

    def worker(key):
        close_old_connections()
        try:
            client = APIClient()
            client.credentials(HTTP_X_DEMO_USER='student-a')
            return create(client, oid, key=key).status_code
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, ['parallel-a', 'parallel-b']))
    assert sorted(results) == [201, 409]
    assert db.execute("SELECT COUNT(*) AS n FROM audit_events WHERE action='TEAM_CREATED'").fetchone()['n'] == 1


def test_runtime_cannot_directly_modify_or_enumerate_teams(api):
    _, state = api
    with psycopg.connect(os.environ['DATABASE_URL'], autocommit=True) as db:
        db.execute('SET ROLE smartpro_runtime')
        # Owner-run runtime_read_boundary.sql removes legacy blanket reads.
        # Only the tables needed by the synopsis domain remain queryable.
        assert db.execute('SELECT COUNT(*) FROM projects').fetchone()[0] > 0
        for statement in ["SELECT * FROM users",
                          "SELECT * FROM department_role_assignments",
                          "SELECT * FROM teams",
                          "SELECT * FROM team_memberships",
                          "SELECT * FROM idempotency_records",
                          "SELECT * FROM audit_events",
                          "SELECT * FROM student_profiles",
                          "SELECT * FROM student_offering_windows",
                          "INSERT INTO teams(department_id,cycle_id,name,curriculum_offering_id) VALUES(NULL,NULL,'No',NULL)",
                          "DELETE FROM teams"]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute(statement)
    rows = state['db'].execute("""
        SELECT proname,proconfig,NOT EXISTS (
          SELECT FROM aclexplode(coalesce(proacl,acldefault('f',proowner))) acl
          WHERE acl.grantee=0 AND acl.privilege_type='EXECUTE') AS public_denied
        FROM pg_proc
        WHERE proname IN ('smartpro_create_student_team','smartpro_student_eligible_teams')
    """).fetchall()
    assert len(rows) == 2
    assert all(row['public_denied'] and
               'search_path=pg_catalog, public, pg_temp' in row['proconfig'] for row in rows)


def test_database_failure_is_sanitized(api):
    client, state = api
    with patch('smartpro.teams.connection.cursor', side_effect=OperationalError('sensitive DB message')):
        response = create(client, state['idt_offering'])
    assert response.status_code == 503
    assert 'sensitive' not in response.content.decode()


def test_academic_evidence_is_unchanged_after_creation(api):
    client, state = api
    db = state['db']
    tables = ['submission_items','review_roster_members','approval_decisions',
              'result_releases','result_student_scores']
    def snapshot():
        return [db.execute(f'SELECT to_jsonb(x) AS data FROM {t} x ORDER BY to_jsonb(x)::text').fetchall()
                for t in tables]
    before = snapshot()
    publish(db, state['idt_offering'])
    assert create(client, state['idt_offering']).status_code == 201
    assert snapshot() == before


def test_012_install_requires_prior_011(prepared):  # noqa: F811
    with pytest.raises(psycopg.errors.RaiseException, match='Activate curriculum 010 and student reads 011'):
        execute_file(prepared['db'], ROOT / 'proposals/curriculum/012_team_creation.sql')
    prepared['db'].execute('ROLLBACK')
    assert prepared['db'].execute("SELECT to_regprocedure('public.smartpro_create_student_team(uuid,uuid,text,text,text)') AS func").fetchone()['func'] is None


@pytest.mark.parametrize('path,method', [(CREATE, 'get'), (LIST.format('13000000-0000-4000-8000-000000000001'), 'post')])
def test_mutating_wrong_http_methods(api, path, method):
    client, _ = api
    assert getattr(client, method)(path).status_code == 405
