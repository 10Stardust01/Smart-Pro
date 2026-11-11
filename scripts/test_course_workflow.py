"""Course workflow contracts in a new disposable database; preserve all source data."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.conninfo import make_conninfo
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'backend')]
from department_demo import settings,TARGET,CSE,FACULTY,install_documents
from db_setup import execute_file

def main(test_name=None):
 _,owner,app=settings(ROOT/'.test-data/pg-memberships.env.json');name='smartpro_test_demo_acceptance_courses_'+uuid4().hex[:10]
 with psycopg.connect(**dict(owner,dbname='postgres'),autocommit=True) as manager:manager.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(sql.Identifier(name),sql.Identifier(TARGET)))
 storage=tempfile.TemporaryDirectory(prefix='smartpro-courses-')
 os.environ.update(DATABASE_URL=make_conninfo(**dict(app,dbname=name)),DJANGO_SETTINGS_MODULE='smartpro.settings',DJANGO_SECRET_KEY='synthetic-course-tests',SMARTPRO_ENV='demo',SMARTPRO_DEMO_AUTH='YES',SMARTPRO_DEPARTMENT_DEMO='YES',SMARTPRO_DATA_DIR=storage.name)
 for gate in ['CURRICULUM','TEAM','MEMBERSHIP','PROJECT','STAFF','ACADEMIC','DOCUMENT','COURSE']:os.environ['SMARTPRO_'+gate+'_API']='YES'
 import django;django.setup()
 from django.db import connection,close_old_connections
 from rest_framework.test import APIClient
 class Contracts(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
   cls.db=psycopg.connect(**dict(owner,dbname=name),autocommit=True,row_factory=dict_row);install_documents(cls.db)
   for candidate in ['037_course_coordination.sql','038_course_assessment_lifecycle.sql','039_course_deadlines_notifications.sql','040_course_integration.sql','041_course_scope_guards.sql','042_course_authorized_operations.sql','043_runtime_function_grants.sql','044_coordinator_own_corrections.sql','045_admin_course_appointments.sql','046_department_leadership.sql','047_department_intake.sql','048_course_evaluation_queue.sql','049_paginated_evaluation_queue.sql','050_document_project_pages.sql','051_department_intake_pages.sql','052_department_directory.sql','053_department_import_outcomes.sql','054_department_offering_pages.sql','055_leadership_history_pages.sql','056_coordinator_catalog_scope_prefilter.sql','057_department_identity_navigation.sql','058_course_command_lock_order.sql','059_published_correction_authority.sql','060_published_stage_evidence_rerelease.sql','061_published_correction_read_visibility.sql','062_paged_published_correction_reads.sql','063_department_faculty_management.sql','064_academic_access_handover.sql','065_exceptional_overall_correction_policy_alignment.sql']:execute_file(cls.db,ROOT/'proposals/curriculum'/candidate)
  @classmethod
  def tearDownClass(cls):cls.db.close();connection.close()
  def client(self,who='staff-policy',role=None):
   c=APIClient()
   if who=='tech-admin':c.credentials(HTTP_X_DEMO_USER=who)
   else:c.credentials(HTTP_X_DEMO_USER=who,HTTP_X_SMARTPRO_ROLE=role or {'staff-policy':'HOD','department-admin':'Admin','coordinator':'Coordinator','faculty-a':'Faculty','student-a':'Student'}.get(who,'Faculty'))
   return c
  def post(self,path,body,who='staff-policy',role=None,key=None):return self.client(who,role).post(path,body,format='json',HTTP_IDEMPOTENCY_KEY=key or uuid4().hex)
  def ok(self,r,status=200):self.assertEqual(r.status_code,status,r.content);return r.json()
  def offering(self,project_policy=None):
   kind=str(self.db.execute('INSERT INTO curriculum_types(code,label) VALUES(%s,%s) RETURNING id',('COURSE-'+uuid4().hex.upper(),'Isolated course')).fetchone()['id'])
   admin=str(self.db.execute("SELECT id FROM department_role_assignments WHERE user_id='00000000-0000-4000-8000-000000000012' AND role_code='ACADEMIC_ADMIN' ORDER BY id LIMIT 1").fetchone()['id'])
   cfg=dict(curriculumTypeId=kind,cycleId='11000000-0000-4000-8000-000000000001',semester='SYNTHETIC-SEM-3',projectPolicyId=project_policy or str(self.db.execute('SELECT policy_id FROM demo_catalog WHERE department_id=%s',(CSE,)).fetchone()['policy_id']),teamPolicyId=str(self.db.execute('SELECT id FROM team_membership_policy_versions WHERE department_id=%s ORDER BY version_no LIMIT 1',(CSE,)).fetchone()['id']),adminRoleId=admin,visibleFrom='2026-01-01T00:00:00Z',visibleUntil='2027-06-01T00:00:00Z',submissionOpensAt='2026-01-01T00:00:00Z',submissionClosesAt='2027-06-01T00:00:00Z',maxBytes=2097152,facultyApprovalEnabled=True,teamCreationEnabled=True)
   base=f'/api/v1/documents/departments/{CSE}'
   i=self.ok(self.post(base,dict(action='AUTHORIZE',configuration=cfg)))['instructionId']
   return self.ok(self.post(base,dict(action='CONFIGURE',instructionId=i),who='department-admin'))['offeringId']
  def authority(self):return dict(hodMandateId=str(self.db.execute('SELECT id FROM academic_hod_mandates WHERE department_id=%s AND enabled',(CSE,)).fetchone()['id']),source='EXTERNAL_INSTRUCTION',confirmed=True,reference='')
  def appoint(self,oid,uid=FACULTY,version=0,active=True,who='department-admin',key=None,permissions=None):
   return self.post(f'/api/v1/courses/offerings/{oid}/coordinators',dict(userId=uid,expectedVersion=version,active=active,validUntil='2027-06-01T00:00:00Z',responsibilities=permissions if permissions is not None else ['OVERVIEW','REQUIREMENTS','PLAN','GUIDE','EVALUATORS','SUBMISSIONS','DEADLINES','RESULTS','CORRECTIONS','HISTORY'],authority=None),who=who,key=key)
  def command(self,oid,action,body,who='staff-policy',role=None,key=None):return self.post(f'/api/v1/courses/offerings/{oid}/commands',dict(action=action,**body),who,role,key)
  def activate(self,oid):
   row=self.db.execute('SELECT availability,management_revision FROM curriculum_offerings WHERE id=%s',(oid,)).fetchone()
   if row['availability']!='ACTIVE':self.ok(self.post(f'/api/v1/staff/departments/{CSE}/offering-management',dict(action='AVAILABILITY',offeringId=oid,expectedRevision=row['management_revision'],availability='ACTIVE',authority=self.authority()),who='department-admin'))
  def project(self,oid,guide_id=FACULTY):
   self.activate(oid)
   team=self.ok(self.post('/api/v1/teams',dict(offeringId=oid,name='Course verification team'),who='student-a'),201)['id']
   pid=self.ok(self.post('/api/v1/projects',dict(offeringId=oid,teamId=team,title='Course verification project',description='Synthetic assessment evidence'),who='student-a'),201)['id']
   self.ok(self.post(f'/api/v1/staff/departments/{CSE}/projects/{pid}/guide',dict(facultyId=guide_id,expectedGuideId=None)))
   return pid
  def framework(self,oid,n=1,scheme=None,allow_final_corrections=True):
   cat=scheme or self.db.execute('SELECT * FROM demo_catalog WHERE department_id=%s',(CSE,)).fetchone()
   policy=str(self.db.execute('SELECT id FROM academic_evaluation_policies WHERE department_id=%s ORDER BY version_no DESC LIMIT 1',(CSE,)).fetchone()['id'])
   stages=[dict(key='stage-'+str(i),name='Authorized assessment '+str(i),schemeVersionId=str(cat['scheme_id']),schemeModeId=str(cat['mode_id']),policyId=policy,weight='100' if n==1 else '25' if i==1 else '75',required=True,opensAt='2026-01-01T00:00:00Z',deadline='2027-06-01T00:00:00Z') for i in range(1,n+1)]
   cfg=dict(stages=stages,method='SINGLE_RAW' if n==1 else 'WEIGHTED_NORMALIZED',rounding='HALF_UP',decimalPlaces=2,scale='100',allowFinalCorrections=allow_final_corrections,outsidePanelAuthorizer=True,maxExtensionDays=10,publicationRoles=['Coordinator','HOD'])
   fid=self.ok(self.command(oid,'FRAMEWORK',dict(expectedVersion=0,configuration=cfg,authority=None)))['id']
   self.ok(self.command(oid,'PLAN',dict(expectedVersion=0,frameworkId=fid,schedules={x['key']:'2026-12-01T09:00:00Z' for x in stages}),who='coordinator'))
   return cfg
  def stage(self,oid,pid,key,mark,faculty=None,faculty_id=FACULTY,race=False):
   faculty=faculty or self.client('faculty-a')
   rid=self.ok(self.command(oid,'CREATE_STAGE',dict(projectId=pid,stageKey=key,facultyIds=[]),who='coordinator'))['id']
   w=self.ok(faculty.get('/api/v1/workspace'));r=next(r for r in w['reviews'] if r['id']==rid)
   self.assertEqual(r['label'],'Authorized assessment '+key.removeprefix('stage-'))
   self.assertEqual(len(r['assessments']),1);a=r['assessments'][0];self.assertEqual(a['facultyId'],faculty_id)
   scores=[dict(criterionId=c['id'],studentId=uid,marks=str(mark[c['scope']] if isinstance(mark,dict) else mark)) for c in r['criteria'] for uid in ([None] if c['scope']=='TEAM' else [x['id'] for x in r['roster']])]
   root=f'/api/v1/academic/departments/{CSE}'
   def submit(path,body):
    return faculty.post(root+f'/assessments/{a["id"]}/{path}',body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex)
   def race_submit(path,body):
    from threading import Barrier
    barrier=Barrier(2)
    def run(_):
     try:
      barrier.wait(timeout=5)
      return submit(path,body)
     finally:close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as workers:responses=list(workers.map(run,range(2)))
    self.assertEqual(sum(response.status_code==200 for response in responses),1)
    self.assertTrue(all(response.status_code in (200,403,409) for response in responses))
    return next(response.json() for response in responses if response.status_code==200)
   body=dict(expectedAssessmentVersion=a['version'],scores=scores)
   saved=race_submit('draft',body) if race else self.ok(submit('draft',body))
   body=dict(expectedAssessmentVersion=saved['assessmentVersion'])
   if race:race_submit('finalize',body)
   else:self.ok(submit('finalize',body))
   self.ok(self.post(root+f'/reviews/{rid}/publish',dict(expectedReviewRevision=r['revision']),who='coordinator'))
   for who in ['coordinator','staff-policy']:
    history=self.ok(self.client(who).get(root+f'/reviews/{rid}/results'))['results']
    self.assertEqual(len(history),1)
   return rid,a['id'],scores
  def test_course_assignment_waits_for_governance_before_locking_coordinator(self):
   from queue import Queue
   from time import monotonic, sleep
   from psycopg.types.json import Jsonb
   oid=self.offering()
   self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'))
   pid=self.project(oid);self.framework(oid)
   backend=Queue()
   def assign():
    with psycopg.connect(**dict(app,dbname=name),autocommit=True) as runtime:
     runtime.execute('SET ROLE smartpro_runtime')
     runtime.execute("SET lock_timeout='5s'")
     backend.put(runtime.info.backend_pid)
     return runtime.execute('SELECT public.smartpro_course_command(%s,%s,%s,%s,%s)',
       ('00000000-0000-4000-8000-000000000008',oid,'CREATE_STAGE',
        Jsonb(dict(projectId=pid,stageKey='stage-1',facultyIds=[],_actingRole='Coordinator')),uuid4().hex)).fetchone()[0]
   with ThreadPoolExecutor(max_workers=1) as pool, psycopg.connect(**dict(owner,dbname=name),autocommit=True) as probe:
    with self.db.transaction():
     self.db.execute('SELECT 1 FROM academic_governance_settings WHERE department_id=%s FOR UPDATE',(CSE,))
     future=pool.submit(assign)
     worker_pid=backend.get(timeout=5)
     deadline=monotonic()+3
     while monotonic()<deadline:
      if self.db.info.backend_pid in probe.execute('SELECT pg_blocking_pids(%s)',(worker_pid,)).fetchone()[0]:
       break
      sleep(.02)
     else:self.fail('Stage creation did not reach the controlled governance wait')
     with probe.transaction():
      mandates=probe.execute("""SELECT id FROM academic_coordinator_mandates
       WHERE department_id=%s AND user_id='00000000-0000-4000-8000-000000000008'
       ORDER BY id FOR UPDATE NOWAIT""",(CSE,)).fetchall()
      self.assertTrue(mandates)
    self.assertIn('id',future.result(timeout=5))
  def test_new_faculty_appointment_reevaluates_the_same_client(self):
   from unittest.mock import patch
   from smartpro.identity import DEMO_USERS
   uid=str(uuid4())
   self.db.execute("INSERT INTO users(id,display_name,email) VALUES(%s,'Isolated new faculty',%s)",(uid,uid+'@example.invalid'))
   self.db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'STUDENT')",(uid,CSE))
   alias='readiness-faculty'
   with patch.dict(DEMO_USERS,{alias:uid}):
    faculty=self.client(alias,'Student')
    self.ok(faculty.get('/api/v1/workspace'))
    faculty.credentials(HTTP_X_DEMO_USER=alias,HTTP_X_SMARTPRO_ROLE='Faculty')
    self.assertEqual(faculty.get('/api/v1/workspace').status_code,401)
    path=f'/api/v1/staff/departments/{CSE}/setup'
    grant=dict(action='RECORD',kind='FACULTY_ACCESS',configuration=dict(userId=uid,validUntil='2027-06-01T00:00:00Z'),authority=self.authority())
    self.assertEqual(self.post(path,grant,who='staff-policy').status_code,403)
    self.ok(self.post(path,grant,who='department-admin'))
    self.assertEqual(self.ok(faculty.get('/api/v1/workspace'))['reviews'],[])
    oid=self.offering();self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'))
    pid=self.project(oid,guide_id=uid);self.framework(oid)
    rid,aid,_=self.stage(oid,pid,'stage-1',25,faculty=faculty,faculty_id=uid)
    other=self.offering();self.ok(self.appoint(other,uid='00000000-0000-4000-8000-000000000008'))
    other_pid=self.project(other);self.framework(other)
    other_rid,_,_=self.stage(other,other_pid,'stage-1',25)
    root=f'/api/v1/academic/departments/{CSE}'
    self.assertEqual(faculty.get(root+f'/reviews/{other_rid}/results').status_code,403)
    other_department=self.db.execute('SELECT id FROM departments WHERE id<>%s ORDER BY id LIMIT 1',(CSE,)).fetchone()['id']
    other_department_path=f'/api/v1/academic/departments/{other_department}/reviews/{rid}/results'
    self.assertEqual(faculty.get(other_department_path).status_code,403)
    self.assertEqual(self.client().get(other_department_path).status_code,403)
    result_path=root+f'/reviews/{rid}/results'
    before=self.ok(self.client().get(result_path))['results']
    self.ok(faculty.get(result_path))
    scoped=self.offering();self.ok(self.appoint(scoped,uid='00000000-0000-4000-8000-000000000008'))
    scoped_project=self.project(scoped)
    guide_path=f'/api/v1/staff/departments/{CSE}/projects/{scoped_project}/guide'
    documents=f'/api/v1/documents/departments/{CSE}'
    def visible_projects():
     return {item['id'] for item in self.ok(faculty.get(documents))['projects']}
    self.assertNotIn(scoped_project,visible_projects())
    old_guide=str(self.db.execute("SELECT id FROM faculty_assignments WHERE project_id=%s AND assignment_type='GUIDE' AND valid_until IS NULL",(scoped_project,)).fetchone()['id'])
    new_guide=self.ok(self.post(guide_path,dict(facultyId=uid,expectedGuideId=old_guide)))['id']
    self.assertIn(scoped_project,visible_projects())
    end_path=f'/api/v1/staff/departments/{CSE}/assignment-management'
    end=dict(action='END_ASSIGNMENT',assignmentId=new_guide)
    self.assertEqual(self.post(end_path,end,who='department-admin').status_code,403)
    self.ok(self.post(end_path,end))
    self.assertNotIn(scoped_project,visible_projects())
    self.ok(faculty.get(result_path))
    self.assertEqual(self.ok(self.client().get(result_path))['results'],before)
    self.assertEqual(self.db.execute('SELECT state FROM assessments WHERE id=%s',(aid,)).fetchone()['state'],'FINALIZED')
  def test_authorized_faculty_grant_expires_on_the_same_client(self):
   from unittest.mock import patch
   from smartpro.identity import DEMO_USERS
   uid=str(uuid4())
   self.db.execute("INSERT INTO users(id,display_name,email) VALUES(%s,'Isolated finite faculty',%s)",(uid,uid+'@example.invalid'))
   self.db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'STUDENT')",(uid,CSE))
   alias='finite-faculty'
   with patch.dict(DEMO_USERS,{alias:uid}):
    faculty=self.client(alias,'Faculty')
    expiry=self.db.execute("SELECT clock_timestamp()+interval '5 seconds' AS expiry").fetchone()['expiry']
    grant=dict(action='RECORD',kind='FACULTY_ACCESS',configuration=dict(userId=uid,validUntil=expiry.isoformat()),authority=self.authority())
    self.ok(self.post(f'/api/v1/staff/departments/{CSE}/setup',grant,who='department-admin'))
    self.ok(faculty.get('/api/v1/workspace'))
    self.db.execute('SELECT pg_sleep_until(%s)',(expiry,))
    self.assertEqual(faculty.get('/api/v1/workspace').status_code,401)
    self.ok(self.client(alias,'Student').get('/api/v1/workspace'))
  def test_public_cannot_execute_owner_privilege_functions(self):
   public_definers=self.db.execute("""
      SELECT p.oid::regprocedure::text AS signature FROM pg_proc p
      JOIN pg_namespace n ON n.oid=p.pronamespace
      WHERE n.nspname='public' AND p.prosecdef AND EXISTS(
        SELECT FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
        WHERE a.grantee=0 AND a.privilege_type='EXECUTE'
      ) ORDER BY 1
   """).fetchall()
   self.assertEqual(public_definers,[])
  def test_faculty_reference_requires_local_opt_in_and_exact_scope(self):
   from unittest.mock import patch

   from django.conf import settings as django_settings
   path=f'/api/v1/faculty-reference/departments/{CSE}'
   admin=self.client('department-admin')
   with patch.dict(os.environ,{'SMARTPRO_FACULTY_REFERENCE':'NO'}):
    self.assertEqual(admin.get(path).status_code,404)
   assigned=self.offering();self.ok(self.appoint(assigned,uid='00000000-0000-4000-8000-000000000008'))
   unrelated=self.offering();self.ok(self.appoint(unrelated,uid=FACULTY))
   with patch.dict(os.environ,{'SMARTPRO_FACULTY_REFERENCE':'YES'}):
    self.assertEqual(APIClient().get(path).status_code,401)
    for who,role in [('student-a','Student'),('faculty-a','Faculty'),('tech-admin',None)]:
     self.assertEqual(self.client(who,role).get(path).status_code,403)
    self.assertEqual(admin.get(path,REMOTE_ADDR='192.0.2.1').status_code,404)
    with patch.dict(django_settings.DATABASES['default'],{'NAME':'smartpro_normal_workspace'}):
     self.assertEqual(admin.get(path).status_code,401)
    self.assertEqual(admin.get(f'/api/v1/faculty-reference/departments/{uuid4()}').status_code,404)
    self.assertEqual(admin.post(path,{},format='json').status_code,405)
    self.assertEqual(admin.get('/demo-assets/bit_main_cse_2026-11-07.json').status_code,404)
    snapshot=self.ok(admin.get(path))
    self.assertEqual(snapshot,self.ok(self.client().get(path)))
    coordinator=self.client('coordinator')
    self.assertEqual(coordinator.get(path).status_code,403)
    self.assertEqual(coordinator.get(path,{'offeringId':unrelated}).status_code,403)
    self.assertEqual(snapshot,self.ok(coordinator.get(path,{'offeringId':assigned})))
    self.assertEqual(len(snapshot['records']),36)
    self.assertEqual(sum(row['earlierReference'] is not None for row in snapshot['records']),11)
    self.assertEqual(sum(row['irinsProfileUrl'] is not None for row in snapshot['records']),9)
    self.assertEqual(snapshot['irinsReportedProfiles'],39)
    with patch.dict(os.environ,{'SMARTPRO_ENV':'local'}):
     self.assertEqual(admin.get(path).status_code,401)
   reference_names={row['name'] for row in snapshot['records']}
   users=self.db.execute('SELECT display_name FROM users').fetchall()
   self.assertTrue(reference_names.isdisjoint({row['display_name'] for row in users}))
   candidates=self.ok(admin.get(f'/api/v1/courses/departments/{CSE}'))['faculty']
   self.assertTrue(reference_names.isdisjoint({row['display_name'] for row in candidates}))
  def test_department_leadership_lifecycle_and_concurrent_successors(self):
   from unittest.mock import patch
   from smartpro.identity import DEMO_USERS
   dept=str(uuid4())
   self.db.execute("INSERT INTO departments(id,code,name) VALUES(%s,%s,'Isolated leadership department')",(dept,'LEAD-'+uuid4().hex[:8]))
   identities={alias:str(uuid4()) for alias in ['test-hod','test-first-admin','test-admin','test-extra','test-successor']}
   for alias,uid in identities.items():
    self.db.execute('INSERT INTO users(id,display_name,email) VALUES(%s,%s,%s)',(uid,alias,uid+'@example.invalid'))
    self.db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'FACULTY')",(uid,dept))
   with psycopg.connect(**dict(app,dbname=name)) as runtime:
    self.assertFalse(runtime.execute("SELECT has_function_privilege('public.smartpro_bootstrap_first_hod(uuid,uuid,text)','EXECUTE')").fetchone()[0])
   first_hod=str(self.db.execute('SELECT smartpro_bootstrap_first_hod(%s,%s,%s) AS id',(dept,identities['test-hod'],'Synthetic verified fixture')).fetchone()['id'])
   with self.assertRaises(psycopg.errors.CheckViolation):
    self.db.execute('SELECT smartpro_bootstrap_first_hod(%s,%s,%s)',(dept,identities['test-extra'],'Duplicate fixture'))
   base=f'/api/v1/staff/departments/{dept}'
   with patch.dict(DEMO_USERS,identities):
    hod=self.client('test-hod','HOD')
    former=self.client('test-first-admin','Admin')
    admin=self.client('test-admin','Admin')
    def change(client,action,**fields):
     return client.post(base+'/leadership',dict(action=action,**fields),format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex)
    first_admin=self.ok(change(hod,'APPOINT_ADMIN',userId=identities['test-first-admin']))['appointmentId']
    self.ok(former.get(base+'/setup'))
    self.assertEqual(change(hod,'APPOINT_ADMIN',userId=identities['test-extra']).status_code,409)
    from threading import Barrier
    barrier=Barrier(2)
    def replace(alias):
     try:
      barrier.wait(timeout=5)
      return change(self.client('test-hod','HOD'),'REPLACE_ADMIN',appointmentId=first_admin,userId=identities[alias])
     finally:close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
     replies=list(pool.map(replace,('test-admin','test-extra')))
    self.assertEqual(sorted(reply.status_code for reply in replies),[200,409])
    if replies[1].status_code==200:
     self.ok(change(hod,'REPLACE_ADMIN',appointmentId=replies[1].json()['appointmentId'],userId=identities['test-admin']))
    self.assertEqual(former.get(base+'/setup').status_code,401)
    history=self.ok(change(hod,'HISTORY',page=1,q='test-admin'))
    self.assertTrue(any(term['appointed_by']=='test-hod' for term in history['history']))
    self.assertEqual(self.client('faculty-a').post(base+'/leadership',dict(action='HISTORY',page=1,q=''),format='json').status_code,403)
    self.ok(admin.get(base+'/setup'))
    self.assertEqual(change(admin,'APPOINT_ADMIN',userId=identities['test-extra']).status_code,403)
    self.assertEqual(change(admin,'APPOINT_HOD',userId=identities['test-successor']).status_code,409)
    self.assertEqual(change(admin,'RESIGN_HOD',appointmentId=first_hod).status_code,403)
    self.ok(change(hod,'SET_ADMIN_CAPACITY',capacity=2))
    extra=self.client('test-extra','Admin')
    extra_term=self.ok(change(hod,'APPOINT_ADMIN',userId=identities['test-extra']))['appointmentId']
    self.ok(extra.get(base+'/setup'))
    self.ok(change(hod,'END_ADMIN',appointmentId=extra_term))
    self.assertEqual(extra.get(base+'/setup').status_code,401)
    self.ok(change(hod,'APPOINT_ADMIN',userId=identities['test-extra']))
    self.ok(change(hod,'RESIGN_HOD',appointmentId=first_hod))
    self.assertEqual(hod.get(base+'/setup').status_code,401)
    self.assertTrue(self.ok(admin.get(base+'/setup'))['leadership']['vacancyByResignation'])
    self.assertEqual(change(admin,'APPOINT_HOD',userId=identities['test-admin']).status_code,403)
    def attempt(caller,target):
     try:return change(self.client(caller,'Admin'),'APPOINT_HOD',userId=identities[target]).status_code
     finally:close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
     attempts=[pool.submit(attempt,'test-admin','test-successor'),pool.submit(attempt,'test-extra','test-first-admin')]
     self.assertEqual(sorted(item.result(timeout=10) for item in attempts),[200,409])
    terms=self.db.execute("SELECT id,valid_until FROM department_role_assignments WHERE department_id=%s AND role_code='HOD' ORDER BY valid_from",(dept,)).fetchall()
    self.assertEqual(len(terms),2)
    self.assertEqual(str(terms[0]['id']),first_hod)
    self.assertIsNotNone(terms[0]['valid_until'])
    self.assertIsNone(terms[1]['valid_until'])
  def test_selected_coordinator_role_does_not_borrow_hod_scope(self):
   hod_id='00000000-0000-4000-8000-000000000004'
   self.db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'FACULTY')",(hod_id,CSE))
   one=self.offering();self.ok(self.appoint(one,uid=hod_id,permissions=['RESULTS']))
   two=self.offering();self.ok(self.appoint(two,uid='00000000-0000-4000-8000-000000000008'))
   pid=self.project(two);self.framework(two);rid,_,_=self.stage(two,pid,'stage-1',20)
   revision=self.db.execute('SELECT revision FROM academic_review_bindings WHERE review_id=%s',(rid,)).fetchone()['revision']
   path=f'/api/v1/academic/departments/{CSE}/reviews/{rid}/publish'
   self.assertEqual(self.post(path,dict(expectedReviewRevision=revision),role='Coordinator').status_code,403)
   self.assertEqual(self.post(f'/api/v1/documents/departments/{CSE}',dict(action='ASSIGN_REVIEWER',projectId=pid,facultyId=hod_id),role='Coordinator').status_code,403)
  def test_individual_and_combined_marking_publish_student_scores(self):
   route=f'/api/v1/staff/departments/{CSE}/setup'
   def record(kind,configuration):
    return self.ok(self.post(route,dict(action='RECORD',kind=kind,configuration=configuration,
      authority=self.authority()),who='department-admin'))['id']
   for mode in ('INDIVIDUAL','COMBINED'):
    base=record('PROJECT_POLICY',dict(label='Marking verification '+mode,projectType='MINI',allowStudentRegistration=True))
    criteria=[dict(label='Individual understanding',scope='STUDENT',maximum='40')]
    if mode=='COMBINED':criteria.insert(0,dict(label='Team evidence',scope='TEAM',maximum='60'))
    policy=record('REVIEW_BLUEPRINT',dict(policyVersionId=base,cycleId='11000000-0000-4000-8000-000000000001',
      label='Verification '+mode,stages=[dict(code='CHECK',label='Marking verification',mode=mode,criteria=criteria)]))
    scheme=self.db.execute("""SELECT v.id AS scheme_id,m.id AS mode_id FROM review_definitions d
      JOIN scheme_versions v ON v.review_definition_id=d.id JOIN scheme_modes m ON m.scheme_version_id=v.id
      WHERE d.policy_version_id=%s AND m.mode_code=%s""",(policy,mode)).fetchone()
    oid=self.offering(policy);self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'))
    pid=self.project(oid);self.framework(oid,scheme=scheme)
    rid,aid,scores=self.stage(oid,pid,'stage-1',dict(TEAM=35,STUDENT=23),race=mode=='COMBINED')
    expected='23.00' if mode=='INDIVIDUAL' else '58.00'
    release=self.db.execute('SELECT results FROM academic_result_versions WHERE review_id=%s',(rid,)).fetchone()['results']
    self.assertEqual(list(release.values()),[expected])
    self.ok(self.command(oid,'PUBLISH_FINAL',dict(projectId=pid,expectedVersion=0),who='coordinator'))
    result=self.db.execute('SELECT results FROM course_final_results WHERE project_id=%s',(pid,)).fetchone()['results']
    self.assertEqual(result,release)
    revision=self.db.execute('SELECT revision FROM academic_review_bindings WHERE review_id=%s',(rid,)).fetchone()['revision']
    self.assertEqual(self.command(oid,'REQUEST_CORRECTION',dict(reviewId=rid,assessmentId=aid,
      expectedReviewRevision=revision,scores=scores),who='faculty-a').status_code,403)

  def test_z_evaluation_queue_paginates_the_entire_offering(self):
   oid=self.offering()
   self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'))
   pid=self.project(oid)
   self.db.execute("""INSERT INTO projects(department_id,cycle_id,team_id,project_type,policy_version_id,project_code,title)
      SELECT department_id,cycle_id,team_id,project_type,policy_version_id,
      gen_random_uuid()::text,'Page sample '||lpad(n::text,3,'0') FROM projects CROSS JOIN generate_series(1,204) n WHERE id=%s""",(pid,))
   url=f'/api/v1/courses/offerings/{oid}/evaluation-queue'
   client=self.client('coordinator')
   ids=[]
   for page in range(1,10):
    result=self.ok(client.get(url,{'page':page,'status':'unassigned'}))
    self.assertEqual((result['total'],result['page']),(205,page))
    ids.extend(project['id'] for project in result['projects'])
   self.assertEqual(len(set(ids)),205)
   result=self.ok(client.get(url,{'q':'sample 204','page':999}))
   self.assertEqual((result['total'],result['page']),(1,1))
   self.assertEqual(result['projects'][0]['title'],'Page sample 204')
   project_id=result['projects'][0]['id']
   documents=f'/api/v1/documents/departments/{CSE}'
   document_page=self.ok(client.get(documents,{'listing':'1','page':9,'offering':oid}))
   self.assertEqual((document_page['total'],len(document_page['projects'])),(205,5))
   searched=self.ok(client.get(documents,{'listing':'1','q':'sample 204','offering':oid}))
   self.assertEqual([row['id'] for row in searched['projects']],[project_id])
   student=self.client('student-a')
   self.assertEqual(self.ok(student.get(documents,{'listing':'1','offering':oid}))['total'],205)
   self.assertEqual([row['id'] for row in self.ok(student.get(documents,{'project':project_id}))['projects']],[project_id])
   foreign=f'/api/v1/documents/departments/{uuid4()}'
   self.assertEqual(student.get(foreign,{'project':project_id}).status_code,403)
   evidence=self.ok(client.get(documents,{'project':project_id}))
   self.assertEqual([row['id'] for row in evidence['projects']],[project_id])
   self.assertEqual(self.client('faculty-a').get(documents,{'project':project_id}).status_code,403)

   self.assertEqual(self.ok(client.get(url,{'status':'published'}))['total'],0)
   self.assertEqual(client.get(url,{'status':'invalid'}).status_code,400)

  def test_readiness_and_admin_configuration_keep_document_reads_bounded(self):
   url=f'/api/v1/documents/departments/{CSE}'
   response=self.ok(self.client('department-admin').get(url,{'configuration':'1'}))
   self.assertEqual(response['projects'],[])
   self.assertTrue(response['operationalAdmin'])
   self.assertEqual(self.client('student-a').get(url,{'configuration':'1'}).status_code,403)
   self.assertEqual(APIClient().get('/health/live').json(),{'status':'ok'})
   self.assertEqual(APIClient().get('/health/ready').status_code,200)
   from unittest.mock import patch
   with patch.dict(os.environ,{'SMARTPRO_DATA_DIR':str(ROOT/'missing-health-test-storage')}):
    self.assertEqual(APIClient().get('/health/ready').status_code,503)

  def test_verified_identity_requires_bearer_and_rechecks_effective_role(self):
   from django.test import RequestFactory, override_settings
   from rest_framework.exceptions import AuthenticationFailed
   from smartpro.identity import VerifiedIdentityAuthentication
   from unittest.mock import patch
   adapter=VerifiedIdentityAuthentication()
   request=RequestFactory().get('/api/v1/workspace',HTTP_X_DEMO_USER='staff-policy')
   self.assertIsNone(adapter.authenticate(request))
   actor='00000000-0000-4000-8000-000000000001'
   with override_settings(IDENTITY_RESOLVER='fixture.resolve'), patch('django.utils.module_loading.import_string',return_value=lambda _:actor):
    request=RequestFactory().get('/api/v1/workspace',HTTP_AUTHORIZATION='Bearer synthetic-token',HTTP_X_SMARTPRO_ROLE='Student')
    self.assertEqual(adapter.authenticate(request)[0].role,'Student')
    request=RequestFactory().get('/api/v1/workspace',HTTP_AUTHORIZATION='Bearer synthetic-token',HTTP_X_SMARTPRO_ROLE='HOD')
    with self.assertRaises(AuthenticationFailed):adapter.authenticate(request)

  def test_evaluation_queue_reports_authoritative_readiness_and_scope(self):
   oid=self.offering()
   coordinator='00000000-0000-4000-8000-000000000008'
   self.ok(self.appoint(oid,uid=coordinator))
   pid=self.project(oid,guide_id=coordinator)
   self.framework(oid,2)
   url=f'/api/v1/courses/offerings/{oid}/evaluation-queue'
   def project():
    return next(p for p in self.ok(self.client('coordinator').get(url))['projects'] if p['id']==pid)
   for who,role in [('student-a','Student'),('faculty-a','Faculty'),('faculty-a','Coordinator')]:
    self.assertIn(self.client(who,role).get(url).status_code,(401,403))
   other=self.offering()
   self.assertEqual(self.client('coordinator').get(f'/api/v1/courses/offerings/{other}/evaluation-queue').status_code,403)
   self.assertIn('Assign evaluators',project()['stages'][0]['blocker'])
   rid=self.ok(self.command(oid,'CREATE_STAGE',dict(projectId=pid,stageKey='stage-1',facultyIds=[]),who='coordinator'))['id']
   entry=project()['stages'][0]
   self.assertEqual(entry['reviewId'],rid)
   self.assertIsNotNone(entry['ownAssessmentId'])
   self.assertIn('0 of 1',entry['blocker'])
   self.assertIn('required/contributing stage',project()['overallBlocker'])
   root=f'/api/v1/academic/departments/{CSE}'
   a=entry['ownAssessmentId']
   self.assertEqual(self.post(root+f'/assessments/{a}/finalize',dict(expectedAssessmentVersion=1),who='faculty-a').status_code,403)
   self.assertEqual(self.post(root+f'/reviews/{rid}/publish',dict(expectedReviewRevision=0),who='coordinator').status_code,409)

  def test_single_multi_stage_guides_and_final_lock(self):
   from synthetic_synopsis import pdf_bytes
   from django.core.files.uploadedfile import SimpleUploadedFile
   for n in [1,2]:
    oid=self.offering();self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'));pid=self.project(oid);self.framework(oid,n)
    base=f'/api/v1/documents/departments/{CSE}'
    vid=self.ok(self.client('student-a').post(base+f'/projects/{pid}/uploads',{'file':SimpleUploadedFile('synopsis.pdf',pdf_bytes(),content_type='application/pdf')},format='multipart',HTTP_IDEMPOTENCY_KEY=uuid4().hex))['documentVersionId']
    def record():return next(p for p in self.ok(self.client('faculty-a').get(base))['projects'] if p['id']==pid)
    case=record()['case'];self.ok(self.post(base,dict(action='SUBMIT',projectId=pid,documentVersionId=vid,expectedCaseVersion=case['version']),who='student-a'));case=record()['case']
    self.ok(self.post(base,dict(action='DECIDE',projectId=pid,attemptId=case['attempts'][-1]['id'],expectedCaseVersion=case['version'],decision='APPROVE',comment='Accepted under the configured synopsis rules'),who='faculty-a'))
    self.stage(oid,pid,'stage-1',20)
    case=record()['case'];self.ok(self.command(oid,'REOPEN_SYNOPSIS',dict(projectId=pid,expectedCaseVersion=case['version'],comment='Add the subsequent validation evidence.'),who='faculty-a'))
    case=record()['case'];self.assertEqual(case['state'],'CHANGES_REQUESTED');self.assertEqual(case['attempts'][0]['state'],'APPROVED');self.assertEqual(len(case['attempts'][0]['feedback']),2)
    if n==2:
     self.assertEqual(self.command(oid,'PUBLISH_FINAL',dict(projectId=pid,expectedVersion=0),who='coordinator').status_code,409)
     self.stage(oid,pid,'stage-2',40)
    queue_url=f'/api/v1/courses/offerings/{oid}/evaluation-queue'
    ready=self.ok(self.client('coordinator').get(queue_url))['projects'][0]
    self.assertIsNone(ready['overallBlocker'])
    self.assertEqual([stage['publishedVersion'] for stage in ready['stages']],[1]*n)
    self.ok(self.command(oid,'PUBLISH_FINAL',dict(projectId=pid,expectedVersion=0),who='coordinator'))
    closed=self.ok(self.client('coordinator').get(queue_url))['projects'][0]
    self.assertEqual(closed['overallVersion'],1)
    self.assertIn('exceptional revision',closed['overallBlocker'])
    details=self.ok(self.client('coordinator').get(f'/api/v1/courses/offerings/{oid}/details'))
    self.assertEqual((details['studentCount'],details['teamCount'],details['projectCount']),(1,1,1))
    self.assertEqual(details['reviewProgress'],dict(total=n,published=n))
    self.assertEqual(details['submissionProgress'],dict(awaitingReview=0,awaitingRevision=0))
    final=self.db.execute('SELECT results FROM course_final_results WHERE project_id=%s',(pid,)).fetchone()['results'];self.assertEqual(final['00000000-0000-4000-8000-000000000001'],'40.00' if n==1 else '70.00')
    self.assertEqual(self.command(oid,'REOPEN_SYNOPSIS',dict(projectId=pid,expectedCaseVersion=case['version'],comment='Too late'),who='faculty-a').status_code,403)
    self.assertEqual(self.client('student-a').post(base+f'/projects/{pid}/uploads',{'file':SimpleUploadedFile('revision.pdf',pdf_bytes(),content_type='application/pdf')},format='multipart',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,403)
  def test_department_csv_intake_and_explicit_reconciliation(self):
   student='00000000-0000-4000-8000-000000000001'
   profile=self.db.execute('SELECT usn,semester_key,section FROM student_profiles WHERE user_id=%s',(student,)).fetchone()
   dept_code=self.db.execute('SELECT code FROM departments WHERE id=%s',(CSE,)).fetchone()['code']
   oid=self.offering();self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'))
   pid=self.project(oid);self.framework(oid);rid,_,_=self.stage(oid,pid,'stage-1',20)
   result_path=f'/api/v1/academic/departments/{CSE}/reviews/{rid}/results'
   history=self.ok(self.client().get(result_path))['results']
   path=f'/api/v1/staff/departments/{CSE}/intake'
   def send(action,body,who='department-admin'):
    return self.post(path,dict(action=action,**body),who=who)
   columns='Ref,Name,Dept,Number,Semester,Section\n'
   record=f'student-001,Isolated Learner,{dept_code},{profile["usn"]},{profile["semester_key"]},B\n'
   csv_text=columns+record
   self.assertEqual(self.ok(send('HEADERS',dict(csv=csv_text)))['headers'][0],'Ref')
   mapping=dict(key='Ref',name='Name',department='Dept',usn='Number',semester='Semester',section='Section')
   payload=dict(csv=csv_text,source='OFFICIAL',kind='STUDENT',mapping=mapping)
   self.assertEqual(send('PREVIEW',payload,who='faculty-a').status_code,403)
   self.assertTrue(self.ok(send('PREVIEW',dict(payload,csv=csv_text+record)))['issues'])
   self.assertTrue(self.ok(send('PREVIEW',dict(payload,csv=csv_text.replace(dept_code,'WRONG'))))['issues'])
   self.assertEqual(self.ok(send('PREVIEW',payload))['issues'],[])
   first=self.ok(send('APPLY',dict(payload,reference='Synthetic approved export',confirmed=True)))['batchId']
   self.assertEqual(self.ok(send('APPLY',dict(payload,reference='Synthetic approved export',confirmed=True)))['batchId'],first)
   roles=self.db.execute('SELECT count(*) AS count FROM department_role_assignments').fetchone()['count']
   fallback=self.ok(send('APPLY',dict(payload,source='FORM_EXPORT',reference='Isolated forms export',confirmed=True)))['batchId']
   self.assertEqual(self.db.execute('SELECT count(*) AS count FROM department_role_assignments').fetchone()['count'],roles)
   self.assertEqual(self.db.execute('SELECT section FROM student_profiles WHERE user_id=%s',(student,)).fetchone()['section'],profile['section'])
   reconciliation=dict(source='FORM_EXPORT',kind='STUDENT',identityKey='student-001',expectedBatchId=fallback,userId=student,confirmed=True)
   self.ok(send('RECONCILE',reconciliation))
   self.assertEqual(self.db.execute('SELECT section FROM student_profiles WHERE user_id=%s',(student,)).fetchone()['section'],profile['section'])
   corrected=self.ok(send('APPLY',dict(payload,csv=csv_text.replace(',B\n',',C\n'),reference='Corrected official export',confirmed=True)))['batchId']
   self.assertEqual(send('RECONCILE',dict(reconciliation,source='OFFICIAL',expectedBatchId=first)).status_code,409)
   self.ok(send('RECONCILE',dict(reconciliation,source='OFFICIAL',expectedBatchId=corrected)))
   self.assertEqual(self.db.execute('SELECT section FROM student_profiles WHERE user_id=%s',(student,)).fetchone()['section'],'C')
   self.assertEqual(self.ok(self.client().get(result_path))['results'],history)
   faculty_csv=f'Ref,Name,Dept\nstaff-001,Isolated Faculty,{dept_code}\n'
   self.ok(send('APPLY',dict(csv=faculty_csv,mapping={k:mapping[k] for k in ('key','name','department')},
     source='OFFICIAL',kind='FACULTY',reference='Synthetic staff export',confirmed=True)))
   self.assertEqual(self.db.execute('SELECT count(*) AS count FROM department_role_assignments').fetchone()['count'],roles)
  def test_department_intake_pages_search_beyond_first_page_and_require_admin(self):
   path=f'/api/v1/staff/departments/{CSE}/intake'
   code=self.db.execute('SELECT code FROM departments WHERE id=%s',(CSE,)).fetchone()['code']
   csv='Ref,Name,Dept\n'+''.join(f'paging-{i},Paging Faculty {i:02d},{code}\n' for i in range(31))
   response=self.post(path,dict(action='APPLY',csv=csv,mapping=dict(key='Ref',name='Name',department='Dept'),
      source='OFFICIAL',kind='FACULTY',reference='Synthetic paging export',confirmed=True),who='department-admin')
   batch_id=self.ok(response)['batchId']
   admin=self.client('department-admin')
   setup=self.ok(admin.get(f'/api/v1/staff/departments/{CSE}/setup',dict(intake='metadata')))
   self.assertEqual(setup['intake'],dict(departmentCode=code))
   filters=dict(action='LIST',kind='FACULTY',q='Paging Faculty',page=1,batchPage=1)
   first=self.ok(admin.post(path,filters,format='json'))
   second=self.ok(admin.post(path,dict(filters,page=2),format='json'))
   self.assertEqual((first['recordCount'],second['recordCount']),(31,31))
   self.assertEqual((len(first['records']),len(second['records'])),(25,6))
   self.assertTrue({row['identity_key'] for row in first['records']}.isdisjoint(row['identity_key'] for row in second['records']))
   exact=self.ok(admin.post(path,dict(action='LIST',kind='FACULTY',q='paging-30',page=1,batchPage=1),format='json'))
   self.assertEqual([row['identity_key'] for row in exact['records']],['paging-30'])
   self.assertTrue(any(batch['id']==batch_id and batch['actor_name'] for batch in first['batches']))
   self.assertEqual(admin.get(path,dict(page=0)).status_code,400)
   self.assertEqual(admin.get(path.replace(str(CSE),str(uuid4()))).status_code,403)
   for role in ('staff-policy','faculty-a','student-a'):
    self.assertEqual(self.client(role).get(path).status_code,403)
   self.assertFalse(self.db.execute("SELECT EXISTS(SELECT FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a "
    "WHERE p.oid='public.smartpro_department_intake_page(uuid,uuid,text,text,integer,integer)'::regprocedure "
    "AND a.grantee=0 AND a.privilege_type='EXECUTE') AS allowed").fetchone()['allowed'])
  def test_verified_department_directory_pages_and_scope(self):
   path=f'/api/v1/staff/departments/{CSE}/intake'
   admin=self.client('department-admin')
   ids=self.db.execute("INSERT INTO users(display_name,email) SELECT 'Directory Learner '||n,'directory-'||n||'@example.invalid' FROM generate_series(10,40) n RETURNING id,display_name").fetchall()
   for user in ids:
    number=user['display_name'].split()[-1]
    self.db.execute("INSERT INTO student_profiles(user_id,usn,section,semester_key,department_id) VALUES(%s,%s,'B','SYNTHETIC-SEM-3',%s)",(user['id'],'DIRECTORY-'+number,CSE))
   filters=dict(action='DIRECTORY',kind='STUDENT',q='Directory Learner',page=1)
   first=self.ok(admin.post(path,filters,format='json'))
   last=self.ok(admin.post(path,dict(filters,page=2),format='json'))
   self.assertEqual((first['total'],len(first['records']),len(last['records'])),(31,25,6))
   self.assertEqual(last['records'][-1]['usn'],'DIRECTORY-40')
   exact=self.ok(admin.post(path,dict(filters,q='DIRECTORY-40'),format='json'))
   self.assertEqual(exact['records'],[last['records'][-1]])
   self.assertEqual(admin.post(path.replace(str(CSE),str(uuid4())),filters,format='json').status_code,403)
   for who in ('staff-policy','faculty-a','student-a'):
    self.assertEqual(self.client(who).post(path,filters,format='json').status_code,403)
   faculty=self.ok(admin.post(path,dict(filters,kind='FACULTY',q=''),format='json'))
   self.assertGreater(faculty['total'],0)
   self.assertTrue(all(row['usn'] is None for row in faculty['records']))
  def test_multipart_import_outcomes_retry_and_stale_preview(self):
   import json
   from io import BytesIO
   from django.core.files.uploadedfile import SimpleUploadedFile
   from openpyxl import Workbook
   path=f'/api/v1/staff/departments/{CSE}/intake'
   code=self.db.execute('SELECT code FROM departments WHERE id=%s',(CSE,)).fetchone()['code']
   admin=self.client('department-admin')
   mapping=json.dumps(dict(key='Ref',name='Name',department='Dept'))
   def send(action,rows,excel=False,request_key=None,**fields):
    if excel:
     workbook=Workbook()
     for row in [('Ref','Name','Dept'),*rows]:workbook.active.append(row)
     buf=BytesIO()
     workbook.save(buf)
     name,content='source.xlsx',buf.getvalue()
    else:
     name,content='source.csv',('Ref,Name,Dept\n'+''.join(','.join(row)+'\n' for row in rows)).encode()
    payload=dict(action=action,file=SimpleUploadedFile(name,content))
    if action!='HEADERS':
     payload.update(mapping=mapping,source='OFFICIAL',kind='FACULTY',**fields)
    return self.client('department-admin').post(path,payload,format='multipart',HTTP_IDEMPOTENCY_KEY=request_key or uuid4().hex)
   rows=[(f'bulk-{i}',f'Bulk Faculty {i}',code) for i in range(1100)]
   self.assertEqual(self.ok(send('HEADERS',rows,True))['headers'],['Ref','Name','Dept'])
   planned=self.ok(send('PREVIEW',rows,True))
   self.assertEqual(planned['counts']['created'],1100)
   key=uuid4().hex
   apply=dict(reference='Isolated workbook export',confirmed='true',expectedRevision=planned['revision'])
   saved=self.ok(send('APPLY',rows,True,key,**apply))
   self.assertEqual(saved['counts']['created'],1100)
   self.assertEqual(self.ok(send('APPLY',rows,True,key,**apply)),saved)
   self.assertEqual(send('APPLY',rows,True,**apply).status_code,409)
   changed=[('bulk-0','Corrected Faculty Name',code),rows[1]]
   planned=self.ok(send('PREVIEW',changed))
   self.assertEqual(planned['counts'],dict(created=0,updated=1,unchanged=1,rejected=0,conflicts=0))
   updated=self.ok(send('APPLY',changed,reference='Corrected export',confirmed='true',expectedRevision=planned['revision']))
   self.assertEqual(updated['counts'],planned['counts'])
   from threading import Barrier
   variants=[[(rows[2][0],label,code)] for label in ('Race version A','Race version B')]
   revisions=[self.ok(send('PREVIEW',variant))['revision'] for variant in variants]
   barrier=Barrier(2)
   def race(index):
    try:
     barrier.wait(timeout=5)
     return send('APPLY',variants[index],reference='Concurrent correction',confirmed='true',expectedRevision=revisions[index]).status_code
    finally:close_old_connections()
   with ThreadPoolExecutor(max_workers=2) as pool:
    self.assertEqual(sorted(pool.map(race,range(2))),[200,409])
   invalid=self.ok(send('PREVIEW',[rows[2],rows[2],('other','Wrong Department','WRONG')]))
   self.assertEqual((invalid['counts']['conflicts'],invalid['counts']['rejected']),(2,1))
   self.assertEqual(send('PREVIEW',[('formula','=1+1',code)],True).status_code,400)
   page=self.ok(admin.get(path,dict(kind='FACULTY')))
   self.assertTrue(any(batch['id']==updated['batchId'] and batch['outcome']['updated']==1 for batch in page['batches']))
   name=self.db.execute('SELECT display_name FROM users WHERE id=%s',(FACULTY,)).fetchone()['display_name']
   same_name=[('possible-match',name,code),('second-match',name,code)]
   self.ok(send('APPLY',same_name,reference='Ambiguous names',confirmed='true'))
   matches=self.ok(admin.post(path,dict(action='LIST',kind='FACULTY',q='possible-match',page=1,batchPage=1),format='json'))
   row=matches['records'][0]
   self.assertTrue(row['possible_match'])
   self.assertIsNone(row['linked_user_id'])
   targets=self.ok(admin.post(path,dict(action='DIRECTORY',kind='FACULTY',q=name,page=1),format='json'))
   self.assertTrue(any(person['id']==FACULTY for person in targets['records']))
   verified=dict(action='RECONCILE',kind='FACULTY',source='OFFICIAL',identityKey='possible-match',
                 expectedBatchId=row['batch_id'],userId=FACULTY,confirmed=True,evidenceReference='Synthetic employee ID verified')
   self.ok(self.post(path,verified,who='department-admin'))
   self.assertEqual(self.post(path,dict(verified,identityKey='second-match'),who='department-admin').status_code,409)
   self.assertTrue(self.db.execute("SELECT EXISTS(SELECT FROM audit_events WHERE action='INTAKE_RECONCILE' "
     "AND metadata->>'evidenceReference'='Synthetic employee ID verified') AS found").fetchone()['found'])
   from zipfile import ZipFile
   unsafe=BytesIO()
   with ZipFile(unsafe,'w') as archive:
    archive.writestr('unusual.part','<!DOCTYPE test [<!ENTITY payload "x">]><test/>'.encode('utf-16'))
   rejected=admin.post(path,dict(action='HEADERS',file=SimpleUploadedFile('unsafe.xlsx',unsafe.getvalue())),format='multipart')
   self.assertEqual(rejected.status_code,400)
   self.assertIn('unsupported XML',rejected.json()['detail']['message'])

  def test_department_offering_and_appointment_pages_reach_full_scope(self):
   oid=self.offering()
   catalog=f'/api/v1/courses/departments/{CSE}'
   self.db.execute("INSERT INTO curriculum_types(code,label) SELECT 'D1-OFFERING-'||n,'Directory Offering '||n FROM generate_series(100,304) n")
   self.db.execute("INSERT INTO curriculum_offerings(curriculum_type_id,department_id,cycle_id,semester_key) "
    "SELECT id,%s,'11000000-0000-4000-8000-000000000001','SYNTHETIC-SEM-3' FROM curriculum_types WHERE code LIKE 'D1-OFFERING-%%'",(CSE,))
   admin=self.client('department-admin')
   first=self.ok(admin.get(catalog,dict(page=1,q='Directory Offering')))
   final=self.ok(admin.get(catalog,dict(page=9,q='Directory Offering')))
   self.assertEqual((first['total'],len(first['offerings']),len(final['offerings'])),(205,25,5))
   self.assertEqual(final['offerings'][-1]['label'],'Directory Offering 304')
   for version in range(26):self.ok(self.appoint(oid,version=version))
   for client in (admin,self.client()):
    details=self.ok(client.get(catalog,dict(page=9,q='Directory Offering',selected=oid,appointmentPage=2)))
    selected=next(row for row in details['offerings'] if row['id']==oid)
    self.assertEqual(details['appointmentTotal'],26)
    self.assertEqual([term['version'] for term in selected['appointments']],[1])
    self.assertEqual(selected['effective_count'],1)
    self.assertTrue(selected['appointments'][0]['actor_name'])
   self.assertEqual(self.client('student-a').get(catalog,dict(page=1)).status_code,403)
   self.assertEqual(admin.get(catalog.replace(str(CSE),str(uuid4())),dict(page=1)).status_code,403)
  def test_non_hod_faculty_details_and_access_term_history(self):
   """Isolated API check for Admin detail changes and Faculty term lifecycle."""
   department=f'/api/v1/staff/departments/{CSE}'
   person=str(self.db.execute(
      "INSERT INTO users(display_name) VALUES('Original managed faculty') RETURNING id"
   ).fetchone()['id'])
   first_term=str(self.db.execute("""
      INSERT INTO department_role_assignments(user_id,department_id,role_code)
      VALUES(%s,%s,'FACULTY') RETURNING id""",(person,CSE)).fetchone()['id'])
   url=department+'/records/'+person
   admin=self.client('department-admin')
   record=lambda:self.ok(admin.get(url))
   current=record()
   self.assertTrue(current['faculty'])
   self.assertEqual(current['facultyAdmin']['details']['revision'],0)
   self.assertTrue(current['facultyAdmin']['canManage'])
   self.assertEqual(self.client('faculty-a').get(url).status_code,403)
   self.assertEqual(admin.get(f'/api/v1/staff/departments/{uuid4()}/records/{person}').status_code,403)
   def apply(action,**values):
    return self.post(url,dict(action=action,**values),who='department-admin')
   body=dict(displayName='Departmental faculty name',designation='Assistant Professor',
       contactEmail='managed@example.edu',expectedRevision=0,reason='Correct faculty details')
   key=uuid4().hex
   changed=self.ok(self.post(url,dict(action='EDIT_DETAILS',**body),who='department-admin',key=key))
   self.assertEqual(changed['record']['details']['revision'],1)
   self.assertEqual(changed['record']['details']['displayName'],body['displayName'])
   self.assertEqual(self.ok(self.post(url,dict(action='EDIT_DETAILS',**body),
       who='department-admin',key=key)),changed)
   self.assertEqual(apply('EDIT_DETAILS',**body).status_code,409)
   self.assertEqual(self.db.execute(
       'SELECT display_name FROM users WHERE id=%s',(person,)).fetchone()['display_name'],
       'Original managed faculty')
   term=next(x for x in record()['facultyAdmin']['terms'] if x['active'])
   amended=self.ok(apply('AMEND_TERM',termId=first_term,
     expectedAuthorityRevision=term['staff_authority_revision'],
     validUntil='2027-05-01T12:00:00+00:00',
     reason='Plan term validity'))
   self.assertEqual(amended['record']['terms'][0]['id'],first_term)
   self.assertEqual(apply('AMEND_TERM',termId=first_term,
     expectedAuthorityRevision=term['staff_authority_revision'],
     validUntil='2027-06-01T12:00:00+00:00',
     reason='Outdated term revision').status_code,409)
   fresh=next(x for x in record()['facultyAdmin']['terms'] if x['active'])
   self.ok(apply('TERMINATE',termId=first_term,
      expectedAuthorityRevision=fresh['staff_authority_revision'],
      reason='End a term with no ongoing academic responsibilities'))
   self.assertFalse(any(t['active'] for t in record()['facultyAdmin']['terms']))
   self.assertEqual(self.db.execute(
       'SELECT count(*) AS n FROM department_role_assignments WHERE id=%s',
       (first_term,)).fetchone()['n'],1)
   reinstated=self.ok(apply('REINSTATE',reason='Approved fresh Faculty appointment'))
   active=next(t for t in reinstated['record']['terms'] if t['active'])
   self.assertNotEqual(active['id'],first_term)
   self.assertEqual(apply('REINSTATE',reason='Duplicate appointment').status_code,409)
   self.assertEqual(self.db.execute(
      'SELECT count(*) AS n FROM faculty_assignments WHERE faculty_user_id=%s',
      (person,)).fetchone()['n'],0)
   self.assertEqual(self.db.execute(
      "SELECT count(*) AS n FROM audit_events WHERE target_type='FACULTY_RECORD' AND target_id=%s",
      (person,)).fetchone()['n'],4)
   self.assertEqual(self.client('student-a').post(url,
      dict(action='REINSTATE',reason='Not authorized'),format='json').status_code,403)
   # The Admin cannot modify the HOD's active Faculty record.
   hod=str(self.db.execute("""SELECT user_id FROM department_role_assignments
      WHERE department_id=%s AND role_code='HOD'
        AND valid_from<=clock_timestamp() AND
          (valid_until IS NULL OR clock_timestamp()<valid_until)
      LIMIT 1""",(CSE,)).fetchone()['user_id'])
   self.assertEqual(self.post(department+'/records/'+hod,
      dict(action='EDIT_DETAILS',**body),who='department-admin').status_code,403)
   # Immediate app-access revocation must not be blocked by unfinished
   # academic work or the last-Coordinator ordinary appointment safeguard.
   offering=self.offering()
   other='00000000-0000-4000-8000-000000000008'
   self.ok(self.appoint(offering,uid=other))
   assigned_project=self.project(offering,guide_id=person)
   self.framework(offering)
   review=self.ok(self.command(offering,'CREATE_STAGE',
       dict(projectId=assigned_project,stageKey='stage-1',facultyIds=[]),
       who='coordinator'))['id']
   evaluator=str(self.db.execute("""SELECT id FROM evaluator_assignments
       WHERE review_id=%s AND faculty_user_id=%s""",(review,person)).fetchone()['id'])
   solo=self.offering();self.ok(self.appoint(solo,uid=person));self.activate(solo)
   self.assertTrue(self.db.execute('SELECT EXISTS(SELECT 1 FROM smartpro_course_coordinators(%s)) AS ok',
       (solo,)).fetchone()['ok'])
   current_term=next(t for t in record()['facultyAdmin']['terms'] if t['active'])
   termination=dict(action='TERMINATE',termId=current_term['id'],
       expectedAuthorityRevision=current_term['staff_authority_revision'],
       reason='Withdraw SMART-PRO access and hand off academic responsibilities')
   retry_key=uuid4().hex
   first=self.ok(self.post(url,termination,who='department-admin',key=retry_key))
   self.assertEqual(first,self.ok(self.post(url,termination,who='department-admin',key=retry_key)))
   self.assertFalse(any(t['active'] for t in record()['facultyAdmin']['terms']))
   self.assertFalse(self.db.execute('SELECT smartpro_current_project_guide(%s,%s) AS ok',
       (person,assigned_project)).fetchone()['ok'])
   self.assertFalse(self.db.execute('SELECT smartpro_evaluator_active(%s) AS ok',
       (evaluator,)).fetchone()['ok'])
   self.assertFalse(self.db.execute('SELECT EXISTS(SELECT 1 FROM smartpro_course_coordinators(%s)) AS ok',
       (solo,)).fetchone()['ok'])
   handovers=self.db.execute("""SELECT assignment_kind,assignment_id FROM
       faculty_academic_access_handoffs WHERE faculty_term_id=%s""",
       (current_term['id'],)).fetchall()
   queue=self.ok(self.client('coordinator').get(
       f'/api/v1/courses/offerings/{offering}/evaluation-queue',
       {'q':'','status':'all','page':1}))
   shown=next(p for p in queue['projects'] if p['id']==assigned_project)
   self.assertGreaterEqual(shown['facultyAccessHandoverCount'],3)
   self.assertTrue({'GUIDE','REVIEWER','EVALUATOR','COORDINATOR'}<=
       {h['assignment_kind'] for h in handovers})
   with self.assertRaises(psycopg.Error):
    self.db.execute("""UPDATE faculty_academic_access_handoffs
      SET effective_at=clock_timestamp() WHERE faculty_term_id=%s""",
      (current_term['id'],))
   self.assertTrue(self.db.execute("""SELECT valid_until FROM faculty_assignments
       WHERE project_id=%s AND faculty_user_id=%s AND assignment_type='GUIDE'""",
       (assigned_project,person)).fetchone()['valid_until'])
   self.assertEqual(self.db.execute("""SELECT count(*) AS n FROM
       department_role_assignments WHERE id=%s""",
       (current_term['id'],)).fetchone()['n'],1)
   # New Faculty application access never revives the ended Guide, evaluator
   # or immutable Coordinator appointment, even when a login is still valid.
   self.ok(apply('REINSTATE',reason='New Faculty application access term'))
   self.assertFalse(self.db.execute('SELECT smartpro_current_project_guide(%s,%s) AS ok',
       (person,assigned_project)).fetchone()['ok'])
   self.assertFalse(self.db.execute('SELECT smartpro_evaluator_active(%s) AS ok',
       (evaluator,)).fetchone()['ok'])
   self.assertFalse(self.db.execute('SELECT EXISTS(SELECT 1 FROM smartpro_course_coordinators(%s)) AS ok',
       (solo,)).fetchone()['ok'])
   # Authorized existing Coordinator can now explicitly appoint a new Guide.
   self.ok(self.post(f'/api/v1/staff/departments/{CSE}/projects/{assigned_project}/guide',
       dict(facultyId=other,expectedGuideId=None),who='coordinator'))
   self.assertTrue(self.db.execute('SELECT smartpro_current_project_guide(%s,%s) AS ok',
       (other,assigned_project)).fetchone()['ok'])
   self.assertFalse(self.db.execute('SELECT smartpro_current_project_guide(%s,%s) AS ok',
       (person,assigned_project)).fetchone()['ok'])
  def test_expired_faculty_term_reinstatement_never_reactivates_evaluator(self):
   """Natural Faculty term expiry must not revive an old evaluator on reinstatement."""
   person=str(self.db.execute("INSERT INTO users(display_name) VALUES('Expired evaluator fixture') RETURNING id").fetchone()['id'])
   term=str(self.db.execute("""INSERT INTO department_role_assignments(user_id,department_id,role_code)
     VALUES(%s,%s,'FACULTY') RETURNING id""",(person,CSE)).fetchone()['id'])
   other='00000000-0000-4000-8000-000000000008'
   oid=self.offering();self.ok(self.appoint(oid,uid=other))
   pid=self.project(oid,guide_id=other);self.framework(oid)
   rid=self.ok(self.command(oid,'CREATE_STAGE',dict(projectId=pid,stageKey='stage-1',
      facultyIds=[person]),who='coordinator'))['id']
   eid=str(self.db.execute("""SELECT id FROM evaluator_assignments
      WHERE review_id=%s AND faculty_user_id=%s""",(rid,person)).fetchone()['id'])
   self.assertTrue(self.db.execute('SELECT smartpro_evaluator_active(%s) AS ok',(eid,)).fetchone()['ok'])
   # Expire the app role naturally, without the Admin TERMINATE command. This
   # recreates stale academic assignment intervals left after scheduled expiry.
   self.db.execute("""UPDATE department_role_assignments SET valid_until=clock_timestamp()
     WHERE id=%s""",(term,))
   self.assertFalse(self.db.execute("""SELECT smartpro_has_role(%s,%s,'FACULTY',clock_timestamp()) AS ok""",
      (person,CSE)).fetchone()['ok'])
   # Another active departmental role makes the old FACULTY_ACCESS setup
   # path otherwise eligible; it must not bypass assignment cleanup.
   self.db.execute("""INSERT INTO department_role_assignments(user_id,department_id,role_code)
      VALUES(%s,%s,'STUDENT')""",(person,CSE))
   route=f'/api/v1/staff/departments/{CSE}/setup'
   requested=self.ok(self.post(route,dict(action='REQUEST',kind='FACULTY_ACCESS',
      configuration=dict(userId=person,validUntil='2027-06-01T00:00:00Z'),
      reason='Attempt old setup route'),who='department-admin'))['id']
   self.ok(self.post(route,dict(action='APPROVE',requestId=requested),
      who='staff-policy'))
   denied=self.post(route,dict(action='APPLY',requestId=requested),who='department-admin')
   self.assertEqual(denied.status_code,409,denied.content)
   self.ok(self.post(f'/api/v1/staff/departments/{CSE}/records/{person}',
      dict(action='REINSTATE',reason='New academic application access only'),who='department-admin'))
   self.assertTrue(self.db.execute("""SELECT smartpro_has_role(%s,%s,'FACULTY',clock_timestamp()) AS ok""",
      (person,CSE)).fetchone()['ok'])
   self.assertFalse(self.db.execute('SELECT smartpro_evaluator_active(%s) AS ok',(eid,)).fetchone()['ok'],
      'Previously expired evaluation responsibility cannot return without explicit appointment')
   handover=self.db.execute("""SELECT count(*) AS n FROM faculty_academic_access_handoffs
      WHERE faculty_term_id=%s AND assignment_kind='EVALUATOR' AND assignment_id=%s""",
      (term,eid)).fetchone()['n']
   self.assertEqual(handover,1)

  def test_faculty_revocation_concurrent_with_evaluator_assignment(self):
   """Concurrent stage assignment cannot leave revoked Faculty evaluator access."""
   from threading import Barrier
   person=str(self.db.execute("INSERT INTO users(display_name) VALUES('Racing evaluator fixture') RETURNING id").fetchone()['id'])
   term=str(self.db.execute("""INSERT INTO department_role_assignments(user_id,department_id,role_code)
      VALUES(%s,%s,'FACULTY') RETURNING id""",(person,CSE)).fetchone()['id'])
   other='00000000-0000-4000-8000-000000000008'
   oid=self.offering();self.ok(self.appoint(oid,uid=other))
   pid=self.project(oid,guide_id=other);self.framework(oid)
   current=self.ok(self.client('department-admin').get(f'/api/v1/staff/departments/{CSE}/records/{person}'))
   active=next(t for t in current['facultyAdmin']['terms'] if t['active'])
   body=dict(action='TERMINATE',termId=term,
     expectedAuthorityRevision=active['staff_authority_revision'],reason='End application access now')
   gate=Barrier(2)
   def revoke(_):
    close_old_connections()
    try:
     gate.wait(timeout=10)
     return self.post(f'/api/v1/staff/departments/{CSE}/records/{person}',
          body,who='department-admin')
    finally:close_old_connections()
   def assign(_):
    close_old_connections()
    try:
     gate.wait(timeout=10)
     return self.command(oid,'CREATE_STAGE',
       dict(projectId=pid,stageKey='stage-1',facultyIds=[person]),who='coordinator')
    finally:close_old_connections()
   with ThreadPoolExecutor(max_workers=2) as pool:
    a=pool.submit(revoke,None);b=pool.submit(assign,None)
    revoked=a.result(timeout=25);assigned=b.result(timeout=25)
   self.assertEqual(revoked.status_code,200,revoked.content)
   self.assertIn(assigned.status_code,(200,403,409),assigned.content)
   self.assertFalse(self.db.execute("""SELECT smartpro_has_role(%s,%s,'FACULTY',clock_timestamp()) AS ok""",
      (person,CSE)).fetchone()['ok'])
   remaining=self.db.execute("""SELECT e.id,smartpro_evaluator_active(e.id) AS active
      FROM evaluator_assignments e JOIN project_reviews r ON r.id=e.review_id
      WHERE r.project_id=%s AND e.faculty_user_id=%s""",(pid,person)).fetchall()
   self.assertFalse(any(row['active'] for row in remaining),
     'Revocation must close any simultaneously created evaluator assignment')

  def test_faculty_identity_crosswalk_and_candidate_discovery(self):
   from threading import Barrier
   from unittest.mock import patch
   base=f'/api/v1/staff/departments/{CSE}'
   admin=self.client('department-admin')
   faculty=[]
   for _ in range(2):
    uid=str(self.db.execute("INSERT INTO users(display_name) VALUES('Crosswalk Faculty') RETURNING id").fetchone()['id'])
    self.db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'FACULTY')",(uid,CSE))
    faculty.append(uid)
   self.db.execute("WITH generated AS (INSERT INTO users(display_name) SELECT 'Candidate Scale '||n FROM generate_series(100,304) n RETURNING id) "
                   "INSERT INTO department_role_assignments(user_id,department_id,role_code) SELECT id,%s,'FACULTY' FROM generated",(CSE,))
   candidates=self.ok(admin.post(base+'/appointment-candidates',dict(q='Candidate Scale',page=9),format='json'))
   self.assertEqual((candidates['total'],len(candidates['records'])),(205,5))
   self.assertEqual(candidates['records'][-1]['display_name'],'Candidate Scale 304')
   self.assertEqual(self.client('faculty-a').post(base+'/appointment-candidates',dict(q='',page=1),format='json').status_code,403)
   self.assertEqual(self.client('faculty-a').get(base+'/records/'+faculty[0]).status_code,403)
   self.assertEqual(admin.get(base.replace(str(CSE),str(uuid4()))+'/records/'+faculty[0]).status_code,403)
   oid=self.offering();self.ok(self.appoint(oid,uid=faculty[0]))
   history=self.db.execute('SELECT to_jsonb(v) AS row FROM course_coordinator_versions v WHERE offering_id=%s',(oid,)).fetchall()
   from smartpro.setup_views import faculty_crosswalk_roster
   refs=[r['ref'] for r in faculty_crosswalk_roster()[:2]]
   def command(i,action,**data):
    return self.post(base+'/records/'+faculty[i],dict(action=action,**data),who='department-admin')
   with patch('smartpro.demo_views.faculty_reference_enabled',return_value=True):
    self.assertEqual(command(0,'PROPOSE',directoryRef=refs[0],source='fixture',identifier='',evidence='').status_code,400)
    proposals=[]
    for index,ref in enumerate(refs):
     data=dict(directoryRef=ref,source='Synthetic register',identifier='SYN-057',evidence='Synthetic checked source')
     link=self.ok(command(index,'PROPOSE',**data))
     self.assertEqual(link['state'],'PROPOSED')
     self.assertEqual(self.ok(command(index,'PROPOSE',**data))['id'],link['id'])
     proposals.append(link['id'])
    barrier=Barrier(2)
    def verify(i):
     try:
      barrier.wait(timeout=5)
      return command(i,'VERIFY',linkId=proposals[i],evidence='Synthetic reviewer verified identifier').status_code
     finally:close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:outcomes=list(pool.map(verify,range(2)))
    self.assertEqual(sorted(outcomes),[200,409])
    winner=outcomes.index(200)
    record=self.ok(admin.get(base+'/records/'+faculty[winner]))
    self.assertEqual(record['links'][0]['state'],'VERIFIED')
    self.assertTrue(any(event['action']=='FACULTY_IDENTITY_VERIFY' for event in record['history']))
    self.ok(command(winner,'REVOKE',linkId=proposals[winner],evidence='Synthetic revocation'))
    self.ok(command(1-winner,'VERIFY',linkId=proposals[1-winner],evidence='Synthetic corrected association'))
   self.assertEqual(self.db.execute('SELECT to_jsonb(v) AS row FROM course_coordinator_versions v WHERE offering_id=%s',(oid,)).fetchall(),history)
  def test_finalized_correction_requires_specific_independent_authorization(self):
   oid=self.offering();self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'));pid=self.project(oid);self.framework(oid);rid,aid,scores=self.stage(oid,pid,'stage-1',20)
   rev=self.db.execute('SELECT revision FROM academic_review_bindings WHERE review_id=%s',(rid,)).fetchone()['revision']
   changed=[dict(s,marks='21') for s in scores];body=dict(assessmentId=aid,expectedReviewRevision=rev,scores=changed)
   self.assertEqual(self.post(f'/api/v1/academic/departments/{CSE}/reviews/{rid}/evaluations',body,who='faculty-a').status_code,403)
   request=self.ok(self.command(oid,'REQUEST_CORRECTION',dict(reviewId=rid,**body),who='faculty-a'))['id']
   self.ok(self.appoint(oid,uid=FACULTY,permissions=['CORRECTIONS']))
   self.assertEqual(self.command(oid,'AUTHORIZE_CORRECTION',dict(requestId=request,approved=True),who='faculty-a',role='Coordinator').status_code,403)
   self.ok(self.command(oid,'AUTHORIZE_CORRECTION',dict(requestId=request,approved=True),who='coordinator'))
   self.ok(self.command(oid,'APPLY_CORRECTION',dict(requestId=request),who='faculty-a'))
   releases=self.db.execute('SELECT results FROM academic_result_versions WHERE review_id=%s ORDER BY version_no',(rid,)).fetchall();self.assertEqual([x['results']['00000000-0000-4000-8000-000000000001'] for x in releases],['40.00','42.00'])
   self.assertEqual(self.command(oid,'APPLY_CORRECTION',dict(requestId=request),who='coordinator',role='Faculty').status_code,403)
  def test_coordinator_corrects_own_finalized_marks_before_overall_release(self):
   oid=self.offering();self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'))
   pid=self.project(oid);self.framework(oid);rid,aid,scores=self.stage(oid,pid,'stage-1',20)
   self.ok(self.appoint(oid,uid=FACULTY,permissions=['CORRECTIONS']))
   def proposal(mark):
    revision=self.db.execute('SELECT revision FROM academic_review_bindings WHERE review_id=%s',(rid,)).fetchone()['revision']
    return dict(reviewId=rid,assessmentId=aid,expectedReviewRevision=revision,scores=[dict(score,marks=mark) for score in scores])
   body=proposal('21');key=uuid4().hex
   applied=self.ok(self.command(oid,'REQUEST_CORRECTION',body,who='faculty-a',key=key))
   self.assertTrue(applied['appliedImmediately'])
   self.assertEqual(self.ok(self.command(oid,'REQUEST_CORRECTION',body,who='faculty-a',key=key)),applied)
   self.assertIsNone(self.db.execute('SELECT request_id FROM course_correction_authorizations WHERE request_id=%s',(applied['id'],)).fetchone())
   def releases():
    return [x['results']['00000000-0000-4000-8000-000000000001'] for x in self.db.execute('SELECT results FROM academic_result_versions WHERE review_id=%s ORDER BY version_no',(rid,)).fetchall()]
   self.assertEqual(releases(),['40.00','42.00'])
   self.ok(self.command(oid,'PUBLISH_FINAL',dict(projectId=pid,expectedVersion=0),who='coordinator'))
   self.assertEqual(self.command(oid,'REQUEST_CORRECTION',proposal('22'),who='faculty-a').status_code,403)
   self.assertEqual(releases(),['40.00','42.00'])
  def test_concurrent_final_publication_closes_approved_ordinary_correction(self):
   from threading import Barrier
   oid=self.offering()
   self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'))
   pid=self.project(oid);self.framework(oid);rid,aid,scores=self.stage(oid,pid,'stage-1',20)
   rev=self.db.execute('SELECT revision FROM academic_review_bindings WHERE review_id=%s',(rid,)).fetchone()['revision']
   request=self.ok(self.command(oid,'REQUEST_CORRECTION',dict(reviewId=rid,assessmentId=aid,expectedReviewRevision=rev,
     scores=[dict(score,marks='21') for score in scores]),who='faculty-a'))['id']
   self.ok(self.command(oid,'AUTHORIZE_CORRECTION',dict(requestId=request,approved=True),who='coordinator'))
   barrier=Barrier(2)
   def publish():
    try:
     barrier.wait(timeout=5)
     return self.command(oid,'PUBLISH_FINAL',dict(projectId=pid,expectedVersion=0),who='coordinator').status_code
    finally:close_old_connections()
   with ThreadPoolExecutor(max_workers=2) as workers:
    statuses=list(workers.map(lambda _:publish(),range(2)))
   self.assertEqual(sorted(statuses),[200,409])
   self.assertEqual(self.command(oid,'APPLY_CORRECTION',dict(requestId=request),who='faculty-a').status_code,403)
   self.assertEqual(self.db.execute('SELECT count(*) AS n FROM course_final_results WHERE project_id=%s',(pid,)).fetchone()['n'],1)
   self.assertEqual(self.db.execute('SELECT count(*) AS n FROM academic_result_versions WHERE review_id=%s',(rid,)).fetchone()['n'],1)

  def test_deadline_scheduler_dedup_completion_and_revision(self):
   from datetime import datetime,timedelta,timezone
   from synthetic_synopsis import pdf_bytes
   from django.core.files.uploadedfile import SimpleUploadedFile
   oid=self.offering();self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'));pid=self.project(oid);cfg=self.framework(oid)
   cfg['deadlineRules']=dict(kinds=['DOCUMENT','REVISION','EVALUATION','REVIEW','MILESTONE','FINAL_SUBMISSION'],earliestAt='2026-01-01T00:00:00Z',latestAt='2027-06-10T00:00:00Z',maxReminderHours=168)
   f=self.ok(self.command(oid,'FRAMEWORK',dict(expectedVersion=1,configuration=cfg,authority=None)))['id'];self.ok(self.command(oid,'PLAN',dict(expectedVersion=1,frameworkId=f,schedules={'stage-1':'2026-12-01T09:00:00Z'}),who='coordinator'))
   body=dict(deadlineKey='synopsis-submission',expectedVersion=0,projectId=None,kind='DOCUMENT',target='SYNOPSIS',name='Configured synopsis deadline',dueAt=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(),reminderHours=[24,1],notifyRoles=['Student','Faculty','Coordinator','HOD'],active=True)
   d=self.ok(self.command(oid,'DEADLINE',body,who='coordinator'))
   def dispatch():return self.db.execute('SELECT smartpro_dispatch_course_notifications() n').fetchone()['n']
   def alerts(who):return self.ok(self.client(who).get('/api/v1/me/course-notifications'))['alerts']
   dispatch();self.assertTrue(any(a['project_id']==pid and a['bucket']=='OVERDUE' for a in alerts('student-a')))
   self.assertEqual(dispatch()['generatedInApp'],0)
   base=f'/api/v1/documents/departments/{CSE}'
   # The configured window actually closes uploads, not just their warning label.
   upload=lambda:self.client('student-a').post(base+f'/projects/{pid}/uploads',{'file':SimpleUploadedFile('synopsis.pdf',pdf_bytes(),content_type='application/pdf')},format='multipart',HTTP_IDEMPOTENCY_KEY=uuid4().hex)
   self.assertEqual(upload().status_code,409)
   body.update(expectedVersion=d['version'],dueAt=(datetime.now(timezone.utc)+timedelta(hours=20)).isoformat(),reminderHours=[48,24]);d=self.ok(self.command(oid,'DEADLINE',body,who='coordinator'));dispatch()
   self.assertTrue(any(a['project_id']==pid and a['deadline_id']==d['id'] and a['bucket']=='DUE:24' for a in alerts('student-a')))
   vid=self.ok(upload())['documentVersionId'];case=next(p for p in self.ok(self.client('student-a').get(base))['projects'] if p['id']==pid)['case']
   self.ok(self.post(base,dict(action='SUBMIT',projectId=pid,documentVersionId=vid,expectedCaseVersion=case['version']),who='student-a'));dispatch()
   self.assertFalse(any(a['project_id']==pid for a in alerts('student-a')))
   self.assertTrue(any(a['project_id']==pid for a in alerts('faculty-a')))
   self.assertFalse(any(a['project_id']==pid for a in alerts('coordinator') if a['kind']=='EVALUATION'))
   history=self.db.execute('SELECT count(*) n FROM course_notification_history').fetchone()['n'];self.assertGreater(history,0)
   self.assertEqual(self.command(oid,'DEADLINE',dict(body,dueAt='2027-12-01T00:00:00Z',expectedVersion=d['version']),who='coordinator').status_code,400)
  def test_exceptional_overall_correction_not_blocked_by_stage_policy(self):
   """The approved Guide->Coordinator overall release works on a pinned
   stage-correction-disabled plan without reopening finalized stage marks."""
   oid=self.offering();self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'))
   pid=self.project(oid);self.framework(oid,allow_final_corrections=False)
   rid,aid,scores=self.stage(oid,pid,'stage-1',20)
   original=self.ok(self.command(oid,'PUBLISH_FINAL',dict(projectId=pid,expectedVersion=0)))['id']
   flag=self.db.execute("""SELECT (fw.configuration->>'allowFinalCorrections')::boolean AS enabled
     FROM course_final_results r JOIN course_plan_versions cp ON cp.id=r.plan_id
     JOIN course_framework_versions fw ON fw.id=cp.framework_id
     WHERE r.project_id=%s ORDER BY r.version DESC LIMIT 1""",(pid,)).fetchone()
   self.assertFalse(flag['enabled'])
   before=self.db.execute('SELECT to_jsonb(r) AS data FROM course_final_results r WHERE r.id=%s',(original,)).fetchone()['data']
   stage_before=self.db.execute('SELECT to_jsonb(r) AS data FROM academic_result_versions r WHERE r.review_id=%s ORDER BY version_no',(rid,)).fetchall()
   # Stage-mark change remains denied, regardless of exceptional overall workflow.
   rev=self.db.execute('SELECT revision FROM academic_review_bindings WHERE review_id=%s',(rid,)).fetchone()['revision']
   ordinary=dict(reviewId=rid,assessmentId=aid,expectedReviewRevision=rev,
                 scores=[dict(score,marks='21') for score in scores])
   self.assertEqual(self.command(oid,'REQUEST_CORRECTION',ordinary,who='faculty-a').status_code,403)
   # The assigned Guide sees the project through BOTH supported read paths.
   legacy=self.ok(self.client('faculty-a').get('/api/v1/me/published-corrections'))
   self.assertIn(pid,[row['projectId'] for row in legacy['projects']])
   scoped=self.ok(self.client('faculty-a').get('/api/v1/me/published-corrections?projectId='+pid))
   self.assertEqual(scoped['project']['projectId'],pid)
   self.assertEqual(self.client('student-a').get('/api/v1/me/published-corrections?projectId='+pid).status_code,403)
   proposal=dict(projectId=pid,expectedVersion=1,
     studentId='00000000-0000-4000-8000-000000000001',marks='42.00',
     reason='Specific exceptional published overall correction')
   self.assertEqual(self.command(oid,'REQUEST_FINAL_REVISION',proposal,who='coordinator').status_code,403)
   key=uuid4().hex
   req=self.ok(self.command(oid,'REQUEST_FINAL_REVISION',proposal,who='faculty-a',key=key))
   self.assertEqual(req,self.ok(self.command(oid,'REQUEST_FINAL_REVISION',proposal,who='faculty-a',key=key)))
   self.assertEqual(self.command(oid,'REQUEST_FINAL_REVISION',dict(proposal,marks='43.00'),who='faculty-a',key=key).status_code,409)
   queue=self.ok(self.client('coordinator').get(f'/api/v1/courses/offerings/{oid}/final-revisions?page=1'))
   self.assertIn(req['id'],[row['id'] for row in queue['requests']])
   self.assertEqual(self.command(oid,'AUTHORIZE_FINAL_REVISION',dict(requestId=req['id'],approved=True),who='student-a').status_code,403)
   decision=dict(requestId=req['id'],approved=True)
   approved=self.ok(self.command(oid,'AUTHORIZE_FINAL_REVISION',decision,who='coordinator'))
   self.assertEqual(approved['newVersion'],2)
   rows=self.db.execute('SELECT * FROM course_final_results WHERE project_id=%s ORDER BY version',(pid,)).fetchall()
   self.assertEqual([r['version'] for r in rows],[1,2])
   self.assertEqual(str(rows[1]['supersedes_id']),original)
   self.assertEqual(rows[0]['sources'],rows[1]['sources'])
   self.assertEqual([r['results']['00000000-0000-4000-8000-000000000001'] for r in rows],['40.00','42.00'])
   self.assertEqual(self.db.execute('SELECT to_jsonb(r) AS data FROM course_final_results r WHERE r.id=%s',(original,)).fetchone()['data'],before)
   self.assertEqual(self.db.execute('SELECT to_jsonb(r) AS data FROM academic_result_versions r WHERE r.review_id=%s ORDER BY version_no',(rid,)).fetchall(),stage_before)
   student=self.ok(self.client('student-a').get(f'/api/v1/documents/departments/{CSE}?project={pid}'))
   item=next(p for p in student['projects'] if p['id']==pid)
   self.assertEqual([r['version'] for r in item['overallResults']],[1,2])
   self.assertEqual(self.command(oid,'AUTHORIZE_FINAL_REVISION',decision,who='coordinator').status_code,409)
   self.assertEqual(self.db.execute('SELECT count(*) n FROM course_final_revision_authorizations WHERE request_id=%s',(req['id'],)).fetchone()['n'],1)

  def test_direct_correction_does_not_reopen_stage_evidence(self):
   oid=self.offering();self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'))
   pid=self.project(oid);self.framework(oid)
   rid,aid,scores=self.stage(oid,pid,'stage-1',20)
   original=self.ok(self.command(oid,'PUBLISH_FINAL',dict(projectId=pid,expectedVersion=0)))['id']
   frozen=self.db.execute('SELECT to_jsonb(v) AS evidence FROM academic_result_versions v WHERE review_id=%s ORDER BY version_no',(rid,)).fetchall()
   assigned=self.db.execute("""SELECT public.smartpro_current_project_guide(%s,%s) AS allowed,
      (SELECT jsonb_agg(to_jsonb(g)) FROM faculty_assignments g WHERE g.project_id=%s) AS guide_assignments,
      public.smartpro_role_choices(%s) AS roles,
      (SELECT jsonb_agg(to_jsonb(r)) FROM department_role_assignments r WHERE r.user_id=%s) AS faculty_roles""",
      (FACULTY,pid,pid,FACULTY,FACULTY)).fetchone()
   self.assertTrue(assigned['allowed'],f"Assigned Guide scope in synthetic fixture: {assigned}")
   proposal=dict(projectId=pid,expectedVersion=1,studentId='00000000-0000-4000-8000-000000000001',marks='42.00',reason='Correct an incorrect published overall mark')
   self.assertEqual(self.command(oid,'REQUEST_FINAL_REVISION',proposal).status_code,403)
   k=uuid4().hex
   req=self.ok(self.command(oid,'REQUEST_FINAL_REVISION',proposal,who='faculty-a',key=k))
   self.assertEqual(req,self.ok(self.command(oid,'REQUEST_FINAL_REVISION',proposal,who='faculty-a',key=k)))
   self.assertEqual(self.command(oid,'REQUEST_FINAL_REVISION',dict(proposal,marks='43.00'),who='faculty-a',key=k).status_code,409)
   self.assertEqual(self.command(oid,'AUTHORIZE_FINAL_REVISION',dict(requestId=req['id'],approved=True),who='student-a').status_code,403)
   decision=dict(requestId=req['id'],approved=True)
   dk=uuid4().hex
   ok=self.ok(self.command(oid,'AUTHORIZE_FINAL_REVISION',decision,who='coordinator',key=dk))
   self.assertEqual(ok,self.ok(self.command(oid,'AUTHORIZE_FINAL_REVISION',decision,who='coordinator',key=dk)))
   v=self.db.execute('SELECT * FROM course_final_results WHERE project_id=%s ORDER BY version',(pid,)).fetchall()
   self.assertEqual([row['results']['00000000-0000-4000-8000-000000000001'] for row in v],['40.00','42.00'])
   self.assertEqual(str(v[-1]['supersedes_id']),original)
   self.assertEqual(v[0]['sources'],v[-1]['sources'])
   self.assertEqual(self.command(oid,'REQUEST_FINAL_REVISION',
      dict(projectId=pid,expectedVersion=2,mode='STAGE_EVIDENCE',
           reason='Attempt to republish unchanged stage evidence'),
      who='faculty-a').status_code,409)
   self.assertEqual(self.db.execute('SELECT to_jsonb(v) AS evidence FROM academic_result_versions v WHERE review_id=%s ORDER BY version_no',(rid,)).fetchall(),frozen)
   self.assertEqual(self.command(oid,'AUTHORIZE_FINAL_REVISION',decision,who='coordinator').status_code,409)
   self.assertEqual(self.command(oid,'REQUEST_EXCEPTIONAL_STAGE_CORRECTION',dict(reviewId=rid,assessmentId=aid,expectedReviewRevision=0,scores=scores),who='faculty-a').status_code,400)

  def test_real_authorized_stage_evidence_rerelease_via_http_correction_commands(self):
   """No owner-seeded result version: evaluator, Coordinator and Guide use the
   actual existing HTTP correction workflow under an isolated pinned true flag."""
   oid=self.offering()
   self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'))
   pid=self.project(oid)
   self.framework(oid,allow_final_corrections=True)
   rid,aid,scores=self.stage(oid,pid,'stage-1',20)
   initial=self.ok(self.command(oid,'PUBLISH_FINAL',
       dict(projectId=pid,expectedVersion=0),who='coordinator'))['id']
   revision=self.db.execute(
       'SELECT revision FROM academic_review_bindings WHERE review_id=%s',(rid,)
   ).fetchone()['revision']
   updated=[dict(s,marks='21') for s in scores]
   body=dict(reviewId=rid,assessmentId=aid,expectedReviewRevision=revision,
             scores=updated,reason='Correct specific synthetic stage criterion')
   self.assertEqual(self.command(oid,'REQUEST_CORRECTION',dict(body,exceptional=False),
       who='faculty-a').status_code,403)
   self.assertEqual(self.command(oid,'REQUEST_CORRECTION',dict(body,exceptional='true'),
       who='faculty-a').status_code,400)
   request=self.ok(self.command(oid,'REQUEST_CORRECTION',
       dict(body,exceptional=True),who='faculty-a'))['id']
   self.assertEqual(self.command(oid,'AUTHORIZE_CORRECTION',
       dict(requestId=request,approved=True,exceptional=False),
       who='coordinator').status_code,403)
   self.assertEqual(self.command(oid,'AUTHORIZE_CORRECTION',
       dict(requestId=request,approved=True,exceptional=True),
       who='student-a').status_code,403)
   self.ok(self.command(oid,'AUTHORIZE_CORRECTION',
       dict(requestId=request,approved=True,exceptional=True),who='coordinator'))
   self.ok(self.command(oid,'APPLY_CORRECTION',
       dict(requestId=request,exceptional=True),who='faculty-a'))
   stage=self.db.execute('SELECT version_no,results,supersedes_id FROM academic_result_versions WHERE review_id=%s ORDER BY version_no',(rid,)).fetchall()
   self.assertEqual([row['version_no'] for row in stage],[1,2])
   self.assertEqual([row['results']['00000000-0000-4000-8000-000000000001'] for row in stage],['40.00','42.00'])
   self.assertIsNotNone(stage[1]['supersedes_id'])
   self.assertEqual(self.db.execute('SELECT COUNT(*) n FROM course_final_results WHERE project_id=%s',(pid,)).fetchone()['n'],1)
   reissue=self.ok(self.command(oid,'REQUEST_FINAL_REVISION',
       dict(projectId=pid,expectedVersion=1,mode='STAGE_EVIDENCE',
            reason='Release independently corrected stage evidence'),
       who='faculty-a'))['id']
   self.assertEqual(self.command(oid,'AUTHORIZE_FINAL_REVISION',
       dict(requestId=reissue,approved=True),who='student-a').status_code,403)
   self.ok(self.command(oid,'AUTHORIZE_FINAL_REVISION',
       dict(requestId=reissue,approved=True),who='coordinator'))
   totals=self.db.execute('SELECT id,version,supersedes_id,results,sources FROM course_final_results WHERE project_id=%s ORDER BY version',(pid,)).fetchall()
   self.assertEqual([r['version'] for r in totals],[1,2])
   self.assertEqual(str(totals[1]['supersedes_id']),initial)
   self.assertNotEqual(totals[0]['sources'],totals[1]['sources'])
   self.assertEqual([r['results']['00000000-0000-4000-8000-000000000001'] for r in totals],['40.00','42.00'])
   student=self.ok(self.client('student-a').get(f'/api/v1/documents/departments/{CSE}?project={pid}'))
   item=next(x for x in student['projects'] if x['id']==pid)
   self.assertEqual([r['version'] for r in item['overallResults']],[1,2])

  def test_release_previously_corrected_stage_evidence_on_guide_request(self):
   """An isolated stage result-version fixture represents evidence already
   corrected by the approved evaluation workflow; no stage-edit API is added."""
   oid=self.offering()
   self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'))
   pid=self.project(oid);self.framework(oid)
   rid,_,_=self.stage(oid,pid,'stage-1',20)
   initial=self.ok(self.command(oid,'PUBLISH_FINAL',dict(projectId=pid,expectedVersion=0)))['id']
   request=dict(projectId=pid,expectedVersion=1,mode='STAGE_EVIDENCE',reason='Release corrected stage scores')
   self.assertEqual(self.command(oid,'REQUEST_FINAL_REVISION',request,who='faculty-a').status_code,409)
   self.assertEqual(self.command(oid,'REQUEST_FINAL_REVISION',request).status_code,403)
   self.db.execute("""INSERT INTO academic_result_versions
       (review_id,version_no,supersedes_id,legacy_release_id,roster_version_id,
        policy_id,actor_id,reason,sources,results,calculation_version)
       SELECT review_id,version_no+1,id,legacy_release_id,roster_version_id,
          policy_id,actor_id,'Synthetic corrected stage release',
          jsonb_set(sources,'{0,scores,0,marks}',to_jsonb('22'::text),false),
          jsonb_set(results,ARRAY['00000000-0000-4000-8000-000000000001'],to_jsonb('42.00'::text)),
          calculation_version
       FROM academic_result_versions WHERE review_id=%s
       ORDER BY version_no DESC LIMIT 1""",(rid,))
   issued=self.ok(self.command(oid,'REQUEST_FINAL_REVISION',request,who='faculty-a'))['id']
   guide=self.ok(self.client('faculty-a').get('/api/v1/me/published-corrections'))
   visible=next(p for p in guide['projects'] if p['projectId']==pid)
   self.assertTrue(any(q['id']==issued and q['type']=='STAGE_EVIDENCE_OVERALL_CORRECTION' for q in visible['requests']))
   details=self.ok(self.client('coordinator').get(f'/api/v1/courses/offerings/{oid}/details'))
   self.assertTrue(any(q['id']==issued and q['snapshot']['type']=='STAGE_EVIDENCE_OVERALL_CORRECTION' for q in details['finalRevisions']))
   self.assertEqual(self.command(oid,'AUTHORIZE_FINAL_REVISION',dict(requestId=issued,approved=True),who='student-a').status_code,403)
   self.ok(self.command(oid,'AUTHORIZE_FINAL_REVISION',dict(requestId=issued,approved=True),who='coordinator'))
   rows=self.db.execute('SELECT id,version,supersedes_id,sources,results FROM course_final_results WHERE project_id=%s ORDER BY version',(pid,)).fetchall()
   self.assertEqual([x['version'] for x in rows],[1,2])
   self.assertEqual(str(rows[1]['supersedes_id']),initial)
   self.assertEqual([x['results']['00000000-0000-4000-8000-000000000001'] for x in rows],['40.00','42.00'])
   self.assertNotEqual(rows[0]['sources'],rows[1]['sources'])

  def test_paged_published_corrections_over_125_and_authority(self):
   """Use isolated synthetic rows to expose old 100-item truncation."""
   from urllib.parse import quote
   oid=self.offering()
   self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'))
   pid=self.project(oid);self.framework(oid);self.stage(oid,pid,'stage-1',20)
   original=self.ok(self.command(oid,'PUBLISH_FINAL',dict(projectId=pid,expectedVersion=0)))['id']
   base=f'/api/v1/courses/offerings/{oid}/final-revisions'
   guide='/api/v1/me/published-corrections'
   ids=[]
   for n in range(126):
    ids.append(self.ok(self.command(oid,'REQUEST_FINAL_REVISION',dict(
      projectId=pid,expectedVersion=1,
      studentId='00000000-0000-4000-8000-000000000001',
      marks='42.00',reason='Synthetic request '+str(n)),who='faculty-a'))['id'])
   head=self.ok(self.client('coordinator').get(base+'?page=1'))
   self.assertEqual((head['total'],len(head['requests']),head['pageSize']),(126,25,25))
   seen=[]
   for n in range(1,7):
    row=self.ok(self.client('coordinator').get(
      base+'?page='+str(n)+'&anchor='+quote(head['anchor'],safe='')))
    seen.extend(q['id'] for q in row['requests'])
   self.assertEqual(set(seen),set(ids))
   self.assertEqual(len(seen),126)
   self.assertEqual(self.client('student-a').get(base).status_code,403)
   self.assertEqual(self.client('faculty-a').get(base).status_code,403)
   self.assertEqual(self.client('coordinator').get(base+'?page=0').status_code,400)
   first=self.ok(self.client('faculty-a').get(guide+f'?projectId={pid}'))
   self.assertEqual((first['project']['projectId'],first['total']), (pid,126))
   seen=[]
   for n in range(1,7):
    row=self.ok(self.client('faculty-a').get(
      guide+f'?projectId={pid}&page={n}&anchor='+quote(first['anchor'],safe='')))
    seen.extend(q['id'] for q in row['requests'])
   self.assertEqual(set(seen),set(ids))
   self.assertEqual(self.client('student-a').get(guide+f'?projectId={pid}').status_code,403)
   # All links must point to the current Guide, not simply any faculty member.
   late=None
   for n in range(126):
    team=self.db.execute("""INSERT INTO public.teams
     (department_id,cycle_id,curriculum_offering_id,name)
     SELECT t.department_id,t.cycle_id,t.curriculum_offering_id,%s
     FROM public.teams t JOIN public.projects p ON p.team_id=t.id
     WHERE p.id=%s RETURNING id""",(f'Synthetic correction team {n}',pid)).fetchone()['id']
    late=self.db.execute("""INSERT INTO public.projects
     (department_id,cycle_id,team_id,project_type,policy_version_id,project_code,title)
     SELECT department_id,cycle_id,%s,project_type,policy_version_id,%s,%s
     FROM public.projects WHERE id=%s RETURNING id""",
     (team,'COR-PAGE-'+uuid4().hex[:16],f'ZZZ correction project {n:03d}',pid)).fetchone()['id']
    self.db.execute("INSERT INTO public.faculty_assignments(project_id,faculty_user_id,assignment_type) VALUES(%s,%s,'GUIDE')",(late,FACULTY))
    self.db.execute("""INSERT INTO public.course_final_results(project_id,plan_id,version,sources,results,actor_id)
     SELECT %s,plan_id,version,sources,results,actor_id FROM public.course_final_results
     WHERE project_id=%s ORDER BY version DESC LIMIT 1""",(late,pid))
   legacy=self.ok(self.client('faculty-a').get(guide))
   self.assertNotIn(str(late),[p['projectId'] for p in legacy['projects']])
   scoped=self.ok(self.client('faculty-a').get(guide+f'?projectId={late}'))
   self.assertEqual(scoped['project']['projectId'],str(late))
   self.assertIsNone(self.ok(self.client('faculty-a').get(guide+f'?projectId={uuid4()}'))['project'])
   self.assertEqual(self.db.execute("SELECT count(*) AS n FROM course_final_results WHERE project_id=%s",(pid,)).fetchone()['n'],1)
   self.ok(self.command(oid,'AUTHORIZE_FINAL_REVISION',dict(requestId=ids[0],approved=True),who='coordinator'))
   rows=self.db.execute("SELECT id,supersedes_id FROM course_final_results WHERE project_id=%s ORDER BY version",(pid,)).fetchall()
   self.assertEqual(len(rows),2)
   self.assertEqual(str(rows[0]['id']),original)
   self.assertEqual(rows[1]['supersedes_id'],rows[0]['id'])

  def test_guide_coordinator_same_person_can_propose_and_approve(self):
   oid=self.offering();self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'))
   pid=self.project(oid);self.framework(oid,allow_final_corrections=False);self.stage(oid,pid,'stage-1',20)
   self.ok(self.appoint(oid,uid=FACULTY,permissions=['CORRECTIONS']))
   self.ok(self.command(oid,'PUBLISH_FINAL',dict(projectId=pid,expectedVersion=0)))
   req=self.ok(self.command(oid,'REQUEST_FINAL_REVISION',dict(projectId=pid,expectedVersion=1,
     studentId='00000000-0000-4000-8000-000000000001',marks='42.00',reason='Correct published total'),
     who='faculty-a',role='Faculty'))['id']
   self.ok(self.command(oid,'AUTHORIZE_FINAL_REVISION',dict(requestId=req,approved=True),who='faculty-a',role='Coordinator'))
   self.assertEqual([r['version'] for r in self.db.execute('SELECT version FROM course_final_results WHERE project_id=%s ORDER BY version',(pid,)).fetchall()],[1,2])
   self.assertEqual(self.db.execute('SELECT count(*) n FROM course_final_revision_authorizations WHERE request_id=%s',(req,)).fetchone()['n'],1)

  def test_decline_and_stale_direct_correction_do_not_change_previous_release(self):
   oid=self.offering();self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'))
   pid=self.project(oid);self.framework(oid);self.stage(oid,pid,'stage-1',20)
   self.ok(self.command(oid,'PUBLISH_FINAL',dict(projectId=pid,expectedVersion=0)))
   proposal=dict(projectId=pid,expectedVersion=1,
     studentId='00000000-0000-4000-8000-000000000001',marks='42.00',reason='Correct published total')
   self.assertEqual(self.command(oid,'REQUEST_FINAL_REVISION',proposal,who='coordinator',role='Faculty').status_code,403)
   self.assertEqual(self.command(oid,'REQUEST_FINAL_REVISION',dict(proposal,marks='9999'),who='faculty-a').status_code,400)
   self.assertEqual(self.command(oid,'REQUEST_FINAL_REVISION',dict(proposal,reason=''),who='faculty-a').status_code,400)
   denied=self.ok(self.command(oid,'REQUEST_FINAL_REVISION',proposal,who='faculty-a'))['id']
   self.ok(self.command(oid,'AUTHORIZE_FINAL_REVISION',dict(requestId=denied,approved=False),who='coordinator'))
   self.assertEqual(self.db.execute('SELECT count(*) n FROM course_final_results WHERE project_id=%s',(pid,)).fetchone()['n'],1)
   stale=self.ok(self.command(oid,'REQUEST_FINAL_REVISION',dict(proposal,marks='43.00'),who='faculty-a'))['id']
   good=self.ok(self.command(oid,'REQUEST_FINAL_REVISION',dict(proposal,marks='44.00'),who='faculty-a'))['id']
   self.ok(self.command(oid,'AUTHORIZE_FINAL_REVISION',dict(requestId=good,approved=True),who='coordinator'))
   self.assertEqual(self.command(oid,'AUTHORIZE_FINAL_REVISION',dict(requestId=stale,approved=True),who='coordinator').status_code,409)
   self.assertEqual(self.db.execute('SELECT count(*) n FROM course_final_results WHERE project_id=%s',(pid,)).fetchone()['n'],2)

  def test_browser_direct_result_correction_actual_django_postgres(self):
   """Browser uses actual SMART-PRO frontend, Django routes and PostgreSQL;
   the runner creates and destroys an isolated synthetic DB per test."""
   import socket,subprocess,time,urllib.request
   from playwright.sync_api import sync_playwright
   oid=self.offering()
   # Preserve the planning Coordinator and appoint the Guide separately so both
   # actual application responsibilities are exercised in the browser.
   self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'))
   self.ok(self.appoint(oid,uid=FACULTY,permissions=['OVERVIEW','CORRECTIONS','RESULTS']))
   pid=self.project(oid)
   self.framework(oid)
   rid,_,_=self.stage(oid,pid,'stage-1',20)
   self.ok(self.command(oid,'PUBLISH_FINAL',dict(projectId=pid,expectedVersion=0)))
   guide_listing=self.ok(self.client('faculty-a').get('/api/v1/me/published-corrections'))
   self.assertIn(pid,[p['projectId'] for p in guide_listing['projects']])
   original=self.db.execute('SELECT id,results,sources FROM course_final_results WHERE project_id=%s ORDER BY version',(pid,)).fetchone()
   stage=self.db.execute('SELECT to_jsonb(v) AS evidence FROM academic_result_versions v WHERE review_id=%s ORDER BY version_no',(rid,)).fetchall()
   with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
    sock.bind(('127.0.0.1',0))
    port=sock.getsockname()[1]
   env=dict(os.environ,PYTHONPATH=str(ROOT/'backend'),SMARTPRO_UI='YES',SMARTPRO_ALLOWED_HOSTS='127.0.0.1,localhost,testserver')
   url=f'http://127.0.0.1:{port}'
   proc=subprocess.Popen([sys.executable,'-m','django','runserver','--noreload',f'127.0.0.1:{port}'],
                          cwd=str(ROOT),env=env,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT)
   try:
    for _ in range(70):
     if proc.poll() is not None:raise RuntimeError('SMART-PRO Django browser server exited')
     try:
      with urllib.request.urlopen(url+'/api/v1/ui/context',timeout=2) as resp:
       if resp.status==200:break
     except Exception:time.sleep(.2)
    else:raise RuntimeError('SMART-PRO browser server did not start')
    with sync_playwright() as pw:
     browser=pw.chromium.launch(headless=True)
     page=browser.new_page(viewport={'width':1280,'height':900})
     errors=[]
     page.on('pageerror',lambda error:errors.append(str(error)))
     page.goto(url,wait_until='domcontentloaded')
     page.locator('button[data-action="login"][data-alias="faculty-a"]').click()
     page.locator('button[data-action="choose-role"][data-role="Faculty"]').wait_for(state='visible',timeout=15000)
     page.locator('button[data-action="choose-role"][data-role="Faculty"]').click()
     page.locator('aside.sidebar nav button[data-go="documents"]').click()
     # The listing is intentionally paginated; open the actual project detail
     # before asserting that its Guide-only correction form is rendered.
     page.locator(f'button[data-action="open-project"][data-project="{pid}"]').click()
     panel=page.locator('form[data-form="guide-final-correction"]')
     panel.wait_for(state='attached',timeout=15000)
     panel.locator('xpath=..').evaluate('(el)=>{if(el.tagName==="DETAILS")el.open=true}')
     # A form can be rendered before its containing disclosure is expanded.
     page.locator('form[data-form="guide-final-correction"]').locator('input[name="marks"]').fill('42.00')
     panel.locator('textarea[name="reason"]').fill('Correct a verified published total')
     panel.locator('button[type="submit"],button.primary').click()
     page.get_by_text('Awaiting Coordinator decision',exact=False).first.wait_for(timeout=15000)
     role=page.locator('#activeRole')
     role.wait_for(timeout=15000)
     role.select_option('Coordinator')
     page.locator(f'button[data-action="open-course"][data-id="{oid}"]').click()
     page.locator('button[data-action="course-section"][data-section="results"]').first.click()
     decision=page.locator('form[data-form="final-revision-authorization"]')
     decision.wait_for(state='visible',timeout=15000)
     decision.locator('select[name="approved"]').select_option('true')
     decision.locator('button').click()
     page.get_by_text('Approved and published',exact=False).first.wait_for(timeout=15000)
     # Verify the same real application displays the preserved original and
     # corrected overall publications to the affected Student.
     page.locator('button[data-action="logout"]').click()
     page.locator('button[data-action="login"][data-alias="student-a"]').click()
     page.locator('aside.sidebar nav button[data-go="documents"]').click()
     page.locator(f'button[data-action="open-project"][data-project="{pid}"]').click()
     history=page.locator('section:has(h3:text("Overall final result history"))').last
     history.wait_for(state='visible',timeout=15000)
     self.assertIn('Version 1',history.inner_text())
     self.assertIn('Version 2',history.inner_text())
     self.assertIn('42.00',history.inner_text())
     self.assertFalse(errors,'Browser JavaScript errors: '+repr(errors))
     browser.close()
   finally:
    proc.terminate()
    try:proc.wait(timeout=7)
    except subprocess.TimeoutExpired:proc.kill();proc.wait()
   versions=self.db.execute('SELECT id,version,supersedes_id,results,sources FROM course_final_results WHERE project_id=%s ORDER BY version',(pid,)).fetchall()
   self.assertEqual([r['version'] for r in versions],[1,2])
   self.assertEqual(versions[0]['id'],original['id'])
   self.assertEqual(versions[1]['supersedes_id'],original['id'])
   self.assertEqual(versions[1]['results']['00000000-0000-4000-8000-000000000001'],'42.00')
   self.assertEqual(versions[1]['sources'],original['sources'])
   self.assertEqual(self.db.execute('SELECT to_jsonb(v) AS evidence FROM academic_result_versions v WHERE review_id=%s ORDER BY version_no',(rid,)).fetchall(),stage)

  def test_browser_https_reviewer_stage_evidence_actual_django_postgres(self):
      """Real staging HTTPS sign-in and Guide-to-Coordinator-to-Student flow.
      Only the disposable PostgreSQL fixture is modified; never hosted data.
      """
      import json, secrets, socket, ssl, subprocess, tempfile, time, urllib.request
      from django.contrib.auth.hashers import make_password
      from playwright.sync_api import sync_playwright
      oid=self.offering()
      self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'))
      self.ok(self.appoint(oid,uid=FACULTY,permissions=['OVERVIEW','CORRECTIONS','RESULTS']))
      pid=self.project(oid);self.framework(oid)
      rid,_,_=self.stage(oid,pid,'stage-1',20)
      original=self.ok(self.command(oid,'PUBLISH_FINAL',dict(projectId=pid,expectedVersion=0)))['id']
      # This test's isolated policy explicitly enables exceptional corrections.
      # Model stage evidence already corrected by its separate authorized process.
      self.db.execute("""INSERT INTO academic_result_versions
         (review_id,version_no,supersedes_id,legacy_release_id,roster_version_id,
          policy_id,actor_id,reason,sources,results,calculation_version)
         SELECT review_id,version_no+1,id,legacy_release_id,roster_version_id,
           policy_id,actor_id,'Synthetic corrected stage release',
           jsonb_set(sources,'{0,scores,0,marks}',to_jsonb('22'::text),false),
           jsonb_set(results,ARRAY['00000000-0000-4000-8000-000000000001'],
                     to_jsonb('42.00'::text)),calculation_version
         FROM academic_result_versions WHERE review_id=%s
         ORDER BY version_no DESC LIMIT 1""",(rid,))
      before_stages=self.db.execute('SELECT to_jsonb(v) evidence FROM academic_result_versions v WHERE review_id=%s ORDER BY version_no',(rid,)).fetchall()
      self.assertEqual(len(before_stages),2)
      password={'test-guide':secrets.token_urlsafe(20),'test-student':secrets.token_urlsafe(20)}
      accounts={alias:dict(actor=actor,label=alias,passwordHash=make_password(password[alias]))
                for alias,actor in [('test-guide',FACULTY),('test-student','00000000-0000-4000-8000-000000000001')]}
      server_code="""
  import os, ssl
  from socketserver import ThreadingMixIn
  from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server
  from django.core.wsgi import get_wsgi_application
  class Threaded(ThreadingMixIn,WSGIServer): daemon_threads=True
  class SecureHandler(WSGIRequestHandler):
      def get_environ(self):
          e=super().get_environ();e['wsgi.url_scheme']='https';e['HTTPS']='on';return e
  srv=make_server('127.0.0.1',int(os.environ['TEST_HTTPS_PORT']),
                  get_wsgi_application(),server_class=Threaded,handler_class=SecureHandler)
  ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
  ctx.load_cert_chain(os.environ['TEST_CERT'],os.environ['TEST_KEY'])
  srv.socket=ctx.wrap_socket(srv.socket,server_side=True)
  srv.serve_forever()
  """
      with socket.socket() as sk:
          sk.bind(('127.0.0.1',0));port=sk.getsockname()[1]
      url=f'https://127.0.0.1:{port}'
      with tempfile.TemporaryDirectory(prefix='smartpro-https-') as tmp:
          cert,key=str(Path(tmp)/'cert.pem'),str(Path(tmp)/'key.pem')
          subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes',
                          '-keyout',key,'-out',cert,'-days','1','-subj','/CN=127.0.0.1',
                          '-addext','subjectAltName=IP:127.0.0.1'],check=True,
                         stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
          env=dict(os.environ,PYTHONPATH=str(ROOT/'backend'),
            DJANGO_SETTINGS_MODULE='smartpro.settings',DJANGO_SECRET_KEY=secrets.token_hex(48),
            SMARTPRO_DEPLOYMENT='staging',SMARTPRO_ENV='staging',SMARTPRO_DEMO_AUTH='NO',
            SMARTPRO_DEPARTMENT_DEMO='NO',SMARTPRO_UI='YES',
            SMARTPRO_STAGING_REVIEWER_AUTH='YES',SMARTPRO_ALLOWED_HOSTS='127.0.0.1,localhost',
            SMARTPRO_CSRF_TRUSTED_ORIGINS=url,SMARTPRO_TRUST_TLS_PROXY='NO',
            SMARTPRO_REVIEWER_ACCOUNTS=json.dumps(accounts),SMARTPRO_REVIEWER_TEST_ACCOUNTS='',
            SMARTPRO_IDENTITY_RESOLVER='',TEST_HTTPS_PORT=str(port),TEST_CERT=cert,TEST_KEY=key)
          with (Path(tmp)/'server.log').open('w') as log:
              proc=subprocess.Popen([sys.executable,'-c',__import__('textwrap').dedent(server_code)],cwd=str(ROOT),env=env,
                                    stdout=log,stderr=subprocess.STDOUT)
              try:
                  for _ in range(70):
                      if proc.poll() is not None:
                          raise RuntimeError('HTTPS staging server exited: '+(Path(tmp)/'server.log').read_text()[-1800:])
                      try:
                          with urllib.request.urlopen(url+'/health/live',timeout=2,
                               context=ssl._create_unverified_context()) as response:
                              if response.status==200:break
                      except Exception:time.sleep(.2)
                  else:raise RuntimeError('HTTPS staging server unavailable: '+(Path(tmp)/'server.log').read_text()[-1800:])
                  with sync_playwright() as pw:
                      browser=pw.chromium.launch(headless=True)
                      page=browser.new_page(ignore_https_errors=True,viewport={'width':1280,'height':900})
                      errors=[]
                      page.on('pageerror',lambda error:errors.append(str(error)))
                      page.goto(url,wait_until='domcontentloaded')
                      self.assertIn('/reviewer/login',page.url)
                      def login(alias):
                          page.locator('input[name="username"]').fill(alias)
                          page.locator('input[name="password"]').fill(password[alias])
                          page.locator('button[type="submit"]').click()
                          page.wait_for_url(url+'/',timeout=20000)
                          page.locator(f'button[data-action="login"][data-alias="{alias}"]').click()
                      login('test-guide')
                      page.locator('button[data-action="choose-role"][data-role="Faculty"]').click(timeout=20000)
                      page.locator('aside.sidebar nav button[data-go="documents"]').click()
                      page.locator(f'button[data-action="open-project"][data-project="{pid}"]').click()
                      form=page.locator('form[data-form="guide-stage-evidence-correction"]')
                      form.wait_for(state='attached',timeout=20000)
                      form.locator('xpath=..').evaluate('(e)=>{if(e.tagName==="DETAILS")e.open=true}')
                      form.locator('textarea[name="reason"]').fill('Publish already-corrected synthetic stage evidence')
                      with page.expect_response(lambda response: response.url.endswith('/commands') and response.request.method=='POST',timeout=20000) as sent:
                          form.locator('button').click()
                      response=sent.value
                      self.assertEqual(response.status,200,'Stage-evidence UI POST: '+response.text()[:600])
                      try:
                          page.get_by_text('Awaiting Coordinator decision',exact=False).first.wait_for(timeout=5000)
                      except Exception:
                          print('Synthetic stage request UI diagnostic:',page.locator('#toast').inner_text()[:500],page.locator('#main').inner_text()[-1500:],flush=True)
                          print('Synthetic stage DB request count:',self.db.execute('SELECT count(*) n FROM course_final_revision_requests WHERE project_id=%s',(pid,)).fetchone()['n'],flush=True)
                          raise
                      self.assertEqual(self.db.execute('SELECT count(*) n FROM course_final_results WHERE project_id=%s',(pid,)).fetchone()['n'],1)
                      page.locator('#activeRole').select_option('Coordinator')
                      page.locator(f'button[data-action="open-course"][data-id="{oid}"]').click()
                      page.locator('button[data-action="course-section"][data-section="results"]').first.click()
                      decision=page.locator('form[data-form="final-revision-authorization"]')
                      decision.wait_for(state='visible',timeout=20000)
                      decision.locator('select[name="approved"]').select_option('true')
                      decision.locator('button').click()
                      page.get_by_text('Approved and published',exact=False).first.wait_for(timeout=20000)
                      page.locator('button[data-action="logout"]').click()
                      page.wait_for_url(url+'/reviewer/login',timeout=20000)
                      login('test-student')
                      page.locator('aside.sidebar nav button[data-go="documents"]').click()
                      page.locator(f'button[data-action="open-project"][data-project="{pid}"]').click()
                      history=page.locator('section:has(h3:text("Overall final result history"))').last
                      history.wait_for(state='visible',timeout=20000)
                      self.assertIn('Version 1',history.inner_text())
                      self.assertIn('Version 2',history.inner_text())
                      self.assertIn('42.00',history.inner_text())
                      self.assertFalse(errors,repr(errors))
                      browser.close()
              finally:
                  proc.terminate()
                  try:proc.wait(timeout=7)
                  except subprocess.TimeoutExpired:proc.kill();proc.wait()
      versions=self.db.execute('SELECT id,version,supersedes_id,results,sources FROM course_final_results WHERE project_id=%s ORDER BY version',(pid,)).fetchall()
      self.assertEqual([v['version'] for v in versions],[1,2])
      self.assertEqual(str(versions[0]['id']),original)
      self.assertEqual(versions[1]['supersedes_id'],versions[0]['id'])
      self.assertEqual([v['results']['00000000-0000-4000-8000-000000000001'] for v in versions],['40.00','42.00'])
      self.assertNotEqual(versions[0]['sources'],versions[1]['sources'])
      self.assertEqual(self.db.execute('SELECT to_jsonb(v) evidence FROM academic_result_versions v WHERE review_id=%s ORDER BY version_no',(rid,)).fetchall(),before_stages)
      self.assertEqual(self.db.execute('SELECT count(*) n FROM course_final_revision_authorizations WHERE request_id IN (SELECT id FROM course_final_revision_requests WHERE project_id=%s)',(pid,)).fetchone()['n'],1)

  def test_milestone_completion_and_exact_requirement_permission(self):
   oid=self.offering()
   self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'))
   pid=self.project(oid)
   cfg=self.framework(oid)
   current=str(self.db.execute("SELECT policy_id FROM submission_offering_requirements WHERE offering_id=%s AND requirement_key='SYNOPSIS'",(oid,)).fetchone()['policy_id'])
   apply=dict(policyId=current,expectedPolicyId=current)
   self.assertEqual(self.command(oid,'APPLY_REQUIREMENT',apply,who='coordinator').status_code,403)
   cfg['requirementPolicyIds']=[current]
   cfg['deadlineRules']=dict(kinds=['MILESTONE'],earliestAt='2026-01-01T00:00:00Z',latestAt='2027-06-10T00:00:00Z',maxReminderHours=168,completionRoles=['Student'])
   version=self.ok(self.command(oid,'FRAMEWORK',dict(expectedVersion=1,configuration=cfg,authority=None)))['id']
   self.ok(self.command(oid,'PLAN',dict(expectedVersion=1,frameworkId=version,schedules={'stage-1':'2026-12-01T09:00:00Z'}),who='coordinator'))
   self.assertEqual(self.command(oid,'APPLY_REQUIREMENT',dict(apply,expectedPolicyId=None),who='coordinator').status_code,409)
   self.ok(self.command(oid,'APPLY_REQUIREMENT',apply,who='coordinator'))
   d=self.ok(self.command(oid,'DEADLINE',dict(deadlineKey='demo-evidence',expectedVersion=0,projectId=pid,kind='MILESTONE',target='GENERAL',name='Evidence checklist',dueAt='2026-11-01T17:00:00Z',reminderHours=[],notifyRoles=['Coordinator'],active=True,completionRole='Student',completionScope='INDIVIDUAL'),who='coordinator'))
   body=dict(deadlineId=d['id'],projectId=pid)
   self.assertEqual(self.command(oid,'COMPLETE_MILESTONE',body,who='faculty-a').status_code,403)
   self.db.execute('SELECT smartpro_dispatch_course_notifications()')
   def feed(who):return self.ok(self.client(who).get('/api/v1/me/course-notifications'))
   self.assertTrue(any(task['deadline_id']==d['id'] and task['can_complete'] for task in feed('student-a')['tasks']))
   self.assertTrue(any(alert['project_id']==pid for alert in feed('coordinator')['alerts']))
   self.assertFalse(any(alert['project_id']==pid for alert in feed('student-a')['alerts']))
   self.ok(self.command(oid,'COMPLETE_MILESTONE',body,who='student-a'))
   self.db.execute('SELECT smartpro_dispatch_course_notifications()')
   self.assertFalse(any(task['deadline_id']==d['id'] for task in feed('student-a')['tasks']))
   self.assertFalse(any(alert['project_id']==pid for alert in feed('coordinator')['alerts']))

  def test_guide_handover_preserves_drafts_and_finalized_marks(self):
   oid=self.offering();self.ok(self.appoint(oid,uid='00000000-0000-4000-8000-000000000008'));pid=self.project(oid);self.framework(oid)
   rid=self.ok(self.command(oid,'CREATE_STAGE',dict(projectId=pid,stageKey='stage-1',facultyIds=[]),who='coordinator'))['id']
   old=str(self.db.execute("SELECT id FROM faculty_assignments WHERE project_id=%s AND assignment_type='GUIDE' AND valid_until IS NULL",(pid,)).fetchone()['id'])
   self.ok(self.post(f'/api/v1/staff/departments/{CSE}/projects/{pid}/guide',dict(facultyId='00000000-0000-4000-8000-000000000008',expectedGuideId=old),who='coordinator'))
   assignments=self.db.execute('SELECT e.faculty_user_id,a.state,smartpro_evaluator_active(e.id) active FROM evaluator_assignments e JOIN assessments a ON a.evaluator_assignment_id=e.id WHERE e.review_id=%s',(rid,)).fetchall()
   self.assertEqual(len(assignments),2);self.assertFalse(next(a for a in assignments if str(a['faculty_user_id'])==FACULTY)['active'])
   self.assertTrue(next(a for a in assignments if str(a['faculty_user_id'])=='00000000-0000-4000-8000-000000000008')['active'])
   detail=self.ok(self.client('coordinator').get(f'/api/v1/courses/offerings/{oid}/details'));self.assertEqual(detail['projectCount'],1)
  def test_coordinator_activation_renewal_and_last_guard_under_admin(self):
   oid=self.offering();student=self.client('student-a')
   self.assertNotIn(oid,[x['id'] for x in self.ok(student.get('/api/v1/me/curriculum-offerings'))['results']])
   denied=student.post('/api/v1/teams',dict(offeringId=oid,name='Blocked team'),format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex);self.assertEqual(denied.status_code,403)
   key=uuid4().hex;a=self.ok(self.appoint(oid,key=key));self.assertEqual(a,self.ok(self.appoint(oid,key=key)));self.activate(oid)
   self.assertIn(oid,[x['id'] for x in self.ok(student.get('/api/v1/me/curriculum-offerings'))['results']])
   denied=self.appoint(oid,version=1,active=False)
   self.assertEqual(denied.status_code,409)
   self.assertIn('last coordinator',denied.json()['detail']['message'])
   uid='00000000-0000-4000-8000-000000000008';self.ok(self.appoint(oid,uid=uid,who='department-admin'))
   self.ok(self.appoint(oid,version=1,active=False));self.ok(self.appoint(oid,uid=uid,version=1,permissions=['OVERVIEW','RESULTS']))
   self.assertEqual(self.appoint(oid,uid=uid,version=1).status_code,409)
   history=self.ok(self.client().get(f'/api/v1/courses/departments/{CSE}'))['offerings'];row=next(o for o in history if o['id']==oid)
   self.assertEqual(len(row['appointments']),4);self.assertTrue(row['has_coordinator'])
   external=next(a for a in row['appointments'] if a['actor_id']=='00000000-0000-4000-8000-000000000012')
   self.assertEqual(external['authority']['source'],'ADMIN_APPOINTMENT')
   self.assertTrue(external['authority']['adminRoleId'])
  def test_exact_offering_scope_roles_and_private_storage(self):
   one=self.offering();two=self.offering()
   uid=str(self.db.execute("INSERT INTO users(display_name,email) VALUES('Scoped faculty',%s) RETURNING id",(uuid4().hex+'@example.invalid',)).fetchone()['id'])
   self.db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'FACULTY')",(uid,CSE));self.ok(self.appoint(one,uid=uid))
   from smartpro.identity import Principal
   scoped=APIClient();scoped.force_authenticate(Principal(uid,role='Coordinator',role_choices=('Coordinator','Faculty')))
   self.assertEqual([o['id'] for o in self.ok(scoped.get(f'/api/v1/courses/departments/{CSE}'))['offerings']],[one])
   for who in ['student-a','faculty-a','tech-admin','coordinator','staff-policy']:self.assertEqual(self.appoint(two,who=who).status_code,403)
   with psycopg.connect(**dict(app,dbname=name),autocommit=True) as runtime:
    with self.assertRaises(psycopg.errors.InsufficientPrivilege):runtime.execute('SELECT * FROM course_coordinator_versions')
   self.assertEqual(self.appoint(one,uid='00000000-0000-4000-8000-000000000001').status_code,403)
  def test_cross_offering_document_case_staff_and_course_read_denials(self):
   from smartpro.identity import Principal
   from synthetic_synopsis import pdf_bytes
   from django.core.files.uploadedfile import SimpleUploadedFile
   one=self.offering();two=self.offering();uid=str(self.db.execute("INSERT INTO users(display_name,email) VALUES('Scoped verifier',%s) RETURNING id",(uuid4().hex+'@example.invalid',)).fetchone()['id'])
   self.db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'FACULTY')",(uid,CSE));self.ok(self.appoint(one,uid=uid));self.ok(self.appoint(two,uid='00000000-0000-4000-8000-000000000008'))
   p1=self.project(one);p2=self.project(two);base=f'/api/v1/documents/departments/{CSE}'
   self.ok(self.post(base,dict(action='ASSIGN_REVIEWER',projectId=p2,facultyId=uid)))
   vid=self.ok(self.client('student-a').post(base+f'/projects/{p2}/uploads',{'file':SimpleUploadedFile('private.pdf',pdf_bytes(),content_type='application/pdf')},format='multipart',HTTP_IDEMPOTENCY_KEY=uuid4().hex))['documentVersionId']
   case=str(self.db.execute('SELECT id FROM submission_cases WHERE project_id=%s',(p2,)).fetchone()['id'])
   scoped=APIClient();scoped.force_authenticate(Principal(uid,role='Coordinator',role_choices=('Coordinator','Faculty')))
   self.assertEqual([p['id'] for p in self.ok(scoped.get(base))['projects']],[p1])
   self.assertEqual(scoped.get(f'/api/v1/document-versions/{vid}/content').status_code,403)
   self.assertEqual(scoped.get(f'/api/v1/submission-cases/{case}').status_code,403)
   self.assertEqual(scoped.get(f'/api/v1/courses/offerings/{two}/details').status_code,403)
   self.assertEqual([p['id'] for p in self.ok(scoped.get(f'/api/v1/staff/departments/{CSE}/projects'))['results']],[p1])
   self.assertEqual([o['id'] for o in self.ok(scoped.get(f'/api/v1/staff/departments/{CSE}/policies'))['results']],[one])
   faculty=APIClient();faculty.force_authenticate(Principal(uid,role='Faculty',role_choices=('Coordinator','Faculty')))
   self.assertEqual(faculty.get(f'/api/v1/document-versions/{vid}/content').status_code,200)
  def test_concurrent_last_removal_rolls_back_and_preserves_history(self):
   oid=self.offering();self.ok(self.appoint(oid));self.activate(oid);other='00000000-0000-4000-8000-000000000008';self.ok(self.appoint(oid,uid=other))
   def revoke(uid):
    close_old_connections()
    try:return self.appoint(oid,uid=uid,version=1,active=False)
    finally:close_old_connections()
   with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(revoke,[FACULTY,other]))
   self.assertEqual(sorted(r.status_code for r in results),[200,409])
   self.assertEqual(self.db.execute('SELECT count(*) n FROM course_coordinator_versions WHERE offering_id=%s',(oid,)).fetchone()['n'],3)
 try:
  suite=unittest.TestSuite([Contracts(test_name)]) if test_name else unittest.defaultTestLoader.loadTestsFromTestCase(Contracts)
  result=unittest.TextTestRunner(verbosity=2).run(suite);return 0 if result.wasSuccessful() else 1
 finally:
  connection.close();storage.cleanup()
  with psycopg.connect(**dict(owner,dbname='postgres'),autocommit=True) as manager:
   assert name.startswith('smartpro_test_demo_acceptance_courses_');manager.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
if __name__=='__main__':
 if len(sys.argv)>2 or (len(sys.argv)==2 and not sys.argv[1].startswith('test_')):
  raise SystemExit('Explicit single course test name required')
 raise SystemExit(main(sys.argv[1] if len(sys.argv)==2 else None))
