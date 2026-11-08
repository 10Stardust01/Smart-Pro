"""Initial assignment/draft/finalization using real PostgreSQL and existing policy APIs."""
# ruff: noqa: F811
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from test_academic_api import (  # noqa: F401
    academic, staff_api, project_api, membership_api, api, active, prepared, send, policy_body,
    DEPT, ROOT, FACULTY, execute_file,
)
from rest_framework.test import APIClient
from django.db import close_old_connections

PROJECT='15000000-0000-4000-8000-000000000001'
SCHEME='22000000-0000-4000-8000-000000000001'
MODE='24000000-0000-4000-8000-000000000003'


@pytest.fixture
def initial(academic):
    hod,state=academic
    execute_file(state['db'],ROOT/'proposals/curriculum/018_initial_evaluations.sql')
    policy=send(hod,'/policies',policy_body())
    assert policy.status_code==200
    body=dict(projectId=PROJECT,schemeVersionId=SCHEME,schemeModeId=MODE,policyId=policy.json()['id'],facultyIds=[FACULTY],reason='Synthetic assigned review')
    return hod,state,body


def assigned(initial):
    hod,state,body=initial
    response=send(hod,'/reviews',body,key='initial-review')
    assert response.status_code==200,response.content
    review=response.json()['reviewId']
    a=state['db'].execute('SELECT id FROM assessments WHERE review_id=%s',(review,)).fetchone()['id']
    client=APIClient()
    client.credentials(HTTP_X_DEMO_USER='faculty-a')
    roster=state['db'].execute('SELECT student_user_id FROM review_roster_members WHERE review_id=%s',(review,)).fetchall()
    criteria=state['db'].execute('SELECT id,score_scope FROM mode_criteria WHERE scheme_mode_id=%s',(MODE,)).fetchall()
    scores=[]
    for c in criteria:
        for student in ([None] if c['score_scope']=='TEAM' else [str(r['student_user_id']) for r in roster]):
            scores.append(dict(criterionId=str(c['id']),studentId=student,marks='1.25'))
    return client,str(a),review,scores


def test_assign_save_finalize_publish_and_idempotent_retries(initial):
    hod,state,body=initial
    faculty,assessment,review,scores=assigned(initial)
    assert send(hod,'/reviews',body,key='initial-review').json()['reviewId']==review
    save=dict(expectedAssessmentVersion=1,reason='Criterion marks entered',scores=scores)
    response=send(faculty,f'/assessments/{assessment}/draft',save,key='save')
    assert response.status_code==200,response.content
    assert send(faculty,f'/assessments/{assessment}/draft',save,key='save').json()==response.json()
    final=dict(expectedAssessmentVersion=2,reason='Faculty finalization')
    response=send(faculty,f'/assessments/{assessment}/finalize',final,key='final')
    assert response.status_code==200,response.content
    assert send(faculty,f'/assessments/{assessment}/finalize',final,key='final').json()==response.json()
    assert send(faculty,f'/assessments/{assessment}/draft',{**save,'expectedAssessmentVersion':3}).status_code==409
    response=send(hod,f'/reviews/{review}/publish',dict(expectedReviewRevision=1,reason='Publish configured review'))
    assert response.status_code==200,response.content
    assert state['db'].execute('SELECT count(*) AS n FROM academic_result_versions WHERE review_id=%s',(review,)).fetchone()['n']==1


@pytest.mark.parametrize('who',['student-a','student-b','tech-admin','faculty-other'])
def test_assignment_and_marks_require_scoped_authority(initial,who):
    _,_,body=initial
    _,assessment,_,scores=assigned(initial)
    client=APIClient()
    client.credentials(HTTP_X_DEMO_USER=who)
    assert send(client,'/reviews',body).status_code==403
    assert send(client,f'/assessments/{assessment}/draft',dict(expectedAssessmentVersion=1,reason='Unauthorized',scores=scores)).status_code==403


@pytest.mark.parametrize('case',['missing','duplicate','maximum','negative','precision','foreign-student'])
def test_invalid_draft_is_atomic(initial,case):
    _,state,_=initial
    faculty,assessment,_,scores=assigned(initial)
    if case=='missing': scores.pop()
    elif case=='duplicate': scores[1]=deepcopy(scores[0])
    elif case=='maximum': scores[0]['marks']='9999'
    elif case=='negative': scores[0]['marks']='-1'
    elif case=='precision': scores[0]['marks']='1.001'
    else: next(s for s in scores if s['studentId'])['studentId']=str(uuid4())
    response=send(faculty,f'/assessments/{assessment}/draft',dict(expectedAssessmentVersion=1,reason='Invalid entry',scores=scores))
    assert response.status_code in (400,409),response.content
    assert state['db'].execute('SELECT row_version FROM assessments WHERE id=%s',(assessment,)).fetchone()['row_version']==1
    assert state['db'].execute('SELECT count(*) AS n FROM team_criterion_scores WHERE assessment_id=%s',(assessment,)).fetchone()['n']==0


def test_finalize_incomplete_and_stale_drafts_fail(initial):
    faculty,assessment,_,_=assigned(initial)
    assert send(faculty,f'/assessments/{assessment}/finalize',dict(expectedAssessmentVersion=1,reason='Incomplete')).status_code==409
    assert send(faculty,f'/assessments/{assessment}/finalize',dict(expectedAssessmentVersion=99,reason='Stale')).status_code==409


@pytest.mark.parametrize('field',['projectId','schemeVersionId','schemeModeId','policyId'])
def test_foreign_or_unknown_configuration_rejected(initial,field):
    hod,state,body=initial
    response=send(hod,'/reviews',{**body,field:str(uuid4())})
    assert response.status_code in (403,409),response.content
    assert state['db'].execute("SELECT count(*) AS n FROM academic_command_receipts WHERE action='CREATE_REVIEW'").fetchone()['n']==0


def test_draft_audit_failure_rolls_back_and_recovers(initial):
    _,state,_=initial
    faculty,assessment,_,scores=assigned(initial)
    db=state['db']
    db.execute("CREATE FUNCTION test_draft_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic failure'; END $$")
    db.execute("CREATE TRIGGER test_draft_fail BEFORE INSERT ON audit_events FOR EACH ROW WHEN (NEW.action='ACADEMIC_SAVE_DRAFT') EXECUTE FUNCTION test_draft_fail()")
    body=dict(expectedAssessmentVersion=1,reason='Save after recovery',scores=scores)
    assert send(faculty,f'/assessments/{assessment}/draft',body,key='recover').status_code==503
    assert db.execute('SELECT row_version FROM assessments WHERE id=%s',(assessment,)).fetchone()['row_version']==1
    db.execute('DROP TRIGGER test_draft_fail ON audit_events')
    assert send(faculty,f'/assessments/{assessment}/draft',body,key='recover').status_code==200


def test_new_initial_capability_has_no_direct_table_grants(initial):
    _,state,_=initial
    assert not state['db'].execute("SELECT has_table_privilege('smartpro_runtime','team_criterion_scores','INSERT') AS ok").fetchone()['ok']
    with pytest.raises(psycopg.errors.CheckViolation):
        state['db'].execute("UPDATE team_criterion_scores SET marks=1 WHERE assessment_id='29000000-0000-4000-8000-000000000001'")


def test_disabled_team_member_cannot_be_silently_omitted(initial):
    hod,state,body=initial
    state['db'].execute("UPDATE users SET account_status='DISABLED' WHERE id='00000000-0000-4000-8000-000000000002'")
    assert send(hod,'/reviews',body).status_code==409
    assert state['db'].execute("SELECT count(*) AS n FROM academic_command_receipts WHERE action='CREATE_REVIEW'").fetchone()['n']==0


def test_concurrent_draft_saves_do_not_overwrite(initial):
    _,assessment,_,scores=assigned(initial)
    def save(value):
        close_old_connections()
        try:
            client=APIClient(); client.credentials(HTTP_X_DEMO_USER='faculty-a')
            data=[{**s,'marks':value} for s in scores]
            return send(client,f'/assessments/{assessment}/draft',dict(expectedAssessmentVersion=1,reason='Concurrent save',scores=data)).status_code
        finally: close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save,['1','2']))==[200,409]


def test_concurrent_same_key_assignments_create_one_review(initial):
    _,state,body=initial
    def assign(_):
        close_old_connections()
        try:
            client=APIClient(); client.credentials(HTTP_X_DEMO_USER='staff-policy')
            response=send(client,'/reviews',body,key='same-assignment')
            assert response.status_code==200,response.content
            return response.json()
        finally: close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(assign,[1,2]))
    assert results[0]==results[1]
    assert state['db'].execute("SELECT count(*) AS n FROM academic_command_receipts WHERE action='CREATE_REVIEW'").fetchone()['n']==1
