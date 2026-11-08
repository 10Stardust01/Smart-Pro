"""Initial review assignment and evaluator-owned draft scoring."""
import os

from rest_framework.decorators import api_view

from .command_input import command_body
from .staff import StaffUnavailable, staff_sql_command
from .student_views import private_response


def command(request,department_id,action,assessment_id=None):
    if os.getenv('SMARTPRO_ACADEMIC_API')!='YES':
        raise StaffUnavailable('Academic service is not enabled')
    fields = ({'projectId','schemeVersionId','schemeModeId','policyId','facultyIds','reason'} if action=='CREATE_REVIEW'
              else {'expectedAssessmentVersion','reason'}|({'scores'} if action=='SAVE_DRAFT' else set()))
    body=command_body(request.data,fields)
    if assessment_id is not None:
        body['assessmentId']=str(assessment_id)
    result=staff_sql_command('SELECT public.smartpro_initial_evaluation(%s,%s,%s,%s,%s)',request.user.id,department_id,action,body,
                             request.headers.get('Idempotency-Key'))
    return private_response(result)


@api_view(['POST'])
def assign(request,department_id):
    return command(request,department_id,'CREATE_REVIEW')


@api_view(['POST'])
def save(request,department_id,assessment_id):
    return command(request,department_id,'SAVE_DRAFT',assessment_id)


@api_view(['POST'])
def finalize(request,department_id,assessment_id):
    return command(request,department_id,'FINALIZE_DRAFT',assessment_id)
