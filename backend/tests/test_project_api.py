"""Project registration against real PostgreSQL, HTTP and restricted credentials."""
import hashlib
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_membership_api import (  # noqa: F401 - initializes Django and fixtures
    membership_api, api, active, prepared, command, SOURCE, A, B, DEPT, CYCLE,
    team, offering, ROOT, execute_file,
)
from django.db import close_old_connections, connection
from rest_framework.test import APIClient

TEAM = '13000000-0000-4000-8000-000000000001'
LEGACY = '15000000-0000-4000-8000-000000000001'
REGISTER = '/api/v1/projects'
LIST = '/api/v1/me/projects'


def academic_policy(db, project_type='MAJOR', status='APPROVED', rule=None):
    version = db.execute('SELECT coalesce(max(version_no),0)+1 AS n FROM project_policy_versions WHERE department_id=%s AND project_type=%s',
                         (DEPT, project_type)).fetchone()['n']
    return db.execute('''INSERT INTO project_policy_versions(department_id,project_type,version_no,policy_status,policy_data)
      VALUES(%s,%s,%s,%s,%s) RETURNING id''',
      (DEPT, project_type, version, status, Jsonb({'studentRegistration': {'enabled': True} if rule is None else rule}))).fetchone()['id']


def configure(db, oid, project_type='MAJOR', *, policy=None, cycle=CYCLE,
              opens="clock_timestamp()-interval '1 day'", closes="clock_timestamp()+interval '1 day'"):
    policy = policy or academic_policy(db, project_type)
    version = db.execute('SELECT coalesce(max(version_no),0)+1 AS n FROM project_registration_policy_versions WHERE offering_id=%s AND project_type=%s',
                         (oid, project_type)).fetchone()['n']
    wid = db.execute(f'''INSERT INTO project_registration_policy_versions
      (offering_id,cycle_id,department_id,project_type,policy_version_id,version_no,opens_at,closes_at)
      VALUES(%s,%s,%s,%s,%s,%s,{opens},{closes}) RETURNING id''',
      (oid, cycle, DEPT, project_type, policy, version)).fetchone()['id']
    db.execute('''INSERT INTO offering_project_registration_policies VALUES(%s,%s,%s)
      ON CONFLICT(offering_id,project_type) DO UPDATE
      SET registration_policy_version_id=excluded.registration_policy_version_id''', (oid, project_type, wid))
    return policy, wid


@pytest.fixture
def project_api(membership_api, monkeypatch):  # noqa: F811
    client, state = membership_api
    execute_file(state['db'], ROOT / 'proposals/curriculum/014_project_registration.sql')
    # Registration regressions exercise the current cumulative upgrade too.
    execute_file(state['db'], ROOT / 'proposals/curriculum/015_staff_administration.sql')
    execute_file(state['db'], ROOT / 'proposals/curriculum/016_academic_governance.sql')
    execute_file(state['db'], ROOT / 'proposals/curriculum/017_academic_result_versions.sql')
    state['policy'], state['registration_policy'] = configure(state['db'], state['societal'])
    monkeypatch.setenv('SMARTPRO_PROJECT_API', 'YES')
    return client, state


def register(client, *, code='TEST-PROJECT', title='Useful project', tid=TEAM,
             project_type='MAJOR', key='project-test'):
    return client.post(REGISTER, {'teamId': str(tid), 'projectType': project_type,
                                 'projectCode': code, 'title': title},
                       format='json', HTTP_IDEMPOTENCY_KEY=key)


def test_registration_uses_existing_projects_and_audited_private_receipt(project_api):
    client, state = project_api
    response = register(client)
    assert response.status_code == 201, response.content
    body = response.json()
    assert body['teamId'] == TEAM and body['projectType'] == 'MAJOR'
    assert body['offeringId'] == str(state['societal']) and body['cycleId'] == CYCLE
    assert body['policyVersionId'] == str(state['policy'])
    assert body['registrationPolicyVersionId'] == str(state['registration_policy'])
    assert response['Cache-Control'] == 'no-store'
    db = state['db']
    receipt = db.execute('SELECT * FROM student_project_registrations WHERE project_id=%s', (body['id'],)).fetchone()
    assert str(receipt['actor_id']) == A and str(receipt['membership_id']) == SOURCE
    assert receipt['response_body'] == body
    audit = db.execute("SELECT metadata,actor_id FROM audit_events WHERE action='PROJECT_REGISTERED'").fetchone()
    assert str(audit['actor_id']) == A and audit['metadata']['membershipId'] == SOURCE
    assert db.execute('SELECT project_code FROM projects WHERE id=%s', (body['id'],)).fetchone()['project_code'] == 'TEST-PROJECT'


def test_classification_and_multiple_projects_are_independent_of_curriculum(project_api):
    client, state = project_api
    configure(state['db'], state['societal'], 'MINI')
    a = register(client, title='Same title')
    b = register(client, code='SECOND', title='Same title', key='second')
    c = register(client, code='MINI-CODE', project_type='MINI', key='mini')
    assert [r.status_code for r in [a, b, c]] == [201, 201, 201]
    assert c.json()['offeringId'] == a.json()['offeringId']
    assert c.json()['projectType'] == 'MINI'


def test_replay_normalizes_input_and_conflicts_do_not_leave_receipts(project_api):
    client, state = project_api
    first = register(client, code='  NORMALIZED  ', title='  Title  ')
    retry = register(client, code='NORMALIZED', title='Title')
    assert first.status_code == 201 and retry.status_code == 200 and retry.json() == first.json()
    assert register(client, code='DIFFERENT', title='Title').status_code == 409
    assert register(client, code='NORMALIZED', title='Title', key='different-key').status_code == 409
    assert state['db'].execute('SELECT count(*) AS n FROM student_project_registrations').fetchone()['n'] == 1
    assert state['db'].execute("SELECT count(*) AS n FROM audit_events WHERE action='PROJECT_REGISTERED'").fetchone()['n'] == 1


@pytest.mark.parametrize('mode', ['disabled', 'expired-role', 'future-role', 'wrong-role-department', 'faculty'])
def test_identity_and_effective_role_are_required_for_reads_and_writes(project_api, mode):
    client, state = project_api
    db = state['db']
    if mode == 'disabled':
        db.execute("UPDATE users SET account_status='DISABLED' WHERE id=%s", (A,))
    elif mode == 'expired-role':
        db.execute("UPDATE department_role_assignments SET valid_from=now()-interval '2 days',valid_until=now()-interval '1 day' WHERE user_id=%s", (A,))
    elif mode == 'future-role':
        db.execute("UPDATE department_role_assignments SET valid_from=now()+interval '1 day' WHERE user_id=%s", (A,))
    elif mode == 'wrong-role-department':
        dept = db.execute("INSERT INTO departments(code,name) VALUES('ROLE-X','Other') RETURNING id").fetchone()['id']
        db.execute('UPDATE department_role_assignments SET department_id=%s WHERE user_id=%s', (dept, A))
    else:
        client.credentials(HTTP_X_DEMO_USER='faculty-a')
    assert register(client).status_code == 403
    assert client.get(LIST).status_code == 403


@pytest.mark.parametrize('mode', ['ended', 'future', 'other-team', 'missing-team'])
def test_only_current_valid_membership_authorizes_registration(project_api, mode):
    client, state = project_api
    db = state['db']
    tid = TEAM
    if mode in ('ended', 'future'):
        assert command(client, 'LEAVE', SOURCE).status_code == 200
        if mode == 'future':
            db.execute("INSERT INTO team_memberships(team_id,user_id,curriculum_offering_id,joined_at) VALUES(%s,%s,%s,clock_timestamp()+interval '1 day')", (TEAM, A, state['societal']))
    else:
        tid = team(db, state['societal']) if mode == 'other-team' else uuid4()
    assert register(client, tid=tid).status_code == 403


@pytest.mark.parametrize('scope', ['department', 'semester', 'offering', 'cycle'])
def test_explicit_offering_and_cycle_scope_cannot_be_bypassed(project_api, scope):
    client, state = project_api
    db = state['db']
    if scope == 'department':
        dept = db.execute("INSERT INTO departments(code,name) VALUES('PROJECT-X','Other') RETURNING id").fetchone()['id']
        cycle = db.execute("INSERT INTO academic_cycles(department_id,code,starts_on,ends_on) VALUES(%s,'OTHER','2026-01-01','2027-01-01') RETURNING id", (dept,)).fetchone()['id']
        oid = offering(db, state['sp'], department=dept, cycle=cycle)
        tid = team(db, oid, department=dept, cycle=cycle)
    elif scope == 'semester':
        oid = offering(db, state['sp'], semester='OTHER-SEM')
        tid = team(db, oid)
    elif scope == 'offering':
        oid = state['idt_offering']
        tid = team(db, oid)
        assert command(client, 'JOIN', tid).status_code == 201
    else:
        cycle = db.execute("INSERT INTO academic_cycles(department_id,code,starts_on,ends_on) VALUES(%s,'PROJECT-NEXT','2040-01-01','2041-01-01') RETURNING id", (DEPT,)).fetchone()['id']
        oid = offering(db, state['sp'], cycle=cycle)
        tid = team(db, oid, cycle=cycle)
        db.execute('INSERT INTO team_memberships(team_id,user_id,curriculum_offering_id) VALUES(%s,%s,%s)', (tid, A, oid))
        configure(db, oid, cycle=cycle, opens="clock_timestamp()+interval '1 day'", closes="clock_timestamp()+interval '2 days'")
    assert register(client, tid=tid).status_code == 403
    if scope in ('offering', 'cycle'):
        # Existing offering's approved binding cannot be attached to another scope.
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            db.execute('INSERT INTO offering_project_registration_policies VALUES(%s,%s,%s) ON CONFLICT(offering_id,project_type) DO UPDATE SET registration_policy_version_id=excluded.registration_policy_version_id',
                       (oid, 'MAJOR', state['registration_policy']))


@pytest.mark.parametrize('mode', ['missing', 'closed', 'future', 'retired'])
def test_missing_or_inapplicable_registration_policy_fails_closed(project_api, mode):
    client, state = project_api
    db = state['db']
    if mode == 'missing':
        db.execute('DELETE FROM offering_project_registration_policies')
    elif mode == 'closed':
        configure(db, state['societal'], opens="clock_timestamp()-interval '2 days'", closes="clock_timestamp()-interval '1 day'")
    elif mode == 'future':
        configure(db, state['societal'], opens="clock_timestamp()+interval '1 day'", closes="clock_timestamp()+interval '2 days'")
    else:
        db.execute("UPDATE project_policy_versions SET policy_status='RETIRED' WHERE id=%s", (state['policy'],))
    assert register(client).status_code == 403
    assert db.execute('SELECT count(*) AS n FROM student_project_registrations').fetchone()['n'] == 0


@pytest.mark.parametrize('status,rule', [('DRAFT', {'enabled': True}), ('APPROVED', {'enabled': False}),
                                       ('APPROVED', {'enabled': True, 'maxProjects': 1})])
def test_unapproved_or_unsupported_rules_cannot_be_published(project_api, status, rule):
    _, state = project_api
    db = state['db']
    policy = academic_policy(db, status=status, rule=rule)
    with pytest.raises(psycopg.errors.CheckViolation):
        configure(db, state['societal'], policy=policy)


def test_committed_retry_and_read_survive_policy_retirement_but_not_membership_loss(project_api):
    client, state = project_api
    first = register(client)
    assert first.status_code == 201
    state['db'].execute('DELETE FROM offering_project_registration_policies')
    state['db'].execute("UPDATE project_policy_versions SET policy_status='RETIRED' WHERE id=%s", (state['policy'],))
    assert register(client).status_code == 200
    assert first.json()['id'] in [r['id'] for r in client.get(LIST).json()['results']]
    assert command(client, 'LEAVE', SOURCE).status_code == 200
    assert register(client).status_code == 403
    assert client.get(LIST).json()['results'] == []


def test_project_reads_are_scoped_private_and_paginated(project_api):
    client, state = project_api
    other = team(state['db'], state['societal'])
    state['db'].execute('''INSERT INTO projects(department_id,cycle_id,team_id,project_type,policy_version_id,project_code,title)
      VALUES(%s,%s,%s,'MAJOR',%s,'PRIVATE','Other team project')''', (DEPT,CYCLE,other,state['policy']))
    ids = {LEGACY}
    for i in range(50):
        response = register(client, code=f'PAGE-{i}', key=f'page-{i}')
        assert response.status_code == 201, response.content
        ids.add(response.json()['id'])
    first = client.get(LIST, {'userId': B, 'teamId': str(other), 'limit': 1000})
    assert first.status_code == 200 and first['Cache-Control'] == 'no-store'
    page = first.json()
    assert len(page['results']) == 50
    second = client.get(LIST, {'cursor': page['nextCursor']}).json()
    assert len(second['results']) == 1 and second['nextCursor'] is None
    rows = page['results']+second['results']
    assert [r['id'] for r in rows] == sorted(ids)
    assert next(r for r in rows if r['id'] == LEGACY)['registrationPolicyVersionId'] is None
    assert 'usn' not in str(rows) and 'membershipId' not in str(rows)
    assert client.get(LIST, {'cursor': 'invalid'}).status_code == 400
    # A current teammate sees team projects without gaining another team's scope.
    client.credentials(HTTP_X_DEMO_USER='student-b')
    assert len(client.get(LIST).json()['results']) == 50


def test_registration_does_not_rewrite_academic_evidence_and_pins_membership_history(project_api):
    client, state = project_api
    db = state['db']
    tables = ['review_roster_members','submission_items','submission_attempts','approval_decisions',
              'result_releases','result_student_scores','team_memberships']
    def snapshot():
        return [db.execute(f'SELECT to_jsonb(t) AS data FROM {t} t ORDER BY to_jsonb(t)::text').fetchall() for t in tables]
    before = snapshot()
    result = register(client)
    assert result.status_code == 201
    assert snapshot() == before
    receipt = db.execute('SELECT * FROM student_project_registrations').fetchone()
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute('UPDATE team_memberships SET left_at=%s WHERE id=%s', (receipt['registered_at'], SOURCE))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute('DELETE FROM student_project_registrations')
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute('UPDATE project_registration_policy_versions SET closes_at=closes_at+interval \'1 day\'')
    other = team(db, state['societal'])
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute('UPDATE projects SET team_id=%s WHERE id=%s', (other, result.json()['id']))


def worker(actor, **values):
    close_old_connections()
    try:
        client = APIClient()
        client.credentials(HTTP_X_DEMO_USER=actor)
        result = register(client, **values)
        return result.status_code, result.json()
    finally:
        connection.close()


@pytest.mark.parametrize('mode', ['same-key', 'changed-key-input', 'same-code', 'different-projects'])
def test_concurrent_registrations_are_idempotent_without_inventing_team_limits(project_api, mode):
    barrier = threading.Barrier(2)
    requests = [('student-a', {}), ('student-a', {})]
    if mode == 'changed-key-input':
        requests[1] = ('student-a', {'title': 'Different title'})
    elif mode == 'same-code':
        requests[1] = ('student-b', {})
    elif mode == 'different-projects':
        requests[1] = ('student-b', {'code': 'ANOTHER-CODE'})
    def run(request):
        barrier.wait(timeout=5)
        return worker(request[0], **request[1])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, requests))
    expected = [200, 201] if mode == 'same-key' else [201, 201] if mode == 'different-projects' else [201, 409]
    assert sorted(r[0] for r in results) == expected, results
    if mode == 'same-key':
        assert results[0][1] == results[1][1]


def test_sixteen_distinct_students_in_isolated_concurrent_registration_waves(project_api):
    """Distinct real actor UUIDs, real PostgreSQL 16, no live reviewer mutation.

    16 independent synthetic student identities, each with separate membership,
    race four waves of 16 operations (three writes and one identical retry).
    Tests capacity/integrity of the DB logic, NOT hosted campus load or login.
    """
    from math import ceil
    from proposals.curriculum.test_contracts import new_student
    from psycopg.rows import dict_row

    _, state = project_api
    db = state['db']
    actors = []
    for index in range(16):
        actor = new_student(db)
        db.execute("INSERT INTO department_role_assignments "
                   "(user_id,department_id,role_code) VALUES(%s,%s,'STUDENT')",
                   (actor, DEPT))
        owned_team = team(db, state['societal'])
        db.execute("INSERT INTO team_memberships "
                   "(team_id,user_id,curriculum_offering_id) VALUES(%s,%s,%s)",
                   (owned_team, actor, state['societal']))
        actors.append((str(actor), owned_team))
    assert len({actor for actor, _ in actors}) == 16
    before = db.execute("SELECT count(*) AS n FROM student_project_registrations").fetchone()['n']

    def wave(number):
        barrier = threading.Barrier(len(actors))
        def attempt(index):
            actor, owned_team = actors[index]
            code = f"ACTOR-{index}-WAVE-{number}"
            request_key = f"isolated-{index}-wave-{number}"
            digest = hashlib.sha256(f"{actor}:{code}:{request_key}".encode()).hexdigest()
            with psycopg.connect(os.environ['DATABASE_URL'], autocommit=True, row_factory=dict_row) as conn:
                conn.execute("SET statement_timeout='15s'")
                barrier.wait(timeout=20)
                start = time.monotonic()
                response = conn.execute(
                    'SELECT public.smartpro_register_student_project(%s,%s,%s,%s,%s,%s,%s) AS result',
                    (actor, owned_team, 'MAJOR', code,
                     f'Isolated distinct student {index} wave {number}', request_key, digest),
                ).fetchone()['result']
                return index, response, time.monotonic()-start
        with ThreadPoolExecutor(max_workers=len(actors)) as pool:
            return list(pool.map(attempt, range(len(actors))))

    first = wave(0)
    replay = wave(0)
    later = wave(1)
    last = wave(2)
    def ids(rows):
        return {i: result['project']['id'] for i, result, _ in rows}
    assert all(r['replayed'] is False for _,r,_ in first + later + last)
    assert all(r['replayed'] is True for _,r,_ in replay)
    assert ids(first) == ids(replay)
    project_ids = list(ids(first).values()) + list(ids(later).values()) + list(ids(last).values())
    assert len(project_ids) == len(set(project_ids)) == 48
    actor_ids = [actor for actor,_ in actors]
    receipts = db.execute(
        'SELECT count(*) AS n FROM student_project_registrations WHERE actor_id=ANY(%s)',
        (actor_ids,)).fetchone()['n']
    audit = db.execute(
        "SELECT count(*) AS n FROM audit_events WHERE actor_id=ANY(%s) AND action='PROJECT_REGISTERED'",
        (actor_ids,)).fetchone()['n']
    assert receipts == audit == 48
    assert db.execute('SELECT count(*) AS n FROM student_project_registrations').fetchone()['n'] == before+48
    for label,rows in [('initial',first),('replay',replay),('later',later),('last',last)]:
        durations=sorted(t for _,_,t in rows)
        p95=durations[ceil(len(durations)*.95)-1]
        print(f"DISTINCT_STUDENT_DB_WAVE kind={label} actors=16 requests=16 "
              f"p95_s={p95:.3f} result_integrity=PASS", flush=True)


def test_stale_repeatable_read_membership_snapshot_aborts_and_reauthorizes(project_api):
    client, state = project_api
    with psycopg.connect(os.environ['DATABASE_URL'], autocommit=True) as stale:
        stale.execute('SET ROLE smartpro_runtime')
        stale.execute('BEGIN ISOLATION LEVEL REPEATABLE READ')
        stale.execute('SELECT smartpro_student_profile(%s)', (A,))
        assert command(client, 'LEAVE', SOURCE).status_code == 200
        with pytest.raises(psycopg.errors.SerializationFailure):
            stale.execute('SELECT smartpro_register_student_project(%s,%s,%s,%s,%s,%s,%s)',
                          (A, TEAM, 'MAJOR', 'STALE', 'Stale snapshot', 'stale', hashlib.sha256(b'stale').hexdigest()))
        stale.execute('ROLLBACK')
    assert register(client).status_code == 403
    assert state['db'].execute('SELECT count(*) AS n FROM student_project_registrations').fetchone()['n'] == 0


@pytest.mark.parametrize('deferred', [False, True])
def test_registration_and_receipt_roll_back_on_audit_or_commit_failure(project_api, deferred):
    client, state = project_api
    db = state['db']
    db.execute("""CREATE FUNCTION fail_project_audit() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN IF NEW.action='PROJECT_REGISTERED' THEN RAISE EXCEPTION 'synthetic failure' USING ERRCODE='23514'; END IF; RETURN NEW; END $$""")
    timing = 'DEFERRABLE INITIALLY DEFERRED' if deferred else ''
    db.execute(f'CREATE CONSTRAINT TRIGGER fail_project_audit AFTER INSERT ON audit_events {timing} FOR EACH ROW EXECUTE FUNCTION fail_project_audit()')
    result = register(client)
    assert result.status_code == (503 if deferred else 409), result.content
    assert db.execute('SELECT count(*) AS n FROM projects').fetchone()['n'] == 1
    assert db.execute('SELECT count(*) AS n FROM student_project_registrations').fetchone()['n'] == 0
    db.execute('DROP TRIGGER fail_project_audit ON audit_events')
    assert register(client).status_code == 201


@pytest.mark.parametrize('failure', [psycopg.errors.SerializationFailure, psycopg.errors.DeadlockDetected])
def test_whole_transaction_retry_rolls_back_before_reauthorization(project_api, monkeypatch, failure):
    from django.db import OperationalError
    from smartpro import projects
    client, state = project_api
    execute = projects._execute
    calls = []
    def fail_once(*args):
        result = execute(*args)
        calls.append(result)
        if len(calls) == 1:
            raise OperationalError('retryable failure') from failure('synthetic retry')
        return result
    monkeypatch.setattr(projects, '_execute', fail_once)
    assert register(client).status_code == 201 and len(calls) == 2
    assert state['db'].execute('SELECT count(*) AS n FROM student_project_registrations').fetchone()['n'] == 1


def test_legacy_direct_idempotency_insert_cannot_forge_registration(project_api):
    client, state = project_api
    forged = str(uuid4())
    with psycopg.connect(os.environ['DATABASE_URL'], autocommit=True) as runtime:
        runtime.execute('SET ROLE smartpro_runtime')
        runtime.execute("INSERT INTO idempotency_records(actor_id,operation,key,request_sha256,state,response_status,response_body) VALUES(%s,'STUDENT_REGISTER_PROJECT','project-test',%s,'COMPLETE',201,%s)",
                        (A, hashlib.sha256(b'forged').hexdigest(), Jsonb({'id': forged})))
        for statement in ['SELECT * FROM student_project_registrations',
                          'INSERT INTO student_project_registrations(project_id) VALUES(NULL)',
                          'SELECT * FROM project_registration_policy_versions',
                          'DELETE FROM offering_project_registration_policies',
                          "INSERT INTO projects(title) VALUES('denied')"]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                runtime.execute(statement)
    result = register(client)
    assert result.status_code == 201 and result.json()['id'] != forged
    rows = state['db'].execute("""SELECT proconfig,NOT EXISTS(SELECT FROM aclexplode(coalesce(proacl,acldefault('f',proowner))) acl
      WHERE acl.grantee=0 AND acl.privilege_type='EXECUTE') AS public_denied
      FROM pg_proc WHERE proname IN ('smartpro_register_student_project','smartpro_student_projects')""").fetchall()
    assert len(rows) == 2 and all(r['public_denied'] and 'search_path=pg_catalog, public, pg_temp' in r['proconfig'] for r in rows)


def test_validation_authentication_and_independent_project_rollout_gate(project_api, monkeypatch):
    client, _ = project_api
    for changes in [{'userId': A}, {'policyVersionId': str(uuid4())}, {'title': ''},
                    {'title': 'x'*501}, {'projectCode': 'x'*121}, {'projectType': 'SOCIETAL'}]:
        body = {'teamId': TEAM, 'projectType': 'MAJOR', 'projectCode': 'CODE', 'title': 'Title', **changes}
        assert client.post(REGISTER, body, format='json', HTTP_IDEMPOTENCY_KEY='input').status_code == 400
    assert client.post(REGISTER, [], format='json', HTTP_IDEMPOTENCY_KEY='input').status_code == 400
    assert register(client, key='bad key').status_code == 400
    assert client.get(REGISTER).status_code == 405 and client.post(LIST, {}, format='json').status_code == 405
    client.credentials()
    assert register(client).status_code == 401
    client.credentials(HTTP_X_DEMO_USER='student-a')
    monkeypatch.setenv('SMARTPRO_ENV', 'production')
    assert register(client).status_code == 401
    monkeypatch.setenv('SMARTPRO_ENV', 'demo')
    monkeypatch.delenv('SMARTPRO_PROJECT_API')
    assert register(client).status_code == 503 and client.get(LIST).status_code == 503
    monkeypatch.setenv('SMARTPRO_PROJECT_API', 'YES')
    monkeypatch.delenv('SMARTPRO_TEAM_API')
    assert register(client).status_code == 201


def wait_blocked(db, pid, blocker):
    deadline = time.monotonic()+3
    while time.monotonic()<deadline:
        if blocker in db.execute('SELECT pg_blocking_pids(%s) AS blockers', (pid,)).fetchone()['blockers']:
            return
        time.sleep(0.01)
    raise AssertionError('expected database row-lock contention was not observed')


def pending_request(action, ready, pids):
    close_old_connections()
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_backend_pid()')
            pids.append(cursor.fetchone()[0])
        ready.set()
        client = APIClient()
        client.credentials(HTTP_X_DEMO_USER='student-a')
        response = register(client) if action == 'register' else command(client, 'LEAVE', SOURCE)
        return response.status_code, response.json()
    finally:
        connection.close()


@pytest.mark.parametrize('first', ['register', 'leave'])
def test_registration_serializes_with_membership_departure_in_both_orders(project_api, first):
    _, state = project_api
    ready, pids = threading.Event(), []
    with ThreadPoolExecutor(max_workers=1) as pool:
        with psycopg.connect(os.environ['DATABASE_URL']) as held:
            held.execute('SET ROLE smartpro_runtime')
            if first == 'register':
                held.execute('SELECT smartpro_register_student_project(%s,%s,%s,%s,%s,%s,%s)',
                             (A, TEAM, 'MAJOR', 'HELD', 'Held registration', 'held', 'a'*64))
            else:
                held.execute('SELECT smartpro_student_membership(%s,%s,%s,%s,%s,%s,%s)',
                             (A, 'LEAVE', SOURCE, None, '', 'held', 'a'*64))
            future = pool.submit(pending_request, 'leave' if first == 'register' else 'register', ready, pids)
            assert ready.wait(3)
            wait_blocked(state['db'], pids[0], held.info.backend_pid)
        status, _ = future.result(timeout=6)
    if first == 'leave':
        assert status == 403
        assert state['db'].execute('SELECT count(*) AS n FROM student_project_registrations').fetchone()['n'] == 0
    else:
        assert status == 200
        receipt = state['db'].execute('SELECT registered_at FROM student_project_registrations').fetchone()
        ended = state['db'].execute('SELECT left_at FROM team_memberships WHERE id=%s', (SOURCE,)).fetchone()
        assert receipt['registered_at'] < ended['left_at']


def test_registration_window_is_rechecked_after_lock_wait(project_api):
    _, state = project_api
    db = state['db']
    _, wid = configure(db, state['societal'], closes="clock_timestamp()+interval '2 seconds'")
    ready, pids = threading.Event(), []
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.transaction():
            db.execute('SELECT id FROM teams WHERE id=%s FOR UPDATE', (TEAM,))
            future = pool.submit(pending_request, 'register', ready, pids)
            assert ready.wait(3)
            wait_blocked(db, pids[0], db.info.backend_pid)
            remaining = db.execute('SELECT extract(epoch FROM closes_at-clock_timestamp()) AS seconds FROM project_registration_policy_versions WHERE id=%s', (wid,)).fetchone()['seconds']
            assert remaining > 0, 'test must observe waiting before the window closes'
            time.sleep(float(remaining)+0.05)
        assert future.result(timeout=6)[0] == 403
    assert db.execute('SELECT count(*) AS n FROM student_project_registrations').fetchone()['n'] == 0


def test_project_registration_window_is_separate_from_team_formation(project_api):
    client, state = project_api
    db = state['db']
    db.execute('DELETE FROM student_offering_windows')
    db.execute('UPDATE curriculum_offerings SET student_team_creation_enabled=false')
    assert register(client).status_code == 201


def test_new_policy_binding_never_relabels_registered_projects(project_api):
    client, state = project_api
    first = register(client)
    assert first.status_code == 201
    new_policy, new_window = configure(state['db'], state['societal'])
    second = register(client, code='NEW-POLICY', key='new-policy')
    assert second.status_code == 201
    assert second.json()['policyVersionId'] == str(new_policy)
    assert second.json()['registrationPolicyVersionId'] == str(new_window)
    assert register(client).json() == first.json()
    assert state['db'].execute("SELECT count(*) AS n FROM audit_events WHERE action='PROJECT_REGISTRATION_POLICY_BOUND'").fetchone()['n'] == 2


def test_same_actor_stale_retry_aborts_before_duplicate_registration(project_api):
    client, _ = project_api
    with psycopg.connect(os.environ['DATABASE_URL'], autocommit=True) as stale:
        stale.execute('SET ROLE smartpro_runtime')
        stale.execute('BEGIN ISOLATION LEVEL REPEATABLE READ')
        stale.execute('SELECT smartpro_student_profile(%s)', (A,))
        first = register(client)
        assert first.status_code == 201
        with pytest.raises(psycopg.errors.SerializationFailure):
            stale.execute('SELECT smartpro_register_student_project(%s,%s,%s,%s,%s,%s,%s)',
                          (A, TEAM, 'MAJOR', 'TEST-PROJECT', 'Useful project', 'project-test', 'b'*64))
        stale.execute('ROLLBACK')
    retry = register(client)
    assert retry.status_code == 200 and retry.json() == first.json()


def test_retry_exhaustion_is_bounded_and_leaves_no_registration(project_api, monkeypatch):
    from django.db import OperationalError
    from smartpro import projects
    client, state = project_api
    calls = []
    def fail(*args):
        calls.append(1)
        raise OperationalError('retry transaction') from psycopg.errors.SerializationFailure('synthetic')
    monkeypatch.setattr(projects, '_execute', fail)
    assert register(client).status_code == 409 and len(calls) == 3
    assert state['db'].execute('SELECT count(*) AS n FROM student_project_registrations').fetchone()['n'] == 0


def test_candidate_requires_membership_upgrade(api):  # noqa: F811
    _, state = api
    with pytest.raises(psycopg.errors.RaiseException, match='Install activated curriculum 010-013'):
        execute_file(state['db'], ROOT / 'proposals/curriculum/014_project_registration.sql')
    state['db'].execute('ROLLBACK')
    assert state['db'].execute("SELECT to_regclass('public.student_project_registrations') AS receipt").fetchone()['receipt'] is None


def test_existing_team_and_membership_flow_integrates_with_registered_projects(project_api):
    client, state = project_api
    original = register(client)
    assert original.status_code == 201
    target = team(state['db'], state['societal'])
    assert command(client, 'TRANSFER', SOURCE, target=target).status_code == 201
    assert client.get(LIST).json()['results'] == []
    transferred = register(client, tid=target, code='TRANSFERRED', key='transferred')
    assert transferred.status_code == 201
    created = client.post('/api/v1/teams', {'offeringId': str(state['idt_offering']), 'name': 'Integrated team'},
                          format='json', HTTP_IDEMPOTENCY_KEY='integrated-team')
    assert created.status_code == 201, created.content
    configure(state['db'], state['idt_offering'], 'MINI')
    second = register(client, tid=created.json()['id'], project_type='MINI', code='IDT-MINI', key='idt-mini')
    assert second.status_code == 201
    assert {r['id'] for r in client.get(LIST).json()['results']} == {second.json()['id'], transferred.json()['id']}
    assert command(client, 'LEAVE', created.json()['membershipId'], key='leave-integrated').status_code == 200
    assert {r['id'] for r in client.get(LIST).json()['results']} == {transferred.json()['id']}
    client.credentials(HTTP_X_DEMO_USER='student-b')
    visible = {r['id'] for r in client.get(LIST).json()['results']}
    assert original.json()['id'] in visible and transferred.json()['id'] not in visible


def test_replay_authorization_is_bound_to_original_team_independently_of_digest(project_api):
    client, state = project_api
    assert register(client).status_code == 201
    receipt = state['db'].execute('SELECT request_sha256 FROM student_project_registrations').fetchone()
    target = team(state['db'], state['societal'])
    assert command(client, 'TRANSFER', SOURCE, target=target).status_code == 201
    # Capability callers must not be able to authorize a receipt through another
    # team merely by passing a previously stored digest. HTTP computes its own
    # digest, but the SQL authorization boundary must independently pin the team.
    with psycopg.connect(os.environ['DATABASE_URL'], autocommit=True) as runtime:
        runtime.execute('SET ROLE smartpro_runtime')
        with pytest.raises(psycopg.errors.UniqueViolation):
            runtime.execute('SELECT smartpro_register_student_project(%s,%s,%s,%s,%s,%s,%s)',
                            (A, target, 'MAJOR', 'TEST-PROJECT', 'Useful project', 'project-test', receipt['request_sha256']))
