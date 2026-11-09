"""Exact, audited operational setup; HOD approval remains separate."""
import os
import csv
import json
from io import StringIO
from decimal import Decimal
from .command_input import command_body
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError
from rest_framework import serializers
from .document_views import enabled
from .staff import _execute,staff_sql_command
from .student_views import private_response

@api_view(['GET','POST'])
def setup(request,department_id):
    enabled()
    if request.method=='GET':
        result=_execute('SELECT public.smartpro_department_setup_read(%s,%s)',(request.user.id,department_id))
        result['options']=_execute('SELECT public.smartpro_setup_options(%s,%s)',(request.user.id,department_id))
        result['instructionSources']=_execute('SELECT public.smartpro_instruction_sources(%s,%s)',(request.user.id,department_id))
        role=getattr(request.user,'role',None)
        if role in ('HOD','Admin') and os.getenv('SMARTPRO_COURSE_API')=='YES' and _execute(
                "SELECT to_regprocedure('public.smartpro_department_leadership(uuid,uuid,text)') IS NOT NULL",()):
            result['leadership']=_execute('SELECT public.smartpro_department_leadership(%s,%s,%s)',(request.user.id,department_id,role))
        if role=='Admin' and intake_available():
            if request.query_params.get('intake')=='metadata' and intake_paging_available():
                result['intake']=_execute(
                    "SELECT jsonb_build_object('departmentCode',public.smartpro_department_intake_code(%s,%s))",
                    (request.user.id,department_id))
            else:
                result['intake']=_execute("SELECT public.smartpro_department_intake(%s,%s,'READ','{}'::jsonb,NULL)",
                                          (request.user.id,department_id))
        result['canApproveRubric']=False
        if getattr(request.user,'role',None)=='HOD':
            result['canApproveRubric']=result['options']['schemeApproval']
        if getattr(request.user,'role',None)=='Admin':
            result['requests']=[r for r in result['requests'] if r['requested_by']==str(request.user.id)]
            result['reviewChoices']=[]
            return private_response(result)
        # Operational administrators receive no academic review capabilities.
        from rest_framework.exceptions import PermissionDenied
        try: result['reviewChoices']=_execute('SELECT public.smartpro_project_review_choices(%s,%s)',(request.user.id,department_id))
        except PermissionDenied: result['reviewChoices']=[]
        if getattr(request.user,'role',None) in ('HOD','Coordinator'):
            result['coordination']=_execute('SELECT public.smartpro_coordination_role_options(%s,%s,%s)',(request.user.id,department_id,request.user.role))
        return private_response(result)
    if not isinstance(request.data,dict):raise ValidationError('Configuration must be an object')
    body=dict(request.data);action=body.pop('action',None)
    fields={'REQUEST':{'kind','configuration','reason'},'APPROVE':{'requestId'},'APPLY':{'requestId'},'RECORD':{'kind','configuration','reason','authority'}}
    if not isinstance(action,str) or action not in fields:raise ValidationError('Unknown setup action')
    body=command_body(body,fields[action])
    if action in ('REQUEST','RECORD'):
        body['reason']=serializers.CharField(max_length=500,allow_blank=True).run_validation(body['reason'])
        if action=='RECORD':
            authority=body['authority']
            if not isinstance(authority,dict) or set(authority)!={'hodMandateId','source','confirmed','reference'} or authority['source']!='EXTERNAL_INSTRUCTION' or authority['confirmed'] is not True:
                raise ValidationError('Record the HOD instruction source')
            serializers.UUIDField().run_validation(authority['hodMandateId'])
            authority['reference']=serializers.CharField(max_length=500,allow_blank=True).run_validation(authority['reference'])
        cfg=body['configuration']
        shapes={'OFFERING':{'curriculumTypeId','cycleId','semester','projectPolicyId','teamPolicyId','adminRoleId','visibleFrom','visibleUntil','submissionOpensAt','submissionClosesAt','maxBytes','facultyApprovalEnabled','teamCreationEnabled'},'CYCLE':{'code','startsOn','endsOn'},'TYPE':{'code','label'},'DOCUMENT_NOT_REQUIRED':{'offeringId'},
                'PROJECT_POLICY':{'label','projectType','allowStudentRegistration'},
                'TEAM_POLICY':{'label','allowJoin','allowLeave','allowTransfer','minimumMembers','maximumMembers','sizeMode'},
                'REVIEW_BLUEPRINT':{'policyVersionId','cycleId','label','stages'},'STUDENT_PROFILE':{'userId','usn','section','semester'},'FACULTY_ACCESS':{'userId','validUntil'}}
        if not isinstance(body['kind'],str) or body['kind'] not in shapes or not isinstance(cfg,dict) or set(cfg)-( {'requiresSynopsis'} if body['kind']=='OFFERING' else set())!=shapes[body['kind']]:raise ValidationError('Complete supported setup configuration required')
        if body['kind']=='OFFERING':
            if action!='RECORD':raise ValidationError('Use the offering configuration action')
            from .staff_views import AwareDateTime
            if 'requiresSynopsis' in cfg and type(cfg['requiresSynopsis']) is not bool:raise ValidationError('Choose the approved synopsis requirement')
            for field in ['visibleFrom','visibleUntil']+(['submissionOpensAt','submissionClosesAt'] if cfg.get('requiresSynopsis',True) else []):AwareDateTime().run_validation(cfg.get(field))
            for field in ['facultyApprovalEnabled','teamCreationEnabled']:
                if type(cfg.get(field)) is not bool:raise ValidationError('Explicit offering permissions required')
            cfg['maxBytes']=serializers.IntegerField(min_value=1,max_value=2097152,allow_null=not cfg.get('requiresSynopsis',True)).run_validation(cfg['maxBytes'])
        if 'code' in cfg:cfg['code']=serializers.CharField(max_length=80).run_validation(cfg['code'])
        if body['kind']=='CYCLE':
            start=serializers.DateField().run_validation(cfg['startsOn']);end=serializers.DateField().run_validation(cfg['endsOn'])
            if start>=end:raise ValidationError('The cycle end must follow its start')
        elif body['kind']=='TYPE':
            cfg['label']=serializers.CharField(max_length=120).run_validation(cfg['label'])
            if cfg['code']!=cfg['code'].upper():raise ValidationError('Classification codes must be uppercase')
        if 'label' in cfg:cfg['label']=serializers.CharField(max_length=120).run_validation(cfg['label'])
        if body['kind']=='PROJECT_POLICY':
            cfg['projectType']=serializers.ChoiceField(['MINI','MAJOR']).run_validation(cfg['projectType'])
            if type(cfg['allowStudentRegistration']) is not bool:raise ValidationError('Choose whether student proposals are permitted')
        if body['kind']=='TEAM_POLICY':
            for key in ['allowJoin','allowLeave','allowTransfer']:
                if type(cfg[key]) is not bool:raise ValidationError('Explicit membership permissions required')
            for key in ['minimumMembers','maximumMembers']:
                cfg[key]=serializers.IntegerField(allow_null=True,min_value=0 if key=='minimumMembers' else 1).run_validation(cfg[key])
            cfg['sizeMode']=serializers.ChoiceField(['ADVISORY','ENFORCED']).run_validation(cfg['sizeMode'])
        if body['kind']=='REVIEW_BLUEPRINT':
            if not isinstance(cfg['stages'],list) or not 1<=len(cfg['stages'])<=10:raise ValidationError('Provide 1–10 complete review stages')
            for stage in cfg['stages']:
                if not isinstance(stage,dict) or set(stage)!={'code','label','mode','criteria'}:raise ValidationError('Complete stage details required')
                for key in ['code','label']:stage[key]=serializers.CharField(max_length=120).run_validation(stage[key])
                stage['mode']=serializers.ChoiceField(['TEAM','INDIVIDUAL','COMBINED']).run_validation(stage['mode'])
                if not isinstance(stage['criteria'],list) or not 1<=len(stage['criteria'])<=30:raise ValidationError('Provide criteria for every review stage')
                for item in stage['criteria']:
                    if not isinstance(item,dict) or set(item)!={'label','scope','maximum'}:raise ValidationError('Complete criterion details required')
                    item['label']=serializers.CharField(max_length=120).run_validation(item['label'])
                    item['scope']=serializers.ChoiceField(['TEAM','STUDENT']).run_validation(item['scope'])
                    item['maximum']=str(serializers.DecimalField(max_digits=9,decimal_places=2,min_value=Decimal('0.01')).run_validation(item['maximum']))
        if body['kind']=='STUDENT_PROFILE':
            for key in ['usn','section','semester']:cfg[key]=serializers.CharField(max_length=80).run_validation(cfg[key])
        if body['kind']=='FACULTY_ACCESS':
            from .staff_views import AwareDateTime
            AwareDateTime().run_validation(cfg['validUntil'])
    if action=='RECORD':
        return private_response(staff_sql_command('SELECT public.smartpro_record_instruction(%s,%s,%s,%s,%s)',request.user.id,department_id,action,body,request.headers.get('Idempotency-Key')))
    return private_response(staff_sql_command('SELECT public.smartpro_setup_current(%s,%s,%s,%s,%s)',request.user.id,department_id,action,body,request.headers.get('Idempotency-Key')))


@api_view(['POST'])
def leadership(request, department_id):
    enabled()
    if os.getenv('SMARTPRO_COURSE_API')!='YES' or not _execute(
            "SELECT to_regprocedure('public.smartpro_change_department_leadership(uuid,uuid,text,jsonb,text)') IS NOT NULL",()):
        from .staff import StaffUnavailable
        raise StaffUnavailable('Department leadership service is unavailable')
    if not isinstance(request.data,dict):
        raise ValidationError('Department leadership command required')
    if isinstance(request.data,dict) and request.data.get('action')=='HISTORY':
        if not _execute("SELECT to_regprocedure('public.smartpro_department_leadership_history(uuid,uuid,text,text,integer)') IS NOT NULL",()):
            from .staff import StaffUnavailable
            raise StaffUnavailable('Department leadership history requires candidate 055')
        filters=command_body({name:value for name,value in request.data.items() if name!='action'},{'page','q'})
        page=serializers.IntegerField(min_value=1,max_value=99999999).run_validation(filters['page'])
        search=serializers.CharField(max_length=120,allow_blank=True).run_validation(filters['q'])
        return private_response(_execute('SELECT public.smartpro_department_leadership_history(%s,%s,%s,%s,%s)',
            (request.user.id,department_id,request.user.role,search,page)))
    action=request.data.get('action')
    fields={
        'APPOINT_ADMIN': {'userId'}, 'REPLACE_ADMIN': {'userId','appointmentId'},
        'END_ADMIN': {'appointmentId'}, 'SET_ADMIN_CAPACITY': {'capacity'},
        'RESIGN_HOD': {'appointmentId'}, 'APPOINT_HOD': {'userId'},
    }
    if not isinstance(action,str) or action not in fields:
        raise ValidationError('Supported department leadership action required')
    body=command_body({k:v for k,v in request.data.items() if k!='action'},fields[action]|{'reason'})
    for name in {'userId','appointmentId'} & body.keys():
        serializers.UUIDField().run_validation(body[name])
    if 'capacity' in body:
        body['capacity']=serializers.IntegerField(min_value=1,max_value=50).run_validation(body['capacity'])
    body['_actingRole']=getattr(request.user,'role',None)
    return private_response(staff_sql_command(
        'SELECT public.smartpro_change_department_leadership(%s,%s,%s,%s,%s)',
        request.user.id,department_id,action,body,request.headers.get('Idempotency-Key')))


def intake_available():
    return os.getenv('SMARTPRO_COURSE_API')=='YES' and _execute(
        "SELECT to_regprocedure('public.smartpro_department_intake(uuid,uuid,text,jsonb,text)') IS NOT NULL",())


def intake_paging_available():
    return _execute("SELECT to_regprocedure('public.smartpro_department_intake_page(uuid,uuid,text,text,integer,integer)') IS NOT NULL",())


@api_view(['GET','POST'])
def intake(request,department_id):
    enabled()
    if not intake_available():
        from .staff import StaffUnavailable
        raise StaffUnavailable('Department intake service is unavailable')
    if getattr(request.user,'role',None)!='Admin':
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied('Department Admin required')
    actor=request.user.id
    if request.method=='GET':
        return intake_page(actor,department_id,{key:request.query_params[key] for key in ('kind','page','batchPage') if key in request.query_params})
    if isinstance(request.data,dict) and request.data.get('action')=='DIRECTORY':
        filters=command_body({name:value for name,value in request.data.items() if name!='action'},
                             {'kind','q','page'})
        if not _execute("SELECT to_regprocedure('public.smartpro_department_directory_page(uuid,uuid,text,text,integer)') IS NOT NULL",()):
            from .staff import StaffUnavailable
            raise StaffUnavailable('Department directory requires candidate 052')
        kind=serializers.ChoiceField(choices=['STUDENT','FACULTY']).run_validation(filters['kind'])
        search=serializers.CharField(max_length=120,allow_blank=True).run_validation(filters['q'])
        page=serializers.IntegerField(min_value=1,max_value=99999999).run_validation(filters['page'])
        return private_response(_execute('SELECT public.smartpro_department_directory_page(%s,%s,%s,%s,%s)',
                                         (actor,department_id,kind,search,page)))
    if isinstance(request.data,dict) and request.data.get('action')=='LIST':
        filters=command_body({name:value for name,value in request.data.items() if name!='action'},
                             {'kind','q','page','batchPage'})
        return intake_page(actor,department_id,filters)
    _execute("SELECT public.smartpro_department_intake(%s,%s,'READ','{}'::jsonb,NULL)",(actor,department_id))
    upload = request.FILES.get('file')
    if upload is not None:
        from .intake_files import read_export
        form=dict(request.data.items())
        del form['file']
        if form.get('action') not in ('HEADERS','PREVIEW','APPLY'):
            raise ValidationError('Supported department import action required')
        if 'mapping' in form:
            try:
                form['mapping']=json.loads(form['mapping'])
            except (TypeError,ValueError):
                raise ValidationError('Invalid column mapping') from None
        if 'confirmed' in form:
            form['confirmed']=form['confirmed']=='true'
    else:
        form=request.data
    if not isinstance(form,dict):
        raise ValidationError('Department import command required')
    action=form.get('action')
    if action not in ('HEADERS','PREVIEW','APPLY','RECONCILE'):
        raise ValidationError('Supported department import action required')
    data={name:value for name,value in form.items() if name!='action'}
    if action=='HEADERS':
        if upload is not None:
            command_body(data,set())
            headers,rows=read_export(upload)
        else:
            csv_text,=command_body(data,{'csv'}).values()
            headers,rows=read_intake_csv(csv_text)
        return private_response({'headers':headers,'sample':rows[:5]})
    if action=='RECONCILE':
        fields={'source','kind','identityKey','expectedBatchId','userId','confirmed'}
        if 'evidenceReference' in data:
            fields.add('evidenceReference')
            data['evidenceReference']=serializers.CharField(max_length=500,allow_blank=True).run_validation(data['evidenceReference'])
        payload=command_body(data,fields)
        serializers.UUIDField().run_validation(payload['userId'])
        serializers.UUIDField().run_validation(payload['expectedBatchId'])
        serializers.CharField(max_length=120).run_validation(payload['identityKey'])
    else:
        fields={'mapping','source','kind'} | ({'csv'} if upload is None else set())
        if action=='APPLY':
            fields|={'reference','confirmed'}
            if 'expectedRevision' in data:
                fields.add('expectedRevision')
                serializers.RegexField(r'^[0-9a-f]{32}$').run_validation(data['expectedRevision'])
        payload=command_body(data,fields)
        headers,rows=read_export(upload) if upload is not None else read_intake_csv(payload.pop('csv'))
        mapping=payload.pop('mapping')
        names=['key','name','department']+(['usn','semester','section'] if payload['kind']=='STUDENT' else [])
        if (not isinstance(mapping,dict) or set(mapping)!=set(names) or
                any(not isinstance(column,str) or column not in headers for column in mapping.values()) or
                len(set(mapping.values()))!=len(names)):
            raise ValidationError('Map each required field to a distinct CSV column')
        indexes={name:headers.index(mapping[name]) for name in names}
        payload['records']=[
            {name:(row[index].strip().upper() if name in ('usn','department') else row[index].strip())
             for name,index in indexes.items()}
            for row in rows
        ]
        if action=='APPLY':
            payload['reference']=serializers.CharField(max_length=500).run_validation(payload['reference'])
    sql='SELECT public.smartpro_department_intake(%s,%s,%s,%s,%s)'
    if action=='PREVIEW':
        from psycopg.types.json import Jsonb
        return private_response(_execute(sql,(actor,department_id,action,Jsonb(payload),None)))
    return private_response(staff_sql_command(sql,actor,department_id,action,payload,request.headers.get('Idempotency-Key')))


def intake_page(actor,department_id,filters):
    if not intake_paging_available():
        from .staff import StaffUnavailable
        raise StaffUnavailable('Department intake paging is unavailable')
    kind=serializers.ChoiceField(choices=['STUDENT','FACULTY']).run_validation(filters.get('kind','STUDENT'))
    search=serializers.CharField(max_length=120,allow_blank=True).run_validation(filters.get('q',''))
    page=serializers.IntegerField(min_value=1,max_value=99999999)
    return private_response(_execute('SELECT public.smartpro_department_intake_page(%s,%s,%s,%s,%s,%s)',
        (actor,department_id,kind,search,page.run_validation(filters.get('page',1)),
         page.run_validation(filters.get('batchPage',1)))))


def read_intake_csv(value):
    if not isinstance(value,str) or len(value.encode('utf-8'))>131072 or '\x00' in value:
        raise ValidationError('Upload a UTF-8 CSV file up to 128 KiB')
    try:
        reader=csv.reader(StringIO(value.removeprefix('\ufeff'),newline=''),strict=True)
        headers=[item.strip() for item in next(reader,[])]
        if (not 1<=len(headers)<=32 or any(not item or len(item)>120 for item in headers) or
                len(set(headers))!=len(headers)):
            raise ValidationError('CSV column names must be distinct and nonempty')
        rows=[]
        for row in reader:
            if not any(field.strip() for field in row):
                continue
            if len(row)!=len(headers) or any(len(field)>120 for field in row) or len(rows)==200:
                raise ValidationError('Use at most 200 complete rows with fields up to 120 characters')
            rows.append(row)
        if not rows:
            raise ValidationError('Include at least one record after the column names')
    except csv.Error:
        raise ValidationError('CSV could not be read') from None
    return headers,rows

def require_record_navigation():
    if not _execute("SELECT to_regclass('public.faculty_identity_links') IS NOT NULL",()):
        from .staff import StaffUnavailable
        raise StaffUnavailable('Department record navigation requires candidate 057')


@api_view(['GET','POST'])
def department_record(request, department_id, person_id):
    from rest_framework.exceptions import PermissionDenied
    enabled()
    if request.user.role!='Admin':
        raise PermissionDenied('Department Admin required')
    require_record_navigation()
    record=_execute('SELECT public.smartpro_department_record(%s,%s,%s)',(request.user.id,department_id,person_id))
    if request.method=='GET':
        if record['faculty']:
            if _execute("SELECT to_regprocedure('public.smartpro_faculty_manage_read(uuid,uuid,uuid)') IS NOT NULL",()):
                record['facultyAdmin']=_execute('SELECT public.smartpro_faculty_manage_read(%s,%s,%s)',
                                                 (request.user.id,department_id,person_id))
            from .demo_views import FACULTY_REFERENCE_DEPARTMENT, faculty_reference_enabled
            if department_id==FACULTY_REFERENCE_DEPARTMENT and faculty_reference_enabled(request):
                record['roster']=faculty_crosswalk_roster()
        return private_response(record)
    if not isinstance(request.data,dict):
        raise ValidationError('Identity command required')
    operation=request.data.get('action')
    management={'EDIT_DETAILS','AMEND_TERM','TERMINATE','REINSTATE'}
    if operation in management:
        if not _execute("SELECT to_regprocedure('public.smartpro_faculty_manage(uuid,uuid,uuid,text,jsonb,text)') IS NOT NULL",()):
            from .staff import StaffUnavailable
            raise StaffUnavailable('Faculty management requires reviewed candidate 063')
        shapes={
            'EDIT_DETAILS':{'displayName','designation','contactEmail','expectedRevision','reason'},
            'AMEND_TERM':{'termId','expectedAuthorityRevision','validUntil','reason'},
            'TERMINATE':{'termId','expectedAuthorityRevision','reason'},
            'REINSTATE':{'reason'}}
        body=command_body({key:value for key,value in request.data.items() if key!='action'},shapes[operation])
        body['reason']=serializers.CharField(max_length=500,trim_whitespace=True).run_validation(body['reason'])
        if not body['reason']:
            raise ValidationError('A reason is required')
        if operation=='EDIT_DETAILS':
            body['displayName']=serializers.CharField(min_length=2,max_length=120).run_validation(body['displayName'])
            body['designation']=serializers.CharField(max_length=120,allow_blank=True).run_validation(body['designation'])
            body['contactEmail']=serializers.EmailField(max_length=254,allow_blank=True).run_validation(body['contactEmail'])
            body['expectedRevision']=serializers.IntegerField(min_value=0).run_validation(body['expectedRevision'])
        if operation in ('AMEND_TERM','TERMINATE'):
            body['termId']=str(serializers.UUIDField().run_validation(body['termId']))
            body['expectedAuthorityRevision']=str(serializers.UUIDField().run_validation(body['expectedAuthorityRevision']))
        if operation=='AMEND_TERM':
            from .staff_views import AwareDateTime
            body['validUntil']=AwareDateTime().run_validation(body['validUntil']).isoformat()
        return private_response(staff_sql_command(
            'SELECT public.smartpro_faculty_manage(%s,%s,%s,%s,%s,%s)',
            request.user.id,department_id,operation,body,
            request.headers.get('Idempotency-Key'),target_id=person_id))
    if operation not in ('PROPOSE','VERIFY','REJECT','REVOKE'):
        raise ValidationError('Supported identity command required')
    fields={'evidence'} | ({'directoryRef','source','identifier'} if operation=='PROPOSE' else {'linkId'})
    payload=command_body({key:value for key,value in request.data.items() if key!='action'},fields)
    payload['evidence']=serializers.CharField(max_length=500).run_validation(payload['evidence'])
    if operation=='PROPOSE':
        from .demo_views import FACULTY_REFERENCE_DEPARTMENT, faculty_reference_enabled
        if department_id!=FACULTY_REFERENCE_DEPARTMENT or not faculty_reference_enabled(request):
            raise PermissionDenied('Department roster is unavailable')
        if payload['directoryRef'] not in {entry['ref'] for entry in faculty_crosswalk_roster()}:
            raise ValidationError('Choose a known directory entry')
        for name in ('source','identifier'):
            payload[name]=serializers.CharField(max_length=120).run_validation(payload[name])
    else:
        serializers.UUIDField().run_validation(payload['linkId'])
    return private_response(staff_sql_command(
        'SELECT public.smartpro_faculty_identity_command(%s,%s,%s,%s,%s,%s)',
        request.user.id,department_id,operation,payload,request.headers.get('Idempotency-Key'),target_id=person_id))


def faculty_crosswalk_roster():
    from pathlib import Path
    source=Path(__file__).with_name('reference_data')/'bit_main_cse_2026-11-07.json'
    return [{'ref':row['bitProfileUrl'],'name':row['name'],'designation':row['designation']}
            for row in json.loads(source.read_text(encoding='utf-8'))['records'] if row['bitProfileUrl']]


@api_view(['POST'])
def appointment_candidates(request, department_id):
    enabled()
    require_record_navigation()
    filters=command_body(request.data,{'q','page'})
    q=serializers.CharField(max_length=120,allow_blank=True).run_validation(filters['q'])
    page=serializers.IntegerField(min_value=1,max_value=99999999).run_validation(filters['page'])
    return private_response(_execute('SELECT public.smartpro_appointment_candidates(%s,%s,%s,%s,%s)',
                                     (request.user.id,department_id,request.user.role,q,page)))
