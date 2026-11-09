"""Disposable PostgreSQL-16-only bootstrap for course correction contracts.

Never connect to or reset Neon, live staging, or a non-test database.
"""
import json
import os
from pathlib import Path
from uuid import uuid4
import sys
import subprocess

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from db_setup import reset_test_database,create_test_login,execute_file
from department_demo import TARGET,CSE,HOD,seed


def main():
    admin=conninfo_to_dict(os.environ['DATABASE_ADMIN_URL'])
    api=conninfo_to_dict(os.environ['DATABASE_URL'])
    if os.environ.get('ALLOW_SMARTPRO_TEST_DB')!='YES' or admin.get('host') not in ('127.0.0.1','localhost') or admin.get('dbname')!='smartpro_test':
        raise RuntimeError('Only explicit loopback smartpro_test database can be used')
    if api.get('host') not in ('127.0.0.1','localhost') or api.get('dbname')!='smartpro_test':
        raise RuntimeError('Only matching loopback test application database can be used')
    reset_test_database()
    create_test_login()
    scratch='smartpro_test_demo_ci_seed_'+uuid4().hex[:10]
    with psycopg.connect(**dict(admin,dbname='postgres'),autocommit=True) as manager:
        if manager.execute('SELECT 1 FROM pg_database WHERE datname=%s',(TARGET,)).fetchone():
            raise RuntimeError('Test fixture target already exists, refusing overwrite')
        manager.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
            sql.Identifier(scratch),sql.Identifier('smartpro_test')))
    with psycopg.connect(**dict(admin,dbname=scratch),autocommit=True,row_factory=dict_row) as db:
        execute_file(db,ROOT/'proposals/curriculum/010_prepare.sql')
        with db.transaction():
            for suffix in [1,2]:
                uid=f'00000000-0000-4000-8000-{suffix:012d}'
                db.execute("""INSERT INTO student_profiles(user_id,usn,section,semester_key,department_id)
                    VALUES(%s,%s,'A','SYNTHETIC-SEM-3',%s)""",
                    (uid,'SYNTHETIC-CSE-'+str(suffix),CSE))
            kind=db.execute("""INSERT INTO curriculum_types(code,label)
                VALUES('SYNTHETIC-INITIAL','Synthetic historical offering') RETURNING id""").fetchone()['id']
            offering=db.execute("""INSERT INTO curriculum_offerings(
                curriculum_type_id,department_id,cycle_id,semester_key)
                VALUES(%s,%s,'11000000-0000-4000-8000-000000000001','SYNTHETIC-SEM-3') RETURNING id""",
                (kind,CSE)).fetchone()['id']
            db.execute("UPDATE teams SET curriculum_offering_id=%s WHERE id='13000000-0000-4000-8000-000000000001'",(offering,))
        execute_file(db,ROOT/'proposals/curriculum/010_activate.sql')
        for n in ['011_student_reads.sql','012_team_creation.sql',
                  '013_membership_commands.sql','014_project_registration.sql',
                  '015_staff_administration.sql','016_academic_governance.sql',
                  '017_academic_result_versions.sql','018_initial_evaluations.sql']:
            execute_file(db,ROOT/'proposals/curriculum'/n)
        with db.transaction():
            hod_role=db.execute("""INSERT INTO department_role_assignments(user_id,department_id,role_code)
                VALUES(%s,%s,'HOD') RETURNING id""",(HOD,CSE)).fetchone()['id']
            db.execute("""INSERT INTO academic_hod_mandates(
                department_id,role_assignment_id,user_id,enabled) VALUES(%s,%s,%s,true)""",
                (CSE,hod_role,HOD))
            db.execute("""INSERT INTO academic_governance_settings(department_id,enabled)
                VALUES(%s,true)""",(CSE,))
            db.execute("""INSERT INTO staff_department_controls(department_id,enabled)
                VALUES(%s,true)""",(CSE,))
            db.execute("""INSERT INTO academic_evaluation_policies(
                department_id,version_no,evaluator_quorum,aggregation,evaluator_weights,approved_by,reason)
                VALUES(%s,1,1,'MEAN','{}'::jsonb,%s,'Synthetic CI evaluation policy')""",(CSE,HOD))
        seed(db)
    with psycopg.connect(**dict(admin,dbname='postgres'),autocommit=True) as manager:
        manager.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
            sql.Identifier(TARGET),sql.Identifier(scratch)))
    destination=ROOT/'.test-data'/'pg-memberships.env.json'
    destination.parent.mkdir(exist_ok=True)
    config={'DATABASE_ADMIN_URL':os.environ['DATABASE_ADMIN_URL'].replace('/smartpro_test','/'+TARGET),
            'DATABASE_URL':os.environ['DATABASE_URL'].replace('/smartpro_test','/'+TARGET)}
    destination.write_text(json.dumps(config),encoding='utf-8')
    # Each contract gets its own ephemeral clone; older full-suite tests may
    # intentionally mutate role/leadership records and require PDF binaries.
    checks=(
        'test_direct_correction_does_not_reopen_stage_evidence',
        'test_release_previously_corrected_stage_evidence_on_guide_request',
        'test_guide_coordinator_same_person_can_propose_and_approve',
        'test_decline_and_stale_direct_correction_do_not_change_previous_release',
        'test_finalized_correction_requires_specific_independent_authorization',
        'test_coordinator_corrects_own_finalized_marks_before_overall_release',
    )
    failures=0
    for name in checks:
        print('Running isolated course contract:',name,flush=True)
        # New process avoids Django's cached database connection outliving its
        # per-test disposable database, unlike calling main() repeatedly.
        run=subprocess.run([sys.executable,str(ROOT/'scripts/test_course_workflow.py'),name],cwd=ROOT)
        if run.returncode!=0:failures+=1
    return 1 if failures else 0


if __name__=='__main__':
    raise SystemExit(main())
