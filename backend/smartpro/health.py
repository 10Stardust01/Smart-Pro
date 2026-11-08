"""Private dependency details stay in logs; probes return status only."""
import logging
import os
from pathlib import Path

from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.http import require_safe

logger = logging.getLogger(__name__)


def response(available):
    result = JsonResponse({'status': 'ok' if available else 'unavailable'}, status=200 if available else 503)
    result['Cache-Control'] = 'no-store'
    return result


@require_safe
def live(request):
    return response(True)


@require_safe
def ready(request):
    signatures = []
    if os.getenv('SMARTPRO_DOCUMENT_API') == 'YES':
        signatures += ['public.smartpro_document_project_page(uuid,uuid,text,text,integer,uuid)',
                       'public.smartpro_course_project_documents(uuid,uuid,uuid,text)']
        storage = os.getenv('SMARTPRO_DATA_DIR')
        if not storage or not Path(storage).is_dir() or not os.access(storage, os.W_OK):
            return response(False)
    if os.getenv('SMARTPRO_COURSE_API') == 'YES':
        signatures += ['public.smartpro_course_evaluation_queue(uuid,uuid,text,text,text,integer)']
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT NOT EXISTS (SELECT FROM unnest(%s::text[]) s WHERE to_regprocedure(s) IS NULL)', (signatures,))
            available = cursor.fetchone()[0]
    except DatabaseError:
        logger.warning('readiness_database_unavailable')
        available = False
    return response(available)
