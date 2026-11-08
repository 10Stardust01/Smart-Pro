"""Explicit academic command routes; the SQL transaction validates authority."""
import os

from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError

from .staff import StaffUnavailable, staff_sql_command, _execute
from .student_views import private_response
from .staff_views import AwareDateTime
from .command_input import command_body


FIELDS = {
    'APPOINT_COORDINATOR': {'expectedRevision','reason','userId','validUntil'},
    'REVOKE_COORDINATOR': {'expectedRevision','reason','mandateId'},
    'DELEGATE_FACULTY': {'expectedRevision','reason','roleAssignmentId','permission','projectId','validUntil'},
    'REVOKE_DELEGATION': {'expectedRevision','reason','grantId'},
    'CREATE_POLICY': {'expectedRevision','reason','evaluatorQuorum','aggregation','evaluatorWeights'},
    'BIND': {'expectedReviewRevision','reason','policyId'},
    'ROSTER': {'expectedReviewRevision','reason','membershipIds'},
    'EVALUATE': {'expectedReviewRevision','reason','assessmentId','scores'},
    'PUBLISH': {'expectedReviewRevision','reason'},
}


def execute(request, department_id, action, review_id=None):
    if os.getenv('SMARTPRO_ACADEMIC_API') != 'YES':
        raise StaffUnavailable('Academic service is not enabled')
    body = command_body(request.data, FIELDS[action])
    if 'validUntil' in body:
        AwareDateTime().run_validation(body['validUntil'])
    sql = 'SELECT public.smartpro_academic_governance(%s,%s,%s,%s,%s)'
    if review_id is not None:
        body['reviewId'] = str(review_id)
        if os.getenv('SMARTPRO_COURSE_API')=='YES':
            body['_actingRole']=getattr(request.user,'role',None)
        sql = 'SELECT public.smartpro_academic_review_command(%s,%s,%s,%s,%s)'
    result = staff_sql_command(sql, request.user.id, department_id, action, body,
                               request.headers.get('Idempotency-Key'))
    return private_response(result)


@api_view(['POST'])
def appoint(request, department_id):
    return execute(request,department_id,'APPOINT_COORDINATOR')


@api_view(['POST'])
def revoke_coordinator(request, department_id):
    return execute(request,department_id,'REVOKE_COORDINATOR')


@api_view(['POST'])
def delegate(request, department_id):
    return execute(request,department_id,'DELEGATE_FACULTY')


@api_view(['POST'])
def revoke_delegation(request, department_id):
    return execute(request,department_id,'REVOKE_DELEGATION')


@api_view(['GET','POST'])
def policy(request, department_id):
    if request.method=='GET':
        if os.getenv('SMARTPRO_ACADEMIC_API') != 'YES':
            raise StaffUnavailable('Academic service is not enabled')
        return private_response(_execute('SELECT public.smartpro_academic_policy_state(%s,%s)',(request.user.id,department_id)))
    return execute(request,department_id,'CREATE_POLICY')


@api_view(['POST'])
def bind_review(request, department_id, review_id):
    return execute(request,department_id,'BIND',review_id)


@api_view(['POST'])
def roster(request, department_id, review_id):
    return execute(request,department_id,'ROSTER',review_id)


@api_view(['POST'])
def evaluate(request, department_id, review_id):
    return execute(request,department_id,'EVALUATE',review_id)


@api_view(['POST'])
def publish(request, department_id, review_id):
    return execute(request,department_id,'PUBLISH',review_id)


@api_view(['GET'])
def results(request, department_id, review_id):
    if os.getenv('SMARTPRO_ACADEMIC_API') != 'YES':
        raise StaffUnavailable('Academic service is not enabled')
    role=getattr(request.user,'role',None)
    if role in ('Student','Faculty') and not _execute('SELECT public.smartpro_role_review_access(%s,%s,%s)',(request.user.id,review_id,role)):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied('This review is not assigned to your responsibility')
    if os.getenv('SMARTPRO_COURSE_API')=='YES' and role in ('HOD','Coordinator'):
        _execute('SELECT public.smartpro_course_review_scope(%s,%s,%s) IS NULL',(request.user.id,review_id,role))
    value = request.query_params.get('afterVersion','0')
    if not value.isdecimal() or len(value)>9:
        raise ValidationError('Invalid result cursor')
    result=_execute('SELECT public.smartpro_academic_results(%s,%s,%s,%s)',(request.user.id,department_id,review_id,int(value)))
    if role=='Student':
        for version in result['results']:
            version['results']={k:v for k,v in version['results'].items() if k==str(request.user.id)}
            version['sources']=[]
    return private_response(result)
