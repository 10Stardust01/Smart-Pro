"""Verify demo APIs in a disposable clone; preserve the persistent demo/source DBs."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'backend'),str(ROOT/'scripts')]
from department_demo import settings, TARGET, CSE, FACULTY, install_documents


def main():
    _,owner,app=settings(ROOT/'.test-data/pg-memberships.env.json')
    name='smartpro_test_demo_verify_'+uuid4().hex[:10]
    with psycopg.connect(**dict(owner,dbname='postgres'),autocommit=True) as manager:
        manager.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(sql.Identifier(name),sql.Identifier(TARGET)))
    env=dict(DATABASE_URL=make_conninfo(**dict(app,dbname=name)),DJANGO_SETTINGS_MODULE='smartpro.settings',
             DJANGO_SECRET_KEY='synthetic-demo-verification-only',SMARTPRO_ENV='demo',SMARTPRO_DEMO_AUTH='YES',SMARTPRO_DEPARTMENT_DEMO='YES')
    for gate in ['CURRICULUM','TEAM','MEMBERSHIP','PROJECT','STAFF','ACADEMIC','DOCUMENT']:
        env['SMARTPRO_'+gate+'_API']='YES'
    os.environ.update(env)
    import django
    django.setup()
    from django.db import connection
    from rest_framework.test import APIClient

    class DemoContracts(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.db=psycopg.connect(**dict(owner,dbname=name),autocommit=True,row_factory=dict_row)
            install_documents(cls.db)

        @classmethod
        def tearDownClass(cls):
            cls.db.close()
            connection.close()

        def client(self,who):
            client=APIClient()
            role={'staff-policy':'HOD','department-admin':'Admin','coordinator':'Coordinator'}.get(who,'Faculty' if who.startswith('faculty') else 'Student' if who.startswith('student') else None)
            client.credentials(HTTP_X_DEMO_USER=who,**({'HTTP_X_SMARTPRO_ROLE':role} if role else {}))
            return client

        def post(self,client,path,body,key=None):
            response=client.post(path,body,format='json',HTTP_IDEMPOTENCY_KEY=key or str(uuid4()))
            return response

        def test_login_role_matrix_and_demo_gates(self):
            for who in ['student-a','student-b','student-new','student-next','student-ece','staff-policy','coordinator','faculty-a','faculty-other','tech-admin']:
                with self.subTest(who=who):
                    response=self.client(who).get('/api/v1/demo/workspace')
                    self.assertEqual(response.status_code,200,response.content)
                    if who=='tech-admin':
                        self.assertFalse(any(response.json()['access'].values()))
                        self.assertEqual(response.json()['reviews'],[])
            with patch.dict(os.environ,SMARTPRO_ENV='production'):
                self.assertEqual(self.client('staff-policy').get('/api/v1/demo/workspace').status_code,401)
                self.assertEqual(self.client('staff-policy').get('/').status_code,404)
            with patch.dict(os.environ,SMARTPRO_DEPARTMENT_DEMO='NO'):
                self.assertEqual(self.client('student-a').get('/api/v1/demo/workspace').status_code,503)
                self.assertEqual(self.client('student-a').get('/').status_code,404)
            with patch.dict(os.environ,SMARTPRO_ACADEMIC_API='NO'):
                self.assertEqual(self.client('faculty-a').get('/api/v1/demo/workspace').status_code,503)
                self.assertEqual(self.client('faculty-a').get('/').status_code,404)

        def test_disabled_department_does_not_leak_evaluation_data_through_discovery(self):
            self.db.execute('UPDATE academic_governance_settings SET enabled=false WHERE department_id=%s',(CSE,))
            try:
                payload=self.client('faculty-a').get('/api/v1/demo/workspace').json()
                self.assertEqual(payload['reviews'],[])
                self.assertTrue(all(not a['action'].startswith('ACADEMIC_') for a in payload['audit']))
            finally:
                self.db.execute('UPDATE academic_governance_settings SET enabled=true WHERE department_id=%s',(CSE,))

        def test_enrollment_is_idempotent_and_uses_trusted_department(self):
            client=self.client('student-next')
            admission=client.get('/api/v1/demo/workspace').json()
            self.assertEqual(self.post(client,'/api/v1/demo/enrollment',{'departmentId':CSE}).status_code,400)
            first=self.post(client,'/api/v1/demo/enrollment',{})
            self.assertEqual(first.status_code,200,first.content)
            self.assertEqual(self.post(client,'/api/v1/demo/enrollment',{}).json(),first.json())
            self.assertEqual(first.json()['department']['id'],admission['department']['id'])
            foreign=self.client('student-a').get('/api/v1/demo/workspace').json()['department']['offeringId']
            self.assertEqual(self.post(client,'/api/v1/teams',{'offeringId':foreign,'name':'Forbidden cross-department team'}).status_code,403)
            self.assertEqual(self.post(self.client('faculty-a'),'/api/v1/demo/enrollment',{}).status_code,403)

        def test_ordinary_and_foreign_roles_cannot_manage_cse_or_read_foreign_reviews(self):
            hod=self.client('staff-policy')
            review=hod.get('/api/v1/demo/workspace').json()['reviews'][0]
            for who in ['student-a','faculty-a','faculty-other','tech-admin']:
                actor=self.client(who)
                self.assertEqual(self.post(actor,f'/api/v1/academic/departments/{CSE}/reviews',dict(projectId=review['projectId'],
                    schemeVersionId=str(uuid4()),schemeModeId=str(uuid4()),policyId=str(uuid4()),facultyIds=[FACULTY],reason='Forbidden')).status_code,403)
            foreign=self.client('faculty-other')
            self.assertEqual(foreign.get(f'/api/v1/academic/departments/{CSE}/reviews/{review["id"]}/results').status_code,403)
            self.assertEqual(foreign.get('/api/v1/demo/workspace').json()['reviews'],[])

        def test_dual_role_student_does_not_gain_unassigned_evaluator_context(self):
            payload=self.client('student-b').get('/api/v1/demo/workspace').json()
            for review in payload['reviews']:
                self.assertEqual(review['roster'],[])
                self.assertEqual(review['criteria'],[])
                self.assertEqual(review['assessments'],[])

        def test_extra_student_role_cannot_change_trusted_home_department(self):
            client=self.client('student-a')
            foreign=self.client('student-ece').get('/api/v1/demo/workspace').json()['department']['id']
            self.db.execute("""INSERT INTO department_role_assignments(id,user_id,department_id,role_code)
              VALUES('00000000-0000-4000-8000-000000000000','00000000-0000-4000-8000-000000000001',%s,'STUDENT')""",(foreign,))
            self.assertEqual(client.get('/api/v1/demo/workspace').json()['department']['id'],CSE)

        def test_full_student_to_corrected_result_workflow(self):
            student=self.client('student-a'); hod=self.client('staff-policy'); teacher=self.client('faculty-a')
            workspace=student.get('/api/v1/demo/workspace').json(); catalog=workspace['department']
            for membership in student.get('/api/v1/me/memberships').json()['results']:
                if membership['offeringId']==catalog['offeringId']:
                    self.assertEqual(self.post(student,f'/api/v1/memberships/{membership["id"]}/end',{}).status_code,200)
            team=self.post(student,'/api/v1/teams',dict(offeringId=catalog['offeringId'],name='Verified end-to-end team'))
            self.assertEqual(team.status_code,201,team.content)
            admin=self.client('department-admin')
            setup=f'/api/v1/staff/departments/{CSE}/setup'
            request=self.post(admin,setup,dict(action='REQUEST',kind='DOCUMENT_NOT_REQUIRED',configuration={'offeringId':catalog['offeringId']},reason='Explicit synthetic no-document evaluation fixture'))
            self.assertEqual(request.status_code,200,request.content)
            self.assertEqual(self.post(hod,setup,dict(action='APPROVE',requestId=request.json()['id'])).status_code,200)
            self.assertEqual(self.post(admin,setup,dict(action='APPLY',requestId=request.json()['id'])).status_code,200)
            project=self.post(student,'/api/v1/projects',dict(offeringId=catalog['offeringId'],teamId=team.json()['id'],title='Verified synthetic project'))
            self.assertEqual(project.status_code,201,project.content)
            base=f'/api/v1/academic/departments/{CSE}'
            config=hod.get(base+'/policies').json()
            policy=self.post(hod,base+'/policies',dict(expectedRevision=config['revision'],reason='Explicit synthetic verification policy',evaluatorQuorum=1,aggregation='MEAN',evaluatorWeights={}))
            self.assertEqual(policy.status_code,200,policy.content)
            assigned=self.post(hod,base+'/reviews',dict(projectId=project.json()['id'],schemeVersionId=catalog['schemeVersionId'],schemeModeId=catalog['schemeModeId'],policyId=policy.json()['id'],facultyIds=[FACULTY],reason='Synthetic assignment'))
            self.assertEqual(assigned.status_code,200,assigned.content)
            rid=assigned.json()['reviewId']
            r=next(r for r in teacher.get('/api/v1/demo/workspace').json()['reviews'] if r['id']==rid)
            assessment=r['assessments'][0]
            marks=[dict(criterionId=c['id'],studentId=person['id'] if person else None,marks='2') for c in r['criteria'] for person in ([None] if c['scope']=='TEAM' else r['roster'])]
            self.assertEqual(self.post(teacher,base+f'/assessments/{assessment["id"]}/draft',dict(expectedAssessmentVersion=1,reason='Rubric entry',scores=marks)).status_code,200)
            final=dict(expectedAssessmentVersion=2,reason='Complete saved marks')
            self.assertEqual(self.post(teacher,base+f'/assessments/{assessment["id"]}/finalize',final,key='finalize').status_code,200)
            self.assertEqual(self.post(teacher,base+f'/assessments/{assessment["id"]}/finalize',final,key='finalize').status_code,200)
            self.assertEqual(self.post(hod,base+f'/reviews/{rid}/publish',dict(expectedReviewRevision=1,reason='Quorum satisfied')).status_code,200)
            for mark in marks: mark['marks']='3'
            corrected=self.post(teacher,base+f'/reviews/{rid}/evaluations',dict(expectedReviewRevision=2,assessmentId=assessment['id'],scores=marks,reason=''))
            self.assertEqual(corrected.status_code,200,corrected.content)
            results=student.get(base+f'/reviews/{rid}/results').json()['results']
            self.assertEqual(len(results),2)
            self.assertEqual([list(v['results'].values())[0] for v in results],['4.00','6.00'])
            self.assertTrue(all(set(v['results'])=={workspace['actor']['id']} and v['sources']==[] for v in results))
            audit=teacher.get('/api/v1/demo/workspace').json()['audit']
            self.assertIn('ACADEMIC_EVALUATE',[a['action'] for a in audit])

        def test_private_demo_tables_and_static_asset_boundaries(self):
            with psycopg.connect(**dict(app,dbname=name)) as db:
                for table in ['demo_admissions','demo_catalog']:
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        with db.transaction(): db.execute(sql.SQL('SELECT * FROM {}').format(sql.Identifier(table)))
            self.assertEqual(self.client('student-a').get('/demo-assets/not-allowed.env').status_code,404)
            response=self.client('student-a').get('/')
            self.assertEqual(response.status_code,200)
            self.assertIn("script-src 'self'",response['Content-Security-Policy'])

    try:
        outcome=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DemoContracts))
        return 0 if outcome.wasSuccessful() else 1
    finally:
        connection.close()
        with psycopg.connect(**dict(owner,dbname='postgres'),autocommit=True) as manager:
            # Only this exact, newly-created disposable clone is removed.
            assert name.startswith('smartpro_test_demo_verify_')
            manager.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


if __name__=='__main__':
    raise SystemExit(main())
