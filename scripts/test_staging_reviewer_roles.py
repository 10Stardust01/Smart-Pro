"""Five-role staging reviewer sign-in contracts; synthetic local HTTP only.

No real password, connected Render account, paid browser provider or live
academic record is used. A separate fully hosted authenticated acceptance
gate remains open.
"""
import json
import os
import re
from unittest.mock import patch

import django

django.setup()

from django.contrib.auth.hashers import make_password
from django.test import Client

from smartpro import reviewer_auth

ROLE_CASES = {
    "test-student": ("00000000-0000-4000-8000-000000000001", ["Student"], "Student"),
    "test-guide": ("00000000-0000-4000-8000-000000000003", ["Faculty"], "Faculty"),
    "test-coordinator": ("00000000-0000-4000-8000-000000000008", ["Faculty", "Coordinator"], "Coordinator"),
    "test-hod": ("00000000-0000-4000-8000-000000000004", ["HOD"], "HOD"),
    "test-admin": ("00000000-0000-4000-8000-000000000012", ["Admin"], "Admin"),
}


class RoleConnection:
    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, statement, params):
        assert statement.strip() == "SELECT public.smartpro_role_choices(%s)"
        self.roles = {actor: choices for actor, choices, _ in ROLE_CASES.values()}[params[0]]

    def fetchone(self):
        return (self.roles,)


def login(client, alias, password):
    page = client.get("/reviewer/login", secure=True)
    assert page.status_code == 200, page.status_code
    csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode())
    assert csrf, "Login form is missing its CSRF token"
    payload = {"username": alias, "password": password, "csrfmiddlewaretoken": csrf.group(1)}
    return client.post("/reviewer/login", payload, secure=True,
                       HTTP_REFERER="https://smartpro.example.test/reviewer/login")


def main():
    assert reviewer_auth.active(), "Staging reviewer authentication is not enabled"
    # New role aliases are *the only* configured test aliases. All passwords
    # are ephemeral CI-only strings; the actual five Render hashes are never read.
    account_map = {}
    for alias, (actor, _roles, _selected_role) in ROLE_CASES.items():
        password = "ci-only-" + alias + "-temporary-secret"
        account_map[alias] = {
            "actor": actor,
            "passwordHash": make_password(password, hasher="pbkdf2_sha256"),
            "label": "Synthetic " + alias,
        }
    os.environ["SMARTPRO_REVIEWER_ACCOUNTS"] = "{}"
    os.environ["SMARTPRO_REVIEWER_TEST_ACCOUNTS"] = json.dumps(account_map)

    with patch("smartpro.reviewer_auth.connection", new=RoleConnection()), \
         patch("smartpro.demo_views._execute", return_value={"dashboard": "synthetic"}):
        for alias, (_actor, roles, selected_role) in ROLE_CASES.items():
            password = "ci-only-" + alias + "-temporary-secret"
            client = Client(enforce_csrf_checks=True, HTTP_HOST="smartpro.example.test")
            granted = login(client, alias, password)
            assert granted.status_code == 302, (alias, granted.status_code)
            assert granted["Location"] == "/"
            assert "smartpro_staging_session" in client.cookies
            current = client.get("/api/v1/workspace", secure=True,
                                 HTTP_X_SMARTPRO_ROLE=selected_role)
            assert current.status_code == 200, (alias, current.status_code)
            other_role = "Student" if selected_role != "Student" else "Admin"
            denied = client.get("/api/v1/workspace", secure=True,
                                HTTP_X_SMARTPRO_ROLE=other_role)
            assert denied.status_code in (401, 403), (alias, denied.status_code)

            # Changing a password hash or removing an alias must invalidate
            # the session immediately (even before normal 8-hour expiry).
            original = account_map[alias]["passwordHash"]
            account_map[alias]["passwordHash"] = make_password(password + "-rotated")
            os.environ["SMARTPRO_REVIEWER_TEST_ACCOUNTS"] = json.dumps(account_map)
            stale = client.get("/api/v1/workspace", secure=True,
                               HTTP_X_SMARTPRO_ROLE=selected_role)
            assert stale.status_code in (401, 403), (alias, stale.status_code)
            account_map[alias]["passwordHash"] = original
            os.environ["SMARTPRO_REVIEWER_TEST_ACCOUNTS"] = json.dumps(account_map)

        # An unconfigured legacy login alias must not become a valid account.
        legacy = Client(enforce_csrf_checks=True, HTTP_HOST="smartpro.example.test")
        failed = login(legacy, "obsolete-student", "ci-only-old-password")
        assert failed.status_code == 200
        assert b"Invalid reviewer account or password" in failed.content

    print("PASS: five synthetic reviewer roles; denied alternate roles; "
          "rotated hashes invalidate sessions; obsolete alias rejected")
    print("SCOPE: local Django signed-HTTPS client with synthetic SQL role provider; "
          "NOT hosted browser acceptance")


if __name__ == "__main__":
    main()
