"""Real PostgreSQL/file tests in one disposable clone; persistent demo is preserved."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'backend'),str(ROOT/'scripts')]
from department_demo import settings,TARGET,CSE,FACULTY,install_documents
from synthetic_synopsis import pdf_bytes


def main():
    _,owner,app=settings(ROOT/'.test-data/pg-memberships.env.json')
    name='smartpro_test_demo_documents_'+uuid4().hex[:10]
    with psycopg.connect(**dict(owner,dbname='postgres'),autocommit=True) as manager:
        manager.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(sql.Identifier(name),sql.Identifier(TARGET)))
    storage=tempfile.TemporaryDirectory(prefix='smartpro-documents-')
    env=dict(DATABASE_URL=make_conninfo(**dict(app,dbname=name)),DJANGO_SETTINGS_MODULE='smartpro.settings',
      DJANGO_SECRET_KEY='synthetic-documents-only',SMARTPRO_ENV='demo',SMARTPRO_DEMO_AUTH='YES',SMARTPRO_DEPARTMENT_DEMO='YES',SMARTPRO_DATA_DIR=storage.name)
    for gate in ['CURRICULUM','TEAM','MEMBERSHIP','PROJECT','STAFF','ACADEMIC','DOCUMENT']:env['SMARTPRO_'+gate+'_API']='YES'
    os.environ.update(env)
    import django
    django.setup()
    from django.db import connection,close_old_connections
    from django.core.files.uploadedfile import SimpleUploadedFile
    from rest_framework.test import APIClient
    base=f'/api/v1/documents/departments/{CSE}'

    class Contracts(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.db=psycopg.connect(**dict(owner,dbname=name),autocommit=True,row_factory=dict_row)
            install_documents(cls.db)

        @classmethod
        def tearDownClass(cls): cls.db.close();connection.close()

        def client(self,who):
            roles={'staff-policy':'HOD','department-admin':'Admin','coordinator':'Coordinator'}
            role=roles.get(who,'Faculty' if who.startswith('faculty') else 'Student' if who.startswith('student') else None)
            c=APIClient();c.credentials(HTTP_X_DEMO_USER=who,**({'HTTP_X_SMARTPRO_ROLE':role} if role else {}));return c

        def command(self,who,action,body,key=None):
            return self.client(who).post(base,dict(action=action,**body),format='json',HTTP_IDEMPOTENCY_KEY=key or uuid4().hex)

        def ok(self,response,status=200):
            self.assertEqual(response.status_code,status,response.content);return response.json()

        def fixture(self,approval=True,closed=False,closes_at=None):
            kind=self.db.execute('INSERT INTO curriculum_types(code,label) VALUES(%s,%s) RETURNING id',('TEST-'+uuid4().hex.upper(),'Synopsis verification studio')).fetchone()['id']
            admin=self.db.execute("SELECT id FROM department_role_assignments WHERE user_id='00000000-0000-4000-8000-000000000012' AND role_code='ACADEMIC_ADMIN'").fetchone()['id']
            policy=self.db.execute('SELECT policy_id FROM demo_catalog WHERE department_id=%s',(CSE,)).fetchone()['policy_id']
            # This fixture deliberately uses the original advisory policy.
            # Tests authoring new policies must not change its membership rules.
            team=self.db.execute('SELECT id FROM team_membership_policy_versions WHERE department_id=%s ORDER BY version_no LIMIT 1',(CSE,)).fetchone()['id']
            config=dict(curriculumTypeId=str(kind),cycleId='11000000-0000-4000-8000-000000000001',semester='SYNTHETIC-SEM-3',projectPolicyId=str(policy),teamPolicyId=str(team),adminRoleId=str(admin),visibleFrom='2026-01-01T00:00:00Z',visibleUntil='2027-06-01T00:00:00Z',submissionOpensAt='2026-01-01T00:00:00Z',submissionClosesAt=closes_at or ('2026-01-02T00:00:00Z' if closed else '2027-06-01T00:00:00Z'),maxBytes=2097152,facultyApprovalEnabled=approval,teamCreationEnabled=True)
            instruction=self.ok(self.command('staff-policy','AUTHORIZE',{'configuration':config,'reason':'Synthetic HOD instruction'}))['instructionId']
            offering=self.ok(self.command('department-admin','CONFIGURE',{'instructionId':instruction}))['offeringId']
            c=self.client('student-a')
            offered=next(o for o in self.ok(c.get('/api/v1/me/curriculum-offerings'))['results'] if o['id']==offering)
            self.assertEqual(offered['projectTypes'],['MAJOR'])
            team=self.ok(c.post('/api/v1/teams',{'offeringId':offering,'name':'Document team'},format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex),201)['id']
            if closed:
                # Historical draft precondition: the old registration service
                # did not require an open document window. Current UI must not.
                project=self.db.execute('SELECT smartpro_register_student_project(%s,%s,%s,%s,%s,%s,%s) AS r',('00000000-0000-4000-8000-000000000001',team,'MAJOR','HIST-'+uuid4().hex,'Historical draft',uuid4().hex,'a'*64)).fetchone()['r']['project']['id']
            else:
                project=self.ok(c.post('/api/v1/projects',{'offeringId':offering,'teamId':team,'title':'Synopsis test project'},format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex),201)['id']
            self.ok(self.command('staff-policy','ASSIGN_REVIEWER',{'projectId':project,'facultyId':FACULTY}))
            return project,instruction,offering,config

        def upload(self,project,data=None,key=None,who='student-a',filename='synopsis.pdf',mime='application/pdf'):
            return self.client(who).post(base+f'/projects/{project}/uploads',{'file':SimpleUploadedFile(filename,pdf_bytes() if data is None else data,content_type=mime)},format='multipart',HTTP_IDEMPOTENCY_KEY=key or uuid4().hex)

        def project(self,who,pid):
            return next(p for p in self.ok(self.client(who).get(base))['projects'] if p['id']==pid)

        def submit(self,pid,vid):
            return self.command('student-a','SUBMIT',{'projectId':pid,'documentVersionId':vid,'expectedCaseVersion':self.project('student-a',pid)['case']['version']})

        def test_complete_revision_approval_and_private_retrieval(self):
            p,_,_,_=self.fixture(); content=pdf_bytes('Initial synthetic synopsis')
            v1=self.ok(self.upload(p,content))['documentVersionId'];self.ok(self.submit(p,v1))
            download=self.client('faculty-a').get(f'/api/v1/document-versions/{v1}/content')
            self.assertEqual(download.status_code,200);self.assertEqual(download.content,content);self.assertEqual(download['Cache-Control'],'private, no-store')
            preview=self.client('faculty-a').get(f'/api/v1/document-versions/{v1}/content?preview=1')
            self.assertEqual(preview.status_code,200,preview.content[:200]);self.assertTrue(preview.content.startswith(b'\x89PNG\r\n\x1a\n'));self.assertEqual(preview['X-Document-Pages'],'1')
            self.assertEqual(self.client('faculty-a').get(f'/api/v1/document-versions/{v1}/content?preview=1&page=2').status_code,400)
            c=self.project('faculty-a',p)['case']
            self.ok(self.command('faculty-a','DECIDE',dict(projectId=p,attemptId=c['attempts'][-1]['id'],expectedCaseVersion=c['version'],decision='REQUEST_CHANGES',comment='Clarify the evaluation method.')))
            self.assertEqual(self.project('student-a',p)['case']['attempts'][0]['feedback'][0]['comment'],'Clarify the evaluation method.')
            v2=self.ok(self.upload(p,pdf_bytes('Revised synopsis with evaluation method')))['documentVersionId'];self.ok(self.submit(p,v2))
            c=self.project('faculty-a',p)['case'];self.ok(self.command('faculty-a','DECIDE',dict(projectId=p,attemptId=c['attempts'][-1]['id'],expectedCaseVersion=c['version'],decision='APPROVE',comment='Synopsis is approved.')))
            for role in ['student-a','faculty-a','coordinator','staff-policy']:
                case=self.project(role,p)['case'];self.assertEqual(case['state'],'APPROVED');self.assertEqual(len(case['attempts']),2);self.assertEqual(len(case['versions']),2)
            self.assertEqual(self.client('faculty-a').get(f'/api/v1/document-versions/{v1}/content?download=1').content,content)
            self.assertEqual(self.upload(p).status_code,409)

        def test_evaluator_reassignment_keeps_drafts_and_blocks_withdrawn_writer(self):
            p,_,_,_=self.fixture();academic=f'/api/v1/academic/departments/{CSE}';hod=self.client('staff-policy')
            policy=self.db.execute("SELECT id FROM academic_evaluation_policies WHERE department_id=%s AND aggregation='MEAN' AND evaluator_quorum=1 ORDER BY version_no DESC LIMIT 1",(CSE,)).fetchone()['id']
            catalog=self.db.execute('SELECT scheme_id,mode_id FROM demo_catalog WHERE department_id=%s',(CSE,)).fetchone()
            rid=self.ok(hod.post(academic+'/reviews',dict(projectId=p,schemeVersionId=str(catalog['scheme_id']),schemeModeId=str(catalog['mode_id']),policyId=str(policy),facultyIds=[FACULTY]),format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))['reviewId']
            other='00000000-0000-4000-8000-000000000008'
            route=academic+f'/reviews/{rid}/management';body=dict(expectedReviewRevision=1,facultyIds=[other])
            for who in ['student-a','faculty-a','department-admin','tech-admin']:self.assertEqual(self.client(who).post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,403)
            original=self.db.execute('SELECT a.id FROM assessments a JOIN evaluator_assignments e ON e.id=a.evaluator_assignment_id WHERE a.review_id=%s AND e.faculty_user_id=%s',(rid,FACULTY)).fetchone()['id']
            self.ok(hod.post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))
            self.assertEqual(self.client('faculty-a').post(academic+f'/assessments/{original}/finalize',dict(expectedAssessmentVersion=2),format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,403)
            self.assertEqual(self.client('faculty-a').get(academic+f'/reviews/{rid}/results').status_code,403)
            data=self.ok(hod.get(route));self.assertEqual(len(data['assignments']),2);self.assertEqual(sum(a['active'] for a in data['assignments']),1)
            self.assertEqual(self.db.execute('SELECT count(*) n FROM assessments WHERE review_id=%s',(rid,)).fetchone()['n'],2)
            self.assertEqual(hod.post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,409)
            faculty=self.client('coordinator');faculty.credentials(HTTP_X_DEMO_USER='coordinator',HTTP_X_SMARTPRO_ROLE='Faculty')
            review=next(r for r in self.ok(faculty.get('/api/v1/workspace'))['reviews'] if r['id']==rid);assessment=review['assessments'][0]
            scores=[dict(criterionId=c['id'],studentId=None if c['scope']=='TEAM' else review['roster'][0]['id'],marks='20') for c in review['criteria']]
            def post(c,path,body):return self.ok(c.post(path,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))
            post(faculty,academic+f'/assessments/{assessment["id"]}/draft',dict(expectedAssessmentVersion=1,scores=scores))
            post(faculty,academic+f'/assessments/{assessment["id"]}/finalize',dict(expectedAssessmentVersion=2))
            post(hod,academic+f'/reviews/{rid}/publish',dict(expectedReviewRevision=2))
            self.assertEqual(self.db.execute('SELECT state FROM assessments WHERE id=%s',(original,)).fetchone()['state'],'DRAFT')
            self.assertEqual(hod.post(route,dict(expectedReviewRevision=3,facultyIds=[FACULTY]),format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,409)

        def test_draft_project_revision_is_versioned_and_closes_after_submission(self):
            p,_,_,_=self.fixture();route=f'/api/v1/projects/{p}/proposal-details'
            body=dict(expectedRevision=1,title='Revised draft project title',description='Revised draft details retained with history.')
            for who in ['faculty-a','staff-policy','coordinator','department-admin','tech-admin','student-b']:
                self.assertEqual(self.client(who).post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,403)
            c=self.client('student-a');key=uuid4().hex
            response=c.post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=key);self.ok(response)
            self.assertEqual(self.ok(c.post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=key)),response.json())
            self.assertEqual(c.post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,409)
            current=self.project('student-a',p);self.assertEqual(current['title'],body['title']);self.assertEqual(current['description'],body['description']);self.assertEqual(len(current['proposalHistory']),1)
            v=self.ok(self.upload(p))['documentVersionId'];self.ok(self.submit(p,v))
            body['expectedRevision']=2;body['title']='Cannot rewrite submitted evidence'
            self.assertEqual(c.post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,409)
            self.assertEqual(self.project('student-a',p)['title'],'Revised draft project title')

        def test_requirement_reviewers_are_scoped_and_reassignment_preserves_case(self):
            from smartpro.identity import Principal
            p,_,offering,_=self.fixture();route=f'/api/v1/staff/departments/{CSE}/document-requirements'
            uid=str(self.db.execute("INSERT INTO users(display_name,email) VALUES('Configured reviewer',%s) RETURNING id",(uuid4().hex+'@example.invalid',)).fetchone()['id'])
            self.db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'FACULTY')",(uid,CSE))
            other=APIClient();other.force_authenticate(Principal(uid,role='Faculty',role_choices=('Faculty',)))
            mandate=str(self.db.execute('SELECT id FROM academic_hod_mandates WHERE department_id=%s AND enabled LIMIT 1',(CSE,)).fetchone()['id'])
            cfg=dict(offeringId=offering,requirementKey=None,expectedPolicyId=None,name='Scoped configured PDF',opensAt='2026-01-01T00:00:00Z',closesAt='2027-06-01T00:00:00Z',maxBytes=2097152,required=True,allowApproval=True,allowChanges=True,allowRevisions=True,reviewerIds=[uid],authority=dict(hodMandateId=mandate,source='EXTERNAL_INSTRUCTION',confirmed=True,reference=''))
            def configure():return self.ok(self.client('department-admin').post(route,cfg,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))
            policy=configure();req=policy['requirementKey']
            response=self.client('student-a').post(base+f'/projects/{p}/uploads?requirementKey={req}',{'file':SimpleUploadedFile('scoped.pdf',pdf_bytes(),content_type='application/pdf')},format='multipart',HTTP_IDEMPOTENCY_KEY=uuid4().hex)
            vid=self.ok(response)['documentVersionId'];c=next(r for r in self.project('student-a',p)['requirements'] if r['key']==req)['case']
            self.ok(self.command('student-a','SUBMIT',dict(projectId=p,requirementKey=req,documentVersionId=vid,expectedCaseVersion=c['version'])))
            self.assertEqual(self.client('faculty-a').get(f'/api/v1/document-versions/{vid}/content').status_code,403)
            self.assertEqual(self.client('faculty-a').get(f'/api/v1/submission-cases/{c["id"]}').status_code,403)
            self.assertEqual(other.get(f'/api/v1/document-versions/{vid}/content').status_code,200)
            cfg.update(requirementKey=req,expectedPolicyId=policy['id'],reviewerIds=[FACULTY]);configure()
            self.assertEqual(other.get(f'/api/v1/document-versions/{vid}/content').status_code,403)
            c=next(r for r in self.project('faculty-a',p)['requirements'] if r['key']==req)['case']
            self.ok(self.command('faculty-a','DECIDE',dict(projectId=p,requirementKey=req,attemptId=c['attempts'][-1]['id'],expectedCaseVersion=c['version'],decision='APPROVE',comment='Authorized reassigned reviewer decision.')))
            self.assertEqual(next(r for r in self.project('student-a',p)['requirements'] if r['key']==req)['policyId'],policy['id'])

        def test_optional_synopsis_does_not_block_proposal_when_its_window_is_closed(self):
            _,_,offering,_=self.fixture()
            previous=str(self.db.execute("SELECT policy_id FROM submission_offering_requirements WHERE offering_id=%s AND requirement_key='SYNOPSIS'",(offering,)).fetchone()['policy_id'])
            mandate=str(self.db.execute('SELECT id FROM academic_hod_mandates WHERE department_id=%s AND enabled LIMIT 1',(CSE,)).fetchone()['id'])
            cfg=dict(offeringId=offering,requirementKey='SYNOPSIS',expectedPolicyId=previous,name='Optional synopsis',opensAt='2026-01-01T00:00:00Z',closesAt='2026-01-02T00:00:00Z',maxBytes=2097152,required=False,allowApproval=True,allowChanges=True,allowRevisions=True,reviewerIds=[FACULTY],authority=dict(hodMandateId=mandate,source='EXTERNAL_INSTRUCTION',confirmed=True,reference=''))
            self.ok(self.client('department-admin').post(f'/api/v1/staff/departments/{CSE}/document-requirements',cfg,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))
            capability=self.ok(self.client('student-a').get(f'/api/v1/curriculum-offerings/{offering}/proposal'))
            self.assertFalse(capability['requiresSynopsis']);self.assertEqual(capability['submissionState'],'NOT_REQUIRED')

        def test_new_offering_does_not_invent_mandatory_documents(self):
            _,_,_,cfg=self.fixture()
            kind=str(self.db.execute("INSERT INTO curriculum_types(code,label) VALUES(%s,'Configured offering without mandated documents') RETURNING id",('NO-DOC-'+uuid4().hex.upper(),)).fetchone()['id'])
            mandate=str(self.db.execute('SELECT id FROM academic_hod_mandates WHERE department_id=%s AND enabled LIMIT 1',(CSE,)).fetchone()['id'])
            cfg.update(curriculumTypeId=kind,requiresSynopsis=False,submissionOpensAt=None,submissionClosesAt=None,maxBytes=None,facultyApprovalEnabled=False)
            body=dict(action='RECORD',kind='OFFERING',configuration=cfg,authority=dict(hodMandateId=mandate,source='EXTERNAL_INSTRUCTION',confirmed=True,reference=''))
            offering=self.ok(self.client('department-admin').post(f'/api/v1/staff/departments/{CSE}/setup',body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))['offeringId']
            self.assertEqual(self.db.execute('SELECT count(*) n FROM submission_offering_requirements WHERE offering_id=%s',(offering,)).fetchone()['n'],0)
            capability=self.ok(self.client('student-a').get(f'/api/v1/curriculum-offerings/{offering}/proposal'))
            self.assertEqual(capability['submissionState'],'NOT_REQUIRED');self.assertFalse(capability['requiresSynopsis'])

        def test_configured_document_uses_existing_storage_feedback_and_revision_history(self):
            p,_,offering,_=self.fixture();route=f'/api/v1/staff/departments/{CSE}/document-requirements'
            mandate=str(self.db.execute('SELECT id FROM academic_hod_mandates WHERE department_id=%s AND enabled LIMIT 1',(CSE,)).fetchone()['id'])
            cfg=dict(offeringId=offering,requirementKey=None,expectedPolicyId=None,name='Department-configured evidence PDF',opensAt='2026-01-01T00:00:00Z',closesAt='2027-06-01T00:00:00Z',maxBytes=2097152,required=True,allowApproval=True,allowChanges=True,allowRevisions=True,reviewerIds=[FACULTY],authority=dict(hodMandateId=mandate,source='EXTERNAL_INSTRUCTION',confirmed=True,reference=''))
            for who in ['student-a','faculty-a','coordinator','staff-policy','tech-admin']:
                self.assertEqual(self.client(who).post(route,cfg,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,403)
            policy=self.ok(self.client('department-admin').post(route,cfg,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex));req=policy['requirementKey']
            def upload(text):return self.ok(self.client('student-a').post(base+f'/projects/{p}/uploads?requirementKey={req}',{'file':SimpleUploadedFile('evidence.pdf',pdf_bytes(text),content_type='application/pdf')},format='multipart',HTTP_IDEMPOTENCY_KEY=uuid4().hex))['documentVersionId']
            def case(who):return next(r for r in self.project(who,p)['requirements'] if r['key']==req)['case']
            def submit(vid):return self.ok(self.command('student-a','SUBMIT',dict(projectId=p,requirementKey=req,documentVersionId=vid,expectedCaseVersion=case('student-a')['version'])))
            def decide(choice,comment):
                c=case('faculty-a');return self.ok(self.command('faculty-a','DECIDE',dict(projectId=p,requirementKey=req,attemptId=c['attempts'][-1]['id'],expectedCaseVersion=c['version'],decision=choice,comment=comment)))
            v1=upload('Configured first version');submit(v1)
            self.assertEqual(self.client('faculty-a').get(f'/api/v1/document-versions/{v1}/content').content,pdf_bytes('Configured first version'))
            decide('COMMENT','Review is in progress.');self.assertEqual(case('student-a')['state'],'AWAITING_REVIEW')
            decide('REQUEST_CHANGES','Expand the methods section.')
            v2=upload('Configured revised version');submit(v2);decide('APPROVE','Revised document accepted.')
            self.assertEqual(case('student-a')['state'],'APPROVED');self.assertEqual(len(case('student-a')['versions']),2)
            self.assertEqual(len(case('student-a')['attempts'][0]['feedback']),2)
            # Configuration revisions append policies; submitted evidence stays pinned.
            cfg.update(requirementKey=req,expectedPolicyId=policy['id'],name='Revised requirement name')
            new=self.ok(self.client('department-admin').post(route,cfg,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex));self.assertNotEqual(new['id'],policy['id'])
            self.assertEqual(next(r for r in self.project('student-a',p)['requirements'] if r['key']==req)['policyId'],policy['id'])
            self.assertEqual(self.client('department-admin').get(f'/api/v1/document-versions/{v1}/content').status_code,403)

        def test_assignment_end_and_coordinator_responsibility_revocation(self):
            p,_,_,_=self.fixture();route=f'/api/v1/staff/departments/{CSE}/assignment-management';hod=self.client('staff-policy')
            assignment=self.db.execute("SELECT id FROM faculty_assignments WHERE project_id=%s AND assignment_type='REVIEWER'",(p,)).fetchone()['id']
            def post(who,body):return self.client(who).post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex)
            for who in ['student-a','faculty-a','department-admin','tech-admin']:self.assertEqual(post(who,dict(action='END_ASSIGNMENT',assignmentId=str(assignment))).status_code,403)
            self.ok(post('staff-policy',dict(action='END_ASSIGNMENT',assignmentId=str(assignment))))
            row=self.db.execute('SELECT valid_until FROM faculty_assignments WHERE id=%s',(assignment,)).fetchone();self.assertIsNotNone(row['valid_until'])
            self.assertEqual(post('staff-policy',dict(action='END_ASSIGNMENT',assignmentId=str(assignment))).status_code,409)
            # Establish an explicit finite guide-allocation responsibility, then
            # revoke it prospectively without changing its immutable grant row.
            coord=self.db.execute("SELECT id FROM academic_coordinator_mandates WHERE user_id='00000000-0000-4000-8000-000000000008' AND NOT revoked ORDER BY id LIMIT 1").fetchone()['id']
            delegated=self.ok(hod.post(f'/api/v1/staff/departments/{CSE}/coordinator-operations',dict(mandateId=str(coord),operation='GUIDE',validUntil='2027-05-01T00:00:00Z'),format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))['id']
            self.ok(post('staff-policy',dict(action='REVOKE_OPERATION',grantId=delegated)))
            self.assertIsNotNone(self.db.execute('SELECT revoked_at FROM coordinator_operation_revocations WHERE grant_id=%s',(delegated,)).fetchone())
            self.assertEqual(post('coordinator',dict(action='REVOKE_OPERATION',grantId=delegated)).status_code,403)
            self.assertTrue(any(a['id']==str(assignment) for a in self.ok(hod.get(route))['assignments']))

        def test_cycle_date_management_has_history_and_preserves_existing_evidence(self):
            route=f'/api/v1/staff/departments/{CSE}/configuration-management';client=self.client('department-admin')
            cycle=next(c for c in self.ok(client.get(route))['cycles'] if c['id']=='11000000-0000-4000-8000-000000000001')
            mandate=str(self.db.execute('SELECT id FROM academic_hod_mandates WHERE department_id=%s AND enabled LIMIT 1',(CSE,)).fetchone()['id'])
            body=dict(action='CYCLE',cycleId=cycle['id'],expectedRevision=cycle['management_revision'],code=cycle['code'],startsOn=cycle['starts_on'],endsOn='2027-07-01',authority=dict(hodMandateId=mandate,source='EXTERNAL_INSTRUCTION',confirmed=True,reference=''))
            def send(who,payload):return self.client(who).post(route,payload,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex)
            for who in ['student-a','faculty-a','coordinator','staff-policy','tech-admin']:self.assertEqual(send(who,body).status_code,403)
            result=self.ok(send('department-admin',body));self.assertEqual(result['revision'],cycle['management_revision']+1)
            self.assertEqual(send('department-admin',body).status_code,409)
            body.update(expectedRevision=result['revision'],startsOn='2020-01-01',endsOn='2020-07-01')
            self.assertEqual(send('department-admin',body).status_code,409)
            data=self.ok(client.get(route));self.assertEqual(data['history'][0]['metadata']['before']['ends_on'],cycle['ends_on'])
            self.assertEqual(next(c for c in data['cycles'] if c['id']==cycle['id'])['ends_on'],'2027-07-01')

        def test_offering_management_edits_availability_history_and_denials(self):
            p,_,oid,cfg=self.fixture()
            route=f'/api/v1/staff/departments/{CSE}/offering-management'
            client=self.client('department-admin')
            mandate=str(self.db.execute('SELECT id FROM academic_hod_mandates WHERE department_id=%s AND enabled LIMIT 1',(CSE,)).fetchone()['id'])
            authority=dict(hodMandateId=mandate,source='EXTERNAL_INSTRUCTION',confirmed=True,reference='')
            def send(body,who='department-admin',key=None):return self.client(who).post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=key or uuid4().hex)
            row=next(x for x in self.ok(client.get(route))['offerings'] if x['id']==oid)
            body=dict(action='EDIT',offeringId=oid,expectedRevision=row['management_revision'],configuration=dict(cfg,submissionClosesAt='2027-05-20T00:00:00Z'),authority=authority)
            for who in ['student-a','faculty-a','coordinator','tech-admin','staff-policy']:self.assertEqual(send(body,who).status_code,403,who)
            result=self.ok(send(body));self.assertEqual(result['revision'],row['management_revision']+1)
            self.assertEqual(send(body).status_code,409)
            body['expectedRevision']=result['revision'];body['configuration']['semester']='OTHER'
            self.assertEqual(send(body).status_code,409)
            pause=dict(action='AVAILABILITY',offeringId=oid,expectedRevision=result['revision'],availability='ARCHIVED',authority=authority)
            key=uuid4().hex;archived=self.ok(send(pause,key=key));self.assertEqual(self.ok(send(pause,key=key)),archived)
            self.assertNotIn(oid,[x['id'] for x in self.ok(self.client('student-a').get('/api/v1/me/curriculum-offerings'))['results']])
            self.assertEqual(self.client('student-a').get(f'/api/v1/curriculum-offerings/{oid}/proposal').status_code,403)
            # Older HOD authorizations cannot silently reactivate it.
            instruction=self.ok(self.command('staff-policy','AUTHORIZE',dict(configuration=cfg)))['instructionId']
            self.assertEqual(self.command('department-admin','CONFIGURE',dict(instructionId=instruction)).status_code,409)
            pause.update(expectedRevision=archived['revision'],availability='ACTIVE');self.ok(send(pause))
            self.assertIn(oid,[x['id'] for x in self.ok(self.client('student-a').get('/api/v1/me/curriculum-offerings'))['results']])
            row=next(x for x in self.ok(client.get(route))['offerings'] if x['id']==oid)
            self.assertEqual(len(row['history']),3)
            self.assertEqual(row['history'][-1]['before_state']['configuration']['submissionClosesAt'],cfg['submissionClosesAt'])

        def test_unused_offering_semester_correction_preserves_identity(self):
            # Reproduce the real Community project defect: arbitrary text differed
            # from the student's trusted semester. Correct only an unused offering.
            _,_,_,cfg=self.fixture()
            kind=self.db.execute("INSERT INTO curriculum_types(code,label) VALUES(%s,'Community project') RETURNING id",('COMM-'+uuid4().hex.upper(),)).fetchone()['id']
            bad=dict(cfg,curriculumTypeId=str(kind),semester='3')
            instruction=self.ok(self.command('staff-policy','AUTHORIZE',dict(configuration=bad)))['instructionId']
            oid=self.ok(self.command('department-admin','CONFIGURE',dict(instructionId=instruction)))['offeringId']
            self.assertNotIn(oid,[o['id'] for o in self.ok(self.client('student-a').get('/api/v1/me/curriculum-offerings'))['results']])
            mandate=str(self.db.execute('SELECT id FROM academic_hod_mandates WHERE department_id=%s AND enabled LIMIT 1',(CSE,)).fetchone()['id'])
            body=dict(action='EDIT',offeringId=oid,expectedRevision=0,configuration=dict(bad,semester=cfg['semester']),authority=dict(hodMandateId=mandate,source='EXTERNAL_INSTRUCTION',confirmed=True,reference=''))
            result=self.ok(self.client('department-admin').post(f'/api/v1/staff/departments/{CSE}/offering-management',body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))
            self.assertEqual(result['offeringId'],oid)
            self.assertIn(oid,[o['id'] for o in self.ok(self.client('student-a').get('/api/v1/me/curriculum-offerings'))['results']])

        def test_preexisting_configuration_receipts_remain_replayable(self):
            # These rows originate in the preserved pre-025 source, not this run.
            row=self.db.execute("SELECT * FROM document_command_receipts WHERE actor_id='00000000-0000-4000-8000-000000000012' AND action='CONFIGURE' AND NOT input ? 'reason' ORDER BY request_key LIMIT 1").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(self.ok(self.command('department-admin','CONFIGURE',row['input'],key=row['request_key'])),row['output'])

        def test_guide_can_read_but_synopsis_decision_needs_reviewer_assignment(self):
            p,_,_,_=self.fixture();vid=self.ok(self.upload(p))['documentVersionId'];self.ok(self.submit(p,vid))
            from smartpro.identity import Principal
            uid=self.db.execute("INSERT INTO users(display_name,email) VALUES('Guide only',%s) RETURNING id",(uuid4().hex+'@example.invalid',)).fetchone()['id']
            self.db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'FACULTY')",(uid,CSE))
            self.db.execute("INSERT INTO faculty_assignments(project_id,faculty_user_id,assignment_type) VALUES(%s,%s,'GUIDE')",(p,uid))
            client=APIClient();client.force_authenticate(Principal(str(uid),role='Faculty',role_choices=('Faculty',)))
            projects=self.ok(client.get(base))['projects'];record=next(x for x in projects if x['id']==p)
            self.assertFalse(record['canReview']);self.assertEqual(client.get(f'/api/v1/document-versions/{vid}/content').content,pdf_bytes())
            case=record['case'];body=dict(action='DECIDE',projectId=p,attemptId=case['attempts'][-1]['id'],expectedCaseVersion=case['version'],decision='APPROVE',comment='Guide is not assigned to review')
            self.assertEqual(client.post(base,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,403)
            self.ok(self.command('staff-policy','ASSIGN_REVIEWER',dict(projectId=p,facultyId=str(uid))))
            self.ok(client.post(base,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))

        def test_proposal_description_is_private_immutable_and_idempotent(self):
            p,_,offering,_=self.fixture()
            team=str(self.db.execute('SELECT team_id FROM projects WHERE id=%s',(p,)).fetchone()['team_id'])
            body=dict(offeringId=offering,teamId=team,title='Proposal with details',description='Study accessible submission and feedback workflows.')
            key=uuid4().hex
            def submit():
                close_old_connections()
                try:return self.client('student-a').post('/api/v1/projects',body,format='json',HTTP_IDEMPOTENCY_KEY=key)
                finally:close_old_connections()
            with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(lambda _:submit(),range(2)))
            self.assertEqual(sorted(r.status_code for r in responses),[200,201])
            project=responses[0].json()['id']
            self.assertEqual(responses[1].json()['id'],project)
            self.assertEqual(self.project('student-a',project)['description'],body['description'])
            body['description']='Changed retry'
            self.assertEqual(submit().status_code,409)
            self.assertEqual(self.db.execute('SELECT description FROM project_proposal_details WHERE project_id=%s',(project,)).fetchone()['description'],'Study accessible submission and feedback workflows.')
            with self.assertRaises(psycopg.Error):self.db.execute('UPDATE project_proposal_details SET description=%s WHERE project_id=%s',('Rewrite',project))
            with psycopg.connect(**dict(app,dbname=name),autocommit=True) as runtime:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):runtime.execute('SELECT * FROM project_proposal_details')

        def test_optional_coordinator_notes_and_external_instruction_denials(self):
            base=f'/api/v1/academic/departments/{CSE}'
            hod=self.client('staff-policy')
            revision=self.ok(hod.get(base+'/policies'))['revision']
            uid=self.db.execute("INSERT INTO users(display_name,email) VALUES('Faculty for appointment',%s) RETURNING id",(uuid4().hex+'@example.invalid',)).fetchone()['id']
            self.db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'FACULTY')",(uid,CSE))
            self.ok(hod.post(base+'/coordinators',dict(expectedRevision=revision,userId=str(uid),validUntil='2027-06-01T00:00:00Z'),format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))
            mandate=self.db.execute('SELECT id,reason FROM academic_coordinator_mandates WHERE user_id=%s',(uid,)).fetchone()
            self.assertEqual(mandate['reason'],'')
            self.ok(hod.post(base+'/coordinators/revoke',dict(expectedRevision=revision+1,mandateId=str(mandate['id'])),format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))
            self.assertTrue(self.db.execute('SELECT revoked FROM academic_coordinator_mandates WHERE id=%s',(mandate['id'],)).fetchone()['revoked'])
            route=f'/api/v1/staff/departments/{CSE}/setup'
            h=self.db.execute('SELECT id FROM academic_hod_mandates WHERE department_id=%s AND enabled LIMIT 1',(CSE,)).fetchone()['id']
            body=dict(action='RECORD',kind='TYPE',configuration=dict(code='EXT-'+uuid4().hex[:8].upper(),label='Approved external course'),authority=dict(hodMandateId=str(h),source='EXTERNAL_INSTRUCTION',confirmed=True,reference=''))
            for who in ['student-a','faculty-a','coordinator','tech-admin','staff-policy']:
                self.assertEqual(self.client(who).post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,403)
            c=self.client('department-admin')
            for malformed in [[1],{'action':{}},{'action':'RECORD','kind':{},'configuration':{},'authority':body['authority']}]:
                self.assertIn(c.post(route,malformed,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,[400,403])
            key=uuid4().hex;c=self.client('department-admin')
            result=self.ok(c.post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=key))
            self.assertEqual(self.ok(c.post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=key)),result)
            body['authority']['confirmed']=False
            self.assertEqual(c.post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,400)
            body['authority']['confirmed']=True;body['authority']['hodMandateId']=str(uuid4())
            self.assertEqual(c.post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,403)

        def test_role_and_foreign_department_denials(self):
            p,_,_,config=self.fixture();vid=self.ok(self.upload(p))['documentVersionId']
            for role in ['student-b','faculty-other','tech-admin','department-admin','student-ece']:
                self.assertEqual(self.client(role).get(f'/api/v1/document-versions/{vid}/content').status_code,403,role)
                self.assertEqual(self.upload(p,who=role).status_code,403,role)
            for role in ['department-admin','coordinator','tech-admin','faculty-a','student-a']:
                self.assertEqual(self.command(role,'AUTHORIZE',{'configuration':config,'reason':'Unauthorized'}).status_code,403,role)

        def test_closed_window_invalid_files_and_missing_policy(self):
            p,_,_,_=self.fixture(closed=True);self.assertEqual(self.upload(p).status_code,409)
            p,_,_,_=self.fixture()
            for data,filename,mime in [(b'bad','synopsis.pdf','application/pdf'),(b'%PDF-1.4\n','synopsis.pdf','application/pdf'),(pdf_bytes(),'x.exe','application/pdf'),(pdf_bytes(),'x.pdf','text/plain'),(pdf_bytes()+b'x'*2097152,'x.pdf','application/pdf'),(pdf_bytes().replace(b'/Type /Catalog',b'/JavaScript /Catalog'),'x.pdf','application/pdf')]:
                self.assertIn(self.upload(p,data,filename=filename,mime=mime).status_code,[400,422])
            self.assertIsNone(self.project('student-a',p)['case'])
            response=self.client('student-a').post(base+f'/projects/{p}/uploads',{'file':[SimpleUploadedFile('a.pdf',pdf_bytes(),content_type='application/pdf'),SimpleUploadedFile('b.pdf',pdf_bytes(),content_type='application/pdf')]},format='multipart',HTTP_IDEMPOTENCY_KEY=uuid4().hex)
            self.assertEqual(response.status_code,400)

        def test_upload_retry_and_conflicting_bytes(self):
            p,_,_,_=self.fixture();key=uuid4().hex
            first=self.ok(self.upload(p,key=key));self.assertEqual(first,self.ok(self.upload(p,key=key)))
            self.assertEqual(self.upload(p,pdf_bytes('Different'),key=key).status_code,400)
            self.assertEqual(len(self.project('student-a',p)['case']['versions']),1)

        def test_approval_disabled_and_stale_case_denied(self):
            p,_,_,_=self.fixture(approval=False);vid=self.ok(self.upload(p))['documentVersionId'];self.ok(self.submit(p,vid));c=self.project('faculty-a',p)['case']
            body=dict(projectId=p,attemptId=c['attempts'][0]['id'],expectedCaseVersion=c['version'],decision='APPROVE',comment='Cannot override configured policy')
            self.assertEqual(self.command('faculty-a','DECIDE',body).status_code,409)
            body.update(decision='REQUEST_CHANGES',expectedCaseVersion=1);self.assertEqual(self.command('faculty-a','DECIDE',body).status_code,409)
            self.assertEqual(self.project('student-a',p)['case']['state'],'AWAITING_REVIEW')

        def test_atomic_rollback_and_retry(self):
            p,_,_,_=self.fixture();key=uuid4().hex
            from smartpro import document_views
            original=document_views.command
            def fail_complete(actor,dept,action,body,k):
                if action=='COMPLETE_UPLOAD':raise RuntimeError('Synthetic failure before metadata commit')
                return original(actor,dept,action,body,k)
            with patch.object(document_views,'command',side_effect=fail_complete):
                with self.assertRaises(RuntimeError):self.upload(p,key=key)
            self.assertEqual(self.project('student-a',p)['case']['versions'],[])
            self.ok(self.upload(p,key=key));self.assertEqual(len(self.project('student-a',p)['case']['versions']),1)

        def test_concurrent_uploads_keep_distinct_ordered_versions(self):
            p,_,_,_=self.fixture()
            def send(n):
                close_old_connections()
                try:return self.upload(p,pdf_bytes('Concurrent '+str(n)+' '+('x'*262144))).status_code
                finally:close_old_connections()
            with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(send,[1,2]))
            self.assertEqual(statuses,[200,200]);self.assertEqual([v['version'] for v in self.project('student-a',p)['case']['versions']],[1,2])

        def test_two_students_upload_then_compete_with_review_for_current_version(self):
            from threading import Barrier
            p,_,offering,_=self.fixture()
            team=self.db.execute('SELECT team_id FROM projects WHERE id=%s',(p,)).fetchone()['team_id']
            student_b='00000000-0000-4000-8000-000000000002'
            self.db.execute('INSERT INTO team_memberships(team_id,user_id,curriculum_offering_id) VALUES(%s,%s,%s)',(team,student_b,offering))
            def parallel(actions):
                barrier=Barrier(len(actions))
                def run(action):
                    close_old_connections()
                    try:
                        barrier.wait(timeout=5)
                        return action()
                    finally:close_old_connections()
                with ThreadPoolExecutor(max_workers=len(actions)) as pool:
                    return list(pool.map(run,actions))
            uploads=parallel([lambda:self.upload(p,pdf_bytes('A '+('x'*262144))),
                              lambda:self.upload(p,pdf_bytes('B '+('y'*262144)),who='student-b')])
            first,second=[self.ok(result)['documentVersionId'] for result in uploads]
            case=self.project('student-a',p)['case']
            self.assertEqual(sorted(v['version'] for v in case['versions']),[1,2])
            submit=lambda actor,version,revision:self.command(actor,'SUBMIT',
                dict(projectId=p,documentVersionId=version,expectedCaseVersion=revision))
            results=parallel([lambda:submit('student-a',first,case['version']),
                              lambda:submit('student-b',second,case['version'])])
            self.assertEqual(sorted(r.status_code for r in results),[200,409])
            case=self.project('faculty-a',p)['case'];attempt=case['attempts'][0]
            rejected_version=second if attempt['versionId']==first else first
            rejected_uploader='student-b' if rejected_version==second else 'student-a'
            review=lambda:self.command('faculty-a','DECIDE',dict(projectId=p,attemptId=attempt['id'],
                expectedCaseVersion=case['version'],decision='REQUEST_CHANGES',comment='Revise the submitted version'))
            results=parallel([review,lambda:submit(rejected_uploader,rejected_version,case['version'])])
            self.assertEqual([r.status_code for r in results],[200,409])
            revised=self.project('student-b',p)['case']
            self.assertEqual(revised['attempts'][0]['versionId'],attempt['versionId'])
            self.assertEqual(len(revised['attempts'][0]['feedback']),1)
            self.ok(submit(rejected_uploader,rejected_version,revised['version']))
            history=self.project('student-a',p)['case']
            self.assertEqual([a['versionId'] for a in history['attempts']],[attempt['versionId'],rejected_version])

        def test_two_students_cross_the_same_submission_deadline(self):
            from threading import Barrier
            deadline=self.db.execute("SELECT clock_timestamp()+interval '8 seconds' AS deadline").fetchone()['deadline']
            p,_,offering,_=self.fixture(closes_at=deadline.isoformat())
            team=self.db.execute('SELECT team_id FROM projects WHERE id=%s',(p,)).fetchone()['team_id']
            self.db.execute('INSERT INTO team_memberships(team_id,user_id,curriculum_offering_id) VALUES(%s,%s,%s)',
                            (team,'00000000-0000-4000-8000-000000000002',offering))
            vid=self.ok(self.upload(p))['documentVersionId']
            case=self.project('student-a',p)['case']
            self.db.execute("SELECT pg_sleep(greatest(0,extract(epoch FROM %s-clock_timestamp()))+0.05)",(deadline,))
            barrier=Barrier(2)
            def submit(actor):
                close_old_connections()
                try:
                    barrier.wait(timeout=5)
                    return self.command(actor,'SUBMIT',dict(projectId=p,documentVersionId=vid,
                        expectedCaseVersion=case['version'])).status_code
                finally:close_old_connections()
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(list(pool.map(submit,['student-a','student-b'])),[409,409])
            history=self.project('student-a',p)['case']
            self.assertEqual([row['id'] for row in history['versions']],[vid])
            self.assertEqual(history['attempts'],[])

        def test_upload_completion_checks_database_deadline(self):
            from smartpro import document_views
            deadline=self.db.execute("SELECT clock_timestamp()+interval '8 seconds' AS deadline").fetchone()['deadline']
            p,_,_,_=self.fixture(closes_at=deadline.isoformat())
            original=document_views.command
            reached=[]
            def wait_until_closed(actor,dept,action,body,key):
                if action=='COMPLETE_UPLOAD':
                    reached.append(action)
                    self.db.execute("SELECT pg_sleep(greatest(0,extract(epoch FROM %s-clock_timestamp()))+0.05)",(deadline,))
                return original(actor,dept,action,body,key)
            with patch.object(document_views,'command',side_effect=wait_until_closed):
                self.assertEqual(self.upload(p).status_code,409)
            self.assertEqual(reached,['COMPLETE_UPLOAD'])
            self.assertEqual(self.project('student-a',p)['case']['versions'],[])

        def test_interrupted_upload_recovers_same_private_object(self):
            from smartpro import document_views
            from smartpro.staff import StaffUnavailable
            p,_,_,_=self.fixture()
            key=uuid4().hex; data=pdf_bytes('Interrupted publication')
            original=document_views.command
            def interrupted(actor,dept,action,body,request_key):
                if action=='COMPLETE_UPLOAD':
                    raise StaffUnavailable('Synthetic interruption before completion')
                return original(actor,dept,action,body,request_key)
            with patch.object(document_views,'command',side_effect=interrupted):
                self.assertEqual(self.upload(p,data,key).status_code,503)
            self.assertEqual(self.project('student-a',p)['case']['versions'],[])
            recovered=self.ok(self.upload(p,data,key))
            self.assertEqual(recovered,self.ok(self.upload(p,data,key)))
            self.assertEqual(len(self.project('student-a',p)['case']['versions']),1)
            response=self.client('faculty-a').get(f"/api/v1/document-versions/{recovered['documentVersionId']}/content")
            self.assertEqual(response.content,data)

        def test_admin_exact_instruction_idempotency_and_direct_table_denial(self):
            _,instruction,_,_=self.fixture()
            self.assertEqual(self.command('department-admin','CONFIGURE',{'instructionId':instruction}).status_code,409)
            self.assertEqual(self.client('department-admin').get('/api/v1/academic/departments/'+CSE+'/policies').status_code,403)
            with psycopg.connect(**dict(app,dbname=name),autocommit=True) as db:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):db.execute('SELECT * FROM offering_operational_instructions')
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):db.execute('SELECT * FROM document_command_receipts')

        def test_feature_gates_disabled(self):
            with patch.dict(os.environ,SMARTPRO_DOCUMENT_API='NO'):
                self.assertEqual(self.client('student-a').get(base).status_code,503)
                self.assertEqual(self.client('student-a').get('/api/v1/document-versions/'+str(uuid4())+'/content').status_code,503)
            with patch.dict(os.environ,SMARTPRO_ENV='production'):
                self.assertEqual(self.client('student-a').get(base).status_code,401)
            with patch.dict(os.environ,SMARTPRO_PROJECT_API='NO'):
                self.assertEqual(self.client('student-a').get(f'/api/v1/curriculum-offerings/{uuid4()}/proposal').status_code,503)
            for gate in ['SMARTPRO_STAFF_API','SMARTPRO_ACADEMIC_API']:
                with patch.dict(os.environ,**{gate:'NO'}):
                    self.assertEqual(self.client('staff-policy').post(f'/api/v1/staff/departments/{CSE}/projects/{uuid4()}/guide',dict(facultyId=FACULTY,expectedGuideId=None,reason='Disabled operation'),format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,503)
            with patch.dict(os.environ,SMARTPRO_ACADEMIC_API='NO'):
                route=f'/api/v1/academic/departments/{CSE}/reviews/{uuid4()}/management'
                self.assertEqual(self.client('staff-policy').get(route).status_code,503)
                self.assertEqual(self.client('staff-policy').post(route,dict(expectedReviewRevision=0,facultyIds=[FACULTY]),format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,503)
            with self.db.transaction(force_rollback=True):
                self.db.execute('UPDATE academic_governance_settings SET enabled=false WHERE department_id=%s',(CSE,))
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.db.transaction():self.db.execute('SELECT smartpro_proposal_offering(%s,%s)',('00000000-0000-4000-8000-000000000001',uuid4()))
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.db.transaction():self.db.execute('SELECT smartpro_register_proposal(%s,%s,%s,%s,%s)',('00000000-0000-4000-8000-000000000001',uuid4(),uuid4(),'Disabled proposal',uuid4().hex))

        def test_legacy_direct_writes_cannot_bypass_managed_workflow(self):
            p,_,_,_=self.fixture();vid=self.ok(self.upload(p))['documentVersionId'];self.ok(self.submit(p,vid));case=self.project('student-a',p)['case']
            with psycopg.connect(**dict(app,dbname=name),autocommit=True) as db:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    db.execute("UPDATE submission_cases SET state='CHANGES_REQUESTED' WHERE id=%s",(case['id'],))
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    db.execute("INSERT INTO upload_sessions(document_id,user_id,storage_key) SELECT document_id,%s,%s FROM document_versions WHERE id=%s",('00000000-0000-4000-8000-000000000001',uuid4().hex+'.pdf',vid))
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    db.execute("INSERT INTO approval_decisions(attempt_id,project_id,reviewer_user_id,decision) VALUES(%s,%s,%s,'APPROVE')",(case['attempts'][0]['id'],p,FACULTY))
            self.assertEqual(self.project('student-a',p)['case']['state'],'AWAITING_REVIEW')

        def test_ended_membership_and_revoked_reviewer_are_denied(self):
            p,_,_,_=self.fixture();vid=self.ok(self.upload(p))['documentVersionId'];self.ok(self.submit(p,vid));case=self.project('student-a',p)['case']
            self.db.execute("UPDATE faculty_assignments SET valid_until=clock_timestamp() WHERE project_id=%s AND faculty_user_id=%s",(p,FACULTY))
            self.assertEqual(self.client('faculty-a').get(f'/api/v1/document-versions/{vid}/content').status_code,403)
            self.assertEqual(self.command('faculty-a','DECIDE',dict(projectId=p,attemptId=case['attempts'][0]['id'],expectedCaseVersion=case['version'],decision='REQUEST_CHANGES',comment='Ended assignment')).status_code,403)
            membership=self.db.execute('SELECT m.id FROM team_memberships m JOIN projects p ON p.team_id=m.team_id WHERE p.id=%s',(p,)).fetchone()['id']
            self.ok(self.client('student-a').post(f'/api/v1/memberships/{membership}/end',{},format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))
            self.assertEqual(self.client('student-a').get(f'/api/v1/document-versions/{vid}/content').status_code,403)
            self.assertEqual(len(self.project('coordinator',p)['case']['versions']),1)

        def test_corrupt_or_missing_storage_fails_closed(self):
            p,_,_,_=self.fixture();vid=self.ok(self.upload(p))['documentVersionId']
            path=next((Path(storage.name)/'files').glob('*.pdf'))
            key=self.db.execute('SELECT f.storage_key FROM document_versions v JOIN file_assets f ON f.id=v.file_asset_id WHERE v.id=%s',(vid,)).fetchone()['storage_key']
            path=Path(storage.name)/'files'/key
            original=path.read_bytes();path.write_bytes(b'x'*len(original))
            self.assertEqual(self.client('faculty-a').get(f'/api/v1/document-versions/{vid}/content').status_code,503)
            self.assertEqual(self.submit(p,vid).status_code,503)
            self.assertEqual(self.project('student-a',p)['case']['attempts'],[])
            path.unlink();self.assertEqual(self.client('faculty-a').get(f'/api/v1/document-versions/{vid}/content').status_code,503)

        def test_same_key_concurrent_upload_and_submission_retries(self):
            p,_,_,_=self.fixture();key=uuid4().hex
            def send(_):
                close_old_connections()
                try:return self.upload(p,key=key)
                finally:close_old_connections()
            with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(send,[1,2]))
            outputs=[self.ok(r) for r in responses];self.assertEqual(outputs[0],outputs[1]);self.assertEqual(len(self.project('student-a',p)['case']['versions']),1)
            body=dict(projectId=p,documentVersionId=outputs[0]['documentVersionId'],expectedCaseVersion=1);key=uuid4().hex
            def submit(_):
                close_old_connections()
                try:return self.ok(self.command('student-a','SUBMIT',body,key))
                finally:close_old_connections()
            with ThreadPoolExecutor(max_workers=2) as pool:submissions=list(pool.map(submit,[1,2]))
            self.assertEqual(submissions[0],submissions[1])
            self.assertEqual(len(self.project('student-a',p)['case']['attempts']),1)

        def test_new_offering_instructions_preserve_pinned_requirements(self):
            p,_,offering,config=self.fixture();self.ok(self.upload(p))
            binding=self.db.execute('SELECT b.policy_id FROM submission_requirement_bindings b JOIN submission_cases c ON c.id=b.case_id WHERE c.project_id=%s',(p,)).fetchone()['policy_id']
            stale=self.ok(self.command('staff-policy','AUTHORIZE',{'configuration':dict(config,maxBytes=150000),'reason':'Older pending instruction'}))['instructionId']
            config=dict(config,maxBytes=100000,facultyApprovalEnabled=False,submissionClosesAt='2027-01-01T00:00:00Z')
            instruction=self.ok(self.command('staff-policy','AUTHORIZE',{'configuration':config,'reason':'New version for future cases'}))['instructionId']
            from smartpro import document_views
            original=document_views.command
            applied=[]
            def install_while_uploading(actor,dept,action,body,key):
                if action=='COMPLETE_UPLOAD':
                    applied.append(self.ok(self.command('department-admin','CONFIGURE',{'instructionId':instruction})))
                return original(actor,dept,action,body,key)
            with patch.object(document_views,'command',side_effect=install_while_uploading):
                self.ok(self.upload(p,pdf_bytes('Pinned window upload '+('x'*262144))))
            self.assertEqual(len(self.project('student-a',p)['case']['versions']),2)
            result,=applied
            self.assertEqual(self.command('department-admin','CONFIGURE',{'instructionId':stale}).status_code,409)
            self.assertEqual(result['offeringId'],offering)
            self.assertEqual(self.project('student-a',p)['requirement']['maxBytes'],2097152)
            self.assertEqual(self.db.execute('SELECT policy_id FROM submission_requirement_bindings WHERE policy_id=%s',(binding,)).fetchone()['policy_id'],binding)
            self.assertEqual(self.db.execute('SELECT count(*) AS n FROM submission_requirement_policies WHERE offering_id=%s',(offering,)).fetchone()['n'],2)

        def test_disabled_governance_and_expired_admin_instruction_denied(self):
            p,instruction,_,_=self.fixture();vid=self.ok(self.upload(p))['documentVersionId']
            with self.db.transaction(force_rollback=True):
                self.db.execute('UPDATE academic_governance_settings SET enabled=false WHERE department_id=%s',(CSE,))
                # A separate connection sees committed controls only; invoke the
                # actual predicate on this transaction to exercise disabled state.
                self.assertFalse(self.db.execute("SELECT smartpro_document_scope(%s,%s,'read') AS allowed",(FACULTY,p)).fetchone()['allowed'])
            with self.db.transaction(force_rollback=True):
                self.db.execute("UPDATE department_role_assignments SET valid_until=clock_timestamp() WHERE user_id='00000000-0000-4000-8000-000000000012' AND role_code='ACADEMIC_ADMIN'")
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.db.transaction():
                        self.db.execute('SELECT smartpro_document_command(%s,%s,%s,%s,%s)',('00000000-0000-4000-8000-000000000012',CSE,'CONFIGURE',psycopg.types.json.Jsonb({'instructionId':instruction}),uuid4().hex))
            self.assertEqual(self.client('faculty-a').get(f'/api/v1/document-versions/{vid}/content').status_code,200)

        def test_missing_case_revision_and_naive_window_denied(self):
            p,_,_,config=self.fixture();vid=self.ok(self.upload(p))['documentVersionId']
            self.assertEqual(self.command('student-a','SUBMIT',{'projectId':p,'documentVersionId':vid,'expectedCaseVersion':None}).status_code,400)
            config=dict(config,visibleFrom='2026-11-01T00:00:00')
            self.assertEqual(self.command('staff-policy','AUTHORIZE',{'configuration':config,'reason':'Naive time rejected'}).status_code,400)

        def test_candidate_prerequisites_and_clean_atomic_install(self):
            from db_setup import execute_file
            scratch='smartpro_test_demo_migration_'+uuid4().hex[:10]
            fresh='smartpro_test_demo_migration_'+uuid4().hex[:10]
            with psycopg.connect(**dict(owner,dbname='postgres'),autocommit=True) as manager:
                manager.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(scratch)))
                manager.execute(sql.SQL('CREATE DATABASE {} TEMPLATE smartpro_test_academic_audit').format(sql.Identifier(fresh)))
            try:
                with psycopg.connect(**dict(owner,dbname=scratch),autocommit=True,row_factory=dict_row) as db:
                    for part in ['workflow','reads','guards']:
                        with self.assertRaises(psycopg.Error):
                            db.execute((ROOT/f'proposals/curriculum/019_document_{part}.sql').read_text())
                        db.execute('ROLLBACK')
                    self.assertIsNone(db.execute("SELECT to_regclass('public.offering_operational_instructions') AS t").fetchone()['t'])
                    for candidate in ['020_department_setup.sql','021_application_workspace.sql','022_proposal_context.sql','023_authorized_setup.sql','024_guide_schedule.sql','025_optional_notes.sql','026_external_instructions.sql','027_proposal_details.sql','028_document_responsibilities.sql','029_offering_lifecycle.sql','030_configuration_lifecycle.sql','031_assignment_lifecycle.sql','032_configurable_documents.sql','033_explicit_submission_requirements.sql','034_project_draft_revisions.sql','035_evaluator_lifecycle.sql','036_guide_synopsis_responsibility.sql']:
                        with self.assertRaises(psycopg.Error):db.execute((ROOT/'proposals/curriculum'/candidate).read_text())
                        db.execute('ROLLBACK')
                with psycopg.connect(**dict(owner,dbname=fresh),autocommit=True,row_factory=dict_row) as db:
                    before=db.execute('SELECT count(*) AS n FROM submission_attempts').fetchone()['n']
                    execute_file(db,ROOT/'proposals/curriculum/018_initial_evaluations.sql')
                    install_documents(db)
                    self.assertIsNotNone(db.execute("SELECT to_regclass('public.submission_offering_requirements') AS t").fetchone()['t'])
                    self.assertEqual(db.execute('SELECT count(*) AS n FROM submission_attempts').fetchone()['n'],before)
                    self.assertFalse(db.execute("SELECT has_table_privilege('smartpro_runtime','public.submission_requirement_policies','INSERT') AS allowed").fetchone()['allowed'])
                    self.assertFalse(db.execute("SELECT EXISTS(SELECT FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a WHERE p.oid='public.smartpro_document_command(uuid,uuid,text,jsonb,text)'::regprocedure AND a.grantee=0 AND a.privilege_type='EXECUTE') AS allowed").fetchone()['allowed'])
            finally:
                with psycopg.connect(**dict(owner,dbname='postgres'),autocommit=True) as manager:
                    for database in [scratch,fresh]:
                        assert database.startswith('smartpro_test_demo_migration_')
                        manager.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))

        def test_setup_requires_hod_then_original_admin_and_persists(self):
            route=f'/api/v1/staff/departments/{CSE}/setup'
            def send(who,body):return self.client(who).post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex)
            body=dict(action='REQUEST',kind='CYCLE',configuration={'code':'YEAR-'+uuid4().hex[:8],'startsOn':'2027-07-01','endsOn':'2028-06-30'},reason='Department calendar')
            for role in ['student-a','faculty-a','tech-admin']:
                self.assertEqual(send(role,body).status_code,403)
            rid=self.ok(send('department-admin',body))['id']
            self.assertEqual(send('department-admin',dict(action='APPLY',requestId=rid)).status_code,403)
            self.assertEqual(send('department-admin',dict(action='APPROVE',requestId=rid)).status_code,403)
            self.ok(send('staff-policy',dict(action='APPROVE',requestId=rid)))
            result=self.ok(send('department-admin',dict(action='APPLY',requestId=rid)))
            self.assertEqual(str(self.db.execute('SELECT id FROM academic_cycles WHERE id=%s',(result['id'],)).fetchone()['id']),result['id'])
            self.assertTrue(any(r['id']==rid and r['configured_at'] for r in self.ok(self.client('department-admin').get(route))['requests']))

        def test_offering_filter_precedes_pagination_and_excludes_other_projects(self):
            p,_,offering,_=self.fixture()
            response=self.ok(self.client('student-a').get('/api/v1/me/projects',{'offeringId':offering}))
            self.assertEqual([r['id'] for r in response['results']],[p])
            self.assertTrue(all(r['offeringId']==offering for r in response['results']))
            self.assertEqual(self.ok(self.client('student-ece').get('/api/v1/me/projects',{'offeringId':offering}))['results'],[])

        def test_application_read_has_no_demo_catalog_dependency(self):
            with self.db.transaction(force_rollback=True):
                self.db.execute('ALTER TABLE demo_catalog RENAME TO hidden_demo_catalog')
                value=self.db.execute('SELECT smartpro_application_workspace(%s) AS w',('00000000-0000-4000-8000-000000000001',)).fetchone()['w']
                self.assertEqual(value['department']['id'],CSE)
                self.assertIsNone(value['admission'])

        def test_fresh_department_is_empty_and_normal_context_has_no_fake_login(self):
            dept=self.db.execute("INSERT INTO departments(code,name) VALUES(%s,'Empty Department') RETURNING id",('EMPTY-'+uuid4().hex,)).fetchone()['id']
            uid=self.db.execute("INSERT INTO users(display_name,email) VALUES('Fresh Admin',%s) RETURNING id",(uuid4().hex+'@example.invalid',)).fetchone()['id']
            self.db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'ACADEMIC_ADMIN')",(uid,dept))
            workspace=self.db.execute('SELECT smartpro_application_workspace(%s) AS w',(uid,)).fetchone()['w']
            self.assertEqual(workspace['department']['id'],str(dept));self.assertIsNone(workspace['department']['offeringId']);self.assertEqual(workspace['assignedProjects'],[])
            self.assertEqual(self.db.execute('SELECT count(*) AS n FROM curriculum_offerings WHERE department_id=%s',(dept,)).fetchone()['n'],0)
            with patch.dict(os.environ,SMARTPRO_ENV='production'):
                context=self.client('student-a').get('/api/v1/ui/context').json()
                self.assertFalse(context['demo']);self.assertEqual(context['identities'],[])

        def test_fresh_department_setup_through_documents_and_corrected_results(self):
            self.run_fresh_department_workflow(external=False)

        def test_external_instruction_setup_and_optional_mark_correction(self):
            self.run_fresh_department_workflow(external=True)

        def run_fresh_department_workflow(self,external):
            # Owner establishes synthetic identity and institutional authority only.
            # Every cycle, policy, rubric, profile and offering is then authored
            # through the real API; no demo_catalog entry or academic defaults.
            from smartpro.identity import Principal
            dept=str(self.db.execute("INSERT INTO departments(code,name) VALUES(%s,'Research Department') RETURNING id",('NEW-'+uuid4().hex[:8],)).fetchone()['id'])
            clients={};users={};roles={}
            for name,role,persona in [('hod','HOD','HOD'),('admin','ACADEMIC_ADMIN','Admin'),('student','STUDENT','Student'),('faculty','FACULTY','Faculty')]:
                uid=str(self.db.execute('INSERT INTO users(display_name,email) VALUES(%s,%s) RETURNING id',('Research '+name,uuid4().hex+'@example.invalid')).fetchone()['id'])
                roles[name]=str(self.db.execute('INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,%s) RETURNING id',(uid,dept,role)).fetchone()['id'])
                users[name]=uid;clients[name]=APIClient();clients[name].force_authenticate(Principal(uid,role=persona,role_choices=(persona,)))
            self.db.execute('INSERT INTO academic_governance_settings(department_id,enabled) VALUES(%s,true)',(dept,))
            self.db.execute('INSERT INTO staff_department_controls(department_id,enabled) VALUES(%s,true)',(dept,))
            self.db.execute('INSERT INTO academic_hod_mandates(department_id,role_assignment_id,user_id,enabled) VALUES(%s,%s,%s,true)',(dept,roles['hod'],users['hod']))
            self.db.execute("INSERT INTO academic_action_grants(user_id,department_id,action_code) VALUES(%s,%s,'APPROVE_SCHEME')",(users['hod'],dept))
            def post(who,path,body,status=200):
                if external:body.pop('reason',None)
                return self.ok(clients[who].post(path,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex),status)
            setup=f'/api/v1/staff/departments/{dept}/setup';documents=f'/api/v1/documents/departments/{dept}';academic=f'/api/v1/academic/departments/{dept}'
            authority=dict(hodMandateId=str(self.db.execute('SELECT id FROM academic_hod_mandates WHERE department_id=%s',(dept,)).fetchone()['id']),source='EXTERNAL_INSTRUCTION',confirmed=True,reference='')
            def configure(kind,cfg):
                if external:return post('admin',setup,dict(action='RECORD',kind=kind,configuration=cfg,authority=authority))['id']
                rid=post('admin',setup,dict(action='REQUEST',kind=kind,configuration=cfg,reason='Synthetic institutional instruction'))['id']
                post('hod',setup,dict(action='APPROVE',requestId=rid))
                return post('admin',setup,dict(action='APPLY',requestId=rid))['id']
            self.assertEqual(self.ok(clients['admin'].get(setup))['offerings'],[])
            cycle=configure('CYCLE',dict(code='2026-27',startsOn='2026-07-01',endsOn='2027-06-30'))
            kind=configure('TYPE',dict(code='STUDIO-'+uuid4().hex[:8].upper(),label='Research studio'))
            policy=configure('PROJECT_POLICY',dict(label='Research project policy',projectType='MAJOR',allowStudentRegistration=True))
            team_policy=configure('TEAM_POLICY',dict(label='Research teams',allowJoin=True,allowLeave=True,allowTransfer=True,minimumMembers=1,maximumMembers=4,sizeMode='ADVISORY'))
            policy=configure('REVIEW_BLUEPRINT',dict(policyVersionId=policy,cycleId=cycle,label='Research review plan',stages=[dict(code='DEMO',label='Research demonstration',mode='COMBINED',criteria=[dict(label='Project evidence',scope='TEAM',maximum='60'),dict(label='Understanding',scope='STUDENT',maximum='40')])]))
            configure('STUDENT_PROFILE',dict(userId=users['student'],usn='NEW-'+uuid4().hex[:8],section='A',semester='SEM-3'))
            offering_config=dict(curriculumTypeId=kind,cycleId=cycle,semester='SEM-3',projectPolicyId=policy,teamPolicyId=team_policy,adminRoleId=roles['admin'],visibleFrom='2026-11-01T00:00:00Z',visibleUntil='2027-05-01T00:00:00Z',submissionOpensAt='2026-11-01T00:00:00Z',submissionClosesAt='2027-05-01T00:00:00Z',maxBytes=2097152,facultyApprovalEnabled=True,teamCreationEnabled=True)
            if external:
                offering=post('admin',setup,dict(action='RECORD',kind='OFFERING',configuration=offering_config,authority=authority))['offeringId']
                provenance=self.db.execute('SELECT approval_source,recorded_by FROM offering_operational_instructions WHERE department_id=%s',(dept,)).fetchone()
                self.assertEqual(provenance['approval_source'],'EXTERNAL_INSTRUCTION');self.assertEqual(str(provenance['recorded_by']),users['admin'])
            else:
                instruction=post('hod',documents,dict(action='AUTHORIZE',configuration=dict(curriculumTypeId=kind,cycleId=cycle,semester='SEM-3',projectPolicyId=policy,teamPolicyId=team_policy,adminRoleId=roles['admin'],visibleFrom='2026-11-01T00:00:00Z',visibleUntil='2027-05-01T00:00:00Z',submissionOpensAt='2026-11-01T00:00:00Z',submissionClosesAt='2027-05-01T00:00:00Z',maxBytes=2097152,facultyApprovalEnabled=True,teamCreationEnabled=True),reason='Explicit offering instruction'))['instructionId']
                offering=post('admin',documents,dict(action='CONFIGURE',instructionId=instruction))['offeringId']
            self.assertEqual([o['id'] for o in self.ok(clients['student'].get('/api/v1/me/curriculum-offerings'))['results']],[offering])
            team=post('student','/api/v1/teams',dict(offeringId=offering,name='Research team'),201)['id']
            project=post('student','/api/v1/projects',dict(offeringId=offering,teamId=team,title='Research evidence notebook'),201)['id']
            response=clients['student'].post(documents+f'/projects/{project}/uploads',{'file':SimpleUploadedFile('synopsis.pdf',pdf_bytes(),content_type='application/pdf')},format='multipart',HTTP_IDEMPOTENCY_KEY=uuid4().hex)
            vid=self.ok(response)['documentVersionId']
            post('student',documents,dict(action='SUBMIT',projectId=project,documentVersionId=vid,expectedCaseVersion=1))
            self.assertEqual(clients['faculty'].get(f'/api/v1/document-versions/{vid}/content').status_code,403)
            post('hod',documents,dict(action='ASSIGN_REVIEWER',projectId=project,facultyId=users['faculty']))
            self.assertEqual(clients['faculty'].get(f'/api/v1/document-versions/{vid}/content').content,pdf_bytes())
            case=self.ok(clients['faculty'].get(documents))['projects'][0]['case']
            post('faculty',documents,dict(action='DECIDE',projectId=project,attemptId=case['attempts'][0]['id'],expectedCaseVersion=case['version'],decision='APPROVE',comment='Research synopsis accepted'))
            evaluation=post('hod',academic+'/policies',dict(expectedRevision=0,reason='Explicit synthetic assessment rule',evaluatorQuorum=1,aggregation='MEAN',evaluatorWeights={}))['id']
            choice=self.db.execute('SELECT smartpro_project_review_choices(%s,%s) AS c',(users['hod'],dept)).fetchone()['c'][0]
            rid=post('hod',academic+'/reviews',dict(projectId=project,schemeVersionId=choice['schemeVersionId'],schemeModeId=choice['schemeModeId'],policyId=evaluation,facultyIds=[users['faculty']],reason='Authorized research evaluator'))['reviewId']
            review=self.ok(clients['faculty'].get('/api/v1/workspace'))['reviews'][0];assessment=review['assessments'][0]
            scores=[dict(criterionId=c['id'],studentId=None if c['scope']=='TEAM' else users['student'],marks='20') for c in review['criteria']]
            post('faculty',academic+f'/assessments/{assessment["id"]}/draft',dict(expectedAssessmentVersion=1,reason='Rubric scores',scores=scores))
            post('faculty',academic+f'/assessments/{assessment["id"]}/finalize',dict(expectedAssessmentVersion=2,reason='Final contribution'))
            post('hod',academic+f'/reviews/{rid}/publish',dict(expectedReviewRevision=1,reason='Quorum verified'))
            scores[0]['marks']='22'
            post('faculty',academic+f'/reviews/{rid}/evaluations',dict(expectedReviewRevision=2,assessmentId=assessment['id'],scores=scores,reason='Direct original evaluator correction'))
            results=self.ok(clients['student'].get(academic+f'/reviews/{rid}/results'))['results']
            self.assertEqual([r['results'][users['student']] for r in results],['40.00','42.00'])
            self.assertEqual(self.db.execute('SELECT count(*) AS n FROM demo_catalog WHERE department_id=%s',(dept,)).fetchone()['n'],0)

        def test_curriculum_classification_and_document_exemption_are_real_records(self):
            route=f'/api/v1/staff/departments/{CSE}/setup'
            def send(who,body):return self.client(who).post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex)
            config={'code':'CURR-'+uuid4().hex[:10].upper(),'label':'Faculty-authorized studio'}
            rid=self.ok(send('department-admin',dict(action='REQUEST',kind='TYPE',configuration=config,reason='New department classification')))['id']
            self.ok(send('staff-policy',dict(action='APPROVE',requestId=rid)))
            result=self.ok(send('department-admin',dict(action='APPLY',requestId=rid)))
            self.assertEqual(self.db.execute('SELECT label FROM curriculum_types WHERE id=%s',(result['id'],)).fetchone()['label'],config['label'])
            row=self.db.execute("SELECT p.id,t.curriculum_offering_id AS offering FROM projects p JOIN teams t ON t.id=p.team_id WHERE p.department_id=%s AND NOT EXISTS(SELECT FROM submission_offering_requirements WHERE offering_id=t.curriculum_offering_id) AND smartpro_project_permission(p.id,%s,'student') LIMIT 1",(CSE,'00000000-0000-4000-8000-000000000001')).fetchone()
            self.assertIsNotNone(row)
            rid=self.ok(send('department-admin',dict(action='REQUEST',kind='DOCUMENT_NOT_REQUIRED',configuration={'offeringId':str(row['offering'])},reason='Explicit exemption')) )['id']
            self.assertEqual(self.project('student-a',str(row['id']))['configurationPending'],True)
            self.ok(send('staff-policy',dict(action='APPROVE',requestId=rid)))
            self.ok(send('department-admin',dict(action='APPLY',requestId=rid)))
            self.assertEqual(self.project('student-a',str(row['id']))['requirementDisposition'],'NOT_REQUIRED')

        def test_setup_read_and_write_fail_when_department_disabled(self):
            with self.db.transaction(force_rollback=True):
                self.db.execute('UPDATE staff_department_controls SET enabled=false WHERE department_id=%s',(CSE,))
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with self.db.transaction():self.db.execute('SELECT smartpro_department_setup_read(%s,%s)',('00000000-0000-4000-8000-000000000012',CSE))

        def authorize_setup(self,kind,configuration,admin='department-admin',hod='staff-policy',dept=CSE):
            route=f'/api/v1/staff/departments/{dept}/setup'
            def send(who,body):return self.client(who).post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex)
            rid=self.ok(send(admin,dict(action='REQUEST',kind=kind,configuration=configuration,reason='Explicit synthetic academic authorization')))['id']
            self.ok(send(hod,dict(action='APPROVE',requestId=rid)))
            return self.ok(send(admin,dict(action='APPLY',requestId=rid)))['id']

        def test_managed_proposal_retries_and_manual_code_bypass_denial(self):
            p,_,offering,_=self.fixture()
            project=self.db.execute('SELECT project_code,project_type,team_id FROM projects WHERE id=%s',(p,)).fetchone()
            self.assertRegex(project['project_code'],r'^P-[0-9a-f]{64}$');self.assertEqual(project['project_type'],'MAJOR')
            body=dict(offeringId=offering,teamId=str(project['team_id']),title='Second proposal');key=uuid4().hex
            client=self.client('student-a')
            first=client.post('/api/v1/projects',body,format='json',HTTP_IDEMPOTENCY_KEY=key)
            self.assertEqual(first.status_code,201,first.content)
            replay=client.post('/api/v1/projects',body,format='json',HTTP_IDEMPOTENCY_KEY=key)
            self.assertEqual(replay.status_code,200);self.assertEqual(replay.json(),first.json())
            self.assertNotEqual(first.json()['id'],p)
            malicious=dict(body,projectCode='CUSTOM',projectType='MINI')
            self.assertEqual(client.post('/api/v1/projects',malicious,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,400)
            self.assertEqual(client.post('/api/v1/projects',dict(teamId=str(project['team_id']),title='Bypass',projectCode='CUSTOM',projectType='MINI'),format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,400)
            self.assertEqual(client.post('/api/v1/projects',dict(body,title='Changed'),format='json',HTTP_IDEMPOTENCY_KEY=key).status_code,409)

        def test_concurrent_managed_proposals_and_transaction_recovery(self):
            p,_,offering,_=self.fixture()
            team=str(self.db.execute('SELECT team_id FROM projects WHERE id=%s',(p,)).fetchone()['team_id'])
            body=dict(offeringId=offering,teamId=team,title='Concurrent managed proposal')
            key=uuid4().hex
            def send(k):
                close_old_connections()
                try:return self.client('student-a').post('/api/v1/projects',body,format='json',HTTP_IDEMPOTENCY_KEY=k)
                finally:close_old_connections()
            with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(send,[key,key]))
            self.assertEqual(sorted(r.status_code for r in responses),[200,201])
            self.assertEqual(responses[0].json(),responses[1].json())
            with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(send,[uuid4().hex,uuid4().hex]))
            self.assertTrue(all(r.status_code==201 for r in responses))
            self.assertNotEqual(responses[0].json()['id'],responses[1].json()['id'])
            from smartpro import projects
            original=projects._execute
            def fail_after_insert(statement,values):
                original(statement,values)
                raise RuntimeError('Synthetic failure after registration, before commit')
            retry=uuid4().hex
            before=self.db.execute('SELECT count(*) AS n FROM projects').fetchone()['n']
            with patch.object(projects,'_execute',side_effect=fail_after_insert):
                with self.assertRaises(RuntimeError):send(retry)
            self.assertEqual(self.db.execute('SELECT count(*) AS n FROM projects').fetchone()['n'],before)
            self.assertEqual(send(retry).status_code,201)

        def test_coordinator_delegation_expiring_during_lock_wait_rolls_back(self):
            p,_,_,_=self.fixture()
            mandate=str(self.db.execute("SELECT id FROM academic_coordinator_mandates WHERE user_id='00000000-0000-4000-8000-000000000008' AND NOT revoked").fetchone()['id'])
            expiry=self.db.execute("SELECT clock_timestamp()+interval '2 seconds' AS t").fetchone()['t'].isoformat()
            self.ok(self.client('staff-policy').post(f'/api/v1/staff/departments/{CSE}/coordinator-operations',dict(mandateId=mandate,operation='GUIDE',validUntil=expiry,reason='Finite synthetic delegation'),format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))
            def send():
                close_old_connections()
                try:return self.client('coordinator').post(f'/api/v1/staff/departments/{CSE}/projects/{p}/guide',dict(facultyId=FACULTY,expectedGuideId=None,reason='Assignment blocked past delegation expiry'),format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex)
                finally:close_old_connections()
            with ThreadPoolExecutor(max_workers=1) as pool:
                with psycopg.connect(**dict(owner,dbname=name)) as blocker:
                    blocker.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(p,))
                    future=pool.submit(send);deadline=time.monotonic()+5
                    while not self.db.execute("SELECT EXISTS(SELECT FROM pg_stat_activity WHERE datname=%s AND wait_event='transactionid' AND query LIKE '%%smartpro_project_operation%%') AS waiting",(name,)).fetchone()['waiting']:
                        self.assertFalse(future.done(),'Operation did not reach the intended row-lock wait')
                        self.assertLess(time.monotonic(),deadline,'Operation did not reach the row-lock barrier')
                        time.sleep(.02)
                    while self.db.execute('SELECT clock_timestamp()<%s::timestamptz AS active',(expiry,)).fetchone()['active']:time.sleep(.02)
                response=future.result(timeout=5)
            self.assertEqual(response.status_code,403,response.content)
            self.assertIsNone(self.project('student-a',p)['guide'])
            self.assertEqual(self.db.execute("SELECT count(*) AS n FROM faculty_assignments WHERE project_id=%s AND assignment_type='GUIDE'",(p,)).fetchone()['n'],0)

        def test_closed_proposal_window_and_wrong_team_cannot_be_bypassed(self):
            p,_,offering,_=self.fixture(closed=True)
            team=str(self.db.execute('SELECT team_id FROM projects WHERE id=%s',(p,)).fetchone()['team_id'])
            body=dict(offeringId=offering,teamId=team,title='Closed proposal')
            self.assertEqual(self.client('student-a').post('/api/v1/projects',body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,409)
            p,_,offering,_=self.fixture();body['offeringId']=offering
            self.assertEqual(self.client('student-a').post('/api/v1/projects',body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,403)
            self.assertEqual(self.client('student-ece').get(f'/api/v1/curriculum-offerings/{offering}/proposal').status_code,403)

        def test_explicit_role_switching_cannot_import_hod_powers_into_admin(self):
            c=self.client('staff-policy');c.credentials(HTTP_X_DEMO_USER='staff-policy')
            context=self.ok(c.get('/api/v1/workspace'));self.assertTrue(context['chooseRole']);self.assertIn('Admin',context['roleChoices']);self.assertIn('HOD',context['roleChoices'])
            self.assertEqual(c.get(base).status_code,403)
            c.credentials(HTTP_X_DEMO_USER='staff-policy',HTTP_X_SMARTPRO_ROLE='Admin')
            w=self.ok(c.get('/api/v1/workspace'));self.assertEqual(w['activeRole'],'Admin');self.assertFalse(w['access']['admin'])
            self.assertEqual(self.ok(c.get(base))['projects'],[])
            self.assertEqual(c.post(base,dict(action='AUTHORIZE',configuration={},reason='No independent academic power'),format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,403)
            c.credentials(HTTP_X_DEMO_USER='student-a',HTTP_X_SMARTPRO_ROLE='HOD')
            self.assertEqual(c.get('/api/v1/workspace').status_code,401)

        def test_dual_role_case_access_and_marks_require_matching_responsibility(self):
            p,_,_,_=self.fixture();vid=self.ok(self.upload(p))['documentVersionId'];case=self.project('student-a',p)['case']
            coord='00000000-0000-4000-8000-000000000008'
            # A valid faculty assignment must not import Faculty access into the
            # same person's Student persona, or permit Admin document access.
            self.db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'STUDENT')",(FACULTY,CSE))
            c=self.client('faculty-a');c.credentials(HTTP_X_DEMO_USER='faculty-a',HTTP_X_SMARTPRO_ROLE='Student')
            self.assertEqual(c.get(f'/api/v1/submission-cases/{case["id"]}').status_code,403)
            self.assertEqual(c.get(f'/api/v1/document-versions/{vid}/content').status_code,403)
            # Coordinator and Faculty are separate contexts even for an assigned
            # evaluator who holds both responsibilities.
            catalog=self.db.execute('SELECT * FROM demo_catalog WHERE department_id=%s',(CSE,)).fetchone()
            policy=self.db.execute('SELECT id FROM academic_evaluation_policies WHERE department_id=%s ORDER BY version_no DESC LIMIT 1',(CSE,)).fetchone()['id']
            response=self.client('staff-policy').post(f'/api/v1/academic/departments/{CSE}/reviews',dict(projectId=p,schemeVersionId=str(catalog['scheme_id']),schemeModeId=str(catalog['mode_id']),policyId=str(policy),facultyIds=[coord],reason='Explicit evaluator assignment'),format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex)
            rid=self.ok(response)['reviewId'];review=next(r for r in self.ok(self.client('coordinator').get('/api/v1/workspace'))['reviews'] if r['id']==rid)
            assessment=review['assessments'][0]
            body=dict(expectedAssessmentVersion=1,reason='Own draft',scores=[dict(criterionId=cr['id'],studentId=None if cr['scope']=='TEAM' else '00000000-0000-4000-8000-000000000001',marks='1') for cr in review['criteria']])
            route=f'/api/v1/academic/departments/{CSE}/assessments/{assessment["id"]}/draft'
            self.assertEqual(self.client('coordinator').post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,403)
            c=self.client('coordinator');c.credentials(HTTP_X_DEMO_USER='coordinator',HTTP_X_SMARTPRO_ROLE='Faculty')
            self.ok(c.post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))

        def test_evaluator_eligibility_uses_real_faculty_role_not_display_name(self):
            p,_,_,_=self.fixture();catalog=self.db.execute('SELECT * FROM demo_catalog WHERE department_id=%s',(CSE,)).fetchone()
            policy=self.db.execute('SELECT id FROM academic_evaluation_policies WHERE department_id=%s ORDER BY version_no DESC LIMIT 1',(CSE,)).fetchone()['id']
            b='00000000-0000-4000-8000-000000000002'
            hod=self.client('staff-policy');workspace=self.ok(hod.get('/api/v1/workspace'))
            self.assertTrue(next(f for f in workspace['faculty'] if f['id']==b)['alsoStudent'])
            body=dict(projectId=p,schemeVersionId=str(catalog['scheme_id']),schemeModeId=str(catalog['mode_id']),policyId=str(policy),facultyIds=[b],reason='Authorized dual-role faculty evaluator')
            self.assertEqual(hod.post(f'/api/v1/academic/departments/{CSE}/reviews',body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,200)
            self.db.execute("UPDATE department_role_assignments SET valid_until=clock_timestamp() WHERE user_id=%s AND department_id=%s AND role_code='FACULTY' AND valid_until IS NULL",(b,CSE))
            p2,_,_,_=self.fixture();body['projectId']=p2
            self.assertEqual(hod.post(f'/api/v1/academic/departments/{CSE}/reviews',body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,403)
            self.assertNotIn(b,[f['id'] for f in self.ok(hod.get('/api/v1/workspace'))['faculty']])

        def test_authorized_policy_blueprint_is_prospective_and_immutable(self):
            original=self.db.execute('SELECT count(*) AS n FROM projects').fetchone()['n']
            policy=self.authorize_setup('PROJECT_POLICY',dict(label='Research project policy',projectType='MAJOR',allowStudentRegistration=True))
            team=self.authorize_setup('TEAM_POLICY',dict(label='Research teams',allowJoin=True,allowLeave=True,allowTransfer=True,minimumMembers=1,maximumMembers=4,sizeMode='ENFORCED'))
            self.assertEqual(self.db.execute('SELECT maximum_members FROM team_membership_policy_versions WHERE id=%s',(team,)).fetchone()['maximum_members'],4)
            blueprint=dict(policyVersionId=policy,cycleId='11000000-0000-4000-8000-000000000001',label='Research review plan',stages=[dict(code='DESIGN',label='Design review',mode='COMBINED',criteria=[dict(label='Team evidence',scope='TEAM',maximum='60'),dict(label='Individual understanding',scope='STUDENT',maximum='40')])])
            newpolicy=self.authorize_setup('REVIEW_BLUEPRINT',blueprint)
            self.assertNotEqual(newpolicy,policy)
            self.assertEqual(self.db.execute('SELECT policy_data FROM project_policy_versions WHERE id=%s',(policy,)).fetchone()['policy_data']['label'],'Research project policy')
            self.assertEqual(self.db.execute('SELECT count(*) AS n FROM projects').fetchone()['n'],original)
            self.assertEqual(self.db.execute("SELECT count(*) AS n FROM scheme_versions v JOIN review_definitions d ON d.id=v.review_definition_id WHERE d.policy_version_id=%s AND v.state='ACTIVE'",(newpolicy,)).fetchone()['n'],1)
            with self.assertRaises(psycopg.errors.CheckViolation):self.db.execute("UPDATE project_policy_versions SET policy_data='{}' WHERE id=%s",(newpolicy,))

        def test_setup_apply_reauthorizes_target_and_failed_request_can_recover(self):
            uid=str(self.db.execute("INSERT INTO users(display_name,email) VALUES('New synthetic student',%s) RETURNING id",(uuid4().hex+'@example.invalid',)).fetchone()['id'])
            role=self.db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'STUDENT') RETURNING id",(uid,CSE)).fetchone()['id']
            route=f'/api/v1/staff/departments/{CSE}/setup'
            def send(who,body,key=None):return self.client(who).post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=key or uuid4().hex)
            rid=self.ok(send('department-admin',dict(action='REQUEST',kind='STUDENT_PROFILE',configuration=dict(userId=uid,usn='NEW-'+uuid4().hex[:8],section='A',semester='SYNTHETIC-SEM-3'),reason='Trusted department intake')))['id']
            self.ok(send('staff-policy',dict(action='APPROVE',requestId=rid)))
            self.db.execute('UPDATE department_role_assignments SET valid_until=clock_timestamp() WHERE id=%s',(role,))
            key=uuid4().hex;body=dict(action='APPLY',requestId=rid)
            self.assertEqual(send('department-admin',body,key).status_code,403)
            self.assertIsNone(self.db.execute('SELECT user_id FROM student_profiles WHERE user_id=%s',(uid,)).fetchone())
            self.db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'STUDENT')",(uid,CSE))
            self.assertEqual(self.ok(send('department-admin',body,key))['id'],uid)
            self.authorize_setup('FACULTY_ACCESS',dict(userId=uid,validUntil='2027-06-01T00:00:00Z'))
            self.assertTrue(self.db.execute("SELECT smartpro_has_role(%s,%s,'FACULTY',clock_timestamp()) AS ok",(uid,CSE)).fetchone()['ok'])

        def test_authorized_guide_synopsis_review_reassignment_and_retained_approval(self):
            p,_,_,_=self.fixture();hod=self.client('staff-policy')
            route=f'/api/v1/staff/departments/{CSE}/projects/{p}/guide'
            management=f'/api/v1/staff/departments/{CSE}/assignment-management'
            def post(client,path,body,key=None):return client.post(path,body,format='json',HTTP_IDEMPOTENCY_KEY=key or uuid4().hex)
            manual=str(self.db.execute("SELECT id FROM faculty_assignments WHERE project_id=%s AND assignment_type='REVIEWER'",(p,)).fetchone()['id'])
            self.ok(post(hod,management,dict(action='END_ASSIGNMENT',assignmentId=manual)))
            first=self.ok(post(hod,route,dict(facultyId=FACULTY,expectedGuideId=None)))['id']
            linked=self.db.execute('SELECT reviewer_assignment_id FROM guide_synopsis_responsibilities WHERE guide_assignment_id=%s',(first,)).fetchone()['reviewer_assignment_id']
            self.assertTrue(self.project('faculty-a',p)['canReview'])
            self.assertEqual(post(hod,management,dict(action='END_ASSIGNMENT',assignmentId=str(linked))).status_code,409)
            v1=self.ok(self.upload(p))['documentVersionId'];self.ok(self.submit(p,v1));case=self.project('faculty-a',p)['case']
            self.ok(self.command('faculty-a','DECIDE',dict(projectId=p,attemptId=case['attempts'][-1]['id'],expectedCaseVersion=case['version'],decision='REQUEST_CHANGES',comment='Clarify the observation method.')))
            other='00000000-0000-4000-8000-000000000008'
            second=self.ok(post(hod,route,dict(facultyId=other,expectedGuideId=first)))['id']
            self.assertIsNotNone(self.db.execute('SELECT valid_until FROM faculty_assignments WHERE id=%s',(linked,)).fetchone()['valid_until'])
            self.assertFalse(self.db.execute("SELECT smartpro_requirement_access(%s,%s,'SYNOPSIS','Faculty',true) AS ok",(FACULTY,p)).fetchone()['ok'])
            faculty=self.client('coordinator');faculty.credentials(HTTP_X_DEMO_USER='coordinator',HTTP_X_SMARTPRO_ROLE='Faculty')
            v2=self.ok(self.upload(p,pdf_bytes('Clarified observation method')))['documentVersionId'];self.ok(self.submit(p,v2))
            project=next(x for x in self.ok(faculty.get(base))['projects'] if x['id']==p);case=project['case'];self.assertTrue(project['canReview'])
            body=dict(action='DECIDE',projectId=p,attemptId=case['attempts'][-1]['id'],expectedCaseVersion=case['version'],decision='APPROVE',comment='Revised method accepted.')
            self.assertEqual(post(self.client('faculty-a'),base,body).status_code,403)
            self.ok(post(faculty,base,body));self.ok(post(hod,management,dict(action='END_ASSIGNMENT',assignmentId=second)))
            case=self.project('student-a',p)['case'];self.assertEqual(case['state'],'APPROVED');self.assertEqual(len(case['versions']),2)
            self.assertEqual([a['feedback'][0]['decision'] for a in case['attempts']],['REQUEST_CHANGES','APPROVE'])
            self.assertEqual(self.db.execute('SELECT count(*) AS n FROM guide_synopsis_responsibilities WHERE project_id=%s',(p,)).fetchone()['n'],2)

        def test_guide_review_respects_policy_and_independent_reviewer_configuration(self):
            p,_,offering,_=self.fixture(approval=False);hod=self.client('staff-policy')
            route=f'/api/v1/staff/departments/{CSE}/projects/{p}/guide'
            first=self.ok(hod.post(route,dict(facultyId=FACULTY,expectedGuideId=None),format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))['id']
            vid=self.ok(self.upload(p))['documentVersionId'];self.ok(self.submit(p,vid));case=self.project('faculty-a',p)['case']
            self.assertEqual(self.command('faculty-a','DECIDE',dict(projectId=p,attemptId=case['attempts'][-1]['id'],expectedCaseVersion=case['version'],decision='APPROVE',comment='Not permitted by pinned policy')).status_code,409)
            mandate=str(self.db.execute('SELECT id FROM academic_hod_mandates WHERE department_id=%s AND enabled',(CSE,)).fetchone()['id'])
            previous=str(self.db.execute("SELECT policy_id FROM submission_offering_requirements WHERE offering_id=%s AND requirement_key='SYNOPSIS'",(offering,)).fetchone()['policy_id'])
            cfg=dict(offeringId=offering,requirementKey='SYNOPSIS',expectedPolicyId=previous,name='Configured synopsis',opensAt='2026-01-01T00:00:00Z',closesAt='2027-06-01T00:00:00Z',maxBytes=2097152,required=True,allowApproval=False,allowChanges=False,allowRevisions=True,reviewerIds=[FACULTY],authority=dict(hodMandateId=mandate,source='EXTERNAL_INSTRUCTION',confirmed=True,reference=''))
            path=f'/api/v1/staff/departments/{CSE}/document-requirements'
            configured=self.ok(self.client('department-admin').post(path,cfg,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))
            # Manual responsibility is distinct even for the same guide/faculty.
            self.assertEqual(self.db.execute("SELECT count(*) AS n FROM faculty_assignments f WHERE project_id=%s AND assignment_type='REVIEWER' AND requirement_key='SYNOPSIS' AND valid_until IS NULL",(p,)).fetchone()['n'],2)
            self.ok(hod.post(route,dict(facultyId='00000000-0000-4000-8000-000000000008',expectedGuideId=first),format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))
            self.assertTrue(self.project('faculty-a',p)['canReview'])
            cfg.update(expectedPolicyId=configured['id'],reviewerIds=[])
            self.ok(self.client('department-admin').post(path,cfg,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))
            # Removing manual reviewers cannot erase the new guide's explicit link.
            self.assertTrue(self.db.execute("SELECT smartpro_requirement_access(%s,%s,'SYNOPSIS','Faculty',true) AS ok",('00000000-0000-4000-8000-000000000008',p)).fetchone()['ok'])
            self.assertFalse(self.db.execute("SELECT smartpro_requirement_access(%s,%s,'SYNOPSIS','Faculty',true) AS ok",(FACULTY,p)).fetchone()['ok'])
            self.assertEqual(self.project('student-a',p)['case']['state'],'AWAITING_REVIEW')
            cfg.update(requirementKey=None,expectedPolicyId=None,name='Independent configured evidence')
            extra=self.ok(self.client('department-admin').post(path,cfg,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))
            guide='00000000-0000-4000-8000-000000000008'
            self.assertTrue(self.db.execute("SELECT smartpro_requirement_access(%s,%s,%s,'Faculty',false) AS ok",(guide,p,extra['requirementKey'])).fetchone()['ok'])
            self.assertFalse(self.db.execute("SELECT smartpro_requirement_access(%s,%s,%s,'Faculty',true) AS ok",(guide,p,extra['requirementKey'])).fetchone()['ok'])

        def test_concurrent_guide_allocation_and_rolled_back_link_retry(self):
            p,_,_,_=self.fixture();route=f'/api/v1/staff/departments/{CSE}/projects/{p}/guide';key=uuid4().hex
            body=dict(projectId=p,facultyId=FACULTY,expectedGuideId=None,reason='',_actingRole='HOD')
            from psycopg.types.json import Jsonb
            with self.db.transaction(force_rollback=True):
                self.db.execute("SELECT smartpro_project_operation(%s,%s,'GUIDE',%s,%s)",('00000000-0000-4000-8000-000000000004',CSE,Jsonb(body),key))
                self.assertEqual(self.db.execute('SELECT count(*) AS n FROM guide_synopsis_responsibilities WHERE project_id=%s',(p,)).fetchone()['n'],1)
            self.assertEqual(self.db.execute('SELECT count(*) AS n FROM guide_synopsis_responsibilities WHERE project_id=%s',(p,)).fetchone()['n'],0)
            def assign(_):
                close_old_connections()
                try:return self.client('staff-policy').post(route,dict(facultyId=FACULTY,expectedGuideId=None),format='json',HTTP_IDEMPOTENCY_KEY=key)
                finally:close_old_connections()
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(assign,range(2)))
            self.assertEqual([r.status_code for r in results],[200,200]);self.assertEqual(results[0].json(),results[1].json())
            self.assertEqual(self.db.execute('SELECT count(*) AS n FROM guide_synopsis_responsibilities WHERE project_id=%s',(p,)).fetchone()['n'],1)
            with psycopg.connect(**dict(app,dbname=name),autocommit=True) as runtime:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):runtime.execute('SELECT * FROM guide_synopsis_responsibilities')
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):runtime.execute('SELECT smartpro_sync_guide_synopsis(%s,%s)',(FACULTY,p))
            with self.assertRaises(psycopg.errors.CheckViolation):self.db.execute('UPDATE guide_synopsis_responsibilities SET assigned_by=%s WHERE project_id=%s',(FACULTY,p))
            other='00000000-0000-4000-8000-000000000008'
            current=results[0].json()['id']
            def replace_guide(uid):
                close_old_connections()
                try:return self.client('staff-policy').post(route,dict(facultyId=uid,expectedGuideId=current),format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex)
                finally:close_old_connections()
            # Two different replacement requests cannot both consume the same
            # expected guide revision. One conflicts and leaves no orphan right.
            new_uid=str(self.db.execute("INSERT INTO users(display_name,email) VALUES('Concurrent guide',%s) RETURNING id",(uuid4().hex+'@example.invalid',)).fetchone()['id'])
            self.db.execute("INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'FACULTY')",(new_uid,CSE))
            with ThreadPoolExecutor(max_workers=2) as pool:conflicts=list(pool.map(replace_guide,[other,new_uid]))
            self.assertEqual(sorted(r.status_code for r in conflicts),[200,409])
            self.assertEqual(self.db.execute('SELECT count(*) AS n FROM guide_synopsis_responsibilities link JOIN faculty_assignments f ON f.id=link.reviewer_assignment_id WHERE link.project_id=%s AND f.valid_until IS NULL',(p,)).fetchone()['n'],1)

        def test_guide_is_separate_allows_same_evaluator_and_preserves_reassignment(self):
            p,_,_,_=self.fixture();route=f'/api/v1/staff/departments/{CSE}/projects/{p}/guide'
            body=dict(facultyId=FACULTY,expectedGuideId=None,reason='Separate primary guide assignment')
            for role in ['department-admin','faculty-a','student-a','coordinator']:
                self.assertEqual(self.client(role).post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,403)
            old=self.ok(self.client('staff-policy').post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))['id']
            self.assertEqual(self.project('student-a',p)['guide']['id'],old)
            body.update(facultyId='00000000-0000-4000-8000-000000000008',expectedGuideId=old)
            self.ok(self.client('staff-policy').post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex))
            self.assertIsNotNone(self.db.execute('SELECT valid_until FROM faculty_assignments WHERE id=%s',(old,)).fetchone()['valid_until'])
            self.assertEqual(self.client('staff-policy').post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=uuid4().hex).status_code,409)

        def test_scheduling_and_explicit_coordinator_delegation(self):
            p,_,_,_=self.fixture();hod=self.client('staff-policy');coord=self.client('coordinator')
            academic=f'/api/v1/academic/departments/{CSE}'
            catalog=self.db.execute('SELECT * FROM demo_catalog WHERE department_id=%s',(CSE,)).fetchone()
            policy=self.db.execute('SELECT id FROM academic_evaluation_policies WHERE department_id=%s ORDER BY version_no DESC LIMIT 1',(CSE,)).fetchone()['id']
            def post(c,route,body,key=None):return c.post(route,body,format='json',HTTP_IDEMPOTENCY_KEY=key or uuid4().hex)
            rid=self.ok(post(hod,academic+'/reviews',dict(projectId=p,schemeVersionId=str(catalog['scheme_id']),schemeModeId=str(catalog['mode_id']),policyId=str(policy),facultyIds=[FACULTY],reason='Scoped planned review')))['reviewId']
            row=self.db.execute('SELECT row_version FROM project_reviews WHERE id=%s',(rid,)).fetchone()
            route=academic+f'/reviews/{rid}/schedule'
            body=dict(scheduledAt='2026-12-15T09:00:00Z',expectedReviewVersion=row['row_version'],reason='Department review calendar')
            self.assertEqual(post(coord,route,body).status_code,403)
            mandate=str(self.db.execute("SELECT id FROM academic_coordinator_mandates WHERE user_id='00000000-0000-4000-8000-000000000008' AND NOT revoked").fetchone()['id'])
            delegate=f'/api/v1/staff/departments/{CSE}/coordinator-operations'
            self.ok(post(hod,delegate,dict(mandateId=mandate,operation='SCHEDULE',validUntil='2027-01-01T00:00:00Z',reason='Explicit scheduling responsibility')))
            key=uuid4().hex;first=self.ok(post(coord,route,body,key));self.assertEqual(first,self.ok(post(coord,route,body,key)))
            self.assertEqual(post(hod,route,body).status_code,409)
            # Delegating scheduling does not implicitly authorize guide changes.
            self.assertEqual(post(coord,f'/api/v1/staff/departments/{CSE}/projects/{p}/guide',dict(facultyId=FACULTY,expectedGuideId=None,reason='No guide delegation')).status_code,403)
            with psycopg.connect(**dict(app,dbname=name),autocommit=True) as db:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):db.execute('SELECT * FROM coordinator_operation_grants')
            self.assertEqual(post(self.client('department-admin'),route,body).status_code,403)

    try:
        outcome=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Contracts))
        return 0 if outcome.wasSuccessful() else 1
    finally:
        connection.close();storage.cleanup()
        with psycopg.connect(**dict(owner,dbname='postgres'),autocommit=True) as manager:
            assert name.startswith('smartpro_test_demo_documents_')
            manager.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


if __name__=='__main__':raise SystemExit(main())
