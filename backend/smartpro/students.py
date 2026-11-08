"""Student read services; SQL owns scope and uses one consistent snapshot."""
import json
import os
from uuid import UUID

import psycopg
from django.db import DatabaseError, connection
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError


class StudentServiceUnavailable(APIException):
    status_code = 503
    default_detail = 'Student curriculum service is not enabled'


def read_student(actor_id, *, offerings=False, cursor=None):
    if os.getenv('SMARTPRO_CURRICULUM_API') != 'YES':
        raise StudentServiceUnavailable()
    try:
        after = UUID(cursor) if cursor is not None else None
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('Invalid curriculum cursor') from None
    try:
        with connection.cursor() as db:
            if offerings:
                db.execute('SELECT smartpro_student_offerings(%s,%s)', (actor_id, after))
            else:
                db.execute('SELECT smartpro_student_profile(%s)', (actor_id,))
            result = db.fetchone()[0]
            return json.loads(result) if isinstance(result, str) else result
    except DatabaseError as exc:
        if isinstance(exc.__cause__, psycopg.errors.InsufficientPrivilege):
            raise PermissionDenied('Active student profile required') from None
        raise
