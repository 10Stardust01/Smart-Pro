"""Executable candidate-010 contracts against isolated synthetic PostgreSQL 16."""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import threading
import time
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from db_setup import reset_test_database, create_test_login, execute_file

HERE = Path(__file__).resolve().parent
A = '00000000-0000-4000-8000-000000000001'
B = '00000000-0000-4000-8000-000000000002'
T = '13000000-0000-4000-8000-000000000001'
DEPT = '10000000-0000-4000-8000-000000000001'
CYCLE = '11000000-0000-4000-8000-000000000001'


def apply(db, filename):
    execute_file(db, HERE / filename)


def offering(db, category, cycle=CYCLE, semester='SYNTHETIC-SEM-3', department=DEPT):
    return db.execute("""
        INSERT INTO curriculum_offerings(curriculum_type_id,department_id,cycle_id,semester_key)
        VALUES(%s,%s,%s,%s) RETURNING id
    """, (category, department, cycle, semester)).fetchone()['id']


def team(db, oid, department=DEPT, cycle=CYCLE):
    return db.execute("""
        INSERT INTO teams(department_id,cycle_id,name,curriculum_offering_id)
        VALUES(%s,%s,'Synthetic team',%s) RETURNING id
    """, (department, cycle, oid)).fetchone()['id']


def join(db, tid, oid, user=A):
    return db.execute("""
        INSERT INTO team_memberships(team_id,user_id,curriculum_offering_id)
        VALUES(%s,%s,%s) RETURNING id
    """, (tid, user, oid)).fetchone()['id']


def new_student(db, department=DEPT, semester='SYNTHETIC-SEM-3'):
    uid = str(uuid4())
    db.execute(
        "INSERT INTO users(id,display_name,email) VALUES(%s,'Synthetic other student',%s)",
        (uid, uid + '@example.invalid'),
    )
    db.execute("""
        INSERT INTO student_profiles(user_id,usn,section,semester_key,department_id)
        VALUES(%s,%s,'A',%s,%s)
    """, (uid, 'SYNTHETIC-' + uid.upper(), semester, department))
    return uid


def visible_offerings(db, student, cycle):
    # Query contract only. Actual authenticated list API is not implemented here.
    return {r['id'] for r in db.execute("""
        SELECT o.id FROM curriculum_offerings o
        JOIN student_profiles s ON s.department_id=o.department_id
                               AND s.semester_key=o.semester_key
        WHERE s.user_id=%s AND o.cycle_id=%s
    """, (student, cycle)).fetchall()}


def reject(db, state, statement, params=()):
    with pytest.raises(psycopg.Error) as caught:
        with db.transaction():
            db.execute(statement, params)
    assert caught.value.sqlstate == state, str(caught.value)


@pytest.fixture
def prepared():
    reset_test_database()
    create_test_login()
    with psycopg.connect(os.environ['DATABASE_ADMIN_URL'], autocommit=True, row_factory=dict_row) as db:
        apply(db, '010_prepare.sql')
        # Synthetic identity tokens, not claims about valid VTU USN formatting.
        db.execute("""
            INSERT INTO student_profiles(user_id,usn,section,semester_key,department_id)
            VALUES(%s,'SYNTHETIC-USN-A','A','SYNTHETIC-SEM-3',%s),
                  (%s,'SYNTHETIC-USN-B','B','SYNTHETIC-SEM-3',%s)
        """, (A, DEPT, B, DEPT))
        sp = db.execute("INSERT INTO curriculum_types(code,label) VALUES('SOCIETAL','Societal Project') RETURNING id").fetchone()['id']
        idt = db.execute("INSERT INTO curriculum_types(code,label) VALUES('IDT','Interdisciplinary Design Thinking') RETURNING id").fetchone()['id']
        so, io = offering(db, sp), offering(db, idt)
        db.execute('UPDATE teams SET curriculum_offering_id=%s WHERE id=%s', (so, T))
        yield {'db': db, 'sp': sp, 'idt': idt, 'societal': so, 'idt_offering': io}


@pytest.fixture
def active(prepared):
    apply(prepared['db'], '010_activate.sql')
    return prepared


def test_same_semester_societal_and_idt_allowed(active):
    db = active['db']
    join(db, team(db, active['idt_offering']), active['idt_offering'])
    rows = db.execute('SELECT curriculum_offering_id FROM team_memberships WHERE user_id=%s AND left_at IS NULL', (A,)).fetchall()
    assert {r['curriculum_offering_id'] for r in rows} == {active['societal'], active['idt_offering']}


def test_second_team_same_offering_rejected(active):
    db = active['db']
    other = team(db, active['societal'])
    reject(db, '23P01', 'INSERT INTO team_memberships(team_id,user_id,curriculum_offering_id) VALUES(%s,%s,%s)',
           (other, A, active['societal']))


def test_duplicate_offering_cannot_bypass_rule(active):
    db = active['db']
    reject(db, '23505', """
        INSERT INTO curriculum_offerings(curriculum_type_id,department_id,cycle_id,semester_key)
        VALUES(%s,%s,%s,'SYNTHETIC-SEM-3')
    """, (active['sp'], DEPT, CYCLE))


def test_distinct_semester_and_cycle_are_separate_offerings(active):
    db = active['db']
    semester = offering(db, active['sp'], semester='SYNTHETIC-SEM-4')
    next_cycle = db.execute("""
        INSERT INTO academic_cycles(department_id,code,starts_on,ends_on)
        VALUES(%s,'SYNTHETIC-NEXT','2027-07-01','2028-06-30') RETURNING id
    """, (DEPT,)).fetchone()['id']
    following = offering(db, active['sp'], cycle=next_cycle)
    sem4_student = new_student(db, semester='SYNTHETIC-SEM-4')
    join(db, team(db, semester), semester, user=sem4_student)
    join(db, team(db, following, cycle=next_cycle), following)
    # An offering in a different semester cannot be joined by Student A.
    reject(db, '23514',
           'INSERT INTO team_memberships(team_id,user_id,curriculum_offering_id) VALUES(%s,%s,%s)',
           (team(db, semester), A, semester))


def test_department_offerings_are_independent_and_scope_checked(active):
    db = active['db']
    dept = db.execute("INSERT INTO departments(code,name) VALUES('OTHER-SYNTHETIC','Other') RETURNING id").fetchone()['id']
    cycle = db.execute("""
        INSERT INTO academic_cycles(department_id,code,starts_on,ends_on)
        VALUES(%s,'SYNTHETIC-2026','2026-07-01','2027-06-30') RETURNING id
    """, (dept,)).fetchone()['id']
    oid = offering(db, active['sp'], cycle=cycle, department=dept)
    other_team = team(db, oid, department=dept, cycle=cycle)
    dept_student = new_student(db, department=dept)
    join(db, other_team, oid, user=dept_student)
    reject(db, '23514',
           'INSERT INTO team_memberships(team_id,user_id,curriculum_offering_id) VALUES(%s,%s,%s)',
           (other_team, A, oid))
    reject(db, '23503', """
        INSERT INTO teams(department_id,cycle_id,name,curriculum_offering_id)
        VALUES(%s,%s,'Wrong department binding',%s)
    """, (DEPT, CYCLE, oid))


def test_student_offering_list_scoped_to_home_department_semester_and_cycle(active):
    db = active['db']
    other_semester = offering(db, active['sp'], semester='SYNTHETIC-SEM-4')
    dept = db.execute("INSERT INTO departments(code,name) VALUES('SECOND-DEPT','Second') RETURNING id").fetchone()['id']
    other_cycle = db.execute("""
        INSERT INTO academic_cycles(department_id,code,starts_on,ends_on)
        VALUES(%s,'SYNTHETIC-2026','2026-07-01','2027-06-30') RETURNING id
    """, (dept,)).fetchone()['id']
    other_department = offering(db, active['sp'], cycle=other_cycle, department=dept)
    future_cycle = db.execute("""
        INSERT INTO academic_cycles(department_id,code,starts_on,ends_on)
        VALUES(%s,'SYNTHETIC-LATER','2027-07-01','2028-06-30') RETURNING id
    """, (DEPT,)).fetchone()['id']
    future_offering = offering(db, active['sp'], cycle=future_cycle)
    shown = visible_offerings(db, A, CYCLE)
    assert shown == {active['societal'], active['idt_offering']}
    assert other_semester not in shown
    assert other_department not in shown
    assert future_offering not in shown
    # This is a SQL selection contract; the authenticated endpoint must still
    # derive user ID from the trusted principal and verify active cycle eligibility.


def test_historical_membership_survives_student_semester_change(active):
    db = active['db']
    db.execute('UPDATE team_memberships SET left_at=clock_timestamp() WHERE user_id=%s', (A,))
    before = db.execute(
        'SELECT id,team_id,user_id,joined_at,left_at FROM team_memberships WHERE user_id=%s',
        (A,),
    ).fetchall()
    db.execute("UPDATE student_profiles SET semester_key='SYNTHETIC-SEM-4' WHERE user_id=%s", (A,))
    after = db.execute(
        'SELECT id,team_id,user_id,joined_at,left_at FROM team_memberships WHERE user_id=%s',
        (A,),
    ).fetchall()
    assert after == before
    assert active['societal'] not in visible_offerings(db, A, CYCLE)


@pytest.mark.parametrize('field,value', [('semester_key', 'SYNTHETIC-SEM-4'),
                                       ('department_id', '10000000-0000-4000-8000-000000000002')])
def test_profile_scope_change_requires_ending_memberships(active, field, value):
    db = active['db']
    if field == 'department_id':
        db.execute("INSERT INTO departments(id,code,name) VALUES(%s,'NEW-DEPT','New department')", (value,))
    # Fixed column names from this parameterization, never request input.
    reject(db, '23514', 'UPDATE student_profiles SET '+field+'=%s WHERE user_id=%s', (value, A))


def test_ended_membership_cannot_be_reopened_after_profile_change(active):
    db = active['db']
    db.execute('UPDATE team_memberships SET left_at=clock_timestamp() WHERE user_id=%s', (A,))
    db.execute("UPDATE student_profiles SET semester_key='SYNTHETIC-SEM-4' WHERE user_id=%s", (A,))
    reject(db, '23514', 'UPDATE team_memberships SET left_at=NULL WHERE user_id=%s', (A,))


def test_activation_rejects_mismatched_unended_legacy_membership(prepared):
    db = prepared['db']
    db.execute("UPDATE student_profiles SET semester_key='SYNTHETIC-SEM-4' WHERE user_id=%s", (A,))
    with pytest.raises(psycopg.Error) as caught:
        apply(db, '010_activate.sql')
    db.rollback()
    assert caught.value.sqlstate == '23514'
    assert db.execute('SELECT count(*) AS n FROM team_memberships WHERE curriculum_offering_id IS NOT NULL').fetchone()['n'] == 0


@pytest.mark.parametrize('field', ['curriculum_offering_id', 'user_id'])
def test_membership_null_or_unregistered_student_rejected(active, field):
    db = active['db']
    tid = team(db, active['idt_offering'])
    if field == 'curriculum_offering_id':
        reject(db, '23502', 'INSERT INTO team_memberships(team_id,user_id) VALUES(%s,%s)', (tid, A))
    else:
        uid = str(uuid4())
        db.execute("INSERT INTO users(id,display_name,email) VALUES(%s,'Unregistered',%s)", (uid, uid+'@example.invalid'))
        reject(db, '23503', 'INSERT INTO team_memberships(team_id,user_id,curriculum_offering_id) VALUES(%s,%s,%s)',
               (tid, uid, active['idt_offering']))


def test_spoofed_membership_offering_rejected(active):
    db = active['db']
    reject(db, '23503', 'INSERT INTO team_memberships(team_id,user_id,curriculum_offering_id) VALUES(%s,%s,%s)',
           (team(db, active['societal']), A, active['idt_offering']))


def frozen_evidence(db):
    tables = ['review_roster_members', 'submission_attempts', 'submission_items',
              'approval_decisions', 'result_releases', 'result_student_scores']
    # The table names are fixed literals, not request input.
    return {t: db.execute('SELECT to_jsonb(x) AS row FROM ' + t + ' x ORDER BY to_jsonb(x)::text').fetchall()
            for t in tables}


def test_transfer_preserves_old_membership_and_frozen_evidence(active):
    db = active['db']
    before = frozen_evidence(db)
    old = db.execute('SELECT * FROM team_memberships WHERE team_id=%s AND user_id=%s', (T, A)).fetchone()
    target = team(db, active['societal'])
    with db.transaction():
        at = db.execute('SELECT clock_timestamp() AS at').fetchone()['at']
        db.execute('UPDATE team_memberships SET left_at=%s WHERE id=%s', (at, old['id']))
        db.execute("""
            INSERT INTO team_memberships(team_id,user_id,curriculum_offering_id,joined_at)
            VALUES(%s,%s,%s,%s)
        """, (target, A, active['societal'], at))
    assert db.execute('SELECT left_at FROM team_memberships WHERE id=%s', (old['id'],)).fetchone()['left_at'] == at
    assert before == frozen_evidence(db)


def test_usn_correction_keeps_uuid_and_memberships(active):
    db = active['db']
    before = db.execute('SELECT * FROM team_memberships WHERE user_id=%s ORDER BY id', (A,)).fetchall()
    db.execute("UPDATE student_profiles SET usn='SYNTHETIC-USN-A-CORRECTED' WHERE user_id=%s", (A,))
    assert before == db.execute('SELECT * FROM team_memberships WHERE user_id=%s ORDER BY id', (A,)).fetchall()
    reject(db, '23505', "UPDATE student_profiles SET usn='SYNTHETIC-USN-B' WHERE user_id=%s", (A,))
    reject(db, '23514', "UPDATE student_profiles SET usn=' synthetic-usn-a ' WHERE user_id=%s", (A,))


def test_scopes_cannot_be_relabelled_or_memberships_reparented(active):
    db = active['db']
    reject(db, '23514', 'UPDATE teams SET curriculum_offering_id=%s WHERE id=%s', (active['idt_offering'], T))
    reject(db, '23514', "UPDATE curriculum_offerings SET semester_key='OTHER' WHERE id=%s", (active['societal'],))
    tid = team(db, active['idt_offering'])
    mid = join(db, tid, active['idt_offering'])
    target = team(db, active['idt_offering'])
    reject(db, '23514', 'UPDATE team_memberships SET team_id=%s WHERE id=%s', (target, mid))


def test_team_without_offering_rejected(active):
    reject(active['db'], '23502', "INSERT INTO teams(department_id,cycle_id,name) VALUES(%s,%s,'No offering')", (DEPT, CYCLE))


def test_concurrent_competing_joins_only_one_commits(active):
    db = active['db']
    oid = active['idt_offering']
    teams = [team(db, oid), team(db, oid)]
    gate = threading.Barrier(2)
    def worker(tid):
        with psycopg.connect(os.environ['DATABASE_ADMIN_URL']) as conn:
            conn.execute("SET statement_timeout='8s'")
            gate.wait(timeout=5)
            try:
                join_result = conn.execute("""
                    INSERT INTO team_memberships(team_id,user_id,curriculum_offering_id)
                    VALUES(%s,%s,%s) RETURNING id
                """, (tid, A, oid)).fetchone()
                conn.commit()
                return 'committed' if join_result else 'missing'
            except psycopg.Error as exc:
                conn.rollback()
                return exc.sqlstate
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, teams))
    assert sorted(results) == ['23P01', 'committed']
    assert db.execute('SELECT count(*) AS n FROM team_memberships WHERE user_id=%s AND curriculum_offering_id=%s', (A, oid)).fetchone()['n'] == 1


def test_activation_rejects_unmapped_legacy_team(prepared):
    db = prepared['db']
    db.execute('UPDATE teams SET curriculum_offering_id=NULL WHERE id=%s', (T,))
    with pytest.raises(psycopg.Error) as caught:
        apply(db, '010_activate.sql')
    db.rollback()
    assert caught.value.sqlstate == '23514'
    assert db.execute('SELECT count(*) AS n FROM team_memberships WHERE curriculum_offering_id IS NOT NULL').fetchone()['n'] == 0


def test_activation_rejects_missing_legacy_usn(prepared):
    db = prepared['db']
    db.execute('DELETE FROM student_profiles WHERE user_id=%s', (A,))
    with pytest.raises(psycopg.Error) as caught:
        apply(db, '010_activate.sql')
    db.rollback()
    assert caught.value.sqlstate == '23514'


def test_activation_rejects_conflicting_legacy_history_without_rewriting(prepared):
    db = prepared['db']
    other = team(db, prepared['societal'])
    db.execute('INSERT INTO team_memberships(team_id,user_id) VALUES(%s,%s)', (other, A))
    before = frozen_evidence(db)
    with pytest.raises(psycopg.Error) as caught:
        apply(db, '010_activate.sql')
    db.rollback()
    assert caught.value.sqlstate == '23P01'
    assert frozen_evidence(db) == before
    assert db.execute('SELECT count(*) AS n FROM team_memberships WHERE curriculum_offering_id IS NOT NULL').fetchone()['n'] == 0


def test_runtime_has_no_new_identity_or_team_write_privileges(active):
    with psycopg.connect(os.environ['DATABASE_URL'], autocommit=True) as conn:
        conn.execute('SET ROLE smartpro_runtime')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('SELECT usn FROM student_profiles')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('SELECT * FROM curriculum_offerings')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('INSERT INTO team_memberships(team_id,user_id,curriculum_offering_id) VALUES(%s,%s,%s)',
                         (T, A, active['societal']))
        for guard in ['smartpro_membership_scope_guard', 'smartpro_student_scope_guard',
                      'smartpro_curriculum_identity_guard']:
            assert not conn.execute('SELECT has_function_privilege(current_user,%s,\'EXECUTE\')',
                                    (guard+'()',)).fetchone()[0]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE curriculum_offerings SET student_team_creation_enabled=true")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("INSERT INTO teams(department_id,cycle_id,name,curriculum_offering_id) VALUES(%s,%s,'Unauthorized',%s)",
                         (DEPT, CYCLE, active['idt_offering']))


def test_activation_preserves_frozen_academic_evidence(prepared):
    db = prepared['db']
    before = frozen_evidence(db)
    apply(db, '010_activate.sql')
    assert before == frozen_evidence(db)


def test_backdated_overlap_rejected_after_old_membership_ended(active):
    db = active['db']
    old = db.execute('SELECT * FROM team_memberships WHERE team_id=%s AND user_id=%s', (T, A)).fetchone()
    at = db.execute('SELECT clock_timestamp() AS at').fetchone()['at']
    db.execute('UPDATE team_memberships SET left_at=%s WHERE id=%s', (at, old['id']))
    target = team(db, active['societal'])
    reject(db, '23P01', """
        INSERT INTO team_memberships(team_id,user_id,curriculum_offering_id,joined_at,left_at)
        VALUES(%s,%s,%s,%s,%s)
    """, (target, A, active['societal'], old['joined_at'], at))


def test_student_details_include_name_section_semester_department_and_usn(active):
    row = active['db'].execute("""
        SELECT u.display_name AS name,s.section,s.semester_key,s.department_id,s.usn
        FROM users u JOIN student_profiles s ON s.user_id=u.id WHERE u.id=%s
    """, (A,)).fetchone()
    assert row == {'name': 'Demo Student A', 'section': 'A',
                   'semester_key': 'SYNTHETIC-SEM-3',
                   'department_id': UUID(DEPT), 'usn': 'SYNTHETIC-USN-A'}


def test_student_details_require_nonempty_fields_and_existing_department(active):
    db = active['db']
    reject(db, '23514', "UPDATE student_profiles SET section=' ' WHERE user_id=%s", (A,))
    reject(db, '23514', "UPDATE student_profiles SET semester_key='' WHERE user_id=%s", (A,))
    uid = new_student(db)
    reject(db, '23503', 'UPDATE student_profiles SET department_id=%s WHERE user_id=%s', (str(uuid4()), uid))


def test_student_can_be_recorded_with_only_the_five_confirmed_details(active):
    db = active['db']
    uid = db.execute("INSERT INTO users(display_name) VALUES('Synthetic new student') RETURNING id").fetchone()['id']
    db.execute("""
        INSERT INTO student_profiles(user_id,usn,section,semester_key,department_id)
        VALUES(%s,'SYNTHETIC-USN-NEW','C','SYNTHETIC-SEM-3',%s)
    """, (uid, DEPT))
    assert db.execute('SELECT email FROM users WHERE id=%s', (uid,)).fetchone()['email'] is None


@pytest.mark.parametrize('isolation', ['READ COMMITTED', 'REPEATABLE READ', 'SERIALIZABLE'])
@pytest.mark.parametrize('first', ['join', 'profile'])
def test_profile_and_join_cannot_commit_incompatible_scope(active, isolation, first):
    db = active['db']
    uid = new_student(db)
    oid = active['idt_offering']
    tid = team(db, oid)
    with psycopg.connect(os.environ['DATABASE_ADMIN_URL'], row_factory=dict_row) as writer, \
         psycopg.connect(os.environ['DATABASE_ADMIN_URL'], row_factory=dict_row) as stale:
        # Both transactions start before the first write commits. This also
        # exercises the stale-snapshot case that row locks alone cannot solve.
        stale.execute('SET TRANSACTION ISOLATION LEVEL '+isolation)
        stale.execute('SELECT semester_key FROM student_profiles WHERE user_id=%s', (uid,))
        if first == 'join':
            join(writer, tid, oid, uid)
        else:
            writer.execute("UPDATE student_profiles SET semester_key='SYNTHETIC-SEM-4' WHERE user_id=%s", (uid,))
        writer.commit()
        with pytest.raises(psycopg.Error) as caught:
            if first == 'join':
                stale.execute("UPDATE student_profiles SET semester_key='SYNTHETIC-SEM-4' WHERE user_id=%s", (uid,))
            else:
                join(stale, tid, oid, uid)
            stale.commit()
        stale.rollback()
        assert caught.value.sqlstate == ('23514' if isolation == 'READ COMMITTED' else '40001')


def test_profile_change_blocked_by_scheduled_end(active):
    db = active['db']
    db.execute("UPDATE team_memberships SET left_at=clock_timestamp()+interval '1 day' WHERE user_id=%s", (A,))
    reject(db, '23514', "UPDATE student_profiles SET semester_key='SYNTHETIC-SEM-4' WHERE user_id=%s", (A,))


def test_ended_legacy_scope_is_preserved_on_activation(prepared):
    db = prepared['db']
    db.execute('UPDATE team_memberships SET left_at=clock_timestamp() WHERE user_id=%s', (A,))
    db.execute("UPDATE student_profiles SET semester_key='SYNTHETIC-SEM-4' WHERE user_id=%s", (A,))
    before = db.execute('SELECT id,user_id,team_id,joined_at,left_at FROM team_memberships ORDER BY id').fetchall()
    apply(db, '010_activate.sql')
    assert before == db.execute('SELECT id,user_id,team_id,joined_at,left_at FROM team_memberships ORDER BY id').fetchall()


def test_preflight_reports_current_scope_mismatch(prepared):
    db = prepared['db']
    db.execute("UPDATE student_profiles SET semester_key='SYNTHETIC-SEM-4' WHERE user_id=%s", (A,))
    cursor = db.execute((HERE / 'preflight.sql').read_text())
    reports = [cursor.fetchall()]
    while cursor.nextset():
        reports.append(cursor.fetchall())
    assert len(reports) == 4
    assert [len(rows) for rows in reports] == [0, 0, 0, 1]
    assert reports[-1][0]['user_id'] == UUID(A)


@pytest.mark.parametrize('first', ['join', 'profile'])
def test_inflight_join_and_profile_edit_serialize(active, first):
    db = active['db']
    uid = new_student(db)
    oid = active['idt_offering']
    tid = team(db, oid)
    ready = threading.Event()
    worker_pid = []
    def action(conn, kind):
        if kind == 'join':
            join(conn, tid, oid, uid)
        else:
            conn.execute("UPDATE student_profiles SET semester_key='SYNTHETIC-SEM-4' WHERE user_id=%s", (uid,))
    def worker():
        with psycopg.connect(os.environ['DATABASE_ADMIN_URL'], row_factory=dict_row) as conn:
            conn.execute("SET statement_timeout='8s'")
            worker_pid.append(conn.info.backend_pid)
            ready.set()
            try:
                action(conn, 'profile' if first == 'join' else 'join')
                conn.commit()
                return 'committed'
            except psycopg.Error as exc:
                conn.rollback()
                return exc.sqlstate
    with psycopg.connect(os.environ['DATABASE_ADMIN_URL'], row_factory=dict_row) as writer:
        action(writer, first)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker)
            try:
                assert ready.wait(timeout=5)
                deadline = time.monotonic()+5
                while time.monotonic()<deadline:
                    row = db.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s', (worker_pid[0],)).fetchone()
                    if row and row['wait_event_type'] == 'Lock':
                        break
                    time.sleep(0.01)
                else:
                    pytest.fail('Competing operation did not wait on the profile row')
            finally:
                writer.commit()
            assert future.result(timeout=10) == '23514'
