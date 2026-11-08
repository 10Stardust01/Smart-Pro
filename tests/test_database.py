"""Actual PostgreSQL integrity, publication and multi-connection race tests."""
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db_setup import reset_test_database
from academic_services import (publish_single_evaluator_test, claim_events,
    acknowledge_event, retry_event, record_local_notification)


def ident(prefix, n=1):
    return f'{prefix}000000-0000-4000-8000-{n:012d}'


P, R, A, SV, MODE, RELEASE = [ident(x) for x in ['15', '26', '29', '22', '24', '2a']]
MODE = ident('24', 3)
ADMIN, FACULTY = ident('00', 4), ident('00', 3)


@pytest.fixture
def db():
    reset_test_database()
    with psycopg.connect(os.environ['DATABASE_ADMIN_URL'], autocommit=True, row_factory=dict_row) as conn:
        yield conn


def reject(db, statement, params=(), states=('23514',)):
    with pytest.raises(psycopg.Error) as caught:
        with db.transaction():
            db.execute(statement, params)
            db.execute('SET CONSTRAINTS ALL IMMEDIATE')
    assert caught.value.sqlstate in states, str(caught.value)


def open_review(db, mode='COMBINED', score=False, finalize=False):
    rid, aid, eid = map(str, [uuid4(), uuid4(), uuid4()])
    mode_id = db.execute('SELECT id FROM scheme_modes WHERE scheme_version_id=%s AND mode_code=%s', (SV, mode)).fetchone()['id']
    with db.transaction():
        db.execute('''INSERT INTO project_reviews(id,project_id,cycle_id,policy_version_id,review_definition_id,round_no,scheme_version_id,scheme_mode_id)
          SELECT %s,project_id,cycle_id,policy_version_id,review_definition_id,
            (SELECT max(round_no)+1 FROM project_reviews WHERE project_id=%s),scheme_version_id,%s
          FROM project_reviews WHERE id=%s''', (rid, P, mode_id, R))
        db.execute('''INSERT INTO review_roster_members(review_id,project_id,team_id,membership_id,student_user_id)
          SELECT %s,project_id,team_id,membership_id,student_user_id FROM review_roster_members WHERE review_id=%s''', (rid, R))
        db.execute("UPDATE project_reviews SET review_state='OPEN',roster_locked_at=clock_timestamp() WHERE id=%s", (rid,))
        db.execute('INSERT INTO evaluator_assignments(id,review_id,faculty_user_id) VALUES(%s,%s,%s)', (eid, rid, FACULTY))
        db.execute('INSERT INTO assessments(id,review_id,scheme_mode_id,evaluator_assignment_id) VALUES(%s,%s,%s,%s)', (aid, rid, mode_id, eid))
        if score:
            for mc in db.execute('''SELECT mc.id,mc.score_scope,rc.maximum FROM mode_criteria mc JOIN rubric_criteria rc ON rc.id=mc.criterion_id
              WHERE mc.scheme_mode_id=%s''', (mode_id,)).fetchall():
                if mc['score_scope'] == 'TEAM':
                    db.execute('INSERT INTO team_criterion_scores(assessment_id,scheme_mode_id,mode_criterion_id,marks) VALUES(%s,%s,%s,%s)',
                               (aid, mode_id, mc['id'], mc['maximum'] / 2))
                else:
                    for m in db.execute('SELECT id FROM review_roster_members WHERE review_id=%s', (rid,)).fetchall():
                        db.execute('''INSERT INTO student_criterion_scores(assessment_id,review_id,scheme_mode_id,roster_member_id,mode_criterion_id,marks)
                          VALUES(%s,%s,%s,%s,%s,%s)''', (aid, rid, mode_id, m['id'], mc['id'], mc['maximum'] / 2))
        if finalize:
            db.execute("UPDATE assessments SET state='FINALIZED' WHERE id=%s", (aid,))
            db.execute("UPDATE project_reviews SET review_state='FINALIZED' WHERE id=%s", (rid,))
    return rid, aid, mode_id


def test_actual_postgresql_16_and_seed(db):
    assert db.execute('SHOW server_version_num').fetchone()['server_version_num'].startswith('16')
    assert db.execute('SELECT count(*) AS n FROM result_student_scores').fetchone()['n'] == 2
    assert [x['total_marks'] for x in db.execute('SELECT total_marks FROM result_student_scores ORDER BY total_marks').fetchall()] == [82, 86]


def test_wrong_academic_cycle_team(db):
    cycle = str(uuid4())
    db.execute("INSERT INTO academic_cycles(id,department_id,code,starts_on,ends_on) VALUES(%s,%s,'NEXT','2027-07-01','2028-06-30')", (cycle, ident('10')))
    reject(db, 'UPDATE projects SET cycle_id=%s WHERE id=%s', (cycle, P), ('23503',))


def test_cross_department_project_and_faculty_rejected(db):
    dept, uid = str(uuid4()), str(uuid4())
    db.execute("INSERT INTO departments(id,code,name) VALUES(%s,'OTHER','Synthetic other department')", (dept,))
    reject(db, 'UPDATE projects SET department_id=%s WHERE id=%s', (dept, P), ('23503', '23514'))
    db.execute('INSERT INTO users(id,display_name,email) VALUES(%s,\'Other faculty\',%s)', (uid, uid+'@example.invalid'))
    db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'FACULTY')", (uid, dept))
    reject(db, 'INSERT INTO evaluator_assignments(review_id,faculty_user_id) VALUES(%s,%s)', (R, uid), ('42501',))


def test_no_unapproved_global_team_or_guide_limits(db):
    team, uid = str(uuid4()), add_faculty(db)
    db.execute('INSERT INTO teams(id,department_id,cycle_id,name) SELECT %s,department_id,cycle_id,\'Second team\' FROM teams LIMIT 1', (team,))
    db.execute('INSERT INTO team_memberships(team_id,user_id) VALUES(%s,%s)', (team, ident('00')))
    db.execute("INSERT INTO faculty_assignments(project_id,faculty_user_id,assignment_type) VALUES(%s,%s,'GUIDE')", (P, uid))
    assert db.execute("SELECT count(*) AS n FROM faculty_assignments WHERE project_id=%s AND assignment_type='GUIDE'", (P,)).fetchone()['n'] == 2


def test_new_project_draft_policy_rejected(db):
    policy = str(uuid4())
    db.execute("INSERT INTO project_policy_versions(id,department_id,project_type,version_no) VALUES(%s,%s,'MAJOR',2)", (policy, ident('10')))
    reject(db, '''INSERT INTO projects(department_id,cycle_id,team_id,project_type,policy_version_id,project_code,title)
      SELECT department_id,cycle_id,team_id,project_type,%s,'DRAFT-P','Invalid' FROM projects WHERE id=%s''', (policy, P))


def test_duplicate_document_version(db):
    reject(db, '''INSERT INTO document_versions(project_id,document_id,version_no,file_asset_id,uploaded_by)
      SELECT project_id,document_id,version_no,file_asset_id,uploaded_by FROM document_versions LIMIT 1''', states=('23505',))


@pytest.mark.parametrize('operation', ['DELETE', 'UPDATE', 'INSERT'])
def test_submitted_item_set_frozen(db, operation):
    if operation == 'DELETE':
        reject(db, 'DELETE FROM submission_items')
    elif operation == 'UPDATE':
        reject(db, 'UPDATE submission_items SET document_version_id=document_version_id')
    else:
        with db.transaction():
            fid, did, vid = map(str, [uuid4(), uuid4(), uuid4()])
            db.execute("INSERT INTO file_assets(id,storage_key,sha256,size_bytes,mime_type,upload_status,uploaded_by,verified_at) VALUES(%s,%s,%s,1,'application/pdf','READY',%s,now())", (fid, fid, 'f' * 64, ident('00')))
            db.execute("INSERT INTO documents(id,project_id,document_type,label) VALUES(%s,%s,'SYNOPSIS','Extra')", (did, P))
            db.execute('INSERT INTO document_versions(id,project_id,document_id,version_no,file_asset_id,uploaded_by) VALUES(%s,%s,%s,1,%s,%s)', (vid, P, did, fid, ident('00')))
        reject(db, 'INSERT INTO submission_items VALUES(%s,%s,%s,%s)', (ident('1a'), P, did, vid))


def test_unsealed_or_empty_attempt_cannot_commit(db):
    reject(db, 'INSERT INTO submission_attempts(case_id,project_id,attempt_no,submitted_by) VALUES(%s,%s,2,%s)', (ident('19'), P, ident('00')))


@pytest.mark.parametrize('change', ["finalized_at=now()+interval '1 day'", 'row_version=row_version+1',
    "state='DRAFT'", f"evaluator_assignment_id='{ident('28')}'", 'review_id=review_id'])
def test_finalized_assessment_immutable(db, change):
    reject(db, f'UPDATE assessments SET {change} WHERE id=%s', (A,))


@pytest.mark.parametrize('table', ['team_criterion_scores', 'student_criterion_scores'])
@pytest.mark.parametrize('verb', ['UPDATE', 'DELETE'])
def test_finalized_source_scores_immutable(db, table, verb):
    query = f'UPDATE {table} SET marks=0' if verb == 'UPDATE' else f'DELETE FROM {table}'
    reject(db, query)


def test_finalized_insert_bypass_blocked(db):
    rid, aid, mode = open_review(db)
    db.execute('DELETE FROM assessments WHERE id=%s', (aid,))
    reject(db, '''INSERT INTO assessments(review_id,scheme_mode_id,evaluator_assignment_id,state)
      SELECT review_id,%s,id,'FINALIZED' FROM evaluator_assignments WHERE review_id=%s''', (mode, rid))


@pytest.mark.parametrize('change', ["version_no=99", "created_at=now()+interval '1 day'", "state='DRAFT'"])
def test_approved_scheme_immutable(db, change):
    reject(db, f'UPDATE scheme_versions SET {change} WHERE id=%s', (SV,))


def test_approved_scheme_insert_bypass_blocked(db):
    reject(db, "INSERT INTO scheme_versions(scheme_id,cycle_id,review_definition_id,version_no,state) SELECT scheme_id,cycle_id,review_definition_id,99,'APPROVED' FROM scheme_versions LIMIT 1")


@pytest.mark.parametrize('marks', [-1, 61, 'NaN'])
def test_invalid_team_marks(db, marks):
    _, aid, mode = open_review(db)
    reject(db, 'INSERT INTO team_criterion_scores(assessment_id,scheme_mode_id,mode_criterion_id,marks) VALUES(%s,%s,%s,%s)', (aid, mode, ident('25', 5), marks))


@pytest.mark.parametrize('mode', ['TEAM', 'INDIVIDUAL', 'COMBINED'])
def test_all_approved_modes_finalize_and_publish(db, mode):
    rid, aid, _ = open_review(db, mode, score=True, finalize=True)
    with db.transaction():
        release = publish_single_evaluator_test(db, rid, aid, ADMIN)
    totals = db.execute('SELECT total_marks FROM result_student_scores WHERE release_id=%s', (release,)).fetchall()
    assert len(totals) == 2 and all(x['total_marks'] == 50 for x in totals)


@pytest.mark.parametrize('mode', ['TEAM', 'INDIVIDUAL', 'COMBINED'])
def test_missing_marks_never_become_zero(db, mode):
    _, aid, _ = open_review(db, mode)
    reject(db, "UPDATE assessments SET state='FINALIZED' WHERE id=%s", (aid,))


def test_unsupported_marking_mode(db):
    _, aid, _ = open_review(db)
    reject(db, 'UPDATE assessments SET scheme_mode_id=%s WHERE id=%s', (str(uuid4()), aid))


def test_wrong_review_evaluator(db):
    rid, aid, mode = open_review(db)
    reject(db, 'INSERT INTO assessments(review_id,scheme_mode_id,evaluator_assignment_id) VALUES(%s,%s,%s)', (rid, mode, ident('28')), ('23503', '23505'))


@pytest.mark.parametrize('table,criterion', [('team_criterion_scores', 6), ('student_criterion_scores', 5)])
def test_team_student_criterion_scope(db, table, criterion):
    rid, aid, mode = open_review(db)
    if table == 'team_criterion_scores':
        reject(db, 'INSERT INTO team_criterion_scores(assessment_id,scheme_mode_id,mode_criterion_id,marks) VALUES(%s,%s,%s,1)', (aid, mode, ident('25', criterion)), ('23503',))
    else:
        member = db.execute('SELECT id FROM review_roster_members WHERE review_id=%s LIMIT 1', (rid,)).fetchone()['id']
        reject(db, 'INSERT INTO student_criterion_scores(assessment_id,review_id,scheme_mode_id,roster_member_id,mode_criterion_id,marks) VALUES(%s,%s,%s,%s,%s,1)', (aid, rid, mode, member, ident('25', criterion)), ('23503',))


def test_student_from_other_review_rejected(db):
    rid, aid, mode = open_review(db)
    reject(db, 'INSERT INTO student_criterion_scores(assessment_id,review_id,scheme_mode_id,roster_member_id,mode_criterion_id,marks) VALUES(%s,%s,%s,%s,%s,1)', (aid, rid, mode, ident('27'), ident('25', 6)), ('23503',))


def test_historical_membership_cannot_be_rewritten(db):
    reject(db, "UPDATE team_memberships SET joined_at=now()+interval '1 day' WHERE id=%s", (ident('14'),))
    reject(db, "UPDATE team_memberships SET left_at=(SELECT roster_locked_at FROM project_reviews WHERE id=%s)-interval '1 microsecond' WHERE id=%s", (R, ident('14')))
    db.execute('UPDATE team_memberships SET left_at=clock_timestamp() WHERE id=%s', (ident('14'),))
    assert db.execute('SELECT count(*) AS n FROM review_roster_members').fetchone()['n'] == 2


def test_freeze_rejects_departed_member(db):
    db.execute('UPDATE team_memberships SET left_at=clock_timestamp() WHERE id=%s', (ident('14'),))
    with pytest.raises(psycopg.errors.CheckViolation):
        open_review(db)


def test_unassigned_or_technical_faculty_denied(db):
    reject(db, 'INSERT INTO evaluator_assignments(review_id,faculty_user_id) VALUES(%s,%s)', (R, ADMIN), ('42501',))


@pytest.mark.parametrize('table', ['result_releases', 'result_student_scores', 'result_source_assessments', 'audit_events', 'approval_decisions', 'document_versions'])
def test_published_and_audit_history_immutable(db, table):
    reject(db, f'DELETE FROM {table}')


def test_release_child_inserts_rejected_after_seal(db):
    rid, aid, _ = open_review(db, score=True, finalize=True)
    reject(db, 'INSERT INTO result_source_assessments(release_id,review_id,assessment_id) VALUES(%s,%s,%s)', (RELEASE, R, aid), ('23503',))
    # Same review, different draft evaluator source: must not be appended to a sealed release.
    new_faculty = add_faculty(db)
    eid = str(uuid4())
    db.execute('INSERT INTO evaluator_assignments(id,review_id,faculty_user_id) VALUES(%s,%s,%s)', (eid, R, new_faculty))
    # A new assessment cannot ordinarily be started after release.
    reject(db, 'INSERT INTO assessments(review_id,scheme_mode_id,evaluator_assignment_id) VALUES(%s,%s,%s)', (R, MODE, eid))


def test_authorized_correction_is_new_release_version(db):
    with db.transaction():
        release2 = publish_single_evaluator_test(db, R, A, ADMIN, 'Synthetic publication reissue; source marks unchanged')
    releases = db.execute('SELECT id,release_no,supersedes_id FROM result_releases WHERE review_id=%s ORDER BY release_no', (R,)).fetchall()
    assert [x['release_no'] for x in releases] == [1, 2]
    assert str(releases[1]['supersedes_id']) == RELEASE and str(releases[1]['id']) == release2
    assert db.execute('SELECT count(*) AS n FROM result_student_scores WHERE release_id=%s', (RELEASE,)).fetchone()['n'] == 2


def test_unauthorized_publication_correction(db):
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        publish_single_evaluator_test(db, R, A, FACULTY, 'Not authorized')


def test_release_without_complete_roster_or_source_cannot_commit(db):
    reject(db, '''INSERT INTO result_releases(review_id,release_no,scheme_version_id,scheme_mode_id,calculation_snapshot,released_by,supersedes_id,correction_reason)
      VALUES(%s,2,%s,%s,%s,%s,%s,'Test incomplete')''', (R, SV, MODE, Jsonb({'method': 'single_evaluator_sum', 'exampleOnly': True}), ADMIN, RELEASE))


def test_release_total_must_reproduce_source(db):
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        rid = str(uuid4())
        db.execute('''INSERT INTO result_releases(id,review_id,release_no,scheme_version_id,scheme_mode_id,calculation_snapshot,released_by,supersedes_id,correction_reason)
          VALUES(%s,%s,2,%s,%s,%s,%s,%s,'Wrong total probe')''',
          (rid, R, SV, MODE, Jsonb({'method': 'single_evaluator_sum', 'exampleOnly': True}), ADMIN, RELEASE))
        db.execute('INSERT INTO result_source_assessments VALUES(%s,%s,%s)', (rid, R, A))
        db.execute('''INSERT INTO result_student_scores SELECT %s,review_id,roster_member_id,total_marks+1,breakdown
          FROM result_student_scores WHERE release_id=%s''', (rid, RELEASE))
        db.execute('UPDATE result_releases SET sealed_at=clock_timestamp() WHERE id=%s', (rid,))
        db.execute('SET CONSTRAINTS ALL IMMEDIATE')


def test_review_cannot_finalize_before_assessments(db):
    rid, _, _ = open_review(db)
    reject(db, "UPDATE project_reviews SET review_state='FINALIZED' WHERE id=%s", (rid,))


def test_same_team_membership_intervals_cannot_overlap(db):
    reject(db, '''INSERT INTO team_memberships(team_id,user_id,joined_at,left_at)
      SELECT team_id,user_id,joined_at,joined_at+interval '1 day' FROM team_memberships WHERE id=%s''',
      (ident('14'),), ('23P01',))


def test_submission_preserves_membership_history_without_review(db):
    # End-of-term changes may close membership, but may not rewrite its identity.
    user, team, member = map(str, [uuid4(), uuid4(), uuid4()])
    db.execute('INSERT INTO users(id,display_name,email) VALUES(%s,\'Synthetic submitter\',%s)', (user, user+'@example.invalid'))
    db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'STUDENT')", (user, ident('10')))
    db.execute('INSERT INTO team_memberships(id,team_id,user_id) VALUES(%s,%s,%s)', (member, ident('13'), user))
    with db.transaction():
        attempt = str(uuid4())
        db.execute('INSERT INTO submission_attempts(id,case_id,project_id,attempt_no,submitted_by) VALUES(%s,%s,%s,2,%s)', (attempt, ident('19'), P, user))
        db.execute('INSERT INTO submission_items SELECT %s,project_id,document_id,document_version_id FROM submission_items LIMIT 1', (attempt,))
        db.execute('UPDATE submission_attempts SET sealed_at=clock_timestamp() WHERE id=%s', (attempt,))
    reject(db, "UPDATE team_memberships SET joined_at=joined_at-interval '1 day' WHERE id=%s", (member,))


def test_runtime_cannot_edit_roles_or_truncate_evidence(db):
    db.execute('SET ROLE smartpro_runtime')
    reject(db, "UPDATE department_role_assignments SET role_code='HOD'", states=('42501',))
    reject(db, 'TRUNCATE audit_events', states=('42501',))
    reject(db, 'INSERT INTO academic_action_grants(user_id,department_id,action_code) VALUES(%s,%s,\'CORRECT_RESULTS\')', (FACULTY, ident('10')), ('42501',))


def add_faculty(db):
    uid = str(uuid4())
    db.execute('INSERT INTO users(id,display_name,email) VALUES(%s,%s,%s)', (uid, 'Synthetic faculty', f'{uid}@example.invalid'))
    db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'FACULTY')", (uid, ident('10')))
    return uid


def race(first, second):
    gate = threading.Barrier(2)
    pids = []
    def run(fn):
        with psycopg.connect(os.environ['DATABASE_ADMIN_URL'], row_factory=dict_row) as conn:
            conn.execute("SET statement_timeout='8s'")
            pid = conn.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid']
            assert conn.execute('SHOW transaction_isolation').fetchone()['transaction_isolation'] == 'read committed'
            pids.append(pid)
            gate.wait(timeout=5)
            try:
                value = fn(conn)
                conn.commit()
                return ('committed', value)
            except psycopg.Error as exc:
                conn.rollback()
                return ('rejected', exc.sqlstate)
    with ThreadPoolExecutor(max_workers=2) as pool:
        fs = [pool.submit(run, fn) for fn in [first, second]]
        results = [f.result(timeout=15) for f in fs]
    assert len(set(pids)) == 2
    print('REAL CONCURRENT BACKENDS', pids, results, flush=True)
    return results


def test_score_update_races_finalization(db):
    _, aid, _ = open_review(db, score=True)
    results = race(lambda c: c.execute("UPDATE assessments SET state='FINALIZED' WHERE id=%s", (aid,)).rowcount,
                   lambda c: c.execute('UPDATE team_criterion_scores SET marks=1 WHERE assessment_id=%s', (aid,)).rowcount)
    assert results[0][0] == 'committed'
    assert results[1][0] == 'committed' or results[1] == ('rejected', '23514')
    assert db.execute('SELECT state FROM assessments WHERE id=%s', (aid,)).fetchone()['state'] == 'FINALIZED'


def test_scheme_approval_races_incomplete_child_insert(db):
    sv, rc, mode, mc = map(str, [uuid4(), uuid4(), uuid4(), uuid4()])
    with db.transaction():
        db.execute('INSERT INTO scheme_versions(id,scheme_id,cycle_id,review_definition_id,version_no) SELECT %s,scheme_id,cycle_id,review_definition_id,2 FROM scheme_versions LIMIT 1', (sv,))
        db.execute("INSERT INTO rubric_criteria(id,scheme_version_id,code,label,maximum,sort_order) VALUES(%s,%s,'ONLY','Only criterion',100,1)", (rc, sv))
        db.execute("INSERT INTO scheme_modes(id,scheme_version_id,mode_code) VALUES(%s,%s,'TEAM')", (mode, sv))
        db.execute("INSERT INTO mode_criteria(id,scheme_version_id,scheme_mode_id,criterion_id,score_scope) VALUES(%s,%s,%s,%s,'TEAM')", (mc, sv, mode, rc))
    results = race(
        lambda c: c.execute("UPDATE scheme_versions SET state='APPROVED',approved_by=%s,approved_at=now() WHERE id=%s", (ADMIN, sv)).rowcount,
        lambda c: c.execute("INSERT INTO rubric_criteria(scheme_version_id,code,label,maximum,sort_order) VALUES(%s,'EXTRA','Unmapped',10,2)", (sv,)).rowcount)
    assert sorted(x[0] for x in results) == ['committed', 'rejected']
    assert next(x[1] for x in results if x[0] == 'rejected') == '23514'


def test_two_workers_do_not_claim_same_event(db):
    db.execute('DELETE FROM outbox_events')
    db.execute("INSERT INTO outbox_events(event_type,aggregate_id) VALUES('TEST',%s)", (str(uuid4()),))
    results = race(lambda c: [str(x['id']) for x in claim_events(c, 1)], lambda c: [str(x['id']) for x in claim_events(c, 1)])
    assert all(x[0] == 'committed' for x in results)
    assert sorted(len(x[1]) for x in results) == [0, 1]


def test_expired_claim_recovery_and_stale_owner_rejected(db):
    event = claim_events(db, 1, 30)[0]
    db.execute("UPDATE outbox_events SET claimed_until=clock_timestamp()-interval '1 second' WHERE id=%s", (event['id'],))
    replacement = claim_events(db, 10, 30)
    new = next(x for x in replacement if x['id'] == event['id'])
    assert new['claim_token'] != event['claim_token']
    assert not acknowledge_event(db, event['id'], event['claim_token'])
    assert acknowledge_event(db, event['id'], new['claim_token'])


def test_retry_backoff_dead_letter_and_local_deduplication(db):
    event = claim_events(db, 1)[0]
    assert retry_event(db, event['id'], event['claim_token'], 'Synthetic provider failure', 1)
    assert db.execute('SELECT status FROM outbox_events WHERE id=%s', (event['id'],)).fetchone()['status'] == 'DEAD'
    assert record_local_notification(db, event['id'], ident('00'), 'synthetic-once')
    assert record_local_notification(db, event['id'], ident('00'), 'synthetic-once') is None


@pytest.mark.parametrize('policy', ['institutional_approval_quorum', 'multi_evaluator_aggregation',
    'mark_correction_authority_and_amendment', 'retrospective_membership_exceptions'])
def test_pending_institutional_policy(policy):
    pytest.skip(f'Faculty policy not decided: {policy}; no institutional behavior invented')
