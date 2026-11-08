"""Student project reads and transactional registration; SQL owns authorization."""
import hashlib
import json
import os
import time
from uuid import UUID

from django.db import DatabaseError, connection, transaction
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from .teams import _IDEMPOTENCY_PATTERN


class ProjectServiceUnavailable(APIException):
    status_code = 503
    default_detail = 'Student project service is not enabled'


class ProjectConflict(APIException):
    status_code = 409
    default_detail = 'Your proposal conflicts with a recent change. Refresh the offering and team, then retry with the same request key.'


def _enabled():
    if os.getenv('SMARTPRO_CURRICULUM_API') != 'YES' or os.getenv('SMARTPRO_PROJECT_API') != 'YES':
        raise ProjectServiceUnavailable()


def _execute(statement, values):
    try:
        with connection.cursor() as cursor:
            cursor.execute(statement, values)
            result = cursor.fetchone()[0]
            return json.loads(result) if isinstance(result, str) else result
    except DatabaseError as exc:
        state = getattr(exc.__cause__ or exc, 'sqlstate', None)
        if state == '42501':
            raise PermissionDenied('Current team membership and applicable registration policy required') from None
        if state in ('23505', '23514', '23P01'):
            raise ProjectConflict() from None
        if state == '22023':
            raise ValidationError('Invalid project registration') from None
        raise


def register_project(actor_id, team_id, project_type, project_code, title, idempotency_key, *, offering_id=None, description=None):
    _enabled()
    if not idempotency_key or not _IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
        raise ValidationError('A valid Idempotency-Key header is required')
    payload = {'teamId': str(team_id), 'projectType': project_type,
               'projectCode': project_code.strip() if project_code is not None else None, 'title': title.strip()}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    attempts = 1 if connection.in_atomic_block else 3
    for attempt in range(attempts):
        try:
            with transaction.atomic():
                if offering_id is not None and description is not None:
                    return _execute('SELECT public.smartpro_register_proposal(%s,%s,%s,%s,%s,%s)',(actor_id,offering_id,team_id,payload['title'],description,idempotency_key))
                if offering_id is not None:
                    return _execute('SELECT public.smartpro_register_proposal(%s,%s,%s,%s,%s)',(actor_id,offering_id,team_id,payload['title'],idempotency_key))
                return _execute('SELECT public.smartpro_register_student_project(%s,%s,%s,%s,%s,%s,%s)',
                                (actor_id, team_id, project_type, payload['projectCode'], payload['title'],
                                 idempotency_key, digest))
        except DatabaseError as exc:
            state = getattr(exc.__cause__ or exc, 'sqlstate', None)
            if state not in ('40001', '40P01') or connection.in_atomic_block:
                raise
            if attempt == attempts-1:
                raise ProjectConflict('Concurrent registration change; retry with the same Idempotency-Key') from None
            time.sleep(0.02 * (attempt+1))


def student_projects(actor_id, cursor=None, offering_id=None):
    _enabled()
    try:
        after = UUID(cursor) if cursor is not None else None
        offering = UUID(offering_id) if offering_id is not None else None
    except (TypeError, ValueError, AttributeError):
        raise ValidationError('Invalid project cursor') from None
    if offering is not None:
        return _execute('SELECT public.smartpro_student_projects_for_offering(%s,%s,%s)',(actor_id,offering,after))
    return _execute('SELECT public.smartpro_student_projects(%s,%s)', (actor_id, after))
