import os
from rest_framework.decorators import api_view
from .staff import staff_sql_command, _enabled, StaffUnavailable
from .staff_views import AwareDateTime
from .command_input import command_body
from .student_views import private_response

def command(request,dept,action,target=None):
    _enabled()
    if os.getenv('SMARTPRO_ACADEMIC_API')!='YES':raise StaffUnavailable('Academic operations are not enabled')
    fields={'GUIDE':{'facultyId','expectedGuideId','reason'},'SCHEDULE':{'scheduledAt','expectedReviewVersion','reason'},'DELEGATE_OPERATION':{'mandateId','operation','validUntil','reason'}}
    body=command_body(request.data,fields[action])
    body['_actingRole']=getattr(request.user,'role',None)
    if action=='GUIDE':body['projectId']=str(target)
    if action=='SCHEDULE':body['reviewId']=str(target);AwareDateTime().run_validation(body['scheduledAt'])
    if action=='DELEGATE_OPERATION':AwareDateTime().run_validation(body['validUntil'])
    return private_response(staff_sql_command('SELECT public.smartpro_project_operation(%s,%s,%s,%s,%s)',request.user.id,dept,action,body,request.headers.get('Idempotency-Key')))

@api_view(['POST'])
def guide(request,department_id,project_id):return command(request,department_id,'GUIDE',project_id)
@api_view(['POST'])
def schedule(request,department_id,review_id):return command(request,department_id,'SCHEDULE',review_id)
@api_view(['POST'])
def delegate(request,department_id):return command(request,department_id,'DELEGATE_OPERATION')
