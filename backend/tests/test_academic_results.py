"""Real PostgreSQL published corrections, aggregation and retrospective history."""
# ruff: noqa: F811
from copy import deepcopy
from decimal import Decimal
import sys
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
import psycopg
from django.db import close_old_connections
from test_academic_api import (  # noqa: F401
    academic, staff_api, project_api, membership_api, api, active, prepared,
    send, policy_body, coordinator, B, FACULTY, HOD, DEPT, ROOT, execute_file, BASE,
)
from rest_framework.test import APIClient
from proposals.curriculum.test_contracts import new_student

REVIEW = '26000000-0000-4000-8000-000000000001'
ASSESSMENT = '29000000-0000-4000-8000-000000000001'
STUDENT = '00000000-0000-4000-8000-000000000001'


def path(suffix):
    return f'/reviews/{REVIEW}/{suffix}'


def review_post(client,action,revision=0,**body):
    return send(client,path(action),dict(expectedReviewRevision=revision,reason='Synthetic reviewed operation',**body))


def evaluator():
    client = APIClient()
    client.credentials(HTTP_X_DEMO_USER='faculty-a')
    return client


@pytest.fixture
def marking(academic):
    hod,state = academic
    assert state['db'].execute("SELECT to_regclass('public.academic_result_versions') AS installed").fetchone()['installed']
    return hod,state


def bind(hod,quorum=1,strategy='MEAN',weights=None,revision=0):
    body = policy_body(revision)
    body.update(evaluatorQuorum=quorum,aggregation=strategy,evaluatorWeights=weights or {})
    response = send(hod,'/policies',body)
    assert response.status_code == 200,response.content
    response = review_post(hod,'policy',policyId=response.json()['id'])
    assert response.status_code == 200,response.content
    return response.json()


def scores(db,assessment=ASSESSMENT,value=None,members=None):
    # Use the reviewed baseline helper for exact mode-criterion identities.
    original = db.execute('SELECT smartpro_academic_base_scores(%s) AS scores',(assessment,)).fetchone()['scores']
    if value is not None:
        for item in original:
            item['marks'] = str(value)
    if members:
        criteria = {x['criterionId'] for x in original if x['studentId'] is not None}
        existing = {x['studentId'] for x in original if x['studentId'] is not None}
        for member in members-existing:
            for criterion in criteria:
                original.append(dict(criterionId=criterion,studentId=member,marks=str(value or 1)))
        original = [x for x in original if x['studentId'] is None or x['studentId'] in members]
    return original


def legacy_snapshot(db):
    return [db.execute(f'SELECT to_jsonb(t) AS row FROM {t} t ORDER BY to_jsonb(t)::text').fetchall()
            for t in ['review_roster_members','team_criterion_scores','student_criterion_scores',
                      'assessments','result_releases','result_source_assessments','result_student_scores']]


def test_original_faculty_direct_correction_publishes_without_coordinator(marking):
    hod,state = marking
    db = state['db']
    before = legacy_snapshot(db)
    bind(hod)
    response = review_post(evaluator(),'evaluations',1,assessmentId=ASSESSMENT,scores=scores(db,value=1))
    assert response.status_code == 200,response.content
    assert response.json()['resultVersionId']
    current = db.execute('SELECT * FROM academic_result_versions').fetchone()
    assert str(current['actor_id']) == FACULTY
    assert legacy_snapshot(db) == before
    corrected = scores(db,value=2)
    response = review_post(evaluator(),'evaluations',2,assessmentId=ASSESSMENT,scores=corrected)
    assert response.status_code == 200,response.content
    assert db.execute('SELECT count(*) AS n FROM academic_result_versions').fetchone()['n'] == 2
    assert db.execute("SELECT metadata->>'correctionKind' AS kind FROM audit_events WHERE action='ACADEMIC_EVALUATE' LIMIT 1").fetchone()['kind'] == 'ORIGINAL_EVALUATOR_DIRECT'
    assert legacy_snapshot(db) == before


def test_quorum_failures_and_immutable_policy_binding(marking):
    hod,state = marking
    bind(hod,quorum=2)
    assert review_post(hod,'publish',1).status_code == 409
    assert state['db'].execute('SELECT count(*) AS n FROM academic_result_versions').fetchone()['n'] == 0
    assert review_post(hod,'policy',1,policyId=str(uuid4())).status_code == 409


@pytest.mark.parametrize('who',['student-a','student-b','tech-admin','staff-policy'])
def test_only_original_evaluator_can_revise_its_assessment(marking,who):
    hod,state = marking
    bind(hod)
    actor = APIClient()
    actor.credentials(HTTP_X_DEMO_USER=who)
    response = review_post(actor,'evaluations',1,assessmentId=ASSESSMENT,scores=scores(state['db'],value=1))
    assert response.status_code == 403


@pytest.mark.parametrize('case',['missing','duplicate','too-high','negative','foreign-student','fractional-precision'])
def test_invalid_evaluations_are_atomic(marking,case):
    hod,state = marking
    bind(hod)
    data = scores(state['db'],value=1)
    if case=='missing': data.pop()
    elif case=='duplicate': data[1]=deepcopy(data[0])
    elif case=='too-high': data[0]['marks']='999999'
    elif case=='negative': data[0]['marks']='-1'
    elif case=='fractional-precision': data[0]['marks']='1.001'
    else:
        next(x for x in data if x['studentId'] is not None)['studentId']=str(uuid4())
    assert review_post(evaluator(),'evaluations',1,assessmentId=ASSESSMENT,scores=data).status_code in (400,409)
    assert state['db'].execute('SELECT count(*) AS n FROM academic_evaluation_versions').fetchone()['n'] == 0
    assert state['db'].execute('SELECT revision FROM academic_review_bindings').fetchone()['revision'] == 1


def test_retrospective_roster_requires_coordinator_eligibility_and_reevaluation(marking):
    hod,state = marking
    db = state['db']
    coord,_ = coordinator(hod)
    bind(hod,revision=1)
    assert review_post(hod,'publish',1).status_code == 200
    before = legacy_snapshot(db)
    new_user = new_student(db)
    db.execute("""INSERT INTO department_role_assignments(user_id,department_id,role_code,valid_from)
      SELECT %s,%s,'STUDENT',roster_locked_at-interval '2 hours' FROM project_reviews WHERE id=%s""",(new_user,DEPT,REVIEW))
    member = db.execute('''INSERT INTO team_memberships(team_id,user_id,curriculum_offering_id,joined_at)
      SELECT p.team_id,%s,t.curriculum_offering_id,r.roster_locked_at-interval '1 hour'
      FROM project_reviews r JOIN projects p ON p.id=r.project_id JOIN teams t ON t.id=p.team_id WHERE r.id=%s RETURNING id''',(new_user,REVIEW)).fetchone()['id']
    members = [str(x['membership_id']) for x in db.execute('SELECT membership_id FROM review_roster_members WHERE review_id=%s',(REVIEW,))]+[str(member)]
    assert review_post(hod,'roster',2,membershipIds=members).status_code == 403
    corrected = review_post(coord,'roster',2,membershipIds=members)
    assert corrected.status_code == 200,corrected.content
    assert corrected.json()['resultVersionId'] is None
    assert review_post(coord,'publish',3).status_code == 409
    assert db.execute('SELECT count(*) AS n FROM academic_result_versions').fetchone()['n'] == 1
    current_students = {str(x['student_user_id']) for x in db.execute('SELECT student_user_id FROM academic_roster_members WHERE roster_version_id=%s',(corrected.json()['rosterVersionId'],))}
    response = review_post(evaluator(),'evaluations',3,assessmentId=ASSESSMENT,scores=scores(db,value=1,members=current_students))
    assert response.status_code == 200,response.content
    assert response.json()['resultVersionId']
    assert db.execute('SELECT count(*) AS n FROM academic_result_versions').fetchone()['n'] == 2
    assert legacy_snapshot(db) == before


def test_student_read_only_returns_own_marks_and_no_source_scores(marking):
    hod,state = marking
    bind(hod)
    assert review_post(hod,'publish',1).status_code == 200
    student = state['student']
    response = student.get(BASE+path('results'))
    assert response.status_code == 200,response.content
    assert response.json()['context'] is None
    assert set(response.json()['results'][0]['results']) == {STUDENT}
    assert response.json()['results'][0]['sources'] == []


@pytest.mark.parametrize('strategy,expected',[('MEAN','4.00'),('MIN','2.00'),('MAX','6.00'),('WEIGHTED_MEAN','5.00')])
def test_multiple_evaluator_quorum_and_decimal_aggregation(marking,monkeypatch,strategy,expected):
    hod,state = marking
    db = state['db']
    rid = str(uuid4())
    with db.transaction():
        db.execute('''INSERT INTO project_reviews(id,project_id,cycle_id,policy_version_id,review_definition_id,round_no,scheme_version_id,scheme_mode_id)
          SELECT %s,project_id,cycle_id,policy_version_id,review_definition_id,99,scheme_version_id,scheme_mode_id FROM project_reviews WHERE id=%s''',(rid,REVIEW))
        db.execute('''INSERT INTO review_roster_members(review_id,project_id,team_id,membership_id,student_user_id)
          SELECT %s,project_id,team_id,membership_id,student_user_id FROM review_roster_members WHERE review_id=%s''',(rid,REVIEW))
        db.execute("UPDATE project_reviews SET review_state='OPEN',roster_locked_at=clock_timestamp() WHERE id=%s",(rid,))
        for faculty,value in [(FACULTY,1),(B,3)]:
            assignment = db.execute('INSERT INTO evaluator_assignments(review_id,faculty_user_id) VALUES(%s,%s) RETURNING id',(rid,faculty)).fetchone()['id']
            aid = db.execute('''INSERT INTO assessments(review_id,scheme_mode_id,evaluator_assignment_id)
              SELECT id,scheme_mode_id,%s FROM project_reviews WHERE id=%s RETURNING id''',(assignment,rid)).fetchone()['id']
            db.execute('''INSERT INTO team_criterion_scores(assessment_id,scheme_mode_id,mode_criterion_id,marks)
              SELECT %s,scheme_mode_id,mode_criterion_id,%s FROM team_criterion_scores WHERE assessment_id=%s''',(aid,value,ASSESSMENT))
            db.execute('''INSERT INTO student_criterion_scores(assessment_id,review_id,scheme_mode_id,roster_member_id,mode_criterion_id,marks)
              SELECT %s,%s,s.scheme_mode_id,n.id,s.mode_criterion_id,%s FROM student_criterion_scores s
              JOIN review_roster_members old ON old.id=s.roster_member_id JOIN review_roster_members n ON n.student_user_id=old.student_user_id AND n.review_id=%s
              WHERE s.assessment_id=%s''',(aid,rid,value,rid,ASSESSMENT))
            db.execute("UPDATE assessments SET state='FINALIZED' WHERE id=%s",(aid,))
    monkeypatch.setattr(sys.modules[__name__],'REVIEW',rid)
    bind(hod,quorum=2,strategy=strategy,weights={FACULTY:'1',B:'3'} if strategy=='WEIGHTED_MEAN' else {})
    published = review_post(hod,'publish',1)
    assert published.status_code == 200,published.content
    result = db.execute('SELECT results FROM academic_result_versions WHERE id=%s',(published.json()['resultVersionId'],)).fetchone()['results']
    assert all(Decimal(x)==Decimal(expected) for x in result.values())


def test_correction_idempotency_and_concurrent_revision_conflict(marking):
    hod,state = marking
    bind(hod)
    data = scores(state['db'],value=1)
    body = dict(expectedReviewRevision=1,reason='',assessmentId=ASSESSMENT,scores=data)
    first = send(evaluator(),path('evaluations'),body,key='direct-correction')
    assert first.status_code == 200,first.content
    assert send(evaluator(),path('evaluations'),body,key='direct-correction').json() == first.json()
    assert send(evaluator(),path('evaluations'),{**body,'reason':'different'},key='direct-correction').status_code == 409
    # Build payloads before entering threads; the owner fixture connection is
    # not shared by request transactions or relied on for concurrency safety.
    values = {v:scores(state['db'],value=v) for v in [2,3]}
    def request(value):
        close_old_connections()
        try:
            return review_post(evaluator(),'evaluations',2,assessmentId=ASSESSMENT,scores=values[value]).status_code
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(request,[2,3])) == [200,409]
    assert state['db'].execute('SELECT count(*) AS n FROM academic_evaluation_versions').fetchone()['n'] == 2
    assert state['db'].execute('SELECT count(*) AS n FROM academic_result_versions').fetchone()['n'] == 2


@pytest.mark.parametrize('failure',['audit','commit'])
def test_failure_rolls_back_entire_correction_and_same_key_recovers(marking,failure):
    hod,state = marking
    bind(hod)
    db = state['db']
    db.execute("""CREATE FUNCTION test_academic_failure() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'synthetic failure'; END $$""")
    if failure=='audit':
        db.execute("CREATE TRIGGER test_academic_fail BEFORE INSERT ON audit_events FOR EACH ROW WHEN (NEW.action='ACADEMIC_EVALUATE') EXECUTE FUNCTION test_academic_failure()")
        table='audit_events'
    else:
        db.execute('CREATE CONSTRAINT TRIGGER test_academic_fail AFTER INSERT ON academic_result_versions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION test_academic_failure()')
        table='academic_result_versions'
    body = dict(expectedReviewRevision=1,reason='',assessmentId=ASSESSMENT,scores=scores(db,value=1))
    assert send(evaluator(),path('evaluations'),body,key='recover').status_code == 503
    assert db.execute('SELECT count(*) AS n FROM academic_evaluation_versions').fetchone()['n'] == 0
    assert db.execute('SELECT count(*) AS n FROM academic_result_versions').fetchone()['n'] == 0
    assert db.execute('SELECT revision FROM academic_review_bindings').fetchone()['revision'] == 1
    db.execute(f'DROP TRIGGER test_academic_fail ON {table}')
    assert send(evaluator(),path('evaluations'),body,key='recover').status_code == 200


def test_published_versions_and_evaluator_authority_history_cannot_be_rewritten(marking):
    hod,state = marking
    bind(hod)
    assert review_post(evaluator(),'evaluations',1,assessmentId=ASSESSMENT,scores=scores(state['db'],value=1)).status_code == 200
    for table in ['academic_evaluation_versions','academic_result_versions','academic_roster_versions','academic_roster_members']:
        with pytest.raises(psycopg.errors.CheckViolation):
            state['db'].execute(f'DELETE FROM {table}')
    with pytest.raises(psycopg.errors.CheckViolation):
        state['db'].execute("UPDATE department_role_assignments SET valid_until=clock_timestamp()-interval '1 second' WHERE user_id=%s AND role_code='FACULTY'",(FACULTY,))


@pytest.mark.parametrize('case',['unknown','too-late','missing-historical-role'])
def test_retrospective_correction_rejects_unproven_eligibility(marking,case):
    hod,state = marking
    coord,_ = coordinator(hod)
    bind(hod,revision=1)
    membership = str(uuid4())
    if case in ('too-late','missing-historical-role'):
        uid = new_student(state['db'])
        membership = str(state['db'].execute('''INSERT INTO team_memberships(team_id,user_id,curriculum_offering_id)
          SELECT p.team_id,%s,t.curriculum_offering_id FROM project_reviews r JOIN projects p ON p.id=r.project_id
          JOIN teams t ON t.id=p.team_id WHERE r.id=%s RETURNING id''',(uid,REVIEW)).fetchone()['id'])
        if case=='missing-historical-role':
            # Recreate the membership with historical dates; no historical
            # STUDENT role has been supplied to prove academic eligibility.
            state['db'].execute('DELETE FROM team_memberships WHERE id=%s',(membership,))
            membership = str(state['db'].execute('''INSERT INTO team_memberships(team_id,user_id,curriculum_offering_id,joined_at)
              SELECT p.team_id,%s,t.curriculum_offering_id,r.roster_locked_at-interval '1 hour' FROM project_reviews r
              JOIN projects p ON p.id=r.project_id JOIN teams t ON t.id=p.team_id WHERE r.id=%s RETURNING id''',(uid,REVIEW)).fetchone()['id'])
    assert review_post(coord,'roster',1,membershipIds=[membership]).status_code == 409
    assert state['db'].execute('SELECT count(*) AS n FROM academic_roster_versions').fetchone()['n'] == 1


def test_read_context_is_scoped_and_runtime_cannot_write_result_tables(marking):
    hod,state = marking
    bind(hod)
    assert hod.get(BASE+'/policies').status_code == 200
    assert hod.get(BASE+'/policies').json()['revision'] == 1
    response = evaluator().get(BASE+path('results'))
    assert response.status_code == 200
    assert response.json()['context']['revision'] == 1
    assert len(response.json()['context']['criteria']) == 2
    stranger = APIClient()
    stranger.credentials(HTTP_X_DEMO_USER='tech-admin')
    assert stranger.get(BASE+path('results')).status_code == 403
    assert hod.get(BASE+path('results'),{'afterVersion':'-1'}).status_code == 400
    assert not state['db'].execute("SELECT has_table_privilege('smartpro_runtime','academic_result_versions','INSERT') AS ok").fetchone()['ok']


def test_candidate_prerequisites_rollback_and_existing_capability_identity(membership_api):
    _,state = membership_api
    db = state['db']
    with pytest.raises(psycopg.Error):
        execute_file(db,ROOT/'proposals/curriculum/016_academic_governance.sql')
    db.execute('ROLLBACK')
    assert db.execute("SELECT to_regclass('academic_governance_settings') AS t").fetchone()['t'] is None
    execute_file(db,ROOT/'proposals/curriculum/014_project_registration.sql')
    execute_file(db,ROOT/'proposals/curriculum/015_staff_administration.sql')
    with pytest.raises(psycopg.Error):
        execute_file(db,ROOT/'proposals/curriculum/017_academic_result_versions.sql')
    db.execute('ROLLBACK')
    assert db.execute("SELECT to_regclass('academic_result_versions') AS t").fetchone()['t'] is None
    signature = 'public.smartpro_staff_authority(uuid,uuid,text,uuid,boolean)'
    before = db.execute('SELECT to_regprocedure(%s)::oid AS oid',(signature,)).fetchone()['oid']
    # Compile a calling PL/pgSQL function before replacement, then keep its
    # connection alive through the forward install. Existing callers retain OIDs.
    db.execute("""CREATE FUNCTION test_existing_authority_caller() RETURNS uuid LANGUAGE plpgsql AS $$
      BEGIN RETURN public.smartpro_staff_authority('00000000-0000-4000-8000-000000000003',
        '10000000-0000-4000-8000-000000000001','READ_PROJECTS'); END $$""")
    role = db.execute("SELECT id FROM department_role_assignments WHERE user_id=%s AND role_code='FACULTY'",(FACULTY,)).fetchone()['id']
    grant = db.execute("""INSERT INTO staff_permission_assignments(user_id,department_id,role_assignment_id,required_role,permission,grant_reason)
      VALUES(%s,%s,%s,'FACULTY','READ_PROJECTS','Synthetic existing owner grant') RETURNING id""",(FACULTY,DEPT,role)).fetchone()['id']
    assert db.execute('SELECT test_existing_authority_caller() AS id').fetchone()['id'] == grant
    execute_file(db,ROOT/'proposals/curriculum/016_academic_governance.sql')
    execute_file(db,ROOT/'proposals/curriculum/017_academic_result_versions.sql')
    assert db.execute('SELECT to_regprocedure(%s)::oid AS oid',(signature,)).fetchone()['oid'] == before
    assert db.execute('SELECT test_existing_authority_caller() AS id').fetchone()['id'] == grant
    assert db.execute('SELECT count(*) AS n FROM academic_governance_settings').fetchone()['n'] == 0
    assert db.execute('SELECT count(*) AS n FROM academic_hod_mandates').fetchone()['n'] == 0
