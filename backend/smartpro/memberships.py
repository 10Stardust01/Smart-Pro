"""Self-service membership commands; each retry owns the entire transaction."""
import hashlib
import json
import os
import time
from uuid import UUID

from django.db import DatabaseError, connection, transaction
from rest_framework.exceptions import ValidationError

from .teams import _check_enabled, _db_result, _IDEMPOTENCY_PATTERN, TeamConflict, TeamServiceUnavailable


def _enabled():
    _check_enabled()
    if os.getenv('SMARTPRO_MEMBERSHIP_API') != 'YES':
        raise TeamServiceUnavailable('Student membership service is not enabled')


def own_memberships(actor_id, cursor=None):
    _enabled()
    try:
        after = UUID(cursor) if cursor is not None else None
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('Invalid membership cursor') from None
    return _db_result('SELECT public.smartpro_student_memberships(%s,%s)', (actor_id, after))


def change_membership(actor_id, action, *, membership_id=None, team_id=None,
                      reason='', idempotency_key=None):
    _enabled()
    if not idempotency_key or not _IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
        raise ValidationError('A valid Idempotency-Key header is required')
    reason = reason.strip()
    payload = {'action': action, 'membershipId': str(membership_id) if membership_id else None,
               'teamId': str(team_id) if team_id else None, 'reason': reason}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    # ATOMIC_REQUESTS is disabled. Never retry a savepoint in an outer transaction
    # whose snapshot/authorization may already be stale.
    attempts = 1 if connection.in_atomic_block else 3
    for attempt in range(attempts):
        try:
            with transaction.atomic():
                return _db_result(
                    'SELECT public.smartpro_student_membership(%s,%s,%s,%s,%s,%s,%s)',
                    (actor_id, action, membership_id, team_id, reason, idempotency_key, digest))
        except DatabaseError as exc:
            state = getattr(exc.__cause__ or exc, 'sqlstate', None)
            if state not in ('40001', '40P01') or connection.in_atomic_block:
                raise
            if attempt == attempts-1:
                raise TeamConflict('Concurrent membership change; retry with the same Idempotency-Key') from None
            time.sleep(0.02 * (attempt+1))
