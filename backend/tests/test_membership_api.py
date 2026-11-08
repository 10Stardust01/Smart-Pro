"""Real HTTP, restricted-role SQL, temporal integrity and concurrency contracts."""
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
import threading
from uuid import uuid4

import psycopg
import pytest
from test_team_api import api, publish, create  # noqa: F401 - initializes Django
from django.db import close_old_connections, connection
from rest_framework.test import APIClient

from db_setup import execute_file, ROOT
from proposals.curriculum.test_contracts import (  # noqa: F401
    A, B, DEPT, CYCLE, active, prepared, team, offering, new_student,
)

SOURCE = '14000000-0000-4000-8000-000000000001'


def bind_policy(db, oid, **changes):
    values = dict(allow_join=True, allow_leave=True, allow_transfer=True,
                  minimum_members=None, maximum_members=None, size_mode='ENFORCED')
    values.update(changes)
    row = db.execute('SELECT coalesce(max(version_no),0)+1 AS n FROM team_membership_policy_versions WHERE department_id=%s', (DEPT,)).fetchone()
    policy = db.execute('''INSERT INTO team_membership_policy_versions
      (department_id,version_no,allow_join,allow_leave,allow_transfer,minimum_members,maximum_members,size_mode)
      VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''', (DEPT,row['n'],*values.values())).fetchone()['id']
    db.execute('''INSERT INTO offering_membership_policies(offering_id,cycle_id,department_id,policy_version_id)
      VALUES(%s,%s,%s,%s) ON CONFLICT(offering_id) DO UPDATE SET policy_version_id=excluded.policy_version_id''',
      (oid,CYCLE,DEPT,policy))
    return policy


@pytest.fixture
def membership_api(api, monkeypatch):  # noqa: F811
    client, state = api
    execute_file(state['db'], ROOT / 'proposals/curriculum/013_membership_commands.sql')
    monkeypatch.setenv('SMARTPRO_MEMBERSHIP_API', 'YES')
    for oid in [state['societal'],state['idt_offering']]:
        publish(state['db'], oid)
        bind_policy(state['db'], oid)
    return client, state


def command(client, action, identifier, *, target=None, key='membership-test', reason=None):
    paths = {'JOIN':f'/api/v1/teams/{identifier}/memberships',
             'LEAVE':f'/api/v1/memberships/{identifier}/end',
             'TRANSFER':f'/api/v1/memberships/{identifier}/transfer'}
    body = {'targetTeamId':str(target)} if action=='TRANSFER' else {}
    if reason is not None:
        body['reason'] = reason
    return client.post(paths[action], body, format='json', HTTP_IDEMPOTENCY_KEY=key)


def test_join_leave_and_rejoin_preserve_intervals(membership_api):
    client, state = membership_api
    db = state['db']
    tid = team(db, state['idt_offering'])
    first = command(client,'JOIN',tid)
    assert first.status_code==201, first.content
    mid = first.json()['membershipId']
    ended = command(client,'LEAVE',mid)
    assert ended.status_code==200
    assert command(client,'LEAVE',mid).json()==ended.json()
    second = command(client,'JOIN',tid,key='again')
    assert second.status_code==201 and second.json()['membershipId']!=mid
    rows = db.execute('SELECT joined_at,left_at FROM team_memberships WHERE team_id=%s ORDER BY joined_at',(tid,)).fetchall()
    assert len(rows)==2 and rows[0]['left_at']<=rows[1]['joined_at'] and rows[1]['left_at'] is None
    assert db.execute("SELECT count(*) AS n FROM audit_events WHERE action LIKE 'MEMBERSHIP_%%' AND actor_id=%s",(A,)).fetchone()['n']==3


def test_transfer_preserves_frozen_evidence_and_old_identity(membership_api):
    client, state = membership_api
    db = state['db']
    tables=['review_roster_members','submission_items','submission_attempts','approval_decisions','result_releases','result_student_scores']
    def snapshot():
        return [db.execute(f'SELECT to_jsonb(t) AS data FROM {t} t ORDER BY to_jsonb(t)::text').fetchall() for t in tables]
    before=snapshot()
    old=db.execute('SELECT * FROM team_memberships WHERE id=%s',(SOURCE,)).fetchone()
    target=team(db,state['societal'])
    result=command(client,'TRANSFER',SOURCE,target=target,reason='Student requested transfer')
    assert result.status_code==201,result.content
    body=result.json()
    current=db.execute('SELECT * FROM team_memberships WHERE id=%s',(body['membershipId'],)).fetchone()
    ended=db.execute('SELECT * FROM team_memberships WHERE id=%s',(SOURCE,)).fetchone()
    assert ended['left_at']==current['joined_at'] and current['left_at'] is None
    assert {k:v for k,v in ended.items() if k!='left_at'}=={k:v for k,v in old.items() if k!='left_at'}
    assert snapshot()==before
    assert command(client,'TRANSFER',SOURCE,target=target).status_code==409  # changed reason, same key
    retry=command(client,'TRANSFER',SOURCE,target=target,reason='Student requested transfer')
    assert retry.status_code==200 and retry.json()==body
    audit=db.execute("SELECT metadata FROM audit_events WHERE action='MEMBERSHIP_TRANSFER'").fetchone()['metadata']
    assert audit['previousMembershipId']==SOURCE and audit['policyVersionId']==body['policyVersionId']
    assert audit['reason']=='Student requested transfer'


@pytest.mark.parametrize('action', ['JOIN','LEAVE','TRANSFER'])
def test_policy_operations_disabled_by_explicit_configuration(membership_api,action):
    client,state=membership_api
    db=state['db']
    oid=state['idt_offering'] if action=='JOIN' else state['societal']
    bind_policy(db,oid,**{'allow_'+action.lower():False})
    target=team(db,oid)
    assert command(client,action,target if action=='JOIN' else SOURCE,target=target).status_code==403


@pytest.mark.parametrize('action', ['JOIN','LEAVE','TRANSFER'])
@pytest.mark.parametrize('mode',['disabled','expired-role','future-role','faculty'])
def test_actor_eligibility_is_checked_for_all_commands(membership_api,action,mode):
    client,state=membership_api
    db=state['db']
    target=team(db,state['idt_offering'] if action=='JOIN' else state['societal'])
    if mode=='disabled':
        db.execute("UPDATE users SET account_status='DISABLED' WHERE id=%s",(A,))
    elif mode=='expired-role':
        db.execute("UPDATE department_role_assignments SET valid_from=now()-interval '2 days',valid_until=now()-interval '1 day' WHERE user_id=%s",(A,))
    elif mode=='future-role':
        db.execute("UPDATE department_role_assignments SET valid_from=now()+interval '1 day' WHERE user_id=%s",(A,))
    else:
        client.credentials(HTTP_X_DEMO_USER='faculty-a')
    assert command(client,action,target if action=='JOIN' else SOURCE,target=target).status_code==403


def test_offering_cycle_and_ownership_cannot_be_bypassed(membership_api):
    client,state=membership_api
    db=state['db']
    target=team(db,state['idt_offering'])
    assert command(client,'TRANSFER',SOURCE,target=target).status_code==409
    other_source='14000000-0000-4000-8000-000000000002'
    assert command(client,'LEAVE',other_source).status_code==403
    assert command(client,'JOIN',uuid4()).status_code==403
    # A different semester is inaccessible even if published and creation enabled.
    oid=offering(db,state['sp'],semester='OTHER-SEM')
    publish(db,oid)
    assert command(client,'JOIN',team(db,oid)).status_code==403
    cycle=db.execute("INSERT INTO academic_cycles(department_id,code,starts_on,ends_on) VALUES(%s,'FUTURE-TEST','2040-01-01','2041-01-01') RETURNING id",(DEPT,)).fetchone()['id']
    future=offering(db,state['sp'],cycle=cycle)
    assert command(client,'JOIN',team(db,future,cycle=cycle)).status_code==403


def test_closed_window_blocks_admission_but_not_permitted_departure(membership_api):
    client,state=membership_api
    db=state['db']
    db.execute("UPDATE student_offering_windows SET visible_from=now()-interval '3 days',visible_until=now()-interval '1 day'")
    assert command(client,'JOIN',team(db,state['idt_offering'])).status_code==403
    assert command(client,'TRANSFER',SOURCE,target=team(db,state['societal'])).status_code==403
    assert command(client,'LEAVE',SOURCE).status_code==200


def test_size_policy_enforcement_and_atomic_transfer_rollback(membership_api):
    client,state=membership_api
    db=state['db']
    bind_policy(db,state['societal'],minimum_members=2)
    target=team(db,state['societal'])
    assert command(client,'LEAVE',SOURCE).status_code==409
    assert command(client,'TRANSFER',SOURCE,target=target).status_code==409
    assert db.execute('SELECT left_at FROM team_memberships WHERE id=%s',(SOURCE,)).fetchone()['left_at'] is None
    bind_policy(db,state['societal'],maximum_members=1)
    # Target is the occupied original team; source transfer is rolled back on max.
    assert command(client,'TRANSFER',SOURCE,target=target,key='move-out').status_code==201
    moved=db.execute('SELECT id FROM team_memberships WHERE team_id=%s AND user_id=%s',(target,A)).fetchone()['id']
    assert command(client,'TRANSFER',moved,target='13000000-0000-4000-8000-000000000001',key='move-back').status_code==409
    assert db.execute('SELECT left_at FROM team_memberships WHERE id=%s',(moved,)).fetchone()['left_at'] is None


def test_advisory_limits_and_policy_version_history(membership_api):
    client,state=membership_api
    db=state['db']
    version=bind_policy(db,state['societal'],minimum_members=3,size_mode='ADVISORY')
    result=command(client,'LEAVE',SOURCE)
    assert result.status_code==200 and result.json()['warnings'][0]['code']=='BELOW_MINIMUM'
    bind_policy(db,state['societal'],allow_leave=False)
    retry=command(client,'LEAVE',SOURCE)
    assert retry.status_code==200 and retry.json()==result.json()
    assert retry.json()['policyVersionId']==str(version)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("UPDATE team_membership_policy_versions SET allow_leave=false WHERE id=%s",(version,))
    assert db.execute("SELECT count(*) AS n FROM audit_events WHERE action='MEMBERSHIP_POLICY_BOUND'").fetchone()['n']>=4


def test_team_creation_allows_formation_below_minimum(membership_api):
    client,state=membership_api
    db=state['db']
    # Minimum is formation guidance; it must not prevent creating the first member.
    bind_policy(db,state['idt_offering'],minimum_members=3,maximum_members=3)
    assert create(client,state['idt_offering']).status_code==201


def test_unconfigured_policy_and_other_department_are_denied(membership_api):
    client,state=membership_api
    db=state['db']
    db.execute('DELETE FROM offering_membership_policies WHERE offering_id=%s',(state['idt_offering'],))
    assert command(client,'JOIN',team(db,state['idt_offering'])).status_code==403
    dept=db.execute("INSERT INTO departments(code,name) VALUES('DENIED-DEP','Other') RETURNING id").fetchone()['id']
    cycle=db.execute("INSERT INTO academic_cycles(department_id,code,starts_on,ends_on) VALUES(%s,'OTHER','2026-01-01','2027-01-01') RETURNING id",(dept,)).fetchone()['id']
    oid=offering(db,state['sp'],department=dept,cycle=cycle)
    publish(db,oid)
    assert command(client,'JOIN',team(db,oid,department=dept,cycle=cycle)).status_code==403


def test_scheduled_membership_reserves_capacity(membership_api):
    client,state=membership_api
    db=state['db']
    bind_policy(db,state['idt_offering'],maximum_members=1)
    target=team(db,state['idt_offering'])
    db.execute("INSERT INTO team_memberships(team_id,user_id,curriculum_offering_id,joined_at) VALUES(%s,%s,%s,now()+interval '1 day')",(target,B,state['idt_offering']))
    assert command(client,'JOIN',target).status_code==409


def test_future_member_does_not_satisfy_current_departure_minimum(membership_api):
    client,state=membership_api
    db=state['db']
    bind_policy(db,state['societal'],minimum_members=2)
    student=new_student(db)
    db.execute("INSERT INTO team_memberships(team_id,user_id,curriculum_offering_id,joined_at) VALUES(%s,%s,%s,now()+interval '1 day')",('13000000-0000-4000-8000-000000000001',student,state['societal']))
    assert command(client,'LEAVE',SOURCE).status_code==409


def test_retry_rechecks_account_and_capability_grants(membership_api):
    client,state=membership_api
    db=state['db']
    target=team(db,state['idt_offering'])
    assert command(client,'JOIN',target).status_code==201
    db.execute("UPDATE users SET account_status='DISABLED' WHERE id=%s",(A,))
    assert command(client,'JOIN',target).status_code==403
    row=db.execute("""SELECT proconfig,NOT EXISTS(
      SELECT FROM aclexplode(coalesce(proacl,acldefault('f',proowner))) acl
      WHERE acl.grantee=0 AND acl.privilege_type='EXECUTE') AS public_denied
      FROM pg_proc WHERE proname='smartpro_student_membership'""").fetchone()
    assert row['public_denied'] and 'search_path=pg_catalog, public, pg_temp' in row['proconfig']


def worker_request(actor, action, identifier, target=None, key='parallel'):
    close_old_connections()
    try:
        client=APIClient()
        client.credentials(HTTP_X_DEMO_USER=actor)
        response=command(client,action,identifier,target=target,key=key)
        return response.status_code,response.json()
    finally:
        connection.close()


def test_concurrent_last_place_is_not_oversubscribed(membership_api):
    _,state=membership_api
    db=state['db']
    bind_policy(db,state['idt_offering'],maximum_members=1)
    target=team(db,state['idt_offering'])
    barrier=threading.Barrier(2)
    def worker(actor):
        barrier.wait(timeout=5)
        return worker_request(actor,'JOIN',target)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(worker,['student-a','student-b']))
    assert sorted(r[0] for r in results)==[201,409],results
    assert db.execute('SELECT count(*) AS n FROM team_memberships WHERE team_id=%s AND left_at IS NULL',(target,)).fetchone()['n']==1


def test_concurrent_same_key_replays_once(membership_api):
    _,state=membership_api
    target=team(state['db'],state['idt_offering'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:worker_request('student-a','JOIN',target),range(2)))
    assert sorted(r[0] for r in results)==[200,201] and results[0][1]==results[1][1]


def test_concurrent_different_teams_same_offering_conflict(membership_api):
    _,state=membership_api
    targets=[team(state['db'],state['idt_offering']) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda t:worker_request('student-a','JOIN',t,key=str(t)),targets))
    assert sorted(r[0] for r in results)==[201,409]


def test_opposite_transfers_use_consistent_team_lock_order(membership_api):
    client,state=membership_api
    db=state['db']
    target=team(db,state['societal'])
    client.credentials(HTTP_X_DEMO_USER='student-b')
    bsource='14000000-0000-4000-8000-000000000002'
    moved=command(client,'TRANSFER',bsource,target=target).json()['membershipId']
    barrier=threading.Barrier(2)
    def worker(args):
        actor,mid,tid=args
        barrier.wait(timeout=5)
        return worker_request(actor,'TRANSFER',mid,target=tid,key='swap')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(worker,[('student-a',SOURCE,target),('student-b',moved,'13000000-0000-4000-8000-000000000001')]))
    assert [r[0] for r in results]==[201,201],results


def test_old_repeatable_read_capacity_snapshot_aborts(membership_api):
    client,state=membership_api
    db=state['db']
    bind_policy(db,state['idt_offering'],maximum_members=1)
    target=team(db,state['idt_offering'])
    with psycopg.connect(os.environ['DATABASE_URL'],autocommit=True) as stale:
        stale.execute('SET ROLE smartpro_runtime')
        stale.execute('BEGIN ISOLATION LEVEL REPEATABLE READ')
        stale.execute('SELECT smartpro_student_profile(%s)',(A,))
        client.credentials(HTTP_X_DEMO_USER='student-b')
        assert command(client,'JOIN',target).status_code==201
        with pytest.raises(psycopg.errors.SerializationFailure):
            stale.execute('SELECT smartpro_student_membership(%s,%s,%s,%s,%s,%s,%s)',
                          (A,'JOIN',None,target,'','stale',hashlib.sha256(b'stale').hexdigest()))
        stale.execute('ROLLBACK')
    client.credentials(HTTP_X_DEMO_USER='student-a')
    assert command(client,'JOIN',target).status_code==409


@pytest.mark.parametrize('deferred',[False,True])
def test_failed_transfer_and_commit_roll_back_everything_and_retry(membership_api,deferred):
    client,state=membership_api
    db=state['db']
    target=team(db,state['societal'])
    db.execute("""CREATE FUNCTION fail_membership_audit() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN IF NEW.action='MEMBERSHIP_TRANSFER' THEN RAISE EXCEPTION 'synthetic failure' USING ERRCODE='23514'; END IF; RETURN NEW; END $$""")
    timing='DEFERRABLE INITIALLY DEFERRED' if deferred else ''
    db.execute(f'CREATE CONSTRAINT TRIGGER fail_membership_audit AFTER INSERT ON audit_events {timing} FOR EACH ROW EXECUTE FUNCTION fail_membership_audit()')
    result=command(client,'TRANSFER',SOURCE,target=target)
    assert result.status_code==(503 if deferred else 409),result.content
    assert db.execute('SELECT left_at FROM team_memberships WHERE id=%s',(SOURCE,)).fetchone()['left_at'] is None
    assert db.execute('SELECT count(*) AS n FROM team_memberships WHERE team_id=%s',(target,)).fetchone()['n']==0
    assert db.execute("SELECT count(*) AS n FROM idempotency_records WHERE operation LIKE 'STUDENT_MEMBERSHIP:%'").fetchone()['n']==0
    db.execute('DROP TRIGGER fail_membership_audit ON audit_events')
    assert command(client,'TRANSFER',SOURCE,target=target).status_code==201


def test_validation_gates_and_denied_direct_sql(membership_api,monkeypatch):
    client,state=membership_api
    target=team(state['db'],state['idt_offering'])
    path=f'/api/v1/teams/{target}/memberships'
    for body in [{'userId':A},{'joinedAt':'2000-01-01'},[],{'departmentId':DEPT}]:
        assert client.post(path,body,format='json',HTTP_IDEMPOTENCY_KEY='input').status_code==400
    assert command(client,'JOIN',target,key='bad key').status_code==400
    assert client.get(path).status_code==405
    client.credentials()
    assert command(client,'JOIN',target).status_code==401
    client.credentials(HTTP_X_DEMO_USER='student-a')
    monkeypatch.setenv('SMARTPRO_ENV','production')
    assert command(client,'JOIN',target).status_code==401
    monkeypatch.setenv('SMARTPRO_ENV','demo')
    monkeypatch.delenv('SMARTPRO_MEMBERSHIP_API')
    assert command(client,'JOIN',target).status_code==503
    with psycopg.connect(os.environ['DATABASE_URL'],autocommit=True) as runtime:
        runtime.execute('SET ROLE smartpro_runtime')
        for sql in ['SELECT * FROM team_membership_policy_versions',
                    'DELETE FROM offering_membership_policies',
                    'UPDATE team_memberships SET left_at=now()',
                    "UPDATE teams SET membership_revision=gen_random_uuid()"]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                runtime.execute(sql)


@pytest.mark.parametrize('failure',[psycopg.errors.SerializationFailure,psycopg.errors.DeadlockDetected])
def test_transaction_retry_rolls_back_partial_success_before_reauthorization(membership_api,monkeypatch,failure):
    from django.db import OperationalError
    from smartpro import memberships
    client,state=membership_api
    target=team(state['db'],state['idt_offering'])
    execute=memberships._db_result
    calls=[]
    def fail_first(statement,values):
        result=execute(statement,values)
        calls.append(result)
        if len(calls)==1:
            raise OperationalError('retryable database failure') from failure('synthetic retry')
        return result
    monkeypatch.setattr(memberships,'_db_result',fail_first)
    response=command(client,'JOIN',target)
    assert response.status_code==201 and len(calls)==2,response.content
    assert state['db'].execute('SELECT count(*) AS n FROM team_memberships WHERE team_id=%s',(target,)).fetchone()['n']==1
    assert state['db'].execute("SELECT count(*) AS n FROM audit_events WHERE action='MEMBERSHIP_JOIN'").fetchone()['n']==1


def test_retry_exhaustion_leaves_no_partial_records(membership_api,monkeypatch):
    from django.db import OperationalError
    from smartpro import memberships
    client,state=membership_api
    target=team(state['db'],state['idt_offering'])
    calls=[]
    def always_fail(*args):
        calls.append(1)
        raise OperationalError('concurrent transaction') from psycopg.errors.SerializationFailure('retry')
    monkeypatch.setattr(memberships,'_db_result',always_fail)
    assert command(client,'JOIN',target).status_code==409 and len(calls)==3
    assert state['db'].execute("SELECT count(*) AS n FROM idempotency_records WHERE operation LIKE 'STUDENT_MEMBERSHIP:%'").fetchone()['n']==0


def test_own_memberships_exposes_only_current_actor_and_survives_closed_window(membership_api):
    client,state=membership_api
    db=state['db']
    path='/api/v1/me/memberships'
    db.execute("UPDATE student_offering_windows SET visible_from=now()-interval '3 days',visible_until=now()-interval '1 day'")
    response=client.get(path,{'userId':B})
    assert response.status_code==200 and response['Cache-Control']=='no-store'
    assert [r['id'] for r in response.json()['results']]==[SOURCE]
    assert 'usn' not in str(response.json())
    assert command(client,'LEAVE',SOURCE).status_code==200
    assert client.get(path).json()['results']==[]
    assert client.get(path,{'cursor':'bad'}).status_code==400


def test_own_memberships_are_paged_and_scoped(membership_api):
    client,state=membership_api
    db=state['db']
    ids=[SOURCE]
    for i in range(50):
        category=db.execute('INSERT INTO curriculum_types(code,label) VALUES(%s,%s) RETURNING id',(f'M-{i}',f'Membership {i}')).fetchone()['id']
        oid=offering(db,category)
        tid=team(db,oid)
        ids.append(str(db.execute('INSERT INTO team_memberships(team_id,user_id,curriculum_offering_id) VALUES(%s,%s,%s) RETURNING id',(tid,A,oid)).fetchone()['id']))
    path='/api/v1/me/memberships'
    first=client.get(path).json()
    assert len(first['results'])==50
    second=client.get(path,{'cursor':first['nextCursor']}).json()
    assert len(second['results'])==1 and second['nextCursor'] is None
    assert [r['id'] for r in first['results']+second['results']]==sorted(ids)
