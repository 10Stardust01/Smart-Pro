"""Error envelopes must handle DRF's list and mapping validation payloads."""
import os
import unittest


class ExceptionHandlerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartpro.settings')
        os.environ.setdefault('DJANGO_SECRET_KEY', 'synthetic-error-handler-tests-only')
        os.environ.setdefault('DATABASE_URL', 'postgresql://synthetic@localhost/smartpro_test')
        import django
        django.setup()

    def test_list_validation_error_has_400_envelope(self):
        from rest_framework.exceptions import ValidationError
        from smartpro.views import exception_handler
        response = exception_handler(ValidationError('Invalid curriculum cursor'), {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {'detail': {
            'code': 'REQUEST_REJECTED', 'message': 'Invalid curriculum cursor'}})

    def test_field_validation_error_keeps_safe_envelope(self):
        from rest_framework.exceptions import ValidationError
        from smartpro.views import exception_handler
        response = exception_handler(ValidationError({'cursor': ['Invalid UUID']}), {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['detail']['code'], 'REQUEST_REJECTED')

    def test_authentication_error_keeps_existing_contract(self):
        from rest_framework.exceptions import AuthenticationFailed
        from smartpro.views import exception_handler
        response = exception_handler(AuthenticationFailed('Identity required'), {})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data, {'detail': {
            'code': 'AUTHENTICATION_REQUIRED', 'message': 'Identity required'}})
