"""Read-only PRC progress; committee appointment/decision powers stay unresolved."""
import os

from rest_framework import serializers
from rest_framework.decorators import api_view

from .course_views import enabled
from .staff import StaffUnavailable, _execute
from .student_views import private_response


def available():
    enabled()
    if os.getenv('SMARTPRO_DOCUMENT_API') != 'YES':
        raise StaffUnavailable('PRC progress requires the document service')
    if not _execute("SELECT to_regprocedure('public.smartpro_prc_project_status(uuid,uuid,text)') IS NOT NULL", ()):
        raise StaffUnavailable('PRC progress is not available in this environment')


@api_view(['GET'])
def offering(request, offering_id):
    available()
    page = serializers.IntegerField(min_value=1, max_value=99999999).run_validation(
        request.query_params.get('page', 1))
    return private_response(_execute(
        'SELECT public.smartpro_prc_offering_status(%s,%s,%s,%s)',
        (request.user.id, offering_id, request.user.role, page)))


@api_view(['GET'])
def project(request, project_id):
    available()
    return private_response(_execute(
        'SELECT public.smartpro_prc_project_status(%s,%s,%s)',
        (request.user.id, project_id, request.user.role)))
