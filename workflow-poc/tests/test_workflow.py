"""Execution tests for the PostgreSQL/FastAPI contract harness. The 13 original workflow cases
are retained; only persistence assertions/placeholders/ordering use PostgreSQL.
"""
import os
import sys
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app as proto

@pytest.fixture(autouse=True)
def reset_demo():
    proto.init_demo(reset=True)

@pytest.fixture
def client():
    return TestClient(proto.app)

def forensic():
    """Test-only DB owner connection for assertions, never an HTTP service role."""
    return psycopg.connect(os.environ['DATABASE_ADMIN_URL'], autocommit=True,
                           row_factory=dict_row)


def headers(actor='student-a',key=None):
    h={'X-Demo-User': actor}
    if key: h['Idempotency-Key']=key
    return h

def upload(client,doc='synopsis-1',actor='student-a',content=b'%PDF-1.4\nDemo synthetic PDF bytes\n%%EOF\n'):
    r=client.post(f'/api/v1/documents/{doc}/upload-sessions',headers=headers(actor))
    assert r.status_code==201,r.text
    uid=r.json()['uploadId']
    r=client.put(f'/api/v1/upload-sessions/{uid}/content',content=content,headers={**headers(actor),'Content-Type':'application/pdf'})
    assert r.status_code==200,r.text
    r=client.post(f'/api/v1/upload-sessions/{uid}/complete',headers=headers(actor))
    assert r.status_code==201,r.text
    return r.json()['documentVersionId']

def submission(client,vid,version,key='submit-1',actor='student-a'):
    return client.post('/api/v1/submission-cases/case-1/attempts',json={'documentVersionIds':[vid],'expectedCaseVersion':version},headers=headers(actor,key))

def decision(client,attempt,version,action,key='review-1',actor='faculty-a'):
    return client.post(f'/api/v1/submission-attempts/{attempt}/decisions',json={'decision':action,'comment':'Needs revision' if action=='REQUEST_CHANGES' else 'Approved','expectedCaseVersion':version},headers=headers(actor,key))

def test_complete_synopsis_revision_workflow(client):
    v1=upload(client)
    r=submission(client,v1,1); assert r.status_code==201,r.text
    first=r.json(); assert first['attemptNumber']==1 and first['caseVersion']==2
    rev=decision(client,first['attemptId'],2,'REQUEST_CHANGES'); assert rev.status_code==201,rev.text
    assert rev.json()['caseVersion']==3
    v2=upload(client,content=b'%PDF-1.4\nRevised synopsis\n%%EOF\n')
    second=submission(client,v2,3,key='submit-2'); assert second.status_code==201,second.text
    assert second.json()['attemptNumber']==2 and second.json()['caseVersion']==4
    approved=decision(client,second.json()['attemptId'],4,'APPROVE',key='review-2'); assert approved.status_code==201,approved.text
    assert approved.json()['status']=='APPROVED' and approved.json()['caseVersion']==5
    history=client.get('/api/v1/submission-cases/case-1',headers=headers()).json()
    assert history['state']=='APPROVED' and len(history['attempts'])==2
    assert [a['decision'] for a in history['attempts']]==['REQUEST_CHANGES','APPROVE']
    db=forensic()
    try:
        assert db.execute('SELECT count(*) FROM document_versions').fetchone()['count']==2
        assert db.execute('SELECT count(*) FROM approval_decisions').fetchone()['count']==2
        assert db.execute('SELECT count(*) FROM audit_events').fetchone()['count']==6
        assert db.execute('SELECT count(*) FROM outbox_events').fetchone()['count']==4
        items=db.execute('SELECT i.document_version_id FROM submission_items i JOIN submission_attempts a ON a.id=i.attempt_id ORDER BY a.attempt_no').fetchall()
        assert [str(row['document_version_id']) for row in items]==[v1,v2]
    finally: db.close()

def test_replayed_submission_returns_original_result_without_duplicates(client):
    vid=upload(client)
    r=submission(client,vid,1)
    assert r.status_code==201
    r2=submission(client,vid,1)
    assert r2.status_code==201 and r2.json()==r.json()
    db=forensic()
    try: assert db.execute('SELECT count(*) FROM submission_attempts').fetchone()['count']==1
    finally: db.close()

def test_idempotency_key_cannot_be_reused_with_new_request(client):
    vid=upload(client)
    assert submission(client,vid,1).status_code==201
    other=submission(client,vid,999)
    assert other.status_code==409 and other.json()['detail']['code']=='IDEMPOTENCY_KEY_REUSED'

def test_outsider_and_unassigned_faculty_denied(client):
    r=client.post('/api/v1/documents/synopsis-1/upload-sessions',headers=headers('student-outsider'))
    assert r.status_code==403
    vid=upload(client)
    a=submission(client,vid,1).json()['attemptId']
    bad=decision(client,a,2,'APPROVE',actor='faculty-other')
    assert bad.status_code==403
    bad=client.get('/api/v1/submission-cases/case-1',headers=headers('student-outsider'))
    assert bad.status_code==403

def test_incomplete_upload_cannot_be_finalized(client):
    uid=client.post('/api/v1/documents/synopsis-1/upload-sessions',headers=headers()).json()['uploadId']
    r=client.post(f'/api/v1/upload-sessions/{uid}/complete',headers=headers())
    assert r.status_code==409
    db=forensic()
    try: assert db.execute('SELECT count(*) FROM document_versions').fetchone()['count']==0
    finally: db.close()

def test_wrong_format_rejected(client):
    uid=client.post('/api/v1/documents/synopsis-1/upload-sessions',headers=headers()).json()['uploadId']
    r=client.put(f'/api/v1/upload-sessions/{uid}/content',content=b'not a pdf',headers=headers())
    assert r.status_code==422

def test_stale_decision_and_wrong_transition_refused(client):
    vid=upload(client)
    aid=submission(client,vid,1).json()['attemptId']
    assert decision(client,aid,1,'APPROVE').status_code==409
    good=decision(client,aid,2,'REQUEST_CHANGES'); assert good.status_code==201
    stale=decision(client,aid,2,'APPROVE',key='review-2')
    assert stale.status_code==409
    assert client.get('/api/v1/submission-cases/case-1',headers=headers()).json()['state']=='CHANGES_REQUESTED'

def test_wrong_project_document_rejected(client):
    vid=upload(client)
    # Inject a ready different-project version as if created by its authorized member.
    vid2=upload(client,doc='synopsis-2',actor='student-outsider')
    r=submission(client,vid2,1)
    assert r.status_code==422 and r.json()['detail']['code']=='INVALID_DOCUMENT_VERSION'
    assert submission(client,vid,1).status_code==201

def test_immutable_evidence_triggers(client):
    vid=upload(client)
    aid=submission(client,vid,1).json()['attemptId']
    assert decision(client,aid,2,'APPROVE').status_code==201
    db=forensic()
    try:
        with pytest.raises(Exception): db.execute('UPDATE document_versions SET version_no=3 WHERE id=%s',(vid,))
        with pytest.raises(Exception): db.execute('DELETE FROM submission_items WHERE attempt_id=%s',(aid,))
        with pytest.raises(Exception): db.execute('UPDATE approval_decisions SET comment=%s',( 'tampered',))
    finally: db.close()

def test_missing_idempotency_and_anonymous_access(client):
    vid=upload(client)
    no_key=submission(client,vid,1,key=None)
    assert no_key.status_code==400
    anonymous=client.get('/api/v1/submission-cases/case-1')
    assert anonymous.status_code==401

def test_replayed_decision_returns_identical_result(client):
    vid=upload(client)
    aid=submission(client,vid,1).json()['attemptId']
    r=decision(client,aid,2,'APPROVE')
    assert r.status_code==201
    r2=decision(client,aid,2,'APPROVE')
    assert r2.status_code==201 and r2.json()==r.json()
    db=forensic()
    try: assert db.execute('SELECT count(*) FROM approval_decisions').fetchone()['count']==1
    finally: db.close()

def test_concurrent_submissions_only_one_wins(client):
    from concurrent.futures import ThreadPoolExecutor
    vid=upload(client)
    def try_submit(key):
        with TestClient(proto.app) as c:
            return c.post('/api/v1/submission-cases/case-1/attempts',
                json={'documentVersionIds':[vid], 'expectedCaseVersion':1},
                headers=headers('student-a',key)).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes=list(pool.map(try_submit,['parallel-1','parallel-2']))
    assert sorted(codes)==[201,409]
    db=forensic()
    try: assert db.execute('SELECT count(*) FROM submission_attempts').fetchone()['count']==1
    finally: db.close()

def test_document_version_attached_to_other_project_is_rejected(client):
    vid=upload(client,doc='synopsis-2',actor='student-outsider')
    response=submission(client,vid,1)
    assert response.status_code==422
    db=forensic()
    try: assert db.execute('SELECT count(*) FROM submission_items').fetchone()['count']==0
    finally: db.close()
