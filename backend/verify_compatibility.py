"""Isolated PostgreSQL adapter probe, not a production migration runner."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartpro.settings')


def schema_inventory():
    """Capture schema definitions; deliberately exclude fixture data and OIDs."""
    import psycopg
    from psycopg.rows import dict_row
    from validate import inventory
    snapshot = inventory()
    with psycopg.connect(os.environ['DATABASE_ADMIN_URL'], autocommit=True, row_factory=dict_row) as db:
        snapshot['columns'] = db.execute("""
            SELECT table_name,column_name,ordinal_position,data_type,udt_name,
                   is_nullable,column_default,character_maximum_length,
                   numeric_precision,numeric_scale,is_identity,identity_generation,
                   is_generated,generation_expression
            FROM information_schema.columns WHERE table_schema='public'
            ORDER BY table_name,ordinal_position
        """).fetchall()
        snapshot['function_definitions'] = db.execute("""
            SELECT p.proname,pg_get_function_identity_arguments(p.oid) AS arguments,
                   pg_get_functiondef(p.oid) AS definition
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='public' AND p.prokind IN ('f','p')
            ORDER BY p.proname,arguments
        """).fetchall()
        snapshot['trigger_definitions'] = db.execute("""
            SELECT c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid) AS definition
            FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND NOT t.tgisinternal
            ORDER BY c.relname,t.tgname
        """).fetchall()
    return snapshot


def main():
    from db_setup import reset_test_database, create_test_login
    reset_test_database()
    create_test_login()
    before = schema_inventory()
    import django
    django.setup()
    from django.core.management import call_command
    from django.db import connection
    from rest_framework.test import APIClient
    from smartpro.models import Project, SubmissionItem

    output = io.StringIO()
    call_command('check', stdout=output)
    mapped = io.StringIO()
    call_command('inspectdb', stdout=mapped)
    (ROOT / 'evidence/django-inspectdb.txt').write_text(mapped.getvalue(), encoding='utf-8')
    checks = {}
    checks['project_uuid_read'] = str(Project.objects.first().id).count('-') == 4
    item = SubmissionItem.objects.first()
    checks['composite_key_roundtrip'] = item is not None and len(item.pk) == 2 and SubmissionItem.objects.get(pk=item.pk).pk == item.pk
    checks['unmanaged_models'] = not Project._meta.managed and not SubmissionItem._meta.managed
    with connection.cursor() as cursor:
        cursor.execute('SELECT current_user, session_user')
        current, session = cursor.fetchone()
    checks['restricted_role'] = current == 'smartpro_runtime' and session == 'smartpro_api'
    checks['catalog_unchanged_after_orm'] = before == schema_inventory()
    connection.close()
    reset_test_database('api_seed.sql')
    api_before = schema_inventory()
    client = APIClient()
    url = '/api/v1/submission-cases/19000000-0000-4000-8000-000000000001'
    os.environ['SMARTPRO_DEMO_AUTH'] = 'YES'
    os.environ['SMARTPRO_ENV'] = 'production'
    checks['production_rejects_demo_header'] = client.get(url, HTTP_X_DEMO_USER='student-a').status_code == 401
    os.environ.pop('SMARTPRO_ENV', None)
    checks['missing_environment_rejects_demo_header'] = client.get(url, HTTP_X_DEMO_USER='student-a').status_code == 401
    os.environ['SMARTPRO_ENV'] = 'demo'
    os.environ.pop('SMARTPRO_DEMO_AUTH', None)
    checks['demo_requires_second_switch_present'] = client.get(url, HTTP_X_DEMO_USER='student-a').status_code == 401
    os.environ['SMARTPRO_DEMO_AUTH'] = 'NO'
    checks['demo_requires_second_switch'] = client.get(url, HTTP_X_DEMO_USER='student-a').status_code == 401
    os.environ['SMARTPRO_DEMO_AUTH'] = 'YES'
    checks['missing_identity_denied'] = client.get(url).status_code == 401
    checks['student_scoped_case_read'] = client.get(url, HTTP_X_DEMO_USER='student-a').status_code == 200
    checks['assigned_faculty_read'] = client.get(url, HTTP_X_DEMO_USER='faculty-a').status_code == 200
    checks['unassigned_faculty_denied'] = client.get(url, HTTP_X_DEMO_USER='faculty-other').status_code == 403
    checks['catalog_unchanged_after_api'] = api_before == schema_inventory()
    result = {'django': django.get_version(), 'checks': checks, 'system_check': output.getvalue(),
              'introspection_sha256': hashlib.sha256(mapped.getvalue().encode()).hexdigest(),
              'status': 'PASSED' if all(checks.values()) else 'FAILED'}
    (ROOT / 'evidence/django-compatibility.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
