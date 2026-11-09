"""Offering-scoped coordination; reuse existing academic command transactions."""
import os

from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError

from .command_input import command_body
from .staff import StaffUnavailable, _execute, staff_sql_command
from .staff_views import AwareDateTime
from .student_views import private_response


def enabled():
    if os.getenv('SMARTPRO_COURSE_API') != 'YES' or os.getenv('SMARTPRO_ACADEMIC_API') != 'YES':
        raise StaffUnavailable('Course management is not enabled')


@api_view(['GET'])
def catalog(request, department_id):
    enabled()
    if 'page' in request.query_params:
        if not _execute("SELECT to_regprocedure('public.smartpro_department_offering_page(uuid,uuid,text,text,text,integer,uuid,integer)') IS NOT NULL",()):
            raise StaffUnavailable('Department offering pages require candidate 054')
        q=request.query_params
        page=serializers.IntegerField(min_value=1,max_value=99999999)
        filters=(serializers.CharField(max_length=120,allow_blank=True).run_validation(q.get('q','')),
                 serializers.ChoiceField(choices=['ALL','ACTIVE','PAUSED','ARCHIVED']).run_validation(q.get('availability','ALL')),
                 page.run_validation(q.get('page')),
                 serializers.UUIDField(allow_null=True).run_validation(q.get('selected')),
                 page.run_validation(q.get('appointmentPage',1)))
        return private_response(_execute('SELECT public.smartpro_department_offering_page(%s,%s,%s,%s,%s,%s,%s,%s)',
                                         (request.user.id,department_id,request.user.role,*filters)))
    return private_response(_execute('SELECT public.smartpro_course_catalog(%s,%s,%s)',
                                    (request.user.id,department_id,request.user.role)))


@api_view(['POST'])
def appointments(request, offering_id):
    enabled()
    body=command_body(request.data,{'userId','expectedVersion','active','validUntil','responsibilities','authority','reason'})
    serializers.UUIDField().run_validation(body['userId'])
    body['expectedVersion']=serializers.IntegerField(min_value=0).run_validation(body['expectedVersion'])
    if type(body['active']) is not bool:raise ValidationError('Explicit appointment status required')
    AwareDateTime().run_validation(body['validUntil'])
    serializers.ListField(child=serializers.ChoiceField(['OVERVIEW','REQUIREMENTS','PLAN','GUIDE','EVALUATORS','SUBMISSIONS','DEADLINES','RESULTS','CORRECTIONS','HISTORY']),max_length=10).run_validation(body['responsibilities'])
    if body['authority'] is not None and not isinstance(body['authority'],dict):raise ValidationError('Instruction source required')
    body['_actingRole']=request.user.role
    return private_response(staff_sql_command('SELECT public.smartpro_appoint_course(%s,%s,%s,%s,%s)',
        request.user.id,offering_id,'APPOINT',body,request.headers.get('Idempotency-Key')))


@api_view(['POST'])
def command(request,offering_id):
    enabled()
    if not isinstance(request.data,dict):raise ValidationError('Course command required')
    action=request.data.get('action')
    if action in ('REQUEST_EXCEPTIONAL_STAGE_CORRECTION',
                  'AUTHORIZE_EXCEPTIONAL_STAGE_CORRECTION',
                  'APPLY_EXCEPTIONAL_STAGE_CORRECTION', 'APPLY_FINAL_REVISION'):
        raise ValidationError('Published results use direct Guide-to-Coordinator correction')

    fields={
        'DEADLINE':{'deadlineKey','expectedVersion','projectId','kind','target','name','dueAt','reminderHours','notifyRoles','active','reason'},
        'FRAMEWORK':{'expectedVersion','configuration','authority','reason'},
        'PLAN':{'expectedVersion','frameworkId','schedules','reason'},
        'CREATE_STAGE':{'projectId','stageKey','facultyIds','reason'},
        'REOPEN_SYNOPSIS':{'projectId','expectedCaseVersion','comment','reason'},
        'REQUEST_CORRECTION':{'reviewId','assessmentId','expectedReviewRevision','scores','reason'},
        'AUTHORIZE_CORRECTION':{'requestId','approved','reason'},
        'APPLY_CORRECTION':{'requestId','reason'},
        'PUBLISH_FINAL':{'projectId','expectedVersion','reason'},
        'REQUEST_FINAL_REVISION':{'projectId','expectedVersion','studentId','marks','reason'},
        'AUTHORIZE_FINAL_REVISION':{'requestId','approved','reason'},
        'APPLY_REQUIREMENT':{'policyId','expectedPolicyId','reason'},
        'COMPLETE_MILESTONE':{'deadlineId','projectId','reason'},
    }
    if not isinstance(action,str) or action not in fields:raise ValidationError('Supported course action required')
    optional = {'completionRole','completionScope'} & request.data.keys() if action=='DEADLINE' else set()
    if action=='REQUEST_FINAL_REVISION' and request.data.get('mode')=='STAGE_EVIDENCE':
        fields[action]={'projectId','expectedVersion','mode','reason'}
    body=command_body({k:v for k,v in request.data.items() if k!='action'},fields[action] | optional)
    for key in {'projectId','frameworkId','reviewId','assessmentId','requestId','studentId','policyId','expectedPolicyId','deadlineId'} & body.keys():
        serializers.UUIDField(allow_null=key=='expectedPolicyId' or (action=='DEADLINE' and key=='projectId')).run_validation(body[key])
    for key in {'expectedVersion','expectedCaseVersion','expectedReviewRevision'}&body.keys():body[key]=serializers.IntegerField(min_value=0).run_validation(body[key])
    if action=='FRAMEWORK':
        cfg=body['configuration']
        required={'stages','method','rounding','decimalPlaces','scale','allowFinalCorrections','outsidePanelAuthorizer','maxExtensionDays','publicationRoles'}
        if not isinstance(cfg,dict) or set(cfg)-{'deadlineRules','requirementPolicyIds'}!=required or any(v is None for v in cfg.values()):raise ValidationError('Complete explicit academic framework required')
        if not isinstance(cfg['stages'],list) or not 1<=len(cfg['stages'])<=10:raise ValidationError('Configure one to ten approved stages')
        for stage in cfg['stages']:
            if not isinstance(stage,dict) or set(stage)!={'key','name','schemeVersionId','schemeModeId','policyId','weight','required','opensAt','deadline'} or any(v is None for v in stage.values()):raise ValidationError('Complete stage settings required')
            for key in ['opensAt','deadline']:AwareDateTime().run_validation(stage[key])
    if action=='DEADLINE':
        AwareDateTime().run_validation(body['dueAt'])
        for field in ['deadlineKey','target','name']:body[field]=serializers.CharField(max_length=120).run_validation(body[field])
        serializers.ChoiceField(['DOCUMENT','REVISION','REVIEW','EVALUATION','MILESTONE','FINAL_SUBMISSION']).run_validation(body['kind'])
        serializers.ListField(child=serializers.IntegerField(min_value=0,max_value=8784),max_length=20).run_validation(body['reminderHours'])
        serializers.ListField(child=serializers.ChoiceField(['Student','Faculty','Coordinator','HOD']),max_length=4).run_validation(body['notifyRoles'])
        if type(body['active']) is not bool:raise ValidationError('Explicit deadline status required')
        if body['kind']=='MILESTONE':
            serializers.ChoiceField(['Student','Faculty','Coordinator','HOD']).run_validation(body.get('completionRole'))
            serializers.ChoiceField(['PROJECT','INDIVIDUAL']).run_validation(body.get('completionScope'))
    if action=='PLAN':
        if not isinstance(body['schedules'],dict) or len(body['schedules'])>10:raise ValidationError('Stage schedules required')
        for value in body['schedules'].values():AwareDateTime().run_validation(value)
    if action=='CREATE_STAGE':serializers.ListField(child=serializers.UUIDField(),max_length=50).run_validation(body['facultyIds'])
    if action in ('AUTHORIZE_CORRECTION','AUTHORIZE_FINAL_REVISION') and type(body['approved']) is not bool:
        raise ValidationError('Choose a specific decision')
    if action=='REQUEST_FINAL_REVISION':
        if body.get('mode')!='STAGE_EVIDENCE':
            body['marks']=serializers.RegexField(regex=r'^[0-9]{1,8}([.][0-9]{1,4})?
    if action=='REOPEN_SYNOPSIS':body['comment']=serializers.CharField(max_length=4000,allow_blank=True).run_validation(body['comment'])
    body['_actingRole']=request.user.role
    service='smartpro_course_command'
    if action=='DEADLINE':
        service='smartpro_course_deadline_command'
    elif action in ('REQUEST_FINAL_REVISION','AUTHORIZE_FINAL_REVISION'):
        service='smartpro_course_final_revision'
    elif action in ('APPLY_REQUIREMENT','COMPLETE_MILESTONE'):
        service='smartpro_course_auxiliary'
    sql=f'SELECT public.{service}(%s,%s,%s,%s,%s)'
    return private_response(staff_sql_command(sql,request.user.id,offering_id,action,body,request.headers.get('Idempotency-Key')))


@api_view(['GET'])
def notifications(request):
    enabled()
    return private_response(_execute('SELECT public.smartpro_course_notifications(%s,%s)',(request.user.id,request.user.role)))


@api_view(['GET'])
def details(request,offering_id):
    enabled()
    return private_response(_execute('SELECT public.smartpro_course_details(%s,%s,%s)',(request.user.id,offering_id,request.user.role)))


@api_view(['GET'])
def evaluation_queue(request, offering_id):
    enabled()
    if not _execute("SELECT to_regprocedure('public.smartpro_course_evaluation_queue(uuid,uuid,text,text,text,integer)') IS NOT NULL", ()):
        raise StaffUnavailable('The evaluation queue requires candidates 048 and 049')
    query = serializers.CharField(max_length=120, allow_blank=True).run_validation(request.query_params.get('q', ''))
    status = serializers.ChoiceField(['all', 'unassigned', 'in-progress', 'published']).run_validation(
        request.query_params.get('status', 'all'))
    page = serializers.IntegerField(min_value=1, max_value=2147483647).run_validation(request.query_params.get('page', '1'))
    return private_response(_execute('SELECT public.smartpro_course_evaluation_queue(%s,%s,%s,%s,%s,%s)',
                                    (request.user.id, offering_id, request.user.role, query, status, page)))


@api_view(['GET'])
def guide_final_corrections(request):
    enabled()
    if not _execute("SELECT to_regprocedure('public.smartpro_guide_final_corrections(uuid,text)') IS NOT NULL", ()):
        raise StaffUnavailable('Direct published-result corrections require reviewed candidate 059')
    return private_response(_execute('SELECT public.smartpro_guide_final_corrections(%s,%s)',
                                     (request.user.id,request.user.role)))
,max_length=20).run_validation(body['marks'])
        body['reason']=serializers.CharField(min_length=1,max_length=500,trim_whitespace=True).run_validation(body['reason'])
    if action=='REOPEN_SYNOPSIS':body['comment']=serializers.CharField(max_length=4000,allow_blank=True).run_validation(body['comment'])
    body['_actingRole']=request.user.role
    service='smartpro_course_command'
    if action=='DEADLINE':
        service='smartpro_course_deadline_command'
    elif action in ('REQUEST_FINAL_REVISION','AUTHORIZE_FINAL_REVISION'):
        service='smartpro_course_final_revision'
    elif action in ('APPLY_REQUIREMENT','COMPLETE_MILESTONE'):
        service='smartpro_course_auxiliary'
    sql=f'SELECT public.{service}(%s,%s,%s,%s,%s)'
    return private_response(staff_sql_command(sql,request.user.id,offering_id,action,body,request.headers.get('Idempotency-Key')))


@api_view(['GET'])
def notifications(request):
    enabled()
    return private_response(_execute('SELECT public.smartpro_course_notifications(%s,%s)',(request.user.id,request.user.role)))


@api_view(['GET'])
def details(request,offering_id):
    enabled()
    return private_response(_execute('SELECT public.smartpro_course_details(%s,%s,%s)',(request.user.id,offering_id,request.user.role)))


@api_view(['GET'])
def evaluation_queue(request, offering_id):
    enabled()
    if not _execute("SELECT to_regprocedure('public.smartpro_course_evaluation_queue(uuid,uuid,text,text,text,integer)') IS NOT NULL", ()):
        raise StaffUnavailable('The evaluation queue requires candidates 048 and 049')
    query = serializers.CharField(max_length=120, allow_blank=True).run_validation(request.query_params.get('q', ''))
    status = serializers.ChoiceField(['all', 'unassigned', 'in-progress', 'published']).run_validation(
        request.query_params.get('status', 'all'))
    page = serializers.IntegerField(min_value=1, max_value=2147483647).run_validation(request.query_params.get('page', '1'))
    return private_response(_execute('SELECT public.smartpro_course_evaluation_queue(%s,%s,%s,%s,%s,%s)',
                                    (request.user.id, offering_id, request.user.role, query, status, page)))


@api_view(['GET'])
def guide_final_corrections(request):
    enabled()
    if not _execute("SELECT to_regprocedure('public.smartpro_guide_final_corrections(uuid,text)') IS NOT NULL", ()):
        raise StaffUnavailable('Direct published-result corrections require reviewed candidate 059')
    return private_response(_execute('SELECT public.smartpro_guide_final_corrections(%s,%s)',
                                     (request.user.id,request.user.role)))
