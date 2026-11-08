"""Convert libpq connection settings without dropping transport requirements."""
from psycopg.conninfo import conninfo_to_dict


def database_settings(database_url):
    cfg = conninfo_to_dict(database_url)
    settings = {'ENGINE': 'django.db.backends.postgresql'}
    for source, target in [('dbname', 'NAME'), ('user', 'USER'),
                           ('password', 'PASSWORD'), ('host', 'HOST'), ('port', 'PORT')]:
        settings[target] = cfg.pop(source, '')
    # Retain TLS certificates, verification mode, connection timeout and other
    # libpq parameters. Application role/timeouts take precedence over URL options.
    original_options = cfg.pop('options', '')
    cfg.setdefault('connect_timeout', 5)
    cfg['options'] = (original_options + ' -c role=smartpro_runtime'
                      ' -c statement_timeout=10000 -c lock_timeout=5000').strip()
    settings['OPTIONS'] = cfg
    return settings
