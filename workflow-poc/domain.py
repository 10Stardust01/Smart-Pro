"""Framework-independent PostgreSQL synopsis operations. Synthetic policy only."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

MAX_SIZE = 2 * 1024 * 1024


class DomainError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


def fail(status, code, message):
    raise DomainError(status, code, message)


def connect():
    db = psycopg.connect(os.environ['DATABASE_URL'], autocommit=True, row_factory=dict_row)
    role = os.getenv('SMARTPRO_DB_ROLE')
    if role:
        if role != 'smartpro_runtime':
            db.close()
            raise RuntimeError('Unexpected application role')
        db.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(role)))
    db.execute("SET statement_timeout='10s'")
    db.execute("SET lock_timeout='5s'")
    return db


@contextmanager
def transaction():
    with connect() as db, db.transaction():
        yield db


def object_path(key):
    root = Path(os.environ['SMARTPRO_DATA_DIR']).resolve() / 'files'
    root.mkdir(parents=True, exist_ok=True)
    path = root / key
    if path.resolve().parent != root or path.is_symlink():
        fail(422, 'INVALID_STORAGE_IDENTITY', 'Invalid local object identity')
    return path


def new_id():
    return str(uuid.uuid4())


def has_permission(db, project, actor, permission):
    return db.execute('SELECT smartpro_project_permission(%s,%s,%s) AS allowed',
                      (project, actor, permission)).fetchone()['allowed']


def require_project(db, project, actor, permission):
    if not db.execute('SELECT id FROM projects WHERE id=%s', (project,)).fetchone():
        fail(404, 'PROJECT_NOT_FOUND', 'Project not found')
    if not has_permission(db, project, actor, permission):
        fail(403, 'PROJECT_ACCESS_DENIED', 'User lacks current scoped authority')


def audit(db, actor, project, action, target, kind='SUBMISSION_ATTEMPT'):
    db.execute('''INSERT INTO audit_events(actor_id,project_id,action,target_type,target_id)
                  VALUES(%s,%s,%s,%s,%s)''', (actor, project, action, kind, target))


def event(db, kind, case, attempt):
    db.execute('INSERT INTO outbox_events(event_type,aggregate_id,payload) VALUES(%s,%s,%s)',
               (kind, case, Jsonb({'caseId': str(case), 'attemptId': str(attempt)})))


def idempotent(db, actor, operation, key, body):
    if not key or not key.strip() or len(key) > 128:
        fail(400, 'IDEMPOTENCY_REQUIRED', 'Provide an Idempotency-Key of up to 128 characters')
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    # Authorized service lookup returns a single scoped response; runtime
    # cannot scan other students' or unrelated operations' idempotency rows.
    old = db.execute(
        'SELECT public.smartpro_synopsis_idempotency_lookup(%s,%s,%s) AS record',
        (actor, operation, key),
    ).fetchone()['record']
    if old:
        if old['request_sha256'].strip() != digest:
            fail(409, 'IDEMPOTENCY_KEY_REUSED', 'Key already used for another payload')
        if old['state'] != 'COMPLETE':
            fail(409, 'REQUEST_IN_PROGRESS', 'Retry after the original transaction completes')
        return old['response_body'], digest
    return None, digest


def save_idempotency(db, actor, op, key, digest, result):
    db.execute('''INSERT INTO idempotency_records(actor_id,operation,key,request_sha256,state,response_status,response_body)
                  VALUES(%s,%s,%s,%s,'COMPLETE',201,%s)''', (actor, op, key, digest, Jsonb(result)))


def start_upload(document, actor):
    with transaction() as db:
        doc = db.execute('SELECT * FROM documents WHERE id=%s', (document,)).fetchone()
        if not doc:
            fail(404, 'DOCUMENT_NOT_FOUND', 'Unknown document')
        require_project(db, doc['project_id'], actor, 'student')
        uid = new_id()
        db.execute('INSERT INTO upload_sessions(id,document_id,user_id,storage_key) VALUES(%s,%s,%s,%s)',
                   (uid, document, actor, f'{uid}.pdf'))
    return {'uploadId': uid, 'maxBytes': MAX_SIZE, 'status': 'PENDING'}


def get_upload(db, upload, actor, lock=False):
    up = db.execute('SELECT * FROM upload_sessions WHERE id=%s' + (' FOR UPDATE' if lock else ''), (upload,)).fetchone()
    if not up:
        fail(404, 'UPLOAD_NOT_FOUND', 'Unknown upload session')
    if str(up['user_id']) != str(actor):
        fail(403, 'UPLOAD_OWNER_REQUIRED', 'Upload belongs to another user')
    doc = db.execute('SELECT * FROM documents WHERE id=%s', (up['document_id'],)).fetchone()
    require_project(db, doc['project_id'], actor, 'student')
    return up, doc


def verify_local_pdf(content):
    """Test-only verifier interface: not a PDF parser or malware scanner."""
    if not content or len(content) > MAX_SIZE:
        fail(422, 'BAD_FILE_SIZE', 'Empty or oversized test file')
    if not content.startswith(b'%PDF-'):
        fail(422, 'BAD_FILE_FORMAT', 'Local verifier requires a PDF signature')
    return hashlib.sha256(content).hexdigest(), len(content)


def put_upload(upload, actor, content):
    digest, size = verify_local_pdf(content)
    with transaction() as db:
        up, _ = get_upload(db, upload, actor, lock=True)
        if up['status'] != 'PENDING':
            fail(409, 'UPLOAD_NOT_PENDING', 'Upload already consumed')
        path = object_path(up['storage_key'])
        staging = path.with_suffix('.staging')
        staging.write_bytes(content)
        staging.replace(path)
        # A failed commit leaves a deterministic orphan; retry PENDING can replace it.
        db.execute("UPDATE upload_sessions SET status='UPLOADED',sha256=%s,size_bytes=%s WHERE id=%s",
                   (digest, size, upload))
    return {'status': 'UPLOADED', 'bytes': size}


def completed_upload(db, up):
    row = db.execute('SELECT dv.id,dv.version_no,fa.sha256 FROM document_versions dv JOIN file_assets fa ON fa.id=dv.file_asset_id WHERE dv.id=%s',
                     (up['document_version_id'],)).fetchone()
    return {'documentVersionId': str(row['id']), 'versionNumber': row['version_no'], 'sha256': row['sha256'].strip(), 'status': 'READY'}


def finish_upload(upload, actor):
    # External verification occurs before the short DB completion transaction.
    with transaction() as db:
        up, _ = get_upload(db, upload, actor)
        if up['status'] == 'COMPLETE':
            return completed_upload(db, up)
        if up['status'] != 'UPLOADED':
            fail(409, 'UPLOAD_NOT_READY', 'Upload bytes not committed')
    path = object_path(up['storage_key'])
    if not path.is_file():
        fail(422, 'UPLOAD_MISSING', 'Stored bytes are missing')
    digest, size = verify_local_pdf(path.read_bytes())
    if digest != up['sha256'].strip() or size != up['size_bytes']:
        fail(422, 'UPLOAD_CHANGED', 'Stored bytes differ from uploaded identity')
    with transaction() as db:
        up, doc = get_upload(db, upload, actor, lock=True)
        if up['status'] == 'COMPLETE':
            return completed_upload(db, up)
        if up['status'] != 'UPLOADED':
            fail(409, 'UPLOAD_NOT_READY', 'Upload state changed during verification')
        # The definer lock command checks project membership and holds the
        # document row until commit without granting direct document UPDATE.
        locked = db.execute(
            'SELECT public.smartpro_synopsis_lock_document(%s,%s) AS locked',
            (doc['id'], actor),
        ).fetchone()['locked']
        if not locked:
            fail(404, 'DOCUMENT_NOT_FOUND', 'Document no longer exists')
        version = db.execute('SELECT coalesce(max(version_no),0)+1 AS n FROM document_versions WHERE document_id=%s', (doc['id'],)).fetchone()['n']
        fid, vid = new_id(), new_id()
        db.execute('''INSERT INTO file_assets(id,storage_key,sha256,size_bytes,mime_type,upload_status,uploaded_by,verified_at)
          VALUES(%s,%s,%s,%s,'application/pdf','READY',%s,clock_timestamp())''', (fid, up['storage_key'], digest, size, actor))
        db.execute('''INSERT INTO document_versions(id,project_id,document_id,version_no,file_asset_id,uploaded_by)
          VALUES(%s,%s,%s,%s,%s,%s)''', (vid, doc['project_id'], doc['id'], version, fid, actor))
        db.execute("UPDATE upload_sessions SET status='COMPLETE',document_version_id=%s,completed_at=clock_timestamp() WHERE id=%s", (vid, upload))
        audit(db, actor, doc['project_id'], 'DOCUMENT_VERSION_COMPLETED', vid, 'DOCUMENT_VERSION')
        # Bytes stay at the same key even if this transaction or its COMMIT fails.
    return {'documentVersionId': vid, 'versionNumber': version, 'sha256': digest, 'status': 'READY'}


def submit_attempt(case_id, actor, body, key):
    with transaction() as db:
        case = db.execute('SELECT * FROM submission_cases WHERE id=%s FOR UPDATE', (case_id,)).fetchone()
        if not case:
            fail(404, 'CASE_NOT_FOUND', 'Unknown case')
        require_project(db, case['project_id'], actor, 'student')
        op = f'SUBMIT_ATTEMPT:{case_id}'
        old, digest = idempotent(db, actor, op, key, body)
        if old is not None:
            return old
        if case['row_version'] != body['expectedCaseVersion']:
            fail(409, 'STALE_CASE_VERSION', 'Case changed; refresh it')
        if case['state'] not in ('DRAFT', 'CHANGES_REQUESTED'):
            fail(409, 'CASE_NOT_SUBMITTABLE', 'Case is not accepting attempts')
        if case['submission_type'] != 'SYNOPSIS':
            fail(422, 'INVALID_CASE_TYPE', 'This contract implements synopsis only')
        vids = body['documentVersionIds']
        if len(set(vids)) != len(vids):
            fail(422, 'DUPLICATE_VERSION', 'Version IDs must be unique')
        docs = []
        # File locks must be acquired in the same order for overlapping cases.
        for vid in sorted(vids, key=lambda value: uuid.UUID(str(value))):
            row = db.execute(
                'SELECT public.smartpro_synopsis_locked_version(%s,%s,%s) AS verified',
                (vid, case['project_id'], actor),
            ).fetchone()['verified']
            if not row or row['upload_status'] != 'READY':
                fail(422, 'INVALID_DOCUMENT_VERSION', 'Version is not ready or belongs to another project')
            if row['document_type'] != 'SYNOPSIS':
                fail(422, 'INVALID_DOCUMENT_TYPE', 'Synopsis requires synopsis files')
            path = object_path(row['storage_key'])
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256'].strip():
                fail(422, 'STORED_OBJECT_UNAVAILABLE', 'Verified bytes are missing or changed')
            docs.append(row)
        if len({row['document_id'] for row in docs}) != len(docs):
            fail(422, 'DUPLICATE_DOCUMENT', 'Submit one version per logical document')
        aid = new_id()
        num = db.execute('SELECT coalesce(max(attempt_no),0)+1 AS n FROM submission_attempts WHERE case_id=%s', (case_id,)).fetchone()['n']
        db.execute('''INSERT INTO submission_attempts(id,case_id,project_id,attempt_no,submitted_by)
          VALUES(%s,%s,%s,%s,%s)''', (aid, case_id, case['project_id'], num, actor))
        for row in docs:
            db.execute('''INSERT INTO submission_items(attempt_id,project_id,document_id,document_version_id)
              VALUES(%s,%s,%s,%s)''', (aid, case['project_id'], row['document_id'], row['id']))
        db.execute('UPDATE submission_attempts SET sealed_at=clock_timestamp() WHERE id=%s', (aid,))
        db.execute("UPDATE submission_cases SET state='AWAITING_REVIEW',row_version=row_version+1 WHERE id=%s", (case_id,))
        audit(db, actor, case['project_id'], 'SUBMISSION_ATTEMPT_CREATED', aid)
        event(db, 'SUBMISSION_RECEIVED', case_id, aid)
        result = {'caseId': str(case_id), 'attemptId': aid, 'attemptNumber': num, 'caseVersion': case['row_version'] + 1, 'status': 'AWAITING_REVIEW'}
        save_idempotency(db, actor, op, key, digest, result)
    return result


def decide(attempt_id, actor, body, key):
    with transaction() as db:
        attempt = db.execute('SELECT * FROM submission_attempts WHERE id=%s', (attempt_id,)).fetchone()
        if not attempt:
            fail(404, 'ATTEMPT_NOT_FOUND', 'Unknown attempt')
        case = db.execute('SELECT * FROM submission_cases WHERE id=%s FOR UPDATE', (attempt['case_id'],)).fetchone()
        attempt = db.execute('SELECT * FROM submission_attempts WHERE id=%s FOR UPDATE', (attempt_id,)).fetchone()
        require_project(db, case['project_id'], actor, 'reviewer')
        op = f'REVIEW_DECISION:{attempt_id}'
        old, digest = idempotent(db, actor, op, key, body)
        if old is not None:
            return old
        if case['row_version'] != body['expectedCaseVersion']:
            fail(409, 'STALE_CASE_VERSION', 'Case changed; refresh it')
        if case['state'] != 'AWAITING_REVIEW' or attempt['attempt_state'] != 'SUBMITTED':
            fail(409, 'INVALID_REVIEW_STATE', 'Attempt is not pending review')
        did = new_id()
        state = 'APPROVED' if body['decision'] == 'APPROVE' else 'CHANGES_REQUESTED'
        db.execute('''INSERT INTO approval_decisions(id,attempt_id,project_id,reviewer_user_id,decision,comment)
          VALUES(%s,%s,%s,%s,%s,%s)''', (did, attempt_id, case['project_id'], actor, body['decision'], body['comment']))
        db.execute('UPDATE submission_attempts SET attempt_state=%s WHERE id=%s', (state, attempt_id))
        db.execute('UPDATE submission_cases SET state=%s,row_version=row_version+1 WHERE id=%s', (state, case['id']))
        audit(db, actor, case['project_id'], f'SUBMISSION_{state}', attempt_id)
        event(db, f'SUBMISSION_{state}', case['id'], attempt_id)
        result = {'decisionId': did, 'caseId': str(case['id']), 'attemptId': str(attempt_id), 'status': state, 'caseVersion': case['row_version'] + 1}
        save_idempotency(db, actor, op, key, digest, result)
    return result


def read_case(case_id, actor):
    with transaction() as db:
        case = db.execute('SELECT * FROM submission_cases WHERE id=%s FOR SHARE', (case_id,)).fetchone()
        if not case:
            fail(404, 'CASE_NOT_FOUND', 'Unknown case')
        if not (has_permission(db, case['project_id'], actor, 'student') or has_permission(db, case['project_id'], actor, 'reviewer')):
            fail(403, 'CASE_ACCESS_DENIED', 'User cannot view this case')
        rows = db.execute('''SELECT a.id,a.attempt_no,a.attempt_state AS state,a.submitted_by,d.decision,d.comment
          FROM submission_attempts a LEFT JOIN approval_decisions d ON d.attempt_id=a.id WHERE a.case_id=%s ORDER BY a.attempt_no''', (case_id,)).fetchall()
        for row in rows:
            row['documentVersionIds'] = [str(x['document_version_id']) for x in db.execute(
                'SELECT document_version_id FROM submission_items WHERE attempt_id=%s ORDER BY document_id', (row['id'],)).fetchall()]
        return {'caseId': str(case_id), 'state': case['state'], 'caseVersion': case['row_version'], 'attempts': rows}
