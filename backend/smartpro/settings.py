"""Environment-based settings shared by local, test and hosted deployments."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .database_config import database_settings

BASE_DIR = Path(__file__).resolve().parents[2]
SECRET_KEY = os.environ['DJANGO_SECRET_KEY']
DEPLOYMENT = os.getenv('SMARTPRO_DEPLOYMENT', 'development')
if DEPLOYMENT not in {'development', 'test', 'staging', 'production'}:
    raise ImproperlyConfigured('Unsupported SMARTPRO_DEPLOYMENT')
HOSTED = DEPLOYMENT in {'staging', 'production'}
# An optional browser sign-in adapter for verified staging reviewers only.
STAGING_REVIEWER_AUTH = DEPLOYMENT == 'staging' and os.getenv('SMARTPRO_STAGING_REVIEWER_AUTH') == 'YES'
if os.getenv('SMARTPRO_STAGING_REVIEWER_AUTH') == 'YES' and not STAGING_REVIEWER_AUTH:
    raise ImproperlyConfigured('Reviewer sign-in must never run outside staging')
if STAGING_REVIEWER_AUTH and not os.getenv('SMARTPRO_REVIEWER_ACCOUNTS'):
    raise ImproperlyConfigured('A protected reviewer account configuration is required')
DEBUG = not HOSTED and os.getenv('SMARTPRO_DEBUG') == 'YES'
ALLOWED_HOSTS = [v.strip() for v in os.getenv('SMARTPRO_ALLOWED_HOSTS', '' if HOSTED else 'localhost,127.0.0.1,testserver').split(',') if v.strip()]
if HOSTED and (len(SECRET_KEY) < 50 or not ALLOWED_HOSTS or '*' in ALLOWED_HOSTS):
    raise ImproperlyConfigured('Hosted deployments require a strong secret and explicit hosts')
if HOSTED and (os.getenv('SMARTPRO_ENV') == 'demo' or os.getenv('SMARTPRO_DEMO_AUTH') == 'YES'):
    raise ImproperlyConfigured('Synthetic authentication is unavailable in hosted deployments')
SECURE_SSL_REDIRECT = HOSTED
SESSION_COOKIE_SECURE = HOSTED
CSRF_COOKIE_SECURE = HOSTED
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_TRUSTED_ORIGINS = [v.strip() for v in os.getenv('SMARTPRO_CSRF_TRUSTED_ORIGINS', '').split(',') if v.strip()]
if HOSTED and os.getenv('SMARTPRO_TRUST_TLS_PROXY') == 'YES':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_HSTS_SECONDS = int(os.getenv('SMARTPRO_HSTS_SECONDS', '0')) if HOSTED else 0
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 256 * 1024
DATA_UPLOAD_MAX_NUMBER_FILES = 1
IDENTITY_RESOLVER = os.getenv('SMARTPRO_IDENTITY_RESOLVER', '')
if HOSTED and not IDENTITY_RESOLVER and not STAGING_REVIEWER_AUTH:
    raise ImproperlyConfigured('Configure the approved identity resolver before hosted startup')
if STAGING_REVIEWER_AUTH and IDENTITY_RESOLVER:
    raise ImproperlyConfigured('Use exactly one identity adapter in staging')
if HOSTED and os.getenv('SMARTPRO_DOCUMENT_API') == 'YES':
    storage_root = os.getenv('SMARTPRO_DATA_DIR', '')
    if not storage_root or not Path(storage_root).is_absolute():
        raise ImproperlyConfigured('Hosted document storage requires an absolute private data directory')
ROOT_URLCONF = 'smartpro.urls'
WSGI_APPLICATION = 'smartpro.wsgi.application'
INSTALLED_APPS = ['rest_framework', 'smartpro']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.middleware.common.CommonMiddleware']
if STAGING_REVIEWER_AUTH:
    INSTALLED_APPS.append('django.contrib.sessions')
    MIDDLEWARE = ['django.middleware.security.SecurityMiddleware',
                  'django.contrib.sessions.middleware.SessionMiddleware',
                  'django.middleware.csrf.CsrfViewMiddleware',
                  'django.middleware.common.CommonMiddleware']
    # Signed, Secure, HttpOnly reviewer sessions, without new Django DB tables.
    SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'
    SESSION_COOKIE_AGE = 8 * 60 * 60
    SESSION_COOKIE_NAME = 'smartpro_staging_session'
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
DATABASES = {'default': database_settings(os.environ['DATABASE_URL'])}
DATABASES['default']['CONN_MAX_AGE'] = int(os.getenv('SMARTPRO_DB_CONN_MAX_AGE', '0'))
DATABASES['default']['CONN_HEALTH_CHECKS'] = True
if HOSTED:
    LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {'event': {'()': 'smartpro.operational_logging.EventFormatter'}},
        'handlers': {'stderr': {'class': 'logging.StreamHandler', 'formatter': 'event'}},
        'loggers': {'smartpro': {'handlers': ['stderr'], 'level': 'INFO', 'propagate': False}},
    }
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'smartpro.reviewer_auth.ReviewerAuthentication' if STAGING_REVIEWER_AUTH
        else 'smartpro.identity.VerifiedIdentityAuthentication' if IDENTITY_RESOLVER
        else 'smartpro.identity.DemoAuthentication'
    ],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated','smartpro.role_permissions.ActiveRolePermission'],
    'UNAUTHENTICATED_USER': None,
    'EXCEPTION_HANDLER': 'smartpro.views.exception_handler',
}
# No django.contrib.auth/admin/session tables: identity mapping is a separate decision.
# Domain transactions currently own psycopg connections; do not wrap them in
# Django transaction.atomic and assume a shared transaction.
