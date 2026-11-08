"""Scoped management lifecycles over existing academic records."""
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError

from .command_input import command_body
from .document_views import enabled
from .staff import _enabled, _execute, staff_sql_command
from .staff_views import AwareDateTime
from .student_views import private_response


@api_view(['GET', 'POST'])
def offerings(request, department_id):
    enabled()
    _enabled()
    if request.method == 'GET':
        return private_response(_execute('SELECT public.smartpro_offering_management(%s,%s)', (request.user.id, department_id)))
    if not isinstance(request.data, dict):
        raise ValidationError('Offering details must be an object')
    action = request.data.get('action')
    shapes = {'EDIT': {'offeringId', 'expectedRevision', 'configuration', 'authority', 'reason'},
              'AVAILABILITY': {'offeringId', 'expectedRevision', 'availability', 'authority', 'reason'}}
    if not isinstance(action, str) or action not in shapes:
        raise ValidationError('Choose a supported management action')
    body = command_body({k: v for k, v in request.data.items() if k != 'action'}, shapes[action])
    serializers.UUIDField().run_validation(body['offeringId'])
    body['expectedRevision'] = serializers.IntegerField(min_value=0).run_validation(body['expectedRevision'])
    authority = body['authority']
    if not isinstance(authority, dict) or set(authority) != {'hodMandateId', 'source', 'confirmed', 'reference'}:
        raise ValidationError('Record the approved departmental instruction')
    serializers.UUIDField().run_validation(authority['hodMandateId'])
    if action == 'AVAILABILITY':
        serializers.ChoiceField(['ACTIVE', 'PAUSED', 'ARCHIVED']).run_validation(body['availability'])
    else:
        cfg = body['configuration']
        fields = {'curriculumTypeId', 'cycleId', 'semester', 'projectPolicyId', 'teamPolicyId', 'adminRoleId',
                  'visibleFrom', 'visibleUntil', 'submissionOpensAt', 'submissionClosesAt', 'maxBytes',
                  'facultyApprovalEnabled', 'teamCreationEnabled'}
        if not isinstance(cfg, dict) or set(cfg)-{'requiresSynopsis'} != fields:
            raise ValidationError('Complete offering settings are required')
        for field in ['curriculumTypeId', 'cycleId', 'projectPolicyId', 'teamPolicyId', 'adminRoleId']:
            serializers.UUIDField().run_validation(cfg[field])
        cfg['semester'] = serializers.CharField(max_length=80).run_validation(cfg['semester'])
        if 'requiresSynopsis' in cfg and type(cfg['requiresSynopsis']) is not bool:raise ValidationError('Choose the approved synopsis requirement')
        for field in ['visibleFrom', 'visibleUntil']+(['submissionOpensAt','submissionClosesAt'] if cfg.get('requiresSynopsis',True) else []):
            AwareDateTime().run_validation(cfg[field])
        for field in ['facultyApprovalEnabled', 'teamCreationEnabled']:
            if type(cfg[field]) is not bool:
                raise ValidationError('Explicit offering permissions required')
        cfg['maxBytes'] = serializers.IntegerField(min_value=1, max_value=2097152,allow_null=not cfg.get('requiresSynopsis',True)).run_validation(cfg['maxBytes'])
    return private_response(staff_sql_command('SELECT public.smartpro_manage_offering(%s,%s,%s,%s,%s)',
                                             request.user.id, department_id, action, body,
                                             request.headers.get('Idempotency-Key')))


@api_view(['GET', 'POST'])
def configuration(request, department_id):
    enabled()
    _enabled()
    if request.method == 'GET':
        return private_response(_execute('SELECT public.smartpro_configuration_management(%s,%s)', (request.user.id, department_id)))
    body=command_body(request.data, {'action','cycleId','expectedRevision','code','startsOn','endsOn','authority','reason'})
    if body.pop('action')!='CYCLE':raise ValidationError('Choose cycle management')
    serializers.UUIDField().run_validation(body['cycleId'])
    body['expectedRevision']=serializers.IntegerField(min_value=0).run_validation(body['expectedRevision'])
    body['code']=serializers.CharField(max_length=80).run_validation(body['code'])
    for field in ['startsOn','endsOn']:serializers.DateField().run_validation(body[field])
    if not isinstance(body['authority'],dict):raise ValidationError('Instruction source required')
    return private_response(staff_sql_command('SELECT public.smartpro_manage_configuration(%s,%s,%s,%s,%s)',request.user.id,department_id,'CYCLE',body,request.headers.get('Idempotency-Key')))


@api_view(['GET', 'POST'])
def assignments(request, department_id):
    enabled()
    _enabled()
    if request.method=='GET':
        return private_response(_execute('SELECT public.smartpro_assignment_management(%s,%s,%s)',(request.user.id,department_id,request.user.role)))
    if not isinstance(request.data,dict):raise ValidationError('Assignment command must be an object')
    action=request.data.get('action')
    shapes={'END_ASSIGNMENT':{'assignmentId','reason'},'REVOKE_OPERATION':{'grantId','reason'}}
    if not isinstance(action,str) or action not in shapes:raise ValidationError('Choose an assignment operation')
    body=command_body({k:v for k,v in request.data.items() if k!='action'},shapes[action])
    for key in shapes[action]-{'reason'}:serializers.UUIDField().run_validation(body[key])
    body['_actingRole']=request.user.role
    return private_response(staff_sql_command('SELECT public.smartpro_manage_assignment(%s,%s,%s,%s,%s)',request.user.id,department_id,action,body,request.headers.get('Idempotency-Key')))


@api_view(['GET','POST'])
def document_requirements(request,department_id):
    enabled()
    _enabled()
    if request.method=='GET':return private_response(_execute('SELECT public.smartpro_document_requirement_management(%s,%s)',(request.user.id,department_id)))
    body=command_body(request.data,{'offeringId','requirementKey','expectedPolicyId','name','opensAt','closesAt','maxBytes','required','allowApproval','allowChanges','allowRevisions','reviewerIds','authority','reason'})
    serializers.UUIDField().run_validation(body['offeringId'])
    serializers.UUIDField(allow_null=True).run_validation(body['expectedPolicyId'])
    body['requirementKey']=serializers.CharField(max_length=100,allow_null=True).run_validation(body['requirementKey'])
    body['name']=serializers.CharField(max_length=120).run_validation(body['name'])
    for field in ['opensAt','closesAt']:AwareDateTime().run_validation(body[field])
    body['maxBytes']=serializers.IntegerField(min_value=1,max_value=2097152).run_validation(body['maxBytes'])
    for field in ['required','allowApproval','allowChanges','allowRevisions']:
        if type(body[field]) is not bool:raise ValidationError('Explicit document rules required')
    serializers.ListField(child=serializers.UUIDField(),max_length=50).run_validation(body['reviewerIds'])
    if not isinstance(body['authority'],dict):raise ValidationError('Instruction source required')
    return private_response(staff_sql_command('SELECT public.smartpro_configure_requirement(%s,%s,%s,%s,%s)',request.user.id,department_id,'CONFIGURE',body,request.headers.get('Idempotency-Key')))


@api_view(['POST'])
def revise_proposal(request,project_id):
    from .projects import _enabled as project_enabled
    project_enabled()
    body=command_body(request.data,{'expectedRevision','title','description'})
    body['expectedRevision']=serializers.IntegerField(min_value=1).run_validation(body['expectedRevision'])
    body['title']=serializers.CharField(max_length=500).run_validation(body['title'])
    body['description']=serializers.CharField(max_length=10000,allow_blank=True).run_validation(body['description'])
    return private_response(staff_sql_command('SELECT public.smartpro_revise_proposal(%s,%s,%s,%s,%s)',request.user.id,project_id,'REVISE',body,request.headers.get('Idempotency-Key')))


@api_view(['GET','POST'])
def review_management(request,department_id,review_id):
    import os
    from .staff import StaffUnavailable
    if os.getenv('SMARTPRO_ACADEMIC_API') != 'YES':
        raise StaffUnavailable('Academic service is not enabled')
    enabled()
    if request.method=='GET':
        return private_response(_execute('SELECT public.smartpro_review_management(%s,%s,%s,%s)',(request.user.id,department_id,review_id,request.user.role)))
    body=command_body(request.data,{'expectedReviewRevision','facultyIds'})
    body['expectedReviewRevision']=serializers.IntegerField(min_value=0).run_validation(body['expectedReviewRevision'])
    serializers.ListField(child=serializers.UUIDField(),min_length=1,max_length=50).run_validation(body['facultyIds'])
    body.update(reviewId=str(review_id),_actingRole=request.user.role)
    return private_response(staff_sql_command('SELECT public.smartpro_revise_evaluators(%s,%s,%s,%s,%s)',request.user.id,department_id,'EVALUATORS',body,request.headers.get('Idempotency-Key')))
