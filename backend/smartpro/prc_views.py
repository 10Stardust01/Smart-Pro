"""Scoped PRC assignment and official synopsis-decision endpoints.

No committee quorum or HOD authority is inferred here: only an explicitly
assigned PRC faculty member records the committee outcome for a submitted
synopsis. Existing curriculum/document SQL owns the transaction and audit.
"""
import os

from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError

from .command_input import command_body
from .staff import _enabled, _execute, staff_sql_command, StaffUnavailable
from .student_views import private_response


def _available():
    _enabled()
    if os.getenv('SMARTPRO_ACADEMIC_API') != 'YES' or os.getenv('SMARTPRO_DOCUMENT_API') != 'YES':
        raise StaffUnavailable('PRC requires the academic and document services')
    if not _execute("SELECT to_regprocedure('public.smartpro_prc_command(uuid,uuid,text,jsonb,text)') IS NOT NULL", ()):
        raise StaffUnavailable('PRC workflow migration is not installed')


@api_view(['GET', 'POST'])
def offering(request, offering_id):
    _available()
    if request.method == 'GET':
        return private_response(_execute(
            'SELECT public.smartpro_prc_overview(%s,%s,%s)',
            (request.user.id, offering_id, request.user.role)))

    if not isinstance(request.data, dict):
        raise ValidationError('PRC command must be an object')
    action = request.data.get('action')
    fields = {
        'ACTIVATE': {'reason'},
        'ASSIGN': {'projectId', 'facultyId', 'reason'},
        'END_MEMBER': {'memberId', 'reason'},
        'DECIDE': {'projectId', 'attemptId', 'expectedCaseVersion', 'decision', 'comment'},
    }
    if action not in fields:
        raise ValidationError('Choose a supported PRC command')
    body = command_body({k: v for k, v in request.data.items() if k != 'action'}, fields[action])
    for key in {'projectId', 'facultyId', 'memberId', 'attemptId'} & body.keys():
        serializers.UUIDField().run_validation(body[key])
    if action == 'DECIDE':
        body['expectedCaseVersion'] = serializers.IntegerField(min_value=1).run_validation(body['expectedCaseVersion'])
        serializers.ChoiceField(['APPROVE', 'REQUEST_MODIFICATION', 'REJECT']).run_validation(body['decision'])
        body['comment'] = serializers.CharField(min_length=1, max_length=4000, trim_whitespace=True).run_validation(body['comment'])
    return private_response(staff_sql_command(
        'SELECT public.smartpro_prc_command(%s,%s,%s,%s,%s)',
        request.user.id, offering_id, action, body, request.headers.get('Idempotency-Key')))
