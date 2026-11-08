"""Regression checks for database URL transport and application settings."""
import unittest
from smartpro.database_config import database_settings


class DatabaseConfigTests(unittest.TestCase):
    def test_preserves_transport_requirements(self):
        settings = database_settings(
            'postgresql://app:secret@db.example.invalid:5432/smartpro'
            '?sslmode=verify-full&sslrootcert=%2Fcerts%2Fca.pem'
            '&sslcert=%2Fcerts%2Fclient.pem&sslkey=%2Fcerts%2Fclient.key'
            '&connect_timeout=7&application_name=smartpro')
        self.assertEqual(settings['OPTIONS'], {
            'sslmode': 'verify-full', 'sslrootcert': '/certs/ca.pem',
            'sslcert': '/certs/client.pem', 'sslkey': '/certs/client.key',
            'connect_timeout': '7', 'application_name': 'smartpro',
            'options': '-c role=smartpro_runtime -c statement_timeout=10000 -c lock_timeout=5000',
        })
        self.assertEqual(settings['NAME'], 'smartpro')
        self.assertEqual(settings['USER'], 'app')
        self.assertEqual(settings['PASSWORD'], 'secret')

    def test_url_options_cannot_override_application_role_or_timeouts(self):
        settings = database_settings(
            "dbname=smartpro user=app options='-c application_name=probe -c role=other -c statement_timeout=0'")
        self.assertEqual(settings['OPTIONS']['options'],
                         '-c application_name=probe -c role=other -c statement_timeout=0'
                         ' -c role=smartpro_runtime -c statement_timeout=10000 -c lock_timeout=5000')

    def test_optional_connection_fields_can_use_libpq_defaults(self):
        settings = database_settings('dbname=smartpro user=app')
        self.assertEqual(settings['HOST'], '')
        self.assertEqual(settings['PORT'], '')
        self.assertEqual(settings['PASSWORD'], '')
        self.assertEqual(settings['OPTIONS']['connect_timeout'], 5)


if __name__ == '__main__':
    unittest.main()
