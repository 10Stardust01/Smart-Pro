"""Loopback demonstration assets and narrowly scoped discovery/admission bridge."""
import json
import os
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied, ValidationError

from .identity import DEMO_USERS, local_development_enabled
from .staff import StaffUnavailable, _execute
from .student_views import private_response

FACULTY_REFERENCE_DEPARTMENT = UUID('10000000-0000-4000-8000-000000000001')


def enabled():
    return (os.getenv('SMARTPRO_ENV')=='demo' and os.getenv('SMARTPRO_DEMO_AUTH')=='YES'
            and os.getenv('SMARTPRO_DEPARTMENT_DEMO')=='YES'
            and all(os.getenv('SMARTPRO_'+gate+'_API')=='YES'
                    for gate in ['CURRICULUM','TEAM','MEMBERSHIP','PROJECT','STAFF','ACADEMIC'])
            and (settings.DATABASES['default']['NAME'].startswith('smartpro_test_demo_') or local_development_enabled()))


def asset(request,name='index.html'):
    if not (enabled() or os.getenv('SMARTPRO_UI')=='YES') or name not in {'index.html','app.js','styles.css','documents.js','workflow.js','setup.js','proposal.js','setup-policy.js','coordination.js','offering-management.js','document-requirements.js','course-management.js','faculty-reference.js'}:
        raise Http404
    path=Path(settings.BASE_DIR)/'frontend'/name
    if not path.is_file():
        raise Http404
    response=FileResponse(path.open('rb'),content_type='text/javascript' if name.endswith('.js') else {'index.html':'text/html','styles.css':'text/css'}[name])
    response['Cache-Control']='no-store'
    response['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


def context(request):
    # Explicit demo identities only; normal startup never seeds or offers fake logins.
    is_demo=enabled();people={};responsibilities={}
    if is_demo:
        labels=_execute('SELECT public.smartpro_demo_persona_labels(%s::uuid[])',(list(DEMO_USERS.values()),))
        people={alias:labels[uid] for alias,uid in DEMO_USERS.items() if uid in labels}
        choices=_execute('SELECT jsonb_object_agg(id::text,public.smartpro_role_choices(id)) FROM unnest(%s::uuid[]) AS ids(id)',([DEMO_USERS[alias] for alias in people],))
        responsibilities={alias:choices.get(uid,[]) for alias,uid in DEMO_USERS.items() if alias in people}
    return JsonResponse({'courseManagement':os.getenv('SMARTPRO_COURSE_API')=='YES','demo':is_demo,'identities':list(people) if is_demo else [],'people':people,'responsibilities':responsibilities,
                         'facultyReferenceDepartmentId':str(FACULTY_REFERENCE_DEPARTMENT) if faculty_reference_enabled(request) else None})


def faculty_reference_enabled(request):
    database=settings.DATABASES['default']
    return (os.getenv('SMARTPRO_FACULTY_REFERENCE')=='YES' and os.getenv('SMARTPRO_COURSE_API')=='YES'
            and enabled() and (database['NAME'].startswith('smartpro_test_demo_acceptance_') or local_development_enabled())
            and database['HOST'] in ('127.0.0.1','localhost')
            and request.META.get('REMOTE_ADDR') in ('127.0.0.1','::1'))


@api_view(['GET'])
def faculty_reference(request,department_id):
    if not faculty_reference_enabled(request) or department_id!=FACULTY_REFERENCE_DEPARTMENT:
        raise Http404
    actor,role=request.user.id,request.user.role
    if role in ('Admin','HOD'):
        _execute('SELECT public.smartpro_department_leadership(%s,%s,%s)',(actor,department_id,role))
    elif role=='Coordinator':
        try:
            offering=str(UUID(request.query_params.get('offeringId','')))
        except ValueError:
            raise PermissionDenied('An assigned offering is required') from None
        catalog=_execute('SELECT public.smartpro_course_catalog(%s,%s,%s)',(actor,department_id,role))
        if not any(row['id']==offering for row in catalog['offerings']):
            raise PermissionDenied('An assigned offering is required')
    else:
        raise PermissionDenied('Faculty Reference requires department or course leadership')
    path=Path(__file__).with_name('reference_data')/'bit_main_cse_2026-11-07.json'
    return private_response(json.loads(path.read_text(encoding='utf-8')))


@api_view(['GET'])
def application_workspace(request):
    if os.getenv('SMARTPRO_UI')!='YES' and not enabled():
        raise StaffUnavailable('Application workspace is not enabled')
    return private_response(_execute('SELECT public.smartpro_role_workspace(%s,%s)',(request.user.id,getattr(request.user,'role',None))))


@api_view(['GET'])
def workspace(request):
    if not enabled():
        raise StaffUnavailable('Department demonstration is not enabled')
    legacy=_execute('SELECT public.smartpro_demo_workspace(%s)',(request.user.id,))
    if getattr(request.user,'role',None):
        scoped=_execute('SELECT public.smartpro_role_workspace(%s,%s)',(request.user.id,request.user.role))
        scoped['department']=legacy.get('department');scoped['admission']=legacy.get('admission') if request.user.role=='Student' else None
        return private_response(scoped)
    return private_response(legacy)


@api_view(['POST'])
def enroll(request):
    if not enabled():
        raise StaffUnavailable('Department demonstration is not enabled')
    if request.data!={}:
        raise ValidationError('Enrollment uses only your trusted synthetic admission; no identity or department fields are accepted')
    return private_response(_execute('SELECT public.smartpro_demo_enroll(%s)',(request.user.id,)))
