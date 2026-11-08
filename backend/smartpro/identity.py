"""Explicit synthetic adapter. Fail closed until production identity is supplied."""
import os
from dataclasses import dataclass
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

DEMO_USERS = {
    'department-admin': '00000000-0000-4000-8000-000000000012',
    'student-a': '00000000-0000-4000-8000-000000000001',
    'student-b': '00000000-0000-4000-8000-000000000002',
    'faculty-a': '00000000-0000-4000-8000-000000000003',
    'faculty-other': '00000000-0000-4000-8000-000000000006',
    'staff-policy': '00000000-0000-4000-8000-000000000004',
    'tech-admin': '00000000-0000-4000-8000-000000000007',
    'coordinator': '00000000-0000-4000-8000-000000000008',
    'student-ece': '00000000-0000-4000-8000-000000000009',
    'student-new': '00000000-0000-4000-8000-000000000010',
    'student-next': '00000000-0000-4000-8000-000000000011',
}
DEVELOPMENT_ALIASES = frozenset({'department-admin', 'student-a', 'faculty-a', 'staff-policy', 'coordinator'})


@dataclass(frozen=True)
class Principal:
    id: str
    is_authenticated: bool = True
    role: str | None = None
    role_choices: tuple = ()


def local_development_enabled():
    from django.conf import settings

    cfg = settings.DATABASES['default']
    return (settings.DEPLOYMENT == 'development' and os.getenv('SMARTPRO_LOCAL_DEVELOPMENT') == 'YES'
            and cfg['NAME'] == 'smartpro_dev' and cfg['HOST'] in ('127.0.0.1', 'localhost'))


class DemoAuthentication(BaseAuthentication):
    def authenticate_header(self, request):
        return 'Demo'

    def authenticate(self, request):
        if os.getenv('SMARTPRO_ENV') != 'demo' or os.getenv('SMARTPRO_DEMO_AUTH') != 'YES':
            raise AuthenticationFailed('Production identity adapter is not configured')
        from django.conf import settings
        cfg=settings.DATABASES['default']
        isolated = cfg['NAME'].startswith('smartpro_test') and cfg['HOST'] in ('127.0.0.1','localhost')
        development = local_development_enabled() and request.META.get('REMOTE_ADDR') in ('127.0.0.1','::1')
        if not isolated and not development:
            raise AuthenticationFailed('Synthetic identity requires an isolated test or explicit loopback development workspace')
        alias = request.headers.get('X-Demo-User')
        actor = DEMO_USERS.get(alias) if isolated or alias in DEVELOPMENT_ALIASES else None
        if not actor:
            raise AuthenticationFailed('Synthetic demo identity required')
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regprocedure('public.smartpro_role_choices(uuid)') IS NOT NULL")
            if not cursor.fetchone()[0]:return Principal(actor),None
            cursor.execute('SELECT public.smartpro_role_choices(%s)',(actor,))
            choices=cursor.fetchone()[0]
            if isinstance(choices,str):
                import json
                choices=json.loads(choices)
        chosen=request.headers.get('X-Smartpro-Role')
        if chosen is not None and chosen not in choices:raise AuthenticationFailed('This responsibility is not assigned to your account')
        if chosen is None and len(choices)==1:chosen=choices[0]
        return Principal(actor,role=chosen,role_choices=tuple(choices)),None


class VerifiedIdentityAuthentication(BaseAuthentication):
    """Resolve a verified request to its institution-mapped application UUID."""

    def authenticate_header(self, request):
        return 'Bearer'

    def authenticate(self, request):
        from uuid import UUID

        from django.conf import settings
        from django.db import connection
        from django.utils.module_loading import import_string

        header = get_authorization_header(request).split()
        if not header or header[0].lower() != b'bearer':
            return None
        if len(header) != 2:
            raise AuthenticationFailed('Invalid bearer authorization')
        resolver = import_string(settings.IDENTITY_RESOLVER)
        resolved = resolver(request)
        if resolved is None:
            return None
        try:
            actor = str(UUID(str(resolved)))
        except ValueError:
            raise AuthenticationFailed('Invalid identity mapping') from None
        # The resolver owns token/session validation, expiry and revocation.
        # Read active academic responsibilities anew on every request.
        with connection.cursor() as cursor:
            cursor.execute('SELECT public.smartpro_role_choices(%s)', (actor,))
            choices = cursor.fetchone()[0]
        if isinstance(choices, str):
            import json
            choices = json.loads(choices)
        if not choices:
            raise AuthenticationFailed('No effective application responsibility')
        chosen = request.headers.get('X-Smartpro-Role')
        if chosen is not None and chosen not in choices:
            raise AuthenticationFailed('This responsibility is not assigned to your account')
        if chosen is None and len(choices) == 1:
            chosen = choices[0]
        return Principal(actor, role=chosen, role_choices=tuple(choices)), None
