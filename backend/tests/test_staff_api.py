"""Real staff HTTP, restricted SQL, delegation, versioning and transaction tests."""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_project_api import (  # noqa: F401 - initializes Django/fixtures
    project_api, membership_api, api, active, prepared, register, command,
    TEAM, LEGACY, SOURCE, A, B, DEPT, CYCLE, ROOT, execute_file, academic_policy, team, offering,
)
from django.db import close_old_connections, connection
from rest_framework.test import APIClient

HOD = '00000000-0000-4000-8000-000000000004'
FACULTY = '00000000-0000-4000-8000-000000000003'
TECH = '00000000-0000-4000-8000-000000000007'
PERMISSIONS = ['READ_POLICIES','MANAGE_OFFERINGS','MANAGE_TEAM_POLICY',
               'MANAGE_REGISTRATION_POLICY','READ_PROJECTS','CORRECT_PROJECT']


def grant(db, uid, permission, role='HOD', project=None, department=DEPT):
    rid = db.execute('SELECT id FROM department_role_assignments WHERE user_id=%s AND department_id=%s AND role_code=%s',
                     (uid,department,role)).fetchone()['id']
    return db.execute('''INSERT INTO staff_permission_assignments(user_id,department_id,role_assignment_id,
      required_role,permission,project_id,valid_from,granted_by,grant_reason)
      VALUES(%s,%s,%s,%s,%s,%s,now()-interval '1 day',%s,'Synthetic reviewed grant') RETURNING id''',
      (uid,department,rid,role,permission,project,HOD)).fetchone()['id']


@pytest.fixture
def staff_api(project_api, monkeypatch):  # noqa: F811
    student, state = project_api
    new = register(student)
    assert new.status_code == 201, new.content
    state['managed_project'] = new.json()['id']
    state['student'] = student
    db = state['db']
    db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code,valid_from) VALUES(%s,%s,'HOD',now()-interval '1 day')", (HOD,DEPT))
    db.execute('INSERT INTO staff_department_controls(department_id,enabled,allow_title_corrections) VALUES(%s,true,true)', (DEPT,))
    state['grants'] = {p:grant(db,HOD,p) for p in PERMISSIONS}
    for p in ['READ_PROJECTS','CORRECT_PROJECT']:
        grant(db,FACULTY,p,role='FACULTY',project=state['managed_project'])
    db.execute("INSERT INTO users(id,display_name,email) VALUES(%s,'Synthetic Tech','tech@example.invalid')", (TECH,))
    db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'TECH_ADMIN')", (TECH,DEPT))
    monkeypatch.setenv('SMARTPRO_STAFF_API','YES')
    client = APIClient()
    client.credentials(HTTP_X_DEMO_USER='staff-policy')
    return client, state


def url(action, state, department=DEPT, target=None):
    base = f'/api/v1/staff/departments/{department}'
    if action == 'policies' or action == 'projects':
        return base+'/'+action
    if action == 'CORRECT_TITLE':
        return base+f'/projects/{target or state["managed_project"]}/title'
    suffix = {'PUBLICATION':'publication','TEAM_POLICY':'team-policy','REGISTRATION':'registration-policy'}[action]
    return base+f'/offerings/{target or state["societal"]}/{suffix}'


def payload(action, state, revision=0):
    now = datetime.now(timezone.utc)
    common = {'expectedRevision':revision,'reason':'Reviewed departmental change'}
    if action == 'PUBLICATION':
        return {**common,'visibleFrom':(now-timedelta(days=1)).isoformat(),
                'visibleUntil':(now+timedelta(days=1)).isoformat(),'teamCreationEnabled':True}
    if action == 'TEAM_POLICY':
        return {**common,'allowJoin':True,'allowLeave':True,'allowTransfer':True,
                'minimumMembers':None,'maximumMembers':5,'sizeMode':'ENFORCED'}
    if action == 'REGISTRATION':
        return {**common,'projectType':'MAJOR','policyVersionId':str(state['policy']),
                'opensAt':(now-timedelta(days=1)).isoformat(),'closesAt':(now+timedelta(days=1)).isoformat()}
    return {'expectedProjectVersion':1,'title':'Corrected project title','reason':'Verified initial metadata typo'}


def post(client,state,action,body=None,key='staff-test',**scope):
    return client.post(url(action,state,**scope), payload(action,state) if body is None else body,
                       format='json',HTTP_IDEMPOTENCY_KEY=key)


def test_current_policies_and_projects_require_explicit_department_authority(staff_api):
    client,state = staff_api
    policies = client.get(url('policies',state))
    assert policies.status_code == 200, policies.content
    assert policies.json()['revision'] == 0 and len(policies.json()['results']) == 2
    assert policies['Cache-Control'] == 'no-store'
    rows = client.get(url('projects',state))
    assert rows.status_code == 200
    projects = {r['id']:r for r in rows.json()['results']}
    assert projects[LEGACY]['hasAcademicEvidence'] is True
    assert projects[state['managed_project']]['hasAcademicEvidence'] is False


def test_publication_is_atomic_audited_and_replayable(staff_api):
    client,state = staff_api
    body = payload('PUBLICATION',state)
    first = post(client,state,'PUBLICATION',body)
    assert first.status_code == 200, first.content
    assert first.json()['revision'] == 1 and first.json()['state']['publication']['isVisible']
    assert post(client,state,'PUBLICATION',body).json() == first.json()
    assert post(client,state,'PUBLICATION',{**body,'teamCreationEnabled':False}).status_code == 409
    row = state['db'].execute("SELECT actor_id,metadata FROM audit_events WHERE action='STAFF_PUBLICATION'").fetchone()
    assert str(row['actor_id']) == HOD and row['metadata']['reason'] == body['reason']
    assert row['metadata']['authority']['role'] == 'HOD' and 'old' in row['metadata'] and 'new' in row['metadata']


def test_team_policy_versions_and_registration_bindings_preserve_history(staff_api):
    client,state = staff_api
    db = state['db']
    old = db.execute('SELECT policy_version_id FROM offering_membership_policies WHERE offering_id=%s',(state['societal'],)).fetchone()['policy_version_id']
    changed = post(client,state,'TEAM_POLICY')
    assert changed.status_code == 200, changed.content
    assert changed.json()['state']['teamPolicy']['id'] != str(old)
    assert db.execute('SELECT id FROM team_membership_policy_versions WHERE id=%s',(old,)).fetchone() is not None
    reg = post(client,state,'REGISTRATION',payload('REGISTRATION',state,revision=1),key='registration')
    assert reg.status_code == 200, reg.content
    assert reg.json()['revision'] == 2
    prior = db.execute('SELECT registration_policy_version_id FROM student_project_registrations').fetchone()['registration_policy_version_id']
    assert prior == state['registration_policy']
    assert reg.json()['state']['registrationPolicies'][0]['id'] != str(prior)


def test_delegated_faculty_can_only_correct_scoped_initial_project_title(staff_api):
    client,state = staff_api
    client.credentials(HTTP_X_DEMO_USER='faculty-a')
    listed = client.get(url('projects',state))
    assert listed.status_code == 200 and [r['id'] for r in listed.json()['results']] == [state['managed_project']]
    corrected = post(client,state,'CORRECT_TITLE')
    assert corrected.status_code == 200, corrected.content
    assert corrected.json()['state']['rowVersion'] == 2
    receipt = state['db'].execute('SELECT response_body FROM student_project_registrations').fetchone()['response_body']
    assert receipt['title'] == 'Useful project'
    assert post(client,state,'PUBLICATION').status_code == 403
    assert post(client,state,'CORRECT_TITLE',target=LEGACY,key='other-project').status_code == 403


@pytest.mark.parametrize('action',['PUBLICATION','TEAM_POLICY','REGISTRATION','CORRECT_TITLE'])
@pytest.mark.parametrize('actor',['student-a','tech-admin'])
def test_students_and_technical_admin_have_no_academic_authority(staff_api,action,actor):
    client,state = staff_api
    client.credentials(HTTP_X_DEMO_USER=actor)
    assert post(client,state,action).status_code == 403


def test_ordinary_faculty_guide_and_unassigned_hod_are_not_administrators(staff_api):
    client,state = staff_api
    db = state['db']
    db.execute('UPDATE staff_permission_assignments SET valid_until=clock_timestamp()')
    for actor in ['faculty-a','staff-policy']:
        client.credentials(HTTP_X_DEMO_USER=actor)
        for action in ['PUBLICATION','TEAM_POLICY','REGISTRATION','CORRECT_TITLE']:
            assert post(client,state,action).status_code == 403
        assert client.get(url('policies',state)).status_code == 403
        assert client.get(url('projects',state)).status_code == 403


def test_explicit_coordinator_permission_is_supported_without_implicit_role_powers(staff_api):
    client,state = staff_api
    db = state['db']
    db.execute('UPDATE staff_permission_assignments SET valid_until=clock_timestamp() WHERE user_id=%s',(HOD,))
    db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code,valid_from) VALUES(%s,%s,'COORDINATOR',now()-interval '1 day')",(HOD,DEPT))
    grant(db,HOD,'MANAGE_OFFERINGS',role='COORDINATOR')
    assert post(client,state,'PUBLICATION').status_code == 200
    row = db.execute("SELECT metadata FROM audit_events WHERE action='STAFF_PUBLICATION'").fetchone()
    assert row['metadata']['authority']['role'] == 'COORDINATOR'


@pytest.mark.parametrize('mode',['expired','future','role-expired','disabled-account','disabled-department'])
def test_department_and_effective_delegation_are_revalidated(staff_api,mode):
    client,state = staff_api
    db = state['db']
    if mode in ('expired','future'):
        db.execute('UPDATE staff_permission_assignments SET valid_until=clock_timestamp() WHERE user_id=%s',(HOD,))
        if mode == 'future':
            db.execute('''INSERT INTO staff_permission_assignments(user_id,department_id,role_assignment_id,required_role,
              permission,valid_from,grant_reason) SELECT user_id,department_id,role_assignment_id,required_role,
              permission,clock_timestamp()+interval '1 day','Future synthetic assignment'
              FROM staff_permission_assignments WHERE user_id=%s''',(HOD,))
    elif mode == 'role-expired':
        db.execute("UPDATE department_role_assignments SET valid_until=clock_timestamp() WHERE user_id=%s AND role_code='HOD'",(HOD,))
    elif mode == 'disabled-account':
        db.execute("UPDATE users SET account_status='DISABLED' WHERE id=%s",(HOD,))
    else:
        db.execute('UPDATE staff_department_controls SET enabled=false')
    assert post(client,state,'PUBLICATION').status_code == 403
    assert client.get(url('policies',state)).status_code == 403


def test_foreign_department_and_target_scopes_are_denied(staff_api):
    client,state = staff_api
    db = state['db']
    dept = db.execute("INSERT INTO departments(code,name) VALUES('STAFF-OTHER','Other') RETURNING id").fetchone()['id']
    cycle = db.execute("INSERT INTO academic_cycles(department_id,code,starts_on,ends_on) VALUES(%s,'OTHER','2026-01-01','2027-01-01') RETURNING id",(dept,)).fetchone()['id']
    oid = offering(db,state['sp'],department=dept,cycle=cycle)
    assert post(client,state,'PUBLICATION',department=dept,target=oid).status_code == 403
    assert post(client,state,'PUBLICATION',target=oid).status_code == 403
    assert client.get(url('projects',state,department=dept)).status_code == 403
    rid = db.execute("SELECT id FROM department_role_assignments WHERE user_id=%s AND role_code='FACULTY'",(FACULTY,)).fetchone()['id']
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute('''INSERT INTO staff_permission_assignments(user_id,department_id,role_assignment_id,
          required_role,permission,project_id,grant_reason) VALUES(%s,%s,%s,'FACULTY','READ_PROJECTS',%s,'Invalid scope')''',
          (FACULTY,dept,rid,state['managed_project']))


@pytest.mark.parametrize('role,uid',[('FACULTY',FACULTY),('TECH_ADMIN',TECH),('STUDENT',A)])
def test_configuration_cannot_turn_routine_or_technical_roles_into_policy_authority(staff_api,role,uid):
    _,state = staff_api
    with pytest.raises(psycopg.errors.CheckViolation):
        grant(state['db'],uid,'MANAGE_TEAM_POLICY',role=role)


def test_revision_conflicts_and_receipt_keys_cannot_overwrite_policies(staff_api):
    client,state = staff_api
    first = post(client,state,'TEAM_POLICY')
    assert first.status_code == 200
    assert post(client,state,'PUBLICATION',key='stale-revision').status_code == 409
    assert post(client,state,'REGISTRATION',payload('REGISTRATION',state,revision=1)).status_code == 409
    assert state['db'].execute('SELECT revision FROM staff_department_controls').fetchone()['revision'] == 1
    assert state['db'].execute('SELECT count(*) AS n FROM staff_command_receipts').fetchone()['n'] == 1


def test_unpublication_and_registration_disable_preserve_committed_student_records(staff_api):
    client,state = staff_api
    pub = payload('PUBLICATION',state)
    pub.update(visibleFrom=None,visibleUntil=None,teamCreationEnabled=False)
    assert post(client,state,'PUBLICATION',pub).status_code == 200
    student = state['student']
    assert student.get('/api/v1/me/curriculum-offerings').status_code == 200
    assert str(state['societal']) not in [r['id'] for r in student.get('/api/v1/me/curriculum-offerings').json()['results']]
    reg = payload('REGISTRATION',state,revision=1)
    reg.update(policyVersionId=None,opensAt=None,closesAt=None)
    assert post(client,state,'REGISTRATION',reg,key='close-reg').status_code == 200
    assert register(student,code='DENIED',key='new-reg').status_code == 403
    assert register(student).status_code == 200
    assert state['db'].execute('SELECT count(*) AS n FROM student_project_registrations').fetchone()['n'] == 1


def test_unapproved_or_foreign_registration_policy_cannot_be_published(staff_api):
    client,state = staff_api
    bad = academic_policy(state['db'],status='DRAFT')
    reg = payload('REGISTRATION',state)
    reg['policyVersionId'] = str(bad)
    assert post(client,state,'REGISTRATION',reg).status_code == 403
    reg['policyVersionId'] = str(uuid4())
    assert post(client,state,'REGISTRATION',reg).status_code == 403
    assert state['db'].execute('SELECT revision FROM staff_department_controls').fetchone()['revision'] == 0


@pytest.mark.parametrize('evidence',['document','case','assignment','milestone','review'])
def test_title_correction_refuses_any_existing_academic_activity(staff_api,evidence):
    client,state = staff_api
    db = state['db']
    pid = state['managed_project']
    if evidence == 'document':
        db.execute("INSERT INTO documents(project_id,document_type,label) VALUES(%s,'SYNOPSIS','Draft document')",(pid,))
    elif evidence == 'case':
        db.execute("INSERT INTO submission_cases(project_id,requirement_key,submission_type) VALUES(%s,'TEST:SYNOPSIS','SYNOPSIS')",(pid,))
    elif evidence == 'assignment':
        db.execute("INSERT INTO faculty_assignments(project_id,faculty_user_id,assignment_type) VALUES(%s,%s,'GUIDE')",(pid,FACULTY))
    elif evidence == 'milestone':
        db.execute("INSERT INTO milestones(project_id,title) VALUES(%s,'Initial milestone')",(pid,))
    else:
        pid = db.execute('''INSERT INTO projects(department_id,cycle_id,team_id,project_type,policy_version_id,project_code,title)
          VALUES(%s,%s,%s,'MAJOR','12000000-0000-4000-8000-000000000001','REVIEW-GUARD','Useful project') RETURNING id''',(DEPT,CYCLE,TEAM)).fetchone()['id']
        db.execute('''INSERT INTO project_reviews(project_id,cycle_id,policy_version_id,review_definition_id,scheme_version_id)
          VALUES(%s,%s,'12000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001',
            '22000000-0000-4000-8000-000000000001')''',(pid,CYCLE))
    assert post(client,state,'CORRECT_TITLE',target=pid).status_code == 409
    assert db.execute('SELECT title,row_version FROM projects WHERE id=%s',(pid,)).fetchone() == {'title':'Useful project','row_version':1}


def test_finalized_history_and_sensitive_project_fields_are_never_corrected(staff_api):
    client,state = staff_api
    assert post(client,state,'CORRECT_TITLE',target=LEGACY).status_code == 409
    body = {**payload('CORRECT_TITLE',state),'teamId':str(uuid4())}
    assert post(client,state,'CORRECT_TITLE',body).status_code == 400
    assert post(client,state,'CORRECT_TITLE').status_code == 200
    assert post(client,state,'CORRECT_TITLE',key='stale-title').status_code == 409
    state['db'].execute('UPDATE staff_department_controls SET allow_title_corrections=false')
    body = payload('CORRECT_TITLE',state)
    body['expectedProjectVersion'] = 2
    assert post(client,state,'CORRECT_TITLE',body,key='disabled').status_code == 403


def test_role_and_grant_history_cannot_be_rewritten_after_commands(staff_api):
    client,state = staff_api
    assert post(client,state,'PUBLICATION').status_code == 200
    db = state['db']
    when = db.execute('SELECT occurred_at FROM staff_command_receipts').fetchone()['occurred_at']
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute('UPDATE staff_permission_assignments SET valid_until=%s WHERE id=%s',(when,state['grants']['MANAGE_OFFERINGS']))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("UPDATE department_role_assignments SET valid_until=%s WHERE user_id=%s AND role_code='HOD'",(when,HOD))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute('DELETE FROM staff_command_receipts')
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute('DELETE FROM staff_permission_assignments WHERE id=%s',(state['grants']['MANAGE_OFFERINGS'],))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute('UPDATE staff_department_controls SET revision=0')
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute('DELETE FROM staff_department_controls')
    db.execute("UPDATE department_role_assignments SET valid_until=clock_timestamp() WHERE user_id=%s AND role_code='HOD'",(HOD,))
    assert db.execute("SELECT count(*) AS n FROM audit_events WHERE action='STAFF_ROLE_AUTHORITY_CHANGED'").fetchone()['n'] == 1
    assert post(client,state,'PUBLICATION').status_code == 403


def worker_staff(actor,state,action,body,key):
    close_old_connections()
    try:
        client = APIClient()
        client.credentials(HTTP_X_DEMO_USER=actor)
        response = post(client,state,action,body,key=key)
        return response.status_code,response.json()
    finally:
        connection.close()


@pytest.mark.parametrize('same_key',[True,False])
def test_concurrent_policy_changes_replay_or_conflict_without_lost_updates(staff_api,same_key):
    _,state = staff_api
    body = payload('TEAM_POLICY',state)
    barrier = threading.Barrier(2)
    def run(i):
        barrier.wait(timeout=5)
        return worker_staff('staff-policy',state,'TEAM_POLICY',body,'same' if same_key else f'change-{i}')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run,range(2)))
    assert sorted(r[0] for r in results) == ([200,200] if same_key else [200,409]),results
    assert state['db'].execute('SELECT revision FROM staff_department_controls').fetchone()['revision'] == 1
    assert state['db'].execute('SELECT count(*) AS n FROM staff_command_receipts').fetchone()['n'] == 1


def test_stale_snapshot_cannot_correct_after_concurrent_evidence_creation(staff_api):
    _,state = staff_api
    body = payload('CORRECT_TITLE',state)
    with psycopg.connect(os.environ['DATABASE_URL'],autocommit=True) as stale:
        stale.execute('SET ROLE smartpro_runtime')
        stale.execute('BEGIN ISOLATION LEVEL REPEATABLE READ')
        stale.execute('SELECT id FROM projects WHERE id=%s',(state['managed_project'],))
        state['db'].execute("INSERT INTO documents(project_id,document_type,label) VALUES(%s,'SYNOPSIS','Concurrent document')",(state['managed_project'],))
        with pytest.raises(psycopg.errors.SerializationFailure):
            stale.execute('SELECT smartpro_staff_command(%s,%s,%s,%s,%s,%s)',
                          (HOD,DEPT,'CORRECT_TITLE',state['managed_project'],Jsonb(body),'stale'))
        stale.execute('ROLLBACK')


@pytest.mark.parametrize('deferred',[False,True])
@pytest.mark.parametrize('action',['TEAM_POLICY','CORRECT_TITLE'])
def test_policy_and_receipt_rollback_on_audit_or_commit_failure(staff_api,deferred,action):
    client,state = staff_api
    db = state['db']
    old = db.execute('SELECT count(*) AS n FROM team_membership_policy_versions').fetchone()['n']
    db.execute("""CREATE FUNCTION fail_staff_audit() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN IF NEW.action IN ('STAFF_TEAM_POLICY','STAFF_CORRECT_TITLE') THEN RAISE EXCEPTION 'synthetic failure' USING ERRCODE='23514'; END IF; RETURN NEW; END $$""")
    timing = 'DEFERRABLE INITIALLY DEFERRED' if deferred else ''
    db.execute(f'CREATE CONSTRAINT TRIGGER fail_staff_audit AFTER INSERT ON audit_events {timing} FOR EACH ROW EXECUTE FUNCTION fail_staff_audit()')
    body = payload(action,state)
    response = post(client,state,action,body)
    assert response.status_code == (503 if deferred else 409),response.content
    assert db.execute('SELECT revision FROM staff_department_controls').fetchone()['revision'] == 0
    assert db.execute('SELECT count(*) AS n FROM team_membership_policy_versions').fetchone()['n'] == old
    assert db.execute('SELECT count(*) AS n FROM staff_command_receipts').fetchone()['n'] == 0
    assert db.execute('SELECT title,row_version FROM projects WHERE id=%s',(state['managed_project'],)).fetchone() == {'title':'Useful project','row_version':1}
    db.execute('DROP TRIGGER fail_staff_audit ON audit_events')
    assert post(client,state,action,body).status_code == 200


@pytest.mark.parametrize('failure',[psycopg.errors.SerializationFailure,psycopg.errors.DeadlockDetected])
def test_full_transaction_retry_rolls_back_and_reauthorizes(staff_api,monkeypatch,failure):
    from django.db import OperationalError
    from smartpro import staff
    client,state = staff_api
    execute = staff._execute
    calls = []
    def fail_once(*args):
        response = execute(*args)
        calls.append(1)
        if len(calls) == 1:
            raise OperationalError('retry') from failure('synthetic retry')
        return response
    monkeypatch.setattr(staff,'_execute',fail_once)
    assert post(client,state,'TEAM_POLICY').status_code == 200 and len(calls) == 2
    assert state['db'].execute('SELECT revision FROM staff_department_controls').fetchone()['revision'] == 1
    assert state['db'].execute('SELECT count(*) AS n FROM staff_command_receipts').fetchone()['n'] == 1


def test_input_validation_authentication_and_private_database_capabilities(staff_api,monkeypatch):
    client,state = staff_api
    body = payload('PUBLICATION',state)
    for changed in [{'actorId':HOD},{'reason':''},{'expectedRevision':None},{'visibleFrom':'2026-11-04T12:00:00'},
                    {'visibleUntil':None}]:
        assert post(client,state,'PUBLICATION',{**body,**changed}).status_code == 400
    assert post(client,state,'PUBLICATION',body,key='bad key').status_code == 400
    assert client.get(url('policies',state),{'cursor':'bad'}).status_code == 400
    assert client.get(url('PUBLICATION',state)).status_code == 405
    client.credentials()
    assert post(client,state,'PUBLICATION',body).status_code == 401
    client.credentials(HTTP_X_DEMO_USER='staff-policy')
    monkeypatch.setenv('SMARTPRO_ENV','production')
    assert post(client,state,'PUBLICATION',body).status_code == 401
    monkeypatch.setenv('SMARTPRO_ENV','demo')
    monkeypatch.delenv('SMARTPRO_STAFF_API')
    assert client.get(url('policies',state)).status_code == 503
    with psycopg.connect(os.environ['DATABASE_URL'],autocommit=True) as runtime:
        runtime.execute('SET ROLE smartpro_runtime')
        for sql in ['SELECT * FROM staff_permission_assignments','SELECT * FROM staff_command_receipts',
                    'UPDATE staff_department_controls SET enabled=true','DELETE FROM offering_membership_policies',
                    "UPDATE projects SET title='unsafe'",'SELECT smartpro_staff_offering_state(NULL)']:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                runtime.execute(sql)


def wait_blocked(db,pid,blocker):
    deadline = time.monotonic()+3
    while time.monotonic()<deadline:
        if blocker in db.execute('SELECT pg_blocking_pids(%s) AS ids',(pid,)).fetchone()['ids']:
            return
        time.sleep(0.01)
    raise AssertionError('expected row-lock contention was not observed')


def pending_staff(state,body,ready,pids,action='PUBLICATION'):
    close_old_connections()
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_backend_pid()')
            pids.append(cursor.fetchone()[0])
        ready.set()
        client = APIClient()
        client.credentials(HTTP_X_DEMO_USER='staff-policy')
        response = post(client,state,action,body)
        return response.status_code,response.json()
    finally:
        connection.close()


def test_revocation_committing_first_prevents_waiting_staff_mutation(staff_api):
    _,state = staff_api
    db = state['db']
    ready,pids = threading.Event(),[]
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.transaction():
            db.execute('UPDATE staff_permission_assignments SET valid_until=clock_timestamp() WHERE id=%s',
                       (state['grants']['MANAGE_OFFERINGS'],))
            future = pool.submit(pending_staff,state,payload('PUBLICATION',state),ready,pids)
            assert ready.wait(3)
            wait_blocked(db,pids[0],db.info.backend_pid)
        assert future.result(timeout=6)[0] == 403
    assert db.execute('SELECT revision FROM staff_department_controls').fetchone()['revision'] == 0


def test_natural_delegation_expiry_is_rechecked_after_resource_lock_wait(staff_api):
    _,state = staff_api
    db = state['db']
    db.execute("UPDATE staff_permission_assignments SET valid_until=clock_timestamp()+interval '2 seconds' WHERE id=%s",
               (state['grants']['MANAGE_OFFERINGS'],))
    ready,pids = threading.Event(),[]
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.transaction():
            db.execute('SELECT id FROM curriculum_offerings WHERE id=%s FOR UPDATE',(state['societal'],))
            future = pool.submit(pending_staff,state,payload('PUBLICATION',state),ready,pids)
            assert ready.wait(3)
            wait_blocked(db,pids[0],db.info.backend_pid)
            remaining = db.execute('SELECT extract(epoch FROM valid_until-clock_timestamp()) AS seconds FROM staff_permission_assignments WHERE id=%s',
                                   (state['grants']['MANAGE_OFFERINGS'],)).fetchone()['seconds']
            assert remaining > 0
            time.sleep(float(remaining)+0.05)
        assert future.result(timeout=6)[0] == 403
    assert db.execute('SELECT revision FROM staff_department_controls').fetchone()['revision'] == 0
    assert db.execute('SELECT count(*) AS n FROM staff_command_receipts').fetchone()['n'] == 0


def test_committed_command_holds_authority_until_commit(staff_api):
    _,state = staff_api
    ready = threading.Event()
    pids = []
    def revoke():
        with psycopg.connect(os.environ['DATABASE_ADMIN_URL'],autocommit=True) as admin:
            pids.append(admin.info.backend_pid)
            ready.set()
            admin.execute('UPDATE staff_permission_assignments SET valid_until=clock_timestamp() WHERE id=%s',
                          (state['grants']['MANAGE_OFFERINGS'],))
    with ThreadPoolExecutor(max_workers=1) as pool:
        with psycopg.connect(os.environ['DATABASE_URL']) as held:
            held.execute('SET ROLE smartpro_runtime')
            held.execute('SELECT smartpro_staff_command(%s,%s,%s,%s,%s,%s)',
                         (HOD,DEPT,'PUBLICATION',state['societal'],Jsonb(payload('PUBLICATION',state)),'held'))
            future = pool.submit(revoke)
            assert ready.wait(3)
            wait_blocked(state['db'],pids[0],held.info.backend_pid)
        future.result(timeout=6)
    assert state['db'].execute('SELECT revision FROM staff_department_controls').fetchone()['revision'] == 1


def test_evidence_creation_serializes_with_title_correction(staff_api):
    _,state = staff_api
    db = state['db']
    ready,pids = threading.Event(),[]
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.transaction():
            db.execute("INSERT INTO documents(project_id,document_type,label) VALUES(%s,'SYNOPSIS','Pending evidence')",(state['managed_project'],))
            future = pool.submit(pending_staff,state,payload('CORRECT_TITLE',state),ready,pids,'CORRECT_TITLE')
            assert ready.wait(3)
            wait_blocked(db,pids[0],db.info.backend_pid)
        assert future.result(timeout=6)[0] == 409


def test_current_policy_and_project_pages_are_bounded_and_scope_filtered(staff_api):
    client,state = staff_api
    db = state['db']
    for i in range(50):
        tid = db.execute('INSERT INTO curriculum_types(code,label) VALUES(%s,%s) RETURNING id',(f'STAFF-{i}',f'Staff {i}')).fetchone()['id']
        offering(db,tid)
        db.execute('''INSERT INTO projects(department_id,cycle_id,team_id,project_type,policy_version_id,project_code,title)
          VALUES(%s,%s,%s,'MAJOR',%s,%s,'Scoped project')''',(DEPT,CYCLE,TEAM,state['policy'],f'STAFF-P-{i}'))
    for kind in ['policies','projects']:
        first = client.get(url(kind,state),{'limit':1000}).json()
        assert len(first['results']) == 50 and first['nextCursor'] is not None
        second = client.get(url(kind,state),{'cursor':first['nextCursor']}).json()
        assert len(second['results']) == 2 and second['nextCursor'] is None
        ids = [r['id'] for r in first['results']+second['results']]
        assert ids == sorted(set(ids))
    client.credentials(HTTP_X_DEMO_USER='faculty-a')
    assert [r['id'] for r in client.get(url('projects',state)).json()['results']] == [state['managed_project']]


def test_student_and_synopsis_flow_remains_valid_after_staff_publication(staff_api, monkeypatch, tmp_path):
    monkeypatch.setenv('SMARTPRO_DATA_DIR', str(tmp_path))
    client,state = staff_api
    from smartpro.views import domain
    # Publish explicit registration for a second curriculum, then use existing
    # student/team/project and synopsis services against the full 015 upgrade.
    assert post(client,state,'REGISTRATION',target=state['idt_offering']).status_code == 200
    student = state['student']
    created = student.post('/api/v1/teams',{'offeringId':str(state['idt_offering']),'name':'Staff published team'},
                           format='json',HTTP_IDEMPOTENCY_KEY='new-team')
    assert created.status_code == 201,created.content
    new = register(student,tid=created.json()['id'],code='STAFF-INTEGRATION',key='new-project')
    assert new.status_code == 201
    pid = new.json()['id']
    doc = state['db'].execute("INSERT INTO documents(project_id,document_type,label) VALUES(%s,'SYNOPSIS','Synopsis') RETURNING id",(pid,)).fetchone()['id']
    case = state['db'].execute("INSERT INTO submission_cases(project_id,requirement_key,submission_type) VALUES(%s,'SYNOPSIS:STAFF','SYNOPSIS') RETURNING id",(pid,)).fetchone()['id']
    upload = domain.start_upload(str(doc),A)['uploadId']
    domain.put_upload(upload,A,b'%PDF-1.4\nSynthetic integration')
    version = domain.finish_upload(upload,A)['documentVersionId']
    result = domain.submit_attempt(str(case),A,{'documentVersionIds':[version],'expectedCaseVersion':1},'submit-integrated')
    assert result['status'] == 'AWAITING_REVIEW'
    assert student.get(f'/api/v1/submission-cases/{case}').status_code == 200


def test_policy_commands_preserve_existing_academic_evidence(staff_api):
    client,state = staff_api
    db = state['db']
    tables = ['review_roster_members','submission_items','submission_attempts','approval_decisions',
              'result_releases','result_student_scores','team_memberships','student_project_registrations']
    def snapshot():
        return [db.execute(f'SELECT to_jsonb(t) AS data FROM {t} t ORDER BY to_jsonb(t)::text').fetchall() for t in tables]
    old = snapshot()
    assert post(client,state,'PUBLICATION').status_code == 200
    assert post(client,state,'TEAM_POLICY',payload('TEAM_POLICY',state,revision=1),key='membership').status_code == 200
    assert post(client,state,'REGISTRATION',payload('REGISTRATION',state,revision=2),key='registration').status_code == 200
    assert snapshot() == old


def test_sql_revision_and_receipt_boundary_reject_null_revision_and_legacy_forgery(staff_api):
    client,state = staff_api
    body = payload('PUBLICATION',state)
    with psycopg.connect(os.environ['DATABASE_URL'],autocommit=True) as runtime:
        runtime.execute('SET ROLE smartpro_runtime')
        runtime.execute("INSERT INTO idempotency_records(actor_id,operation,key,request_sha256,state,response_body) VALUES(%s,'STAFF_PUBLICATION','staff-test',%s,'COMPLETE','{}')",(HOD,'a'*64))
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            runtime.execute('SELECT smartpro_staff_command(%s,%s,%s,%s,%s,%s)',
                            (HOD,DEPT,'PUBLICATION',state['societal'],Jsonb({**body,'expectedRevision':None}),'invalid'))
    assert post(client,state,'PUBLICATION',body).status_code == 200
    assert state['db'].execute('SELECT revision FROM staff_department_controls').fetchone()['revision'] == 1


def test_retry_exhaustion_and_disabled_correction_defaults(staff_api,monkeypatch):
    from django.db import OperationalError
    from smartpro import staff
    client,state = staff_api
    state['db'].execute('UPDATE staff_department_controls SET allow_title_corrections=false')
    assert post(client,state,'CORRECT_TITLE').status_code == 403
    calls = []
    def fail(*args):
        calls.append(1)
        raise OperationalError('retry') from psycopg.errors.SerializationFailure('synthetic')
    monkeypatch.setattr(staff,'_execute',fail)
    assert post(client,state,'PUBLICATION').status_code == 409 and len(calls) == 3
    assert state['db'].execute('SELECT revision FROM staff_department_controls').fetchone()['revision'] == 0


def test_deleting_a_draft_document_does_not_reopen_title_correction(staff_api):
    client,state = staff_api
    db = state['db']
    doc = db.execute("INSERT INTO documents(project_id,document_type,label) VALUES(%s,'SYNOPSIS','Draft') RETURNING id",(state['managed_project'],)).fetchone()['id']
    db.execute('DELETE FROM documents WHERE id=%s',(doc,))
    assert post(client,state,'CORRECT_TITLE').status_code == 409


def test_candidate_requires_project_registration_upgrade(membership_api):  # noqa: F811
    _,state = membership_api
    with pytest.raises(psycopg.errors.RaiseException,match='Install activated curriculum 010-014'):
        execute_file(state['db'],ROOT / 'proposals/curriculum/015_staff_administration.sql')
    state['db'].execute('ROLLBACK')
    assert state['db'].execute("SELECT to_regclass('public.staff_department_controls') AS state").fetchone()['state'] is None


def test_revoked_or_replaced_role_cannot_resurrect_a_delegation(staff_api):
    client,state = staff_api
    db = state['db']
    db.execute('UPDATE staff_permission_assignments SET revoked=true WHERE id=%s',(state['grants']['MANAGE_OFFERINGS'],))
    assert post(client,state,'PUBLICATION').status_code == 403
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute('UPDATE staff_permission_assignments SET revoked=false WHERE id=%s',(state['grants']['MANAGE_OFFERINGS'],))
    db.execute("UPDATE department_role_assignments SET valid_until=clock_timestamp() WHERE user_id=%s AND role_code='HOD'",(HOD,))
    db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'HOD')",(HOD,DEPT))
    assert client.get(url('policies',state)).status_code == 403


def test_future_delegation_can_be_cancelled_without_an_active_interval(staff_api):
    client,state = staff_api
    db = state['db']
    db.execute('UPDATE staff_permission_assignments SET revoked=true WHERE user_id=%s',(HOD,))
    rid = db.execute("SELECT id FROM department_role_assignments WHERE user_id=%s AND role_code='HOD'",(HOD,)).fetchone()['id']
    gid = db.execute('''INSERT INTO staff_permission_assignments(user_id,department_id,role_assignment_id,required_role,
      permission,valid_from,grant_reason) VALUES(%s,%s,%s,'HOD','MANAGE_OFFERINGS',clock_timestamp()+interval '1 day',
      'Future approved assignment') RETURNING id''',(HOD,DEPT,rid)).fetchone()['id']
    db.execute('UPDATE staff_permission_assignments SET revoked=true WHERE id=%s',(gid,))
    assert post(client,state,'PUBLICATION').status_code == 403


@pytest.mark.parametrize('record',['grant','role'])
def test_stale_authority_snapshot_cannot_backdate_a_committed_command(staff_api,record):
    client,state = staff_api
    gid = state['grants']['MANAGE_OFFERINGS']
    with psycopg.connect(os.environ['DATABASE_ADMIN_URL'],autocommit=True) as stale:
        stale.execute('BEGIN ISOLATION LEVEL REPEATABLE READ')
        rid = stale.execute('SELECT role_assignment_id FROM staff_permission_assignments WHERE id=%s',(gid,)).fetchone()[0]
        assert post(client,state,'PUBLICATION').status_code == 200
        when = state['db'].execute('SELECT occurred_at FROM staff_command_receipts').fetchone()['occurred_at']
        with pytest.raises(psycopg.errors.SerializationFailure):
            if record == 'grant':
                stale.execute('UPDATE staff_permission_assignments SET valid_until=%s WHERE id=%s',(when,gid))
            else:
                stale.execute('UPDATE department_role_assignments SET valid_until=%s WHERE id=%s',(when,rid))
        stale.execute('ROLLBACK')


def test_different_staff_actors_cannot_overwrite_the_same_policy_revision(staff_api):
    _,state = staff_api
    db = state['db']
    uid = '00000000-0000-4000-8000-000000000006'
    db.execute("INSERT INTO users(id,display_name,email) VALUES(%s,'Synthetic coordinator','coordinator@example.invalid')",(uid,))
    db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'COORDINATOR')",(uid,DEPT))
    grant(db,uid,'MANAGE_OFFERINGS',role='COORDINATOR')
    body = payload('PUBLICATION',state)
    barrier = threading.Barrier(2)
    def run(actor):
        barrier.wait(timeout=5)
        return worker_staff(actor,state,'PUBLICATION',body,'shared-policy-update')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run,['staff-policy','faculty-other']))
    assert sorted(r[0] for r in results) == [200,409],results
    assert db.execute('SELECT revision FROM staff_department_controls').fetchone()['revision'] == 1
    assert db.execute("SELECT count(*) AS n FROM audit_events WHERE action='STAFF_PUBLICATION'").fetchone()['n'] == 1


def test_concurrent_delegated_title_corrections_do_not_lose_updates(staff_api):
    _,state = staff_api
    body = payload('CORRECT_TITLE',state)
    barrier = threading.Barrier(2)
    def run(actor):
        barrier.wait(timeout=5)
        return worker_staff(actor,state,'CORRECT_TITLE',body,'title-update')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run,['staff-policy','faculty-a']))
    assert sorted(r[0] for r in results) == [200,409],results
    assert state['db'].execute('SELECT row_version FROM projects WHERE id=%s',(state['managed_project'],)).fetchone()['row_version'] == 2
