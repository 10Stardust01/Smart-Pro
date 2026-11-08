"""WSGI entry point for a reviewed application server."""
import os

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.wsgi import get_wsgi_application
from django.utils.module_loading import import_string

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartpro.settings')
application = get_wsgi_application()
if settings.IDENTITY_RESOLVER and not callable(import_string(settings.IDENTITY_RESOLVER)):
    raise ImproperlyConfigured('The identity resolver must be callable')
