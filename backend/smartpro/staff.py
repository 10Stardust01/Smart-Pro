"""Departmental staff commands. Authority and transaction integrity live in SQL."""
import json
import os
import time
from uuid import UUID

from django.db import DatabaseError, connection, transaction
from psycopg.types.json import Jsonb
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from .teams import _IDEMPOTENCY_PATTERN


class StaffUnavailable(APIException):
    status_code = 503
    default_detail = 'Department staff service is not enabled'


class StaffConflict(APIException):
    status_code = 409
    default_detail = 'Staff request conflicts with current policy or protected project evidence'


def _enabled():
    if os.getenv('SMARTPRO_STAFF_API') != 'YES':
        raise StaffUnavailable()


def _execute(sql, values):
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, values)
            value = cursor.fetchone()[0]
            return json.loads(value) if isinstance(value, str) else value
    except DatabaseError as exc:
        cause = exc.__cause__ or exc
        state = getattr(cause, 'sqlstate', None)
        if state == '42501':
            raise PermissionDenied('Effective department staff permission required') from None
        if state == '23514':
            message = getattr(getattr(cause, 'diag', None), 'message_primary', None)
            if message in (
                'Appoint a replacement or pause the offering before removing its last coordinator',
                'Appoint a course coordinator before activation',
            ):
                raise StaffConflict(message) from None
        if state in ('23505','23514','23503'):
            raise StaffConflict() from None
        if state and state.startswith('22'):
            raise ValidationError('Invalid staff command') from None
        raise


def staff_command(actor_id, department_id, action, target_id, payload, key):
    _enabled()
    return staff_sql_command('SELECT public.smartpro_staff_command(%s,%s,%s,%s,%s,%s)',
                             actor_id, department_id, action, payload, key, target_id=target_id)


def staff_sql_command(sql, actor_id, department_id, action, payload, key, *, target_id=None):
    """Reuse whole-transaction retry/error semantics for academic commands."""
    if not key or not _IDEMPOTENCY_PATTERN.fullmatch(key):
        raise ValidationError('A valid Idempotency-Key header is required')
    attempts = 1 if connection.in_atomic_block else 3
    for attempt in range(attempts):
        try:
            with transaction.atomic():
                values = (actor_id, department_id, action, Jsonb(payload), key)
                if target_id is not None:
                    values = (actor_id, department_id, action, target_id, Jsonb(payload), key)
                return _execute(sql, values)
        except DatabaseError as exc:
            state = getattr(exc.__cause__ or exc, 'sqlstate', None)
            if state not in ('40001','40P01') or connection.in_atomic_block:
                raise
            if attempt == attempts-1:
                raise StaffConflict('Concurrent staff update; retry with the same Idempotency-Key') from None
            time.sleep(0.02 * (attempt+1))


def staff_read(actor_id, department_id, *, projects=False, cursor=None, acting_role=None):
    _enabled()
    try:
        after = UUID(cursor) if cursor is not None else None
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('Invalid staff cursor') from None
    if os.getenv('SMARTPRO_COURSE_API')=='YES':
        return _execute('SELECT public.smartpro_course_staff_read(%s,%s,%s,%s,%s)',(actor_id,department_id,projects,after,acting_role))
    sql = ('SELECT public.smartpro_staff_projects(%s,%s,%s)' if projects
           else 'SELECT public.smartpro_staff_policies(%s,%s,%s)')
    return _execute(sql, (actor_id, department_id, after))
