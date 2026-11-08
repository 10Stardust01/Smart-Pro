"""Student team discovery/creation. The database enforces scope and atomic writes."""
import hashlib
import json
import os
import re
from uuid import UUID

from django.db import DatabaseError, connection
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError


class TeamServiceUnavailable(APIException):
    status_code = 503
    default_detail = 'Student team service is not enabled'


class TeamConflict(APIException):
    status_code = 409
    default_detail = 'Team operation conflicts with existing state'


_IDEMPOTENCY_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')


def _check_enabled():
    if (os.getenv('SMARTPRO_CURRICULUM_API') != 'YES'
            or os.getenv('SMARTPRO_TEAM_API') != 'YES'):
        raise TeamServiceUnavailable()


def _db_result(statement, values):
    try:
        with connection.cursor() as db:
            db.execute(statement, values)
            value = db.fetchone()[0]
            return json.loads(value) if isinstance(value, str) else value
    except DatabaseError as exc:
        cause = exc.__cause__ or exc
        state = getattr(cause, 'sqlstate', None)
        if state == '42501':
            raise PermissionDenied('Eligible student and published offering required') from None
        if state in ('23505', '23P01', '23514'):
            raise TeamConflict() from None
        if state == '22023':
            raise ValidationError('Invalid team operation') from None
        raise


def eligible_teams(actor_id, offering_id, cursor=None):
    _check_enabled()
    try:
        after = UUID(cursor) if cursor is not None else None
    except (TypeError, ValueError, AttributeError):
        raise ValidationError('Invalid team cursor') from None
    return _db_result(
        'SELECT public.smartpro_student_eligible_teams(%s,%s,%s)',
        (actor_id, offering_id, after),
    )


def create_team(actor_id, offering_id, name, idempotency_key):
    _check_enabled()
    if not idempotency_key or not _IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
        raise ValidationError('A valid Idempotency-Key header is required')
    name = name.strip()
    payload = {'offeringId': str(offering_id), 'name': name}
    # Digest only canonical, validated request values; the key is per actor and operation.
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return _db_result(
        'SELECT public.smartpro_create_student_team(%s,%s,%s,%s,%s)',
        (actor_id, offering_id, name, idempotency_key, digest),
    )
