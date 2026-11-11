"""One-time read-only axe WCAG automated audit on actual signed reviewer workspaces.

Does not assert screen-reader speech, PDF tagging or institutional conformance.
Logs violation rule/impact/count only, not academic content or credentials.
"""
import json
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

from hosted_synthetic_https_writes import BASE

ROLES = ("Student", "Faculty", "Coordinator", "HOD", "Admin")
AXE_PATH = Path(__file__).resolve().parents[1] / "node_modules" / "axe-core" / "axe.min.js"
APPROVAL = "RUN_READ_ONLY_AXE_SYNTHETIC_STAGING"
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]


def must(ok, msg):
    if not ok:
        raise AssertionError(msg)


def login(browser, role, creds):
    ctx = browser.new_context(ignore_https_errors=False, viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.set_default_timeout(35000)
    page.goto(BASE + "/reviewer/login", wait_until="domcontentloaded", timeout=90000)
    page.locator('input[name="username"]').fill(creds["alias"])
    page.locator('input[name="password"]').fill(creds["password"])
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(BASE + "/", timeout=60000)
    page.locator('button[data-action="login"][data-alias="' + creds["alias"] + '"]').click()
    choice = page.locator('button[data-action="choose-role"][data-role="' + role + '"]')
    if choice.count(): choice.click()
    elif page.locator("#activeRole").count(): page.locator("#activeRole").select_option(role)
    page.locator("aside.sidebar nav").wait_for(state="visible", timeout=60000)
    return ctx, page


def inspect(page, label):
    page.wait_for_function("() => document.querySelector('main#main') && document.querySelector('main#main').getAttribute('aria-busy')==='false'", timeout=60000)
    page.add_script_tag(path=str(AXE_PATH))
    results = page.evaluate("""async tags => {
      const a = await axe.run(document, {runOnly:{type:'tag',values:tags}});
      return a.violations.map(v=>({id:v.id, impact:v.impact, count:v.nodes.length}));
    }""", TAGS)
    summaries = [f"{x['id']}:{x['impact']}:{x['count']}" for x in results]
    print(f"AXE_SCREEN {label}: rules_violated={len(results)} ids_impacts_counts={','.join(summaries) or 'none'}", flush=True)
    return (label, results)


def main():
    must(os.getenv("SMARTPRO_AXE_APPROVAL") == APPROVAL, "One-time read-only audit approval missing")
    must(AXE_PATH.is_file(), "Pinned axe-core package missing")
    accounts = json.loads(os.getenv("SMARTPRO_HOSTED_TEST_ACCOUNTS") or "{}")
    must(all(isinstance(accounts.get(r), dict)
             and re.fullmatch(r"[a-z][a-z0-9-]{1,39}", accounts[r].get("alias", ""))
             and accounts[r].get("password") for r in ROLES),
         "Existing signed synthetic reviewer accounts are required")
    all_issues = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for role in ROLES:
                ctx, page = login(browser, role, accounts[role])
                try:
                    all_issues.append(inspect(page, role + ":overview"))
                    destination = "documents" if role in ("Student", "Faculty") else "courses"
                    nav = page.locator('aside.sidebar nav button[data-go="' + destination + '"]')
                    if nav.count() and nav.is_visible():
                        nav.click()
                        all_issues.append(inspect(page, role + ":" + destination))
                    else:
                        print(f"AXE_SCREEN {role}:{destination} not in authorized role navigation; skipped", flush=True)
                finally:
                    ctx.close()
        finally:
            browser.close()
    n = sum(len(v) for _, v in all_issues)
    severe = [(role, v["id"], v["impact"], v["count"])
              for role, issues in all_issues for v in issues if v.get("impact") in ("critical","serious")]
    print(f"AXE_AUDIT_COMPLETE screens={len(all_issues)} rule_violations={n} severe={len(severe)} "
          "scope=automated_wcag2a_aa_21a_aa_only; no_manual_screen_reader_or_pdf_claim",
          flush=True)
    must(not severe, f"Detected {len(severe)} serious/critical WCAG automation findings; audit remains open")
    print("PASS_AUTOMATED_AXE_SEVERE_GATE; not WCAG certification", flush=True)


if __name__ == "__main__":
    main()
