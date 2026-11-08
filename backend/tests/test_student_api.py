"""HTTP and restricted-role PostgreSQL tests on the activated synthetic upgrade."""
import os
from pathlib import Path
import sys
from uuid import uuid4

import django
import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartpro.settings')
os.environ.setdefault('DJANGO_SECRET_KEY', 'synthetic-student-api-tests-only')
django.setup()

from django.db import connection, OperationalError
from rest_framework.test import APIClient
from unittest.mock import patch
from db_setup import execute_file
from proposals.curriculum.test_contracts import (  # noqa: F401
    A, DEPT, CYCLE, prepared, active, offering,
)

PROFILE = '/api/v1/me/profile'
OFFERINGS = '/api/v1/me/curriculum-offerings'


@pytest.fixture
def api(active, monkeypatch):  # noqa: F811 - imported pytest fixture
    connection.close()
    execute_file(active['db'], ROOT / 'proposals/curriculum/011_student_reads.sql')
    monkeypatch.setenv('SMARTPRO_ENV', 'demo')
    monkeypatch.setenv('SMARTPRO_DEMO_AUTH', 'YES')
    monkeypatch.setenv('SMARTPRO_CURRICULUM_API', 'YES')
    client = APIClient()
    client.credentials(HTTP_X_DEMO_USER='student-a')
    yield client, active
    connection.close()


def publish(db, oid, start="now()-interval '1 day'", end="now()+interval '1 day'"):
    # Expressions are fixed test constants, never HTTP inputs.
    db.execute(f'INSERT INTO student_offering_windows VALUES(%s,{start},{end})', (oid,))


def test_profile_from_authenticated_principal(api):
    client, _ = api
    response = client.get(PROFILE, {'userId': str(uuid4()), 'usn': 'OTHER'})
    assert response.status_code == 200
    assert response.json() == {
        'id': A, 'name': 'Demo Student A', 'usn': 'SYNTHETIC-USN-A',
        'section': 'A', 'semester': 'SYNTHETIC-SEM-3',
        'department': {'id': DEPT, 'code': 'DEMO-CSE', 'name': 'Demo CSE'},
    }
    assert response['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('path', [PROFILE, OFFERINGS])
@pytest.mark.parametrize('mode', ['disabled', 'missing-profile', 'expired-role',
                                 'future-role', 'wrong-department-role', 'no-role'])
def test_student_eligibility_denials(api, path, mode):
    client, state = api
    db = state['db']
    if mode == 'disabled':
        db.execute("UPDATE users SET account_status='DISABLED' WHERE id=%s", (A,))
    elif mode == 'missing-profile':
        # Existing membership protects Student A's profile; use an authenticated
        # faculty principal which has no student profile instead.
        client.credentials(HTTP_X_DEMO_USER='faculty-a')
    elif mode == 'expired-role':
        db.execute("UPDATE department_role_assignments SET valid_from=now()-interval '2 days',valid_until=now()-interval '1 day' WHERE user_id=%s", (A,))
    elif mode == 'future-role':
        db.execute("UPDATE department_role_assignments SET valid_from=now()+interval '1 day' WHERE user_id=%s", (A,))
    elif mode == 'wrong-department-role':
        dept = db.execute("INSERT INTO departments(code,name) VALUES('OTHER','Other') RETURNING id").fetchone()['id']
        db.execute('UPDATE department_role_assignments SET department_id=%s WHERE user_id=%s', (dept, A))
    else:
        db.execute('DELETE FROM department_role_assignments WHERE user_id=%s', (A,))
    assert client.get(path).status_code == 403


@pytest.mark.parametrize('path', [PROFILE, OFFERINGS])
def test_authentication_and_rollout_gates(api, monkeypatch, path):
    client, _ = api
    client.credentials()
    assert client.get(path).status_code == 401
    client.credentials(HTTP_X_DEMO_USER='student-a')
    monkeypatch.setenv('SMARTPRO_ENV', 'production')
    assert client.get(path).status_code == 401
    monkeypatch.setenv('SMARTPRO_ENV', 'demo')
    monkeypatch.delenv('SMARTPRO_DEMO_AUTH')
    assert client.get(path).status_code == 401
    monkeypatch.setenv('SMARTPRO_DEMO_AUTH', 'YES')
    monkeypatch.delenv('SMARTPRO_CURRICULUM_API')
    assert client.get(path).status_code == 503


def test_empty_default_and_scope_filters(api):
    client, state = api
    db = state['db']
    assert client.get(OFFERINGS).json() == {'results': [], 'nextCursor': None}
    publish(db, state['societal'])
    # Same department, wrong semester; published but not visible to Student A.
    publish(db, offering(db, state['sp'], semester='OTHER-SEM'))
    dept = db.execute("INSERT INTO departments(code,name) VALUES('OTHER','Other') RETURNING id").fetchone()['id']
    cycle = db.execute("INSERT INTO academic_cycles(department_id,code,starts_on,ends_on) VALUES(%s,'OTHER','2026-01-01','2027-01-01') RETURNING id", (dept,)).fetchone()['id']
    other = offering(db, state['sp'], department=dept, cycle=cycle)
    publish(db, other)
    # Client-supplied actor/scope/cycle never broadens the server-derived scope.
    response = client.get(OFFERINGS, {'departmentId': str(dept), 'semester': 'OTHER-SEM',
                                    'cycleId': str(cycle), 'userId': str(uuid4())})
    assert response.status_code == 200
    assert [r['id'] for r in response.json()['results']] == [str(state['societal'])]
    item = response.json()['results'][0]
    assert item['cycle']['id'] == CYCLE
    assert item['studentTeamCreationEnabled'] is False
    assert 'usn' not in item


@pytest.mark.parametrize('start,end', [
    ("now()+interval '1 day'", "now()+interval '2 days'"),
    ("now()-interval '2 days'", "now()-interval '1 day'"),
])
def test_unavailable_windows(api, start, end):
    client, state = api
    publish(state['db'], state['societal'], start, end)
    assert client.get(OFFERINGS).json()['results'] == []


def test_future_cycle_requires_explicit_window(api):
    client, state = api
    db = state['db']
    cycle = db.execute("INSERT INTO academic_cycles(department_id,code,starts_on,ends_on) VALUES(%s,'FUTURE','2040-01-01','2041-01-01') RETURNING id", (DEPT,)).fetchone()['id']
    oid = offering(db, state['sp'], cycle=cycle)
    assert client.get(OFFERINGS, {'cycleId': str(cycle)}).json()['results'] == []
    publish(db, oid)
    assert [r['id'] for r in client.get(OFFERINGS).json()['results']] == [str(oid)]


def test_bounded_cursor_pagination(api):
    client, state = api
    db = state['db']
    ids = []
    for i in range(51):
        category = db.execute('INSERT INTO curriculum_types(code,label) VALUES(%s,%s) RETURNING id',
                              (f'PAGE-{i}', f'Category {i}')).fetchone()['id']
        oid = offering(db, category)
        ids.append(str(oid))
        publish(db, oid)
    first = client.get(OFFERINGS).json()
    assert len(first['results']) == 50
    assert first['nextCursor'] == first['results'][-1]['id']
    second = client.get(OFFERINGS, {'cursor': first['nextCursor']}).json()
    assert len(second['results']) == 1 and second['nextCursor'] is None
    assert [r['id'] for r in first['results'] + second['results']] == sorted(ids)
    assert client.get(OFFERINGS, {'cursor': 'invalid'}).status_code == 400


def test_runtime_privileges_and_no_public_execution(api):
    _, state = api
    with connection.cursor() as cursor:
        cursor.execute('SELECT current_user,session_user')
        assert cursor.fetchone() == ('smartpro_runtime', 'smartpro_api')
    with psycopg.connect(os.environ['DATABASE_URL'], autocommit=True) as db:
        db.execute('SET ROLE smartpro_runtime')
        for statement in ['SELECT * FROM student_profiles',
                          'SELECT * FROM curriculum_offerings',
                          'SELECT * FROM student_offering_windows',
                          'DELETE FROM student_offering_windows',
                          "INSERT INTO teams(department_id,cycle_id,name) VALUES(NULL,NULL,'denied')"]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute(statement)
    # PUBLIC has no execute grant, and fixed search paths exclude temp shadowing.
    rows = state['db'].execute("""
        SELECT proconfig, NOT EXISTS (
          SELECT FROM aclexplode(coalesce(proacl,acldefault('f',proowner))) a
          WHERE a.grantee=0 AND a.privilege_type='EXECUTE') AS public_denied
        FROM pg_proc WHERE proname IN ('smartpro_student_profile','smartpro_student_offerings')
    """).fetchall()
    assert len(rows) == 2
    for row in rows:
        assert 'search_path=pg_catalog, public, pg_temp' in row['proconfig']
        assert row['public_denied']


def test_database_failure_is_sanitized(api):
    client, _ = api
    with patch('smartpro.students.connection.cursor', side_effect=OperationalError('sensitive backend error')):
        response = client.get(PROFILE)
    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'DATABASE_UNAVAILABLE'
    assert 'sensitive' not in response.content.decode()


def test_reads_do_not_change_academic_evidence(api):
    client, state = api
    db = state['db']
    tables = ['submission_items', 'review_roster_members', 'result_releases', 'result_student_scores',
              'team_memberships', 'approval_decisions', 'audit_events']
    def snapshot():
        return [db.execute(f'SELECT to_jsonb(t) AS data FROM {table} t ORDER BY to_jsonb(t)::text').fetchall()
                for table in tables]
    before = snapshot()
    assert client.get(PROFILE).status_code == 200
    assert client.get(OFFERINGS).status_code == 200
    assert snapshot() == before


@pytest.mark.parametrize('path', [PROFILE, OFFERINGS])
def test_read_only_routes(api, path):
    client, _ = api
    assert client.post(path, {'userId': A}, format='json').status_code == 405


def test_read_installation_rejects_prepare_only_schema(prepared):  # noqa: F811
    db = prepared['db']
    with pytest.raises(psycopg.errors.RaiseException, match='Activate curriculum 010'):
        execute_file(db, ROOT / 'proposals/curriculum/011_student_reads.sql')
    db.execute('ROLLBACK')
    assert db.execute("SELECT to_regclass('public.student_offering_windows') AS table_id").fetchone()['table_id'] is None


def test_window_boundary_is_half_open(api):
    _, state = api
    db = state['db']
    with db.transaction():
        publish(db, state['societal'], start='now()')
        publish(db, state['idt_offering'], end='now()')
        db.execute('SET LOCAL ROLE smartpro_runtime')
        data = db.execute('SELECT smartpro_student_offerings(%s) AS page', (A,)).fetchone()['page']
        assert [r['id'] for r in data['results']] == [str(state['societal'])]
