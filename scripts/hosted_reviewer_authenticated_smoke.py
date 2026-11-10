"""Manual free-only actual Render signed-session smoke; read-only and no credentials in logs."""
import json
import os
import re
from playwright.sync_api import sync_playwright

BASE = "https://smartpro-reviewer-25775915.onrender.com"
ROLES = ("Student", "Faculty", "Coordinator", "HOD", "Admin")


def accounts_from_environment():
    raw = os.environ.get("SMARTPRO_HOSTED_TEST_ACCOUNTS")
    if not raw:
        raise RuntimeError("Private SMARTPRO_HOSTED_TEST_ACCOUNTS secret required")
    accounts = json.loads(raw)
    if not isinstance(accounts, dict) or set(accounts) != set(ROLES):
        raise ValueError("Exactly five reviewer roles required")
    for role in ROLES:
        entry = accounts[role]
        if not isinstance(entry, dict) or set(entry) != {"alias", "password"}:
            raise ValueError(f"{role}: alias/password configuration required")
        if not isinstance(entry["alias"], str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,39}", entry["alias"]):
            raise ValueError(f"{role}: invalid alias")
        if not isinstance(entry["password"], str) or not entry["password"]:
            raise ValueError(f"{role}: password missing")
    return accounts


def check_role(browser, role, entry):
    context = browser.new_context(ignore_https_errors=False)
    try:
        page = context.new_page()
        page.goto(BASE + "/reviewer/login", wait_until="domcontentloaded", timeout=30000)
        if page.locator('input[name="username"]').count() != 1 or page.locator('input[name="password"]').count() != 1:
            raise AssertionError(f"{role}: login form unavailable")
        page.locator('input[name="username"]').fill(entry["alias"])
        page.locator('input[name="password"]').fill(entry["password"])
        page.get_by_role("button", name="Sign in").click(timeout=30000)
        page.wait_for_url(BASE + "/", timeout=30000)
        cookies = [c for c in context.cookies() if c.get("name") == "smartpro_staging_session"]
        if len(cookies) != 1 or not cookies[0].get("httpOnly") or not cookies[0].get("secure"):
            raise AssertionError(f"{role}: secure session absent")
        response = context.request.get(BASE + "/api/v1/workspace", headers={"X-Smartpro-Role": role}, timeout=30000)
        if response.status != 200:
            raise AssertionError(f"{role}: workspace HTTP {response.status}")
        denied_role = "Admin" if role == "Student" else "Student"
        denied = context.request.get(BASE + "/api/v1/workspace", headers={"X-Smartpro-Role": denied_role}, timeout=30000)
        if denied.status not in (401, 403):
            raise AssertionError(f"{role}: role boundary HTTP {denied.status}")
        print(f"PASS {role}: HTTPS login, secure cookie, workspace access and role denial")
    finally:
        context.close()


def main():
    accounts = accounts_from_environment()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for role in ROLES:
                check_role(browser, role, accounts[role])
        finally:
            browser.close()
    print("PASS_HOSTED_AUTHENTICATED_READ_ONLY; not academic write capacity")


if __name__ == "__main__":
    main()
