import importlib.util
import logging
from pathlib import Path

import psycopg
from django.conf import settings
from django.db import DatabaseError
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

spec = importlib.util.spec_from_file_location('smartpro_synopsis_domain', Path(settings.BASE_DIR) / 'workflow-poc/domain.py')
domain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(domain)


def exception_handler(exc, context):
    if isinstance(exc, domain.DomainError):
        return Response({'detail': {'code': exc.code, 'message': exc.message}}, status=exc.status)
    if isinstance(exc, (psycopg.Error, DatabaseError)):
        cause = exc.__cause__ or exc
        logging.getLogger(__name__).error('database_request_rejected sqlstate=%s',
                                         getattr(cause, 'sqlstate', None))
        return Response({'detail': {'code': 'DATABASE_UNAVAILABLE', 'message': 'Database request rejected'}}, status=503)
    response = drf_exception_handler(exc, context)
    if response is not None:
        detail = (response.data.get('detail', 'Request rejected')
                  if isinstance(response.data, dict) else response.data)
        if isinstance(detail, list):
            detail = '; '.join(str(item) for item in detail)
        response.data = {'detail': {'code': 'AUTHENTICATION_REQUIRED' if response.status_code == 401 else 'REQUEST_REJECTED',
                                    'message': str(detail)}}
    return response


@api_view(['GET'])
def read_case(request, case_id):
    role=getattr(request.user,'role',None)
    if role:
        from .staff import _execute
        from rest_framework.exceptions import PermissionDenied
        if not _execute('SELECT public.smartpro_role_case_access(%s,%s,%s)',(request.user.id,case_id,role)):
            raise PermissionDenied('This submission is outside your current responsibility')
    return Response(domain.read_case(str(case_id), request.user.id))
