"""Real-browser frontend smoke tests with completely synthetic API fixtures.

No live identities, credentials, academic records, or remote services are used.
This is an interface regression check, not a substitute for backend security tests.
"""
from __future__ import annotations

import json
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
OUTPUT = ROOT / "browser-artifacts"
ALIAS = "browser-test"
DEPARTMENT_ID = "10000000-0000-4000-8000-000000000001"
ROLES = ("Student", "Faculty", "Coordinator", "HOD", "Admin")


class FrontendHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            target = FRONTEND / "index.html"
        elif path.startswith("/demo-assets/"):
            name = path.removeprefix("/demo-assets/")
            if "/" in name or "\\" in name or not name.endswith((".js", ".css")):
                self.send_error(404)
                return
            target = FRONTEND / name
        else:
            self.send_error(404)
            return
        if not target.is_file():
            self.send_error(404)
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


def workspace(role: str) -> dict:
    is_admin = role in ("HOD", "Admin")
    return {
        "actor": {"id": "00000000-0000-4000-8000-000000000001", "name": f"Synthetic {role}"},
        "roleChoices": [role],
        "activeRole": role,
        "access": {
            "student": role == "Student",
            "faculty": role == "Faculty",
            "admin": is_admin,
            "operations": role == "Admin",
        },
        "department": {
            "id": DEPARTMENT_ID,
            "name": "Synthetic Engineering Department",
            "code": "TEST",
            "offeringId": None,
        },
        "reviews": [],
        "assignedProjects": [],
        "audit": [],
        "faculty": [],
        "enrolled": False,
        "admission": None,
    }


def fixture(role: str, path: str) -> dict:
    if path == "/api/v1/ui/context":
        return {
            "demo": False, "reviewerAuth": True, "courseManagement": True,
            "identities": [ALIAS],
            "people": {ALIAS: f"Synthetic {role}"},
            "responsibilities": {ALIAS: [role]},
            "facultyReferenceDepartmentId": None,
        }
    if path == "/api/v1/workspace":
        return workspace(role)
    if path.startswith("/api/v1/courses/departments/"):
        return {
            "offerings": [], "page": 1, "total": 0,
            "appointmentPage": 1, "appointmentTotal": 0, "faculty": [],
        }
    if path.endswith("/appointment-candidates"):
        return {"records": [], "total": 0, "page": 1}
    if path.endswith("/setup"):
        return {"leadership": None, "intake": None, "requests": []}
    if path == "/api/v1/me/course-notifications":
        return {"tasks": [], "alerts": [], "corrections": []}
    if path.endswith("/offering-management"):
        return {"offerings": [], "page": 1, "total": 0}
    if path.endswith("/policies"):
        return {"policies": []}
    if path.endswith("/results"):
        return {"results": []}
    return {"results": [], "projects": [], "page": 1, "total": 0}


def exercise(browser, origin: str, role: str, mobile: bool = False) -> dict:
    viewport = {"width": 390, "height": 844} if mobile else {"width": 1280, "height": 800}
    context = browser.new_context(viewport=viewport, reduced_motion="reduce")
    script = (
        "sessionStorage.setItem('smartpro.identity', 'browser-test');"
        + "sessionStorage.setItem('smartpro.role.browser-test', " + json.dumps(role) + ");"
    )
    context.add_init_script(script)
    requests = []
    errors = []

    def mock_api(route):
        path = urlsplit(route.request.url).path
        requests.append({"method": route.request.method, "path": path})
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(fixture(role, path)))

    context.route("**/api/v1/**", mock_api)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    label = role.lower() + ("-mobile" if mobile else "-desktop")
    try:
        page.goto(origin, wait_until="domcontentloaded", timeout=20000)
        expect(page.locator(".sidebar")).to_be_visible(timeout=15000)
        expect(page.locator("nav[aria-label='Main navigation'] button").first).to_be_visible()
        expect(page.locator("main#main h1").first).to_be_visible()
        page.screenshot(path=str(OUTPUT / f"{label}-overview.png"), full_page=True)

        target = "enrollment" if role == "Student" else "audit"
        navigation = page.locator(f'.nav button[data-go="{target}"]')
        before = time.monotonic()
        navigation.click()
        expect(navigation).to_have_attribute("aria-current", "page", timeout=4000)
        expect(page.locator("main#main h1").first).to_be_visible(timeout=12000)
        expect(page.locator("main#main")).not_to_have_attribute("aria-busy", "true", timeout=12000)
        elapsed = round((time.monotonic() - before) * 1000)
        assert not errors, f"{role} JavaScript page errors: {errors}"
        page.screenshot(path=str(OUTPUT / f"{label}-navigation.png"), full_page=True)

        overflow = page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 3, f"{label}: {overflow}px horizontal overflow"
        return {
            "role": role, "viewport": "mobile" if mobile else "desktop",
            "navigation_ms_in_ci": elapsed, "mocked_api_calls": len(requests),
            "result": "passed", "live_database_access": False,
        }
    except Exception:
        page.screenshot(path=str(OUTPUT / f"{label}-failure.png"), full_page=True)
        raise
    finally:
        context.close()


def main():
    OUTPUT.mkdir(exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), FrontendHandler)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    origin = f"http://127.0.0.1:{server.server_address[1]}/"
    results = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for role in ROLES:
                    results.append(exercise(browser, origin, role))
                results.append(exercise(browser, origin, "Student", mobile=True))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        (OUTPUT / "results.json").write_text(
            json.dumps({
                "test_type": "synthetic browser frontend smoke",
                "external_services_contacted": False,
                "results": results,
            }, indent=2), encoding="utf-8",
        )
    print(json.dumps(results, indent=2))
    print("Synthetic Chromium checks completed without any academic data or credentials.")


if __name__ == "__main__":
    main()
