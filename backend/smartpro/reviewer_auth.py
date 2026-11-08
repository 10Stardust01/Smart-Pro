"""Staging-only signed-session reviewer login. Never usable for institutional production."""
import hashlib
import hmac
import json
import os
import re
from html import escape
from uuid import UUID

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.core.cache import cache
from django.db import connection
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST
from rest_framework.authentication import BaseAuthentication, SessionAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .identity import Principal


def active():
    return bool(getattr(settings, "STAGING_REVIEWER_AUTH", False))


def _accounts():
    if not active():
        return {}
    try:
        data = json.loads(os.environ.get("SMARTPRO_REVIEWER_ACCOUNTS", "{}"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid staging reviewer account configuration") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Reviewer accounts must be a mapping")
    accounts = {}
    for alias, entry in data.items():
        if not isinstance(alias, str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,39}", alias):
            raise RuntimeError("Invalid reviewer account alias")
        if not isinstance(entry, dict) or not isinstance(entry.get("passwordHash"), str):
            raise RuntimeError("Missing reviewer password hash")
        if not entry["passwordHash"].startswith(("pbkdf2_sha256$", "argon2$")):
            raise RuntimeError("Use a supported, salted reviewer password hash")
        try:
            actor = str(UUID(entry["actor"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Invalid reviewer account UUID") from exc
        label = entry.get("label", alias)
        if not isinstance(label, str) or len(label) > 100:
            raise RuntimeError("Invalid reviewer label")
        accounts[alias] = {"actor": actor, "passwordHash": entry["passwordHash"], "label": label}
    return accounts


def reviewer_session(request):
    if not active() or not hasattr(request, "session"):
        return None
    alias = request.session.get("smartpro_reviewer")
    actor = request.session.get("smartpro_actor")
    verifier = request.session.get("smartpro_credential_verifier")
    entry = _accounts().get(alias) if isinstance(alias, str) else None
    if not entry or entry["actor"] != actor:
        return None
    current = hashlib.sha256(entry["passwordHash"].encode("utf-8")).hexdigest()
    if not isinstance(verifier, str) or not hmac.compare_digest(current, verifier):
        return None
    return alias, entry


class ReviewerAuthentication(BaseAuthentication):
    """A signed, secure, HttpOnly staging session; roles still come from SQL."""

    def authenticate_header(self, request):
        return "Session"

    def authenticate(self, request):
        identity = reviewer_session(request._request)
        if identity is None:
            return None
        _, entry = identity
        with connection.cursor() as cursor:
            cursor.execute("SELECT public.smartpro_role_choices(%s)", (entry["actor"],))
            choices = cursor.fetchone()[0]
        if isinstance(choices, str):
            choices = json.loads(choices)
        if not choices:
            raise AuthenticationFailed("No active academic responsibility")
        chosen = request.headers.get("X-Smartpro-Role")
        if chosen is not None and chosen not in choices:
            raise AuthenticationFailed("Responsibility is not assigned to this account")
        if chosen is None and len(choices) == 1:
            chosen = choices[0]
        # DRF's API views are csrf_exempt by default: validate CSRF explicitly.
        SessionAuthentication.enforce_csrf(self, request)
        return Principal(entry["actor"], role=chosen, role_choices=tuple(choices)), None


def _page(request, error=""):
    token = __import__("django.middleware.csrf", fromlist=["get_token"]).get_token(request)
    message = f'<p role="alert" class="error">{escape(error)}</p>' if error else ""
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SMART-PRO · Reviewer sign-in</title><link rel="stylesheet" href="/demo-assets/styles.css"></head>
<body><main id="main" class="login-form" style="max-width:36rem;margin:7vh auto">
<section class="login-box"><p class="eyebrow">SMART-PRO · REVIEW ACCESS</p>
<h1>Sign in to your department workspace</h1>
<p>Use your assigned reviewer account. Your existing academic responsibilities apply.</p>
{message}
<form method="post" action="/reviewer/login">
<input type="hidden" name="csrfmiddlewaretoken" value="{escape(token, quote=True)}">
<p><label for="username">Reviewer account</label><input id="username" name="username" autocomplete="username" required maxlength="40"></p>
<p><label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required></p>
<p><button class="primary" type="submit">Sign in</button></p>
</form></section></main></body></html>"""
    response = HttpResponse(body, content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-store"
    response["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self' 'unsafe-inline'; form-action 'self';"
        " frame-ancestors 'none'; base-uri 'none'"
    )
    # Preserve HTTPS CSRF referer checks without leaking referrers cross-origin.
    response["Referrer-Policy"] = "same-origin"
    return response


@never_cache
@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def login(request):
    if not active():
        raise Http404
    if request.method == "GET":
        if reviewer_session(request):
            return redirect("/")
        return _page(request)
    alias = request.POST.get("username", "")
    password = request.POST.get("password", "")
    remote = request.META.get("REMOTE_ADDR", "")
    throttle = "smartpro-review-login:" + hashlib.sha256(remote.encode()).hexdigest()
    attempts = int(cache.get(throttle, 0))
    if attempts >= 8:
        return _page(request, "Too many attempts. Try again later.")
    entry = _accounts().get(alias) if isinstance(alias, str) else None
    # Generic failure message; no account existence disclosure.
    valid = bool(entry and isinstance(password, str) and check_password(password, entry["passwordHash"]))
    if not valid:
        cache.set(throttle, attempts + 1, timeout=900)
        return _page(request, "Invalid reviewer account or password.")
    with connection.cursor() as cursor:
        cursor.execute("SELECT public.smartpro_role_choices(%s)", (entry["actor"],))
        available = cursor.fetchone()[0]
    if not available:
        return _page(request, "This reviewer has no current academic responsibility.")
    cache.delete(throttle)
    request.session.flush()
    request.session["smartpro_reviewer"] = alias
    request.session["smartpro_actor"] = entry["actor"]
    request.session["smartpro_credential_verifier"] = hashlib.sha256(entry["passwordHash"].encode()).hexdigest()
    request.session.set_expiry(8 * 60 * 60)
    return redirect("/")


@require_POST
def logout(request):
    if not active():
        raise Http404
    request.session.flush()
    return redirect("/reviewer/login")
