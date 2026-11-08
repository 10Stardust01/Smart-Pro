"""Local-only persistent demonstration. Clone reviewed synthetic data; never migrate production."""
import hashlib
import json
from pathlib import Path
import sys

from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TARGET='smartpro_test_demo_department'
DEVELOPMENT='smartpro_dev'
CSE='10000000-0000-4000-8000-000000000001'
CYCLE='11000000-0000-4000-8000-000000000001'
HOD='00000000-0000-4000-8000-000000000004'
FACULTY='00000000-0000-4000-8000-000000000003'
COORD='00000000-0000-4000-8000-000000000008'


def settings(path):
    env=json.loads(path.read_text())
    owner=conninfo_to_dict(env['DATABASE_ADMIN_URL'])
    app=conninfo_to_dict(env['DATABASE_URL'])
    if owner.get('host') not in ('127.0.0.1','localhost') or not owner.get('dbname','').startswith('smartpro_test'):
        raise RuntimeError('Loopback synthetic PostgreSQL configuration required')
    return env,owner,app


def install_documents(db, *, new_development=False):
    """Synthetic setup only. Refresh this unrolled candidate's functions, retain data."""
    from db_setup import execute_file
    if not db.execute("SELECT (current_database() LIKE 'smartpro_test_demo_%%' AND current_database()<>'smartpro_test_demo_department') OR (%s AND current_database()=%s) AS allowed",(new_development,DEVELOPMENT)).fetchone()['allowed']:
        raise RuntimeError('Document demo setup requires an isolated demo database')
    if not db.execute("SELECT to_regclass('public.offering_operational_instructions') AS t").fetchone()['t']:
        with db.transaction():
            for part in ['workflow','reads','guards']:
                source=(ROOT/f'proposals/curriculum/019_document_{part}.sql').read_text()
                db.execute(source.replace('BEGIN;','',1).strip().removesuffix('COMMIT;'))
        print('PASS SQL atomic document candidate 019',flush=True)
    else:
        for part,marker in [('workflow','CREATE FUNCTION public.smartpro_document_scope'),('reads','CREATE FUNCTION public.smartpro_document_workspace')]:
            source=(ROOT/f'proposals/curriculum/019_document_{part}.sql').read_text()
            source=source[source.index(marker):].replace('CREATE FUNCTION','CREATE OR REPLACE FUNCTION').removesuffix('COMMIT;\n')
            db.execute(source)
        if not db.execute("SELECT to_regprocedure('public.smartpro_managed_document_write_guard()') AS f").fetchone()['f']:
            execute_file(db,ROOT/'proposals/curriculum/019_document_guards.sql')
    if not db.execute("SELECT to_regclass('public.department_setup_requests') AS t").fetchone()['t']:
        execute_file(db,ROOT/'proposals/curriculum/020_department_setup.sql')
    else:
        source=(ROOT/'proposals/curriculum/020_department_setup.sql').read_text(encoding='utf-8')
        source=source[source.index('CREATE FUNCTION public.smartpro_department_setup'):].replace('CREATE FUNCTION','CREATE OR REPLACE FUNCTION').strip().removesuffix('COMMIT;')
        db.execute(source)
    execute_file(db,ROOT/'proposals/curriculum/021_application_workspace.sql')
    execute_file(db,ROOT/'proposals/curriculum/022_proposal_context.sql')
    execute_file(db,ROOT/'proposals/curriculum/023_authorized_setup.sql')
    execute_file(db,ROOT/'proposals/curriculum/024_guide_schedule.sql')
    execute_file(db,ROOT/'proposals/curriculum/025_optional_notes.sql')
    execute_file(db,ROOT/'proposals/curriculum/026_external_instructions.sql')
    execute_file(db,ROOT/'proposals/curriculum/027_proposal_details.sql')
    execute_file(db,ROOT/'proposals/curriculum/028_document_responsibilities.sql')
    execute_file(db,ROOT/'proposals/curriculum/029_offering_lifecycle.sql')
    execute_file(db,ROOT/'proposals/curriculum/030_configuration_lifecycle.sql')
    execute_file(db,ROOT/'proposals/curriculum/031_assignment_lifecycle.sql')
    execute_file(db,ROOT/'proposals/curriculum/032_configurable_documents.sql')
    execute_file(db,ROOT/'proposals/curriculum/033_explicit_submission_requirements.sql')
    execute_file(db,ROOT/'proposals/curriculum/034_project_draft_revisions.sql')
    execute_file(db,ROOT/'proposals/curriculum/035_evaluator_lifecycle.sql')
    execute_file(db,ROOT/'proposals/curriculum/036_guide_synopsis_responsibility.sql')


def pending_admission(db,dept):
    uid='00000000-0000-4000-8000-000000000011'
    db.execute("INSERT INTO users(id,display_name,email) VALUES(%s,'Demo Incoming Student','demo-11@example.invalid') ON CONFLICT(id) DO NOTHING",(uid,))
    db.execute("""INSERT INTO department_role_assignments(user_id,department_id,role_code)
      SELECT %s,%s,'STUDENT' WHERE NOT EXISTS(SELECT FROM department_role_assignments WHERE user_id=%s AND department_id=%s AND role_code='STUDENT')""",(uid,dept,uid,dept))
    db.execute("INSERT INTO demo_admissions VALUES(%s,%s,'SYNTHETIC-ECE-INCOMING','A','SYNTHETIC-SEM-3') ON CONFLICT(user_id) DO NOTHING",(uid,dept))


def seed(db):
    if not db.execute("SELECT current_database() LIKE 'smartpro_test_demo_%' AND current_database()<>'smartpro_test_demo_department' AS allowed").fetchone()['allowed']:
        raise RuntimeError('Legacy fixtures may only be used in isolated test databases')
    uid='00000000-0000-4000-8000-000000000012'
    db.execute("INSERT INTO users(id,display_name,email) VALUES(%s,'Demo Department Admin','demo-admin@example.invalid') ON CONFLICT(id) DO NOTHING",(uid,))
    db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) SELECT %s,%s,'ACADEMIC_ADMIN' WHERE NOT EXISTS(SELECT FROM department_role_assignments WHERE user_id=%s AND department_id=%s AND role_code='ACADEMIC_ADMIN')",(uid,CSE,uid,CSE))
    db.execute('''CREATE TABLE IF NOT EXISTS demo_catalog(department_id uuid PRIMARY KEY REFERENCES departments(id),
      offering_id uuid NOT NULL REFERENCES curriculum_offerings(id),policy_id uuid NOT NULL REFERENCES project_policy_versions(id),
      scheme_id uuid NOT NULL REFERENCES scheme_versions(id),mode_id uuid NOT NULL REFERENCES scheme_modes(id));
      CREATE TABLE IF NOT EXISTS demo_admissions(user_id uuid PRIMARY KEY REFERENCES users(id),department_id uuid NOT NULL REFERENCES departments(id),
        usn text NOT NULL UNIQUE,section text NOT NULL,semester text NOT NULL);
      REVOKE ALL ON demo_catalog,demo_admissions FROM PUBLIC,smartpro_runtime;''')
    if db.execute('SELECT count(*) AS n FROM demo_catalog').fetchone()['n']:
        dept=db.execute("SELECT d.id FROM departments d JOIN demo_catalog c ON c.department_id=d.id WHERE d.code='DEMO-ECE'").fetchone()['id']
        pending_admission(db,dept)
        return
    ece=db.execute("INSERT INTO departments(code,name) VALUES('DEMO-ECE','Electronics & Communication') RETURNING id").fetchone()['id']
    ecycle=db.execute("INSERT INTO academic_cycles(department_id,code,starts_on,ends_on) VALUES(%s,'DEMO-2026','2026-07-01','2027-06-30') RETURNING id",(ece,)).fetchone()['id']
    pending_admission(db,ece)
    for suffix,name,dept,role in [(6,'Demo Electronics Faculty',ece,'FACULTY'),(8,'Demo Coordinator',CSE,'FACULTY'),
                                  (9,'Demo Electronics Student',ece,'STUDENT'),(10,'Demo New Student',ece,'STUDENT')]:
        uid=f'00000000-0000-4000-8000-{suffix:012d}'
        db.execute('INSERT INTO users(id,display_name,email) VALUES(%s,%s,%s) ON CONFLICT(id) DO NOTHING',(uid,name,f'demo-{suffix}@example.invalid'))
        db.execute('''INSERT INTO department_role_assignments(user_id,department_id,role_code)
          SELECT %s,%s,%s WHERE NOT EXISTS(SELECT FROM department_role_assignments WHERE user_id=%s AND department_id=%s AND role_code=%s)''',(uid,dept,role,uid,dept,role))
    db.execute("INSERT INTO demo_admissions VALUES('00000000-0000-4000-8000-000000000010',%s,'SYNTHETIC-ECE-NEW','A','SYNTHETIC-SEM-3')",(ece,))
    db.execute("INSERT INTO student_profiles(user_id,usn,section,semester_key,department_id) VALUES('00000000-0000-4000-8000-000000000009','SYNTHETIC-ECE-9','A','SYNTHETIC-SEM-3',%s)",(ece,))
    kind=db.execute("INSERT INTO curriculum_types(code,label) VALUES('DEMO-CAPSTONE','Department Capstone Studio') RETURNING id").fetchone()['id']
    for dept,cycle in [(CSE,CYCLE),(ece,ecycle)]:
        offering=db.execute("INSERT INTO curriculum_offerings(curriculum_type_id,department_id,cycle_id,semester_key,student_team_creation_enabled) VALUES(%s,%s,%s,'SYNTHETIC-SEM-3',true) RETURNING id",(kind,dept,cycle)).fetchone()['id']
        db.execute("INSERT INTO student_offering_windows VALUES(%s,clock_timestamp()-interval '1 day',clock_timestamp()+interval '30 days')",(offering,))
        version=db.execute('SELECT coalesce(max(version_no),0)+1 AS n FROM project_policy_versions WHERE department_id=%s AND project_type=%s',(dept,'MAJOR')).fetchone()['n']
        policy=db.execute("INSERT INTO project_policy_versions(department_id,project_type,version_no,policy_status,policy_data) VALUES(%s,'MAJOR',%s,'APPROVED',%s) RETURNING id",(dept,version,Jsonb({'studentRegistration':{'enabled':True},'syntheticDemo':True}))).fetchone()['id']
        reg=db.execute("""INSERT INTO project_registration_policy_versions(offering_id,cycle_id,department_id,project_type,policy_version_id,version_no,opens_at,closes_at)
          VALUES(%s,%s,%s,'MAJOR',%s,1,clock_timestamp()-interval '1 day',clock_timestamp()+interval '30 days') RETURNING id""",(offering,cycle,dept,policy)).fetchone()['id']
        db.execute("INSERT INTO offering_project_registration_policies VALUES(%s,'MAJOR',%s)",(offering,reg))
        n=db.execute('SELECT coalesce(max(version_no),0)+1 AS n FROM team_membership_policy_versions WHERE department_id=%s',(dept,)).fetchone()['n']
        size=db.execute("INSERT INTO team_membership_policy_versions(department_id,version_no,allow_join,allow_leave,allow_transfer,minimum_members,maximum_members,size_mode) VALUES(%s,%s,true,true,true,NULL,NULL,'ADVISORY') RETURNING id",(dept,n)).fetchone()['id']
        db.execute('INSERT INTO offering_membership_policies VALUES(%s,%s,%s,%s)',(offering,cycle,dept,size))
        definition=db.execute("INSERT INTO review_definitions(policy_version_id,department_id,project_type,review_code,ordinal,label) VALUES(%s,%s,'MAJOR','DEMO-REVIEW',1,'Project demonstration') RETURNING id",(policy,dept)).fetchone()['id']
        scheme=db.execute("INSERT INTO evaluation_schemes(department_id,cycle_id,review_definition_id,label) VALUES(%s,%s,%s,'Synthetic demonstration rubric') RETURNING id",(dept,cycle,definition)).fetchone()['id']
        sv=db.execute('INSERT INTO scheme_versions(scheme_id,cycle_id,review_definition_id,version_no) VALUES(%s,%s,%s,1) RETURNING id',(scheme,cycle,definition)).fetchone()['id']
        mode=db.execute("INSERT INTO scheme_modes(scheme_version_id,mode_code) VALUES(%s,'COMBINED') RETURNING id",(sv,)).fetchone()['id']
        # Copy the existing reviewed synthetic rubric, not institutional defaults.
        for i,row in enumerate(db.execute("SELECT rc.label,rc.maximum,mc.score_scope FROM mode_criteria mc JOIN rubric_criteria rc ON rc.id=mc.criterion_id WHERE mc.scheme_mode_id='24000000-0000-4000-8000-000000000003' ORDER BY rc.sort_order"),1):
            rc=db.execute('INSERT INTO rubric_criteria(scheme_version_id,code,label,maximum,sort_order) VALUES(%s,%s,%s,%s,%s) RETURNING id',(sv,f'DEMO-{i}',row['label'],row['maximum'],i)).fetchone()['id']
            db.execute('INSERT INTO mode_criteria(scheme_version_id,scheme_mode_id,criterion_id,score_scope) VALUES(%s,%s,%s,%s)',(sv,mode,rc,row['score_scope']))
        db.execute("INSERT INTO academic_action_grants(user_id,department_id,action_code) SELECT %s,%s,'APPROVE_SCHEME' WHERE NOT EXISTS(SELECT FROM academic_action_grants WHERE user_id=%s AND department_id=%s AND action_code='APPROVE_SCHEME' AND valid_until IS NULL)",(HOD,dept,HOD,dept))
        db.execute("UPDATE scheme_versions SET state='APPROVED',approved_by=%s,approved_at=clock_timestamp() WHERE id=%s",(HOD,sv))
        db.execute("UPDATE scheme_versions SET state='ACTIVE' WHERE id=%s",(sv,))
        db.execute('INSERT INTO demo_catalog VALUES(%s,%s,%s,%s,%s)',(dept,offering,policy,sv,mode))
    # Existing CSE bootstrap is cloned, never changed in the source database.
    rev=db.execute('SELECT revision FROM academic_governance_settings WHERE department_id=%s',(CSE,)).fetchone()['revision']
    appointment=db.execute('SELECT smartpro_academic_governance(%s,%s,%s,%s,%s) AS r',(HOD,CSE,'APPOINT_COORDINATOR',Jsonb({'expectedRevision':rev,'reason':'Synthetic demo coordinator appointment','userId':COORD,'validUntil':'2027-06-30T23:59:59+00:00'}),'demo-appointment')).fetchone()['r']
    role=db.execute('SELECT role_assignment_id FROM academic_coordinator_mandates WHERE id=%s',(appointment['id'],)).fetchone()['role_assignment_id']
    for permission in ['READ_POLICIES','READ_PROJECTS','MANAGE_OFFERINGS','MANAGE_TEAM_POLICY','MANAGE_REGISTRATION_POLICY']:
        db.execute("INSERT INTO staff_permission_assignments(user_id,department_id,role_assignment_id,required_role,permission,granted_by,grant_reason) VALUES(%s,%s,%s,'COORDINATOR',%s,%s,'Synthetic demo explicit coordinator scope')",(COORD,CSE,role,permission,HOD))
    policy=db.execute('SELECT id FROM academic_evaluation_policies WHERE department_id=%s ORDER BY version_no DESC LIMIT 1',(CSE,)).fetchone()['id']
    catalog=db.execute('SELECT * FROM demo_catalog WHERE department_id=%s',(CSE,)).fetchone()
    team=db.execute('SELECT smartpro_create_student_team(%s,%s,%s,%s,%s) AS r',('00000000-0000-4000-8000-000000000002',catalog['offering_id'],'Campus Innovators','demo-initial-team',hashlib.sha256(b'demo team').hexdigest())).fetchone()['r']['team']['id']
    project=db.execute('SELECT smartpro_register_student_project(%s,%s,%s,%s,%s,%s,%s) AS r',('00000000-0000-4000-8000-000000000002',team,'MAJOR','DEMO-CAMPUS','Accessible Campus Navigator','demo-initial-project',hashlib.sha256(b'demo project').hexdigest())).fetchone()['r']['project']['id']
    db.execute('SELECT smartpro_initial_evaluation(%s,%s,%s,%s,%s)',(HOD,CSE,'CREATE_REVIEW',Jsonb({'projectId':project,'schemeVersionId':str(catalog['scheme_id']),'schemeModeId':str(catalog['mode_id']),'policyId':str(policy),'facultyIds':[FACULTY],'reason':'Synthetic demo initial assignment'}),'demo-initial-review'))


def readable_test_users(db):
    """Rename only untouched synthetic display labels; never identities or roles."""
    if not db.info.dbname.startswith('smartpro_test_demo_'):
        raise RuntimeError('Synthetic persona maintenance requires a demo clone')
    names=[(1,'Demo Student A','Arjun Mehta'),(2,'Demo Student B','Kiran Shah'),(3,'Demo Faculty','Anika Rao'),
           (4,'Demo Academic Admin','Meera Iyer'),(6,'Demo Electronics Faculty','Sana Qureshi'),
           (8,'Demo Coordinator','Dev Menon'),(9,'Demo Electronics Student','Rhea Nair'),
           (10,'Demo New Student','Rohan Sen'),(11,'Demo Incoming Student','Asha Verma'),(12,'Demo Department Admin','Nisha Reddy')]
    with db.transaction():
        for suffix,old,new in names:
            uid=f'00000000-0000-4000-8000-{suffix:012d}'
            changed=db.execute('UPDATE users SET display_name=%s WHERE id=%s AND display_name=%s RETURNING id',(new,uid,old)).fetchone()
            if changed:
                db.execute("INSERT INTO audit_events(action,target_type,target_id,metadata) VALUES('DEMO_DISPLAY_LABEL_UPDATED','USER',%s,%s)",(uid,Jsonb({'before':old,'after':new,'developmentOnly':True})))


def main():
    raise SystemExit('This fixture launcher is archived. Use scripts/application.py serve for normal startup, or test-workspace for isolated browser acceptance. Existing databases are preserved.')


if __name__=='__main__':
    main()
