"""Local PostgreSQL academic governance and versioned marking contracts."""
# ruff: noqa: F811
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import psycopg
from test_staff_api import (  # noqa: F401
    staff_api, project_api, membership_api, api, active, prepared, HOD, FACULTY, TECH,
    DEPT, ROOT, execute_file, url,
)
from rest_framework.test import APIClient

BASE = f'/api/v1/academic/departments/{DEPT}'
B = '00000000-0000-4000-8000-000000000002'


def until():
    return (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()


def send(client, path, body, key=None):
    return client.post(BASE+path,body,format='json',HTTP_IDEMPOTENCY_KEY=key or str(uuid4()))


def policy_body(revision=0, **changes):
    return dict(expectedRevision=revision,reason='Synthetic configured policy',evaluatorQuorum=1,
                aggregation='MEAN',evaluatorWeights={},**changes)


@pytest.fixture
def academic(staff_api,monkeypatch):
    hod,state = staff_api
    db = state['db']
    # Existing owner grants must still work after the cumulative upgrade.
    assert hod.get(url('projects',state)).status_code == 200
    db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'FACULTY')",(B,DEPT))
    assert db.execute("SELECT to_regclass('public.academic_governance_settings') AS installed").fetchone()['installed']
    db.execute('INSERT INTO academic_governance_settings(department_id,enabled) VALUES(%s,true)',(DEPT,))
    rid = db.execute("SELECT id FROM department_role_assignments WHERE user_id=%s AND role_code='HOD'",(HOD,)).fetchone()['id']
    state['root'] = db.execute('INSERT INTO academic_hod_mandates(department_id,role_assignment_id,user_id,enabled) VALUES(%s,%s,%s,true) RETURNING id',
                              (DEPT,rid,HOD)).fetchone()['id']
    monkeypatch.setenv('SMARTPRO_ACADEMIC_API','YES')
    return hod,state


def coordinator(hod):
    response = send(hod,'/coordinators',dict(expectedRevision=0,reason='Appointment',userId=B,validUntil=until()))
    assert response.status_code == 200,response.content
    client = APIClient()
    client.credentials(HTTP_X_DEMO_USER='student-b')
    return client,response.json()['id']


def test_versioned_quorum_and_aggregation_are_explicit(academic):
    hod,state = academic
    first = send(hod,'/policies',policy_body(),key='policy')
    assert first.status_code == 200,first.content
    assert send(hod,'/policies',policy_body(),key='policy').json() == first.json()
    next_body = policy_body(1)
    next_body.update(evaluatorQuorum=2,aggregation='MAX')
    second = send(hod,'/policies',next_body)
    assert second.status_code == 200
    assert state['db'].execute('SELECT count(*) AS n FROM academic_evaluation_policies').fetchone()['n'] == 2
    assert send(hod,'/policies',next_body,key='policy').status_code == 409


@pytest.mark.parametrize('who',['student-a','faculty-a','tech-admin'])
def test_roles_do_not_imply_policy_or_appointment_authority(academic,who):
    _,state = academic
    client = APIClient()
    client.credentials(HTTP_X_DEMO_USER=who)
    assert send(client,'/policies',policy_body()).status_code == 403
    assert send(client,'/coordinators',dict(expectedRevision=0,reason='No authority',userId=B,validUntil=until())).status_code == 403
    assert state['db'].execute('SELECT count(*) AS n FROM academic_coordinator_mandates').fetchone()['n'] == 0


def test_hod_appointment_coordinator_delegation_and_revocation(academic):
    hod,state = academic
    coord,mandate = coordinator(hod)
    assert send(coord,'/policies',policy_body(1)).status_code == 200
    assert send(coord,'/coordinators',dict(expectedRevision=2,reason='No subappointment',userId=FACULTY,validUntil=until())).status_code == 403
    role = state['db'].execute("SELECT id FROM department_role_assignments WHERE user_id=%s AND role_code='FACULTY'",(FACULTY,)).fetchone()['id']
    body = dict(expectedRevision=2,reason='Routine project work',roleAssignmentId=str(role),permission='READ_PROJECTS',projectId=state['managed_project'],validUntil=until())
    delegated = send(coord,'/delegations',body)
    assert delegated.status_code == 200,delegated.content
    assert send(coord,'/delegations',{**body,'permission':'MANAGE_TEAM_POLICY','expectedRevision':3}).status_code == 403
    assert send(hod,'/coordinators/revoke',dict(expectedRevision=3,reason='End appointment',mandateId=mandate)).status_code == 200
    assert send(coord,'/policies',policy_body(4)).status_code == 403
    assert state['db'].execute('SELECT revoked FROM staff_permission_assignments WHERE id=%s',(delegated.json()['id'],)).fetchone()['revoked']


@pytest.mark.parametrize('mode',['environment','department','root'])
def test_academic_defaults_and_disable_controls(academic,monkeypatch,mode):
    hod,state = academic
    if mode=='environment':
        monkeypatch.delenv('SMARTPRO_ACADEMIC_API')
    elif mode=='department':
        state['db'].execute('UPDATE academic_governance_settings SET enabled=false')
    else:
        state['db'].execute('UPDATE academic_hod_mandates SET enabled=false')
    assert send(hod,'/policies',policy_body()).status_code == (503 if mode=='environment' else 403)


@pytest.mark.parametrize('change',[{'evaluatorQuorum':0},{'aggregation':'INVENTED'}, {'evaluatorWeights':{'bad':-1}}])
def test_invalid_policy_fails_without_receipt_or_revision(academic,change):
    hod,state = academic
    body = policy_body()
    body.update(change)
    assert send(hod,'/policies',body).status_code in (400,409)
    assert state['db'].execute('SELECT revision FROM academic_governance_settings').fetchone()['revision'] == 0
    assert state['db'].execute('SELECT count(*) AS n FROM academic_command_receipts').fetchone()['n'] == 0


@pytest.mark.parametrize('strategy',['MEAN','MIN','MAX','WEIGHTED_MEAN'])
def test_supported_policy_strategies(academic,strategy):
    hod,_ = academic
    body = policy_body()
    body.update(aggregation=strategy,evaluatorWeights={FACULTY:'1.5'} if strategy=='WEIGHTED_MEAN' else {})
    assert send(hod,'/policies',body).status_code == 200


def test_role_history_and_runtime_privileges_remain_protected(academic):
    hod,state = academic
    assert send(hod,'/policies',policy_body()).status_code == 200
    with pytest.raises(psycopg.errors.CheckViolation):
        state['db'].execute("UPDATE department_role_assignments SET valid_until=clock_timestamp()-interval '1 second' WHERE user_id=%s AND role_code='HOD'",(HOD,))
    for table in ['academic_hod_mandates','academic_coordinator_mandates','academic_evaluation_policies','academic_command_receipts']:
        assert not state['db'].execute('SELECT has_table_privilege(%s,%s,%s) AS ok',('smartpro_runtime',table,'INSERT')).fetchone()['ok']


@pytest.mark.parametrize('disable',['root','appointment','department'])
def test_delegated_existing_staff_read_checks_live_chain(academic,disable):
    hod,state = academic
    coord,mandate = coordinator(hod)
    db = state['db']
    # Remove older owner-issued project-read grants so this call exercises only
    # the new delegated grant, rather than an independent valid authorization.
    db.execute("UPDATE staff_permission_assignments SET revoked=true WHERE user_id=%s AND permission='READ_PROJECTS'",(FACULTY,))
    rid = db.execute("SELECT id FROM department_role_assignments WHERE user_id=%s AND role_code='FACULTY'",(FACULTY,)).fetchone()['id']
    body = dict(expectedRevision=1,reason='Delegated view',roleAssignmentId=str(rid),permission='READ_PROJECTS',projectId=state['managed_project'],validUntil=until())
    assert send(coord,'/delegations',body).status_code == 200
    reader = APIClient()
    reader.credentials(HTTP_X_DEMO_USER='faculty-a')
    assert reader.get(url('projects',state)).status_code == 200
    if disable=='root':
        db.execute('UPDATE academic_hod_mandates SET enabled=false')
    elif disable=='appointment':
        db.execute('UPDATE academic_coordinator_mandates SET revoked=true WHERE id=%s',(mandate,))
    else:
        db.execute('UPDATE academic_governance_settings SET enabled=false')
    assert reader.get(url('projects',state)).status_code == 403


def test_invalid_delegation_does_not_hide_independent_owner_grant(academic):
    hod,state = academic
    coord,_ = coordinator(hod)
    db = state['db']
    db.execute("UPDATE staff_permission_assignments SET revoked=true WHERE user_id=%s AND permission='READ_PROJECTS'",(FACULTY,))
    role = db.execute("SELECT id FROM department_role_assignments WHERE user_id=%s AND role_code='FACULTY'",(FACULTY,)).fetchone()['id']
    body = dict(expectedRevision=1,reason='Delegated view',roleAssignmentId=str(role),permission='READ_PROJECTS',projectId=None,validUntil=until())
    assert send(coord,'/delegations',body).status_code == 200
    db.execute('''INSERT INTO staff_permission_assignments(id,user_id,department_id,role_assignment_id,required_role,permission,granted_by,grant_reason)
      VALUES('ffffffff-ffff-4fff-bfff-ffffffffffff',%s,%s,%s,'FACULTY','READ_PROJECTS',%s,'Independent owner grant')''',(FACULTY,DEPT,role,HOD))
    db.execute('UPDATE academic_hod_mandates SET enabled=false')
    reader = APIClient()
    reader.credentials(HTTP_X_DEMO_USER='faculty-a')
    assert reader.get(url('projects',state)).status_code == 200
