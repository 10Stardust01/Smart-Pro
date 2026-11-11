"""One-time, fail-closed signed graphical reviewer correction acceptance.

One existing synthetic-only project; append V3 through Guide/Coordinator UI.
Never edit the historical academic project, any pinned framework, or stage scores.
No retries after a potentially successful write and no secrets in output.
"""
import json
import os
import re
from decimal import Decimal

from playwright.sync_api import sync_playwright

from hosted_synthetic_https_writes import BASE

DEPT = "10000000-0000-4000-8000-000000000001"
HISTORICAL = "67b0acd3-914f-4063-97db-8b8a75359104"
PROJECT = "27543288-69ee-4836-abfe-171a8191325c"
OFFERING = "246bcfa7-02f0-4350-a0fc-26f8accdc97b"
STUDENT_ID = "00000000-0000-4000-8000-000000000001"
APPROVAL = "RUN_SYNTHETIC_GRAPHICAL_CORRECTION_20261111"


def ensure(ok, message):
    if not ok:
        raise AssertionError(message)


def login(browser, role, account):
    context = browser.new_context(viewport={"width": 1280, "height": 900},
                                  ignore_https_errors=False)
    page = context.new_page()
    page.set_default_timeout(30000)
    page.goto(BASE + "/reviewer/login", wait_until="domcontentloaded", timeout=90000)
    page.locator('input[name="username"]').fill(account["alias"])
    page.locator('input[name="password"]').fill(account["password"])
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(BASE + "/", timeout=45000)
    page.locator('button[data-action="login"][data-alias="' + account["alias"] + '"]').click()
    page.wait_for_function(
        "() => !!document.querySelector('aside.sidebar nav') || !!document.querySelector('button[data-action=choose-role]')",
        timeout=40000)
    chosen = page.locator('button[data-action="choose-role"][data-role="' + role + '"]')
    if chosen.count():
        chosen.click()
    elif page.locator("#activeRole").count():
        page.locator("#activeRole").select_option(role)
    page.locator("aside.sidebar nav").wait_for(state="visible", timeout=40000)
    workspace = context.request.get(BASE + "/api/v1/workspace",
                                    headers={"X-Smartpro-Role": role},
                                    timeout=30000)
    ensure(workspace.status == 200, role + ": workspace not authorized")
    return context, page


def project_records(context, role, project):
    r = context.request.get(
        BASE + "/api/v1/documents/departments/" + DEPT + "?project=" + project,
        headers={"X-Smartpro-Role": role}, timeout=30000)
    ensure(r.status == 200, role + ": project history HTTP " + str(r.status))
    return next((x for x in r.json().get("projects", [])
                 if x.get("id") == project), None)


def versions(record):
    ensure(isinstance(record, dict), "Expected exact authorized project")
    return [(int(row["version"]), str(row["results"].get(STUDENT_ID)))
            for row in record.get("overallResults", [])]


def run():
    ensure(os.environ.get("SMARTPRO_GUI_APPROVAL") == APPROVAL,
           "Explicit bounded one-time approval absent")
    accounts = json.loads(os.environ.get("SMARTPRO_HOSTED_TEST_ACCOUNTS") or "{}")
    for role in ("Faculty", "Coordinator", "Student"):
        entry = accounts.get(role)
        ensure(isinstance(entry, dict)
               and re.fullmatch(r"[a-z][a-z0-9-]{1,39}", entry.get("alias", ""))
               and bool(entry.get("password")), "Private " + role + " reviewer credential missing")
    print("PREFLIGHT one existing synthetic project; no academic policy changes", flush=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        contexts = []
        try:
            sc, student = login(browser, "Student", accounts["Student"])
            contexts.append(sc)
            historical_before = project_records(sc, "Student", HISTORICAL)
            ensure(versions(historical_before) and len(versions(historical_before)) == 1,
                   "Historical project not in expected immutable state")
            synthetic_before = project_records(sc, "Student", PROJECT)
            ensure(versions(synthetic_before) == [(1, "40.00"), (2, "41.00")],
                   "Synthetic acceptance fixture changed; refuse to append or retry")
            cc, coordinator = login(browser, "Coordinator", accounts["Coordinator"])
            contexts.append(cc)
            detail_response = cc.request.get(BASE + "/api/v1/courses/offerings/" + OFFERING + "/details",
                                             headers={"X-Smartpro-Role": "Coordinator"},
                                             timeout=30000)
            ensure(detail_response.status == 200, "Coordinator details unavailable")
            detail = detail_response.json()
            originals = [r for r in detail.get("overallResults", [])
                         if r.get("project_id") == PROJECT]
            ensure([r["version"] for r in sorted(originals, key=lambda x: x["version"])] == [1, 2],
                   "Synthetic overall result versions changed")
            original_sources = originals[0]["sources"]
            ensure(all(r["sources"] == original_sources for r in originals),
                   "Original corrected result changed stage sources")
            plan = next((p for p in detail.get("plans", []) if p["id"] == originals[-1]["plan_id"]), None)
            framework = next((f for f in detail.get("frameworks", [])
                              if plan and f["id"] == plan["framework_id"]), None)
            ensure(framework and framework["configuration"]["allowFinalCorrections"] is False,
                   "Unexpected synthetic academic policy; stop")
            fc, faculty = login(browser, "Faculty", accounts["Faculty"])
            contexts.append(fc)
            faculty.goto(BASE + "/?work=documents&workProject=" + PROJECT,
                         wait_until="domcontentloaded", timeout=60000)
            form = faculty.locator('form[data-form="guide-final-correction"]')
            form.wait_for(state="attached", timeout=50000)
            form.evaluate("(f) => {let d=f.closest('details'); if(d)d.open=true;}")
            form.locator('input[name="marks"]').fill("42.00")
            form.locator('textarea[name="reason"]').fill(
                "Synthetic graphical acceptance: append successor without changing stage evidence")
            with faculty.expect_response(
                    lambda r: r.url.endswith("/commands") and r.request.method == "POST",
                    timeout=45000) as submitted:
                form.locator('button[type="submit"], button.primary').click()
            request = submitted.value
            ensure(request.status == 200,
                   "Guide GUI request HTTP " + str(request.status) + "; do not retry")
            faculty.get_by_text("Awaiting Coordinator decision", exact=False).first.wait_for(timeout=45000)
            ensure(versions(project_records(sc, "Student", PROJECT))
                   == [(1, "40.00"), (2, "41.00")],
                   "Pending Guide request unexpectedly published")
            print("PASS_GUI_GUIDE_REQUEST; existing two result versions still immutable", flush=True)
            coordinator.goto(BASE + "/?offering=" + OFFERING + "&section=results",
                             wait_until="domcontentloaded", timeout=60000)
            decision = coordinator.locator('form[data-form="final-revision-authorization"]')
            decision.wait_for(state="visible", timeout=50000)
            ensure(decision.count() == 1, "Expected exactly one synthetic pending decision")
            decision.locator('select[name="approved"]').select_option("true")
            with coordinator.expect_response(
                    lambda r: r.url.endswith("/commands") and r.request.method == "POST",
                    timeout=45000) as decided:
                decision.locator("button").click()
            ensure(decided.value.status == 200,
                   "Coordinator GUI decision HTTP " + str(decided.value.status) + "; do not retry")
            coordinator.get_by_text("Approved and published", exact=False).first.wait_for(timeout=45000)
            print("PASS_GUI_COORDINATOR_DECISION", flush=True)
            student.goto(BASE + "/?work=documents&workProject=" + PROJECT,
                         wait_until="domcontentloaded", timeout=60000)
            history = student.locator('section:has(h3:text("Overall final result history"))').last
            history.wait_for(state="visible", timeout=45000)
            rendered = history.inner_text()
            ensure(all("Version " + str(n) in rendered for n in (1, 2, 3))
                   and all(score in rendered for score in ("40.00", "41.00", "42.00")),
                   "Student graphical original/successor history missing")
            ensure(versions(project_records(sc, "Student", PROJECT))
                   == [(1, "40.00"), (2, "41.00"), (3, "42.00")],
                   "Student exact persisted result versions missing")
            check = cc.request.get(BASE + "/api/v1/courses/offerings/" + OFFERING + "/details",
                                   headers={"X-Smartpro-Role": "Coordinator"},
                                   timeout=30000)
            ensure(check.status == 200, "Coordinator post-test details unavailable")
            after = sorted([r for r in check.json().get("overallResults", [])
                            if r.get("project_id") == PROJECT], key=lambda x: x["version"])
            ensure([r["version"] for r in after] == [1, 2, 3]
                   and after[2]["supersedes_id"] == after[1]["id"]
                   and all(r["sources"] == original_sources for r in after),
                   "Published stage evidence or result ancestry mutated")
            ensure(versions(project_records(sc, "Student", HISTORICAL)) == versions(historical_before),
                   "Pre-existing historical published result changed")
            print("PASS_HOSTED_GRAPHICAL_DIRECT_OVERALL_CORRECTION "
                  "synthetic_versions=1,2,3 old_marks=40.00,41.00,42.00 "
                  "stage_sources_unchanged=true original_historical_project_unchanged=true",
                  flush=True)
        finally:
            for context in contexts:
                context.close()
            browser.close()


if __name__ == "__main__":
    run()
