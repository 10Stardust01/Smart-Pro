import os
import threading
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from fastapi.testclient import TestClient

import app as proto
import domain
from test_workflow import headers, upload, submission, decision, forensic


def admin():
    return psycopg.connect(os.environ['DATABASE_ADMIN_URL'], autocommit=True)


def parallel(first, second):
    gate = threading.Barrier(2)
    def run(fn):
        with TestClient(proto.app) as c:
            gate.wait(timeout=5)
            return fn(c)
    with ThreadPoolExecutor(max_workers=2) as pool:
        fs = [pool.submit(run, fn) for fn in [first, second]]
        return [f.result(timeout=15) for f in fs]


def test_concurrent_conflicting_decisions(client):
    vid = upload(client)
    aid = submission(client, vid, 1).json()['attemptId']
    responses = parallel(lambda c: decision(c, aid, 2, 'APPROVE', key='race-a'),
                         lambda c: decision(c, aid, 2, 'REQUEST_CHANGES', key='race-b'))
    assert sorted(r.status_code for r in responses) == [201, 409]
    winner = next(r for r in responses if r.status_code == 201).json()
    with forensic() as db:
        assert db.execute('SELECT count(*) AS n FROM approval_decisions').fetchone()['n'] == 1
        assert db.execute('SELECT state FROM submission_cases').fetchone()['state'] == winner['status']


def test_two_distinct_authorized_faculty_conflict_under_test_single_reviewer_policy(client):
    with admin() as db:
        db.execute("INSERT INTO faculty_assignments(project_id,faculty_user_id,assignment_type) VALUES(%s,%s,'REVIEWER')", (proto.ALIASES['project-1'], proto.DEMO_USERS['faculty-other']))
    aid = submission(client, upload(client), 1).json()['attemptId']
    responses = parallel(lambda c: decision(c, aid, 2, 'APPROVE', key='faculty-a-race'),
                         lambda c: decision(c, aid, 2, 'REQUEST_CHANGES', actor='faculty-other', key='faculty-b-race'))
    assert sorted(r.status_code for r in responses) == [201, 409]
    with forensic() as db:
        assert db.execute('SELECT count(*) AS n FROM approval_decisions').fetchone()['n'] == 1


def test_concurrent_identical_idempotency_retries(client):
    vid = upload(client)
    responses = parallel(lambda c: submission(c, vid, 1, key='same-key'), lambda c: submission(c, vid, 1, key='same-key'))
    assert [r.status_code for r in responses] == [201, 201]
    assert responses[0].json() == responses[1].json()
    with forensic() as db:
        assert db.execute('SELECT count(*) AS n FROM submission_attempts').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM idempotency_records').fetchone()['n'] == 1
        assert db.execute('SELECT count(*) AS n FROM outbox_events').fetchone()['n'] == 1


def test_concurrent_same_key_different_payload(client):
    vid = upload(client)
    other = upload(client)
    responses = parallel(lambda c: submission(c, vid, 1, key='key-conflict'), lambda c: submission(c, other, 1, key='key-conflict'))
    assert sorted(r.status_code for r in responses) == [201, 409]
    assert next(r for r in responses if r.status_code == 409).json()['detail']['code'] == 'IDEMPOTENCY_KEY_REUSED'


def test_repeated_upload_completion_is_idempotent(client):
    uid = client.post('/api/v1/documents/synopsis-1/upload-sessions', headers=headers()).json()['uploadId']
    assert client.put(f'/api/v1/upload-sessions/{uid}/content', content=b'%PDF-1.4\nSynthetic', headers=headers()).status_code == 200
    responses = parallel(lambda c: c.post(f'/api/v1/upload-sessions/{uid}/complete', headers=headers()),
                         lambda c: c.post(f'/api/v1/upload-sessions/{uid}/complete', headers=headers()))
    assert [r.status_code for r in responses] == [201, 201]
    assert responses[0].json() == responses[1].json()
    with forensic() as db:
        assert db.execute('SELECT count(*) AS n FROM document_versions').fetchone()['n'] == 1


def test_parallel_uploads_allocate_distinct_version_numbers(client):
    ids = []
    for text in [b'%PDF-first', b'%PDF-second']:
        uid = client.post('/api/v1/documents/synopsis-1/upload-sessions', headers=headers()).json()['uploadId']
        assert client.put(f'/api/v1/upload-sessions/{uid}/content', content=text, headers=headers()).status_code == 200
        ids.append(uid)
    rs = parallel(lambda c: c.post(f'/api/v1/upload-sessions/{ids[0]}/complete', headers=headers()),
                  lambda c: c.post(f'/api/v1/upload-sessions/{ids[1]}/complete', headers=headers()))
    assert [r.status_code for r in rs] == [201, 201]
    assert sorted(r.json()['versionNumber'] for r in rs) == [1, 2]


def test_synopsis_runtime_read_privileges_are_narrow(client):
    vid = upload(client)
    result = submission(client, vid, 1, key='privilege-proof')
    assert result.status_code == 201, result.text
    actor = proto.DEMO_USERS['student-a']
    operation = 'SUBMIT_ATTEMPT:' + proto.ALIASES['case-1']
    with domain.connect() as db:
        stored = db.execute(
            'SELECT smartpro_synopsis_idempotency_lookup(%s,%s,%s) AS record',
            (actor, operation, 'privilege-proof'),
        ).fetchone()['record']
        assert stored['state'] == 'COMPLETE'
        assert stored['response_body']['attemptId'] == result.json()['attemptId']
        for key, op in [('another-key', operation),
                        ('privilege-proof', 'STUDENT_CREATE_TEAM'),
                        ('privilege-proof', 'REVIEW_DECISION:' + proto.ALIASES['case-1'])]:
            assert db.execute(
                'SELECT smartpro_synopsis_idempotency_lookup(%s,%s,%s) AS record',
                (actor, op, key),
            ).fetchone()['record'] is None
        for table in ['users', 'departments', 'department_role_assignments',
                      'teams', 'team_memberships', 'idempotency_records',
                      'audit_events', 'result_releases']:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute('SELECT * FROM ' + table)


def test_runtime_write_grants_are_narrow_and_column_scoped(client):
    # Exercise the actual application role, not the test database owner.
    with domain.connect() as db:
        allowed = [
            ('file_assets', 'INSERT'), ('document_versions', 'INSERT'),
            ('submission_items', 'INSERT'), ('approval_decisions', 'INSERT'),
            ('audit_events', 'INSERT'), ('outbox_events', 'INSERT'),
            ('idempotency_records', 'INSERT'), ('upload_sessions', 'INSERT'),
            ('submission_attempts', 'INSERT'),
        ]
        for table, permission in allowed:
            assert db.execute(
                'SELECT has_table_privilege(current_user,%s,%s) AS allowed',
                ('public.' + table, permission),
            ).fetchone()['allowed'], (table, permission)

        forbidden = [
            ('documents', 'INSERT'),
            ('file_assets', 'UPDATE'), ('outbox_events', 'UPDATE'),
            ('idempotency_records', 'UPDATE'),
            ('notification_deliveries', 'INSERT'),
            ('submission_cases', 'INSERT'),
            ('audit_events', 'UPDATE'), ('audit_events', 'DELETE'),
            ('audit_events', 'TRUNCATE'),
        ]
        for table, permission in forbidden:
            assert not db.execute(
                'SELECT has_table_privilege(current_user,%s,%s) AS allowed',
                ('public.' + table, permission),
            ).fetchone()['allowed'], (table, permission)

        for table, allowed_columns, forbidden_columns in [
            ('upload_sessions', ['status', 'sha256', 'size_bytes',
                                 'document_version_id', 'completed_at'],
             ['user_id', 'document_id', 'storage_key', 'created_at']),
            ('submission_cases', ['state', 'row_version'],
             ['project_id', 'submission_type']),
            ('submission_attempts', ['sealed_at', 'attempt_state'],
             ['submitted_by', 'project_id', 'case_id']),
        ]:
            for column in allowed_columns:
                assert db.execute(
                    'SELECT has_column_privilege(current_user,%s,%s,%s) AS allowed',
                    ('public.' + table, column, 'UPDATE'),
                ).fetchone()['allowed'], (table, column)
            for column in forbidden_columns:
                assert not db.execute(
                    'SELECT has_column_privilege(current_user,%s,%s,%s) AS allowed',
                    ('public.' + table, column, 'UPDATE'),
                ).fetchone()['allowed'], (table, column)

        for statement in [
            "UPDATE documents SET label=label",
            "UPDATE file_assets SET upload_status='READY'",
            "UPDATE outbox_events SET status='DEAD'",
            "UPDATE idempotency_records SET state='FAILED'",
            "INSERT INTO notification_deliveries DEFAULT VALUES",
            "DELETE FROM audit_events",
            "TRUNCATE audit_events",
        ]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute(statement)


def test_document_lock_is_authorized_without_document_edit_grant(client):
    document = proto.ALIASES['synopsis-1']
    actor = proto.DEMO_USERS['student-a']
    outsider = proto.DEMO_USERS['student-outsider']
    with domain.connect() as db:
        # Authorized student can serialize versions, but the raw lock and
        # any direct document edits remain forbidden to the runtime account.
        assert db.execute(
            'SELECT smartpro_synopsis_lock_document(%s,%s) AS locked',
            (document, actor),
        ).fetchone()['locked']
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute('SELECT id FROM documents WHERE id=%s FOR UPDATE',
                       (document,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute('UPDATE documents SET label=label WHERE id=%s',
                       (document,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute('SELECT smartpro_synopsis_lock_document(%s,%s)',
                       (document, outsider))


def test_submission_file_guard_locks_as_owner_not_as_runtime(client):
    with admin() as db:
        row = db.execute("""
            SELECT prosecdef,proconfig FROM pg_proc
            WHERE oid='public.smartpro_guard_submitted_file()'::regprocedure
        """).fetchone()
        assert row[0]
        assert 'search_path=pg_catalog, public, pg_temp' in row[1]
    # The actual submission trigger is exercised by the full synopsis
    # API tests and the immutable-evidence regression suite.


def test_verified_file_lock_is_scoped_and_blocks_raw_row_lock(client):
    version_id = upload(client)
    project_id = proto.ALIASES['project-1']
    actor = proto.DEMO_USERS['student-a']
    outsider = proto.DEMO_USERS['student-outsider']
    with domain.connect() as db:
        row = db.execute(
            'SELECT smartpro_synopsis_locked_version(%s,%s,%s) AS verified',
            (version_id, project_id, actor),
        ).fetchone()['verified']
        assert row['id'] == version_id
        assert row['document_type'] == 'SYNOPSIS'
        assert row['upload_status'] == 'READY'
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute('SELECT id FROM file_assets FOR SHARE')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute('SELECT smartpro_synopsis_locked_version(%s,%s,%s)',
                       (version_id, project_id, outsider))
        # Cross-project lookup is denied before exposing any version data:
        # this actor is not a member of the requested project.
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute(
                'SELECT smartpro_synopsis_locked_version(%s,%s,%s)',
                (version_id, proto.ALIASES['project-2'], actor),
            )


def test_write_boundary_revokes_existing_legacy_table_and_column_grants(client):
    from pathlib import Path
    from db_setup import execute_file

    with admin() as db:
        # Simulate pre-hardening runtime grants from the older provisioner.
        db.execute('GRANT INSERT, UPDATE ON documents, file_assets, '
                   'idempotency_records, outbox_events, '
                   'notification_deliveries TO smartpro_runtime')
        db.execute('GRANT UPDATE(label) ON documents TO smartpro_runtime')
        execute_file(db, Path(__file__).resolve().parents[2] /
                     'proposals/security/runtime_write_boundary.sql')

    with domain.connect() as db:
        for table, permission in [
            ('documents', 'INSERT'), ('file_assets', 'UPDATE'),
            ('idempotency_records', 'UPDATE'), ('outbox_events', 'UPDATE'),
            ('notification_deliveries', 'INSERT'),
        ]:
            assert not db.execute(
                'SELECT has_table_privilege(current_user,%s,%s) AS granted',
                ('public.' + table, permission),
            ).fetchone()['granted'], (table, permission)
        assert not db.execute(
            'SELECT has_column_privilege(current_user,%s,%s,%s) AS granted',
            ('public.documents', 'label', 'UPDATE'),
        ).fetchone()['granted']


def test_runtime_login_is_not_migration_owner(client):
    with proto.connect() as db:
        row = db.execute('SELECT session_user,current_user').fetchone()
        assert row['session_user'] != 'smartpro_owner'
        assert row['current_user'] == 'smartpro_runtime'
        assert not db.execute('SELECT rolsuper FROM pg_roles WHERE rolname=session_user').fetchone()['rolsuper']


def test_upload_completion_recovers_from_actual_deferred_commit_failure(client):
    uid = client.post('/api/v1/documents/synopsis-1/upload-sessions', headers=headers()).json()['uploadId']
    assert client.put(f'/api/v1/upload-sessions/{uid}/content', content=b'%PDF-1.4\nRetry me', headers=headers()).status_code == 200
    with admin() as db:
        db.execute("""CREATE FUNCTION test_fail_at_commit() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN RAISE EXCEPTION 'synthetic commit failure' USING ERRCODE='23514'; END $$;
          CREATE CONSTRAINT TRIGGER test_fail_commit AFTER INSERT ON document_versions
          DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION test_fail_at_commit();""")
    response = client.post(f'/api/v1/upload-sessions/{uid}/complete', headers=headers())
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'DATABASE_INTEGRITY_REJECTED'
    with forensic() as db:
        assert db.execute('SELECT count(*) AS n FROM document_versions').fetchone()['n'] == 0
        up = db.execute('SELECT status,storage_key FROM upload_sessions WHERE id=%s', (uid,)).fetchone()
        assert up['status'] == 'UPLOADED' and domain.object_path(up['storage_key']).is_file()
        assert db.execute('SELECT count(*) AS n FROM audit_events').fetchone()['n'] == 0
    with admin() as db:
        db.execute('DROP TRIGGER test_fail_commit ON document_versions')
    assert client.post(f'/api/v1/upload-sessions/{uid}/complete', headers=headers()).status_code == 201
    with forensic() as db:
        assert db.execute('SELECT count(*) AS n FROM document_versions').fetchone()['n'] == 1


def test_two_versions_of_same_logical_document_rejected(client):
    one, two = upload(client), upload(client)
    r = client.post('/api/v1/submission-cases/case-1/attempts',
                    json={'documentVersionIds': [one, two], 'expectedCaseVersion': 1}, headers=headers(key='two-versions'))
    assert r.status_code == 422 and r.json()['detail']['code'] == 'DUPLICATE_DOCUMENT'


def test_missing_or_changed_verified_object_not_submitted(client):
    vid = upload(client)
    with forensic() as db:
        key = db.execute('SELECT fa.storage_key FROM file_assets fa JOIN document_versions dv ON dv.file_asset_id=fa.id WHERE dv.id=%s', (vid,)).fetchone()['storage_key']
    domain.object_path(key).write_bytes(b'%PDF-tampered')
    r = submission(client, vid, 1)
    assert r.status_code == 422 and r.json()['detail']['code'] == 'STORED_OBJECT_UNAVAILABLE'


def test_upload_owner_and_technical_admin_not_academic_authority(client):
    uid = client.post('/api/v1/documents/synopsis-1/upload-sessions', headers=headers()).json()['uploadId']
    assert client.put(f'/api/v1/upload-sessions/{uid}/content', content=b'%PDF-x', headers=headers('student-b')).status_code == 403
    assert client.get('/api/v1/submission-cases/case-1', headers=headers('tech-admin')).status_code == 403
    vid = upload(client)
    aid = submission(client, vid, 1).json()['attemptId']
    assert decision(client, aid, 2, 'APPROVE', actor='tech-admin').status_code == 403


def test_disabled_or_departed_student_cannot_finalize(client):
    uid = client.post('/api/v1/documents/synopsis-1/upload-sessions', headers=headers()).json()['uploadId']
    assert client.put(f'/api/v1/upload-sessions/{uid}/content', content=b'%PDF-x', headers=headers()).status_code == 200
    with admin() as db:
        db.execute('UPDATE team_memberships SET left_at=clock_timestamp() WHERE user_id=%s', (proto.DEMO_USERS['student-a'],))
    assert client.post(f'/api/v1/upload-sessions/{uid}/complete', headers=headers()).status_code == 403


def test_revoked_reviewer_cannot_decide(client):
    aid = submission(client, upload(client), 1).json()['attemptId']
    with admin() as db:
        db.execute('UPDATE faculty_assignments SET valid_until=clock_timestamp() WHERE faculty_user_id=%s', (proto.DEMO_USERS['faculty-a'],))
    assert decision(client, aid, 2, 'APPROVE').status_code == 403


def test_authentication_is_opt_in_and_sql_injection_is_data(client, monkeypatch):
    monkeypatch.setenv('SMARTPRO_DEMO_AUTH', 'NO')
    assert client.get('/api/v1/submission-cases/case-1', headers=headers()).status_code == 401
    monkeypatch.setenv('SMARTPRO_DEMO_AUTH', 'YES')
    assert client.get("/api/v1/submission-cases/' OR 1=1 --", headers=headers()).status_code == 404
    aid = submission(client, upload(client), 1).json()['attemptId']
    text = "'); DROP TABLE users; --"
    r = client.post(f'/api/v1/submission-attempts/{aid}/decisions',
                    json={'decision': 'APPROVE', 'comment': text, 'expectedCaseVersion': 2}, headers=headers('faculty-a', 'injection'))
    assert r.status_code == 201
    with forensic() as db:
        assert db.execute('SELECT comment FROM approval_decisions').fetchone()['comment'] == text
        assert db.execute('SELECT count(*) AS n FROM users').fetchone()['n'] == 7


def test_schema_validation_has_consistent_error_envelope(client):
    r = client.post('/api/v1/submission-cases/case-1/attempts',
                    json={'documentVersionIds': [], 'expectedCaseVersion': 0}, headers=headers(key='bad-input'))
    assert r.status_code == 422
    assert r.json()['detail']['code'] == 'INVALID_REQUEST'
    assert len(r.json()['detail']['errors']) == 2
    assert all('input' not in e for e in r.json()['detail']['errors'])


@pytest.mark.parametrize('content', [b'', b'%PDF-' + b'x' * domain.MAX_SIZE])
def test_empty_and_oversized_upload_rejected(client, content):
    uid = client.post('/api/v1/documents/synopsis-1/upload-sessions', headers=headers()).json()['uploadId']
    assert client.put(f'/api/v1/upload-sessions/{uid}/content', content=content, headers=headers()).status_code == 422
