"""Strict command shapes with optional human notes; auditing is automatic."""
from rest_framework.exceptions import ValidationError


def command_body(data, fields):
    if not isinstance(data, dict) or set(data) - fields or fields - {'reason'} - set(data):
        raise ValidationError('Exactly the documented command fields are required')
    body = dict(data)
    if 'reason' in fields:
        body.setdefault('reason', '')
        if not isinstance(body['reason'], str) or len(body['reason']) > 500:
            raise ValidationError('Optional note must be a string of at most 500 characters')
    return body
