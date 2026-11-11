"""Read-only signed-in keyboard focus/navigation smoke on actual Render Free staging.

Does NOT claim human screen-reader/assistive-technology conformance or PDF
accessibility. No passwords, student record text, or screenshots are logged.
"""
import json,os
from playwright.sync_api import sync_playwright
from hosted_synthetic_https_writes import BASE
from postdeploy_real_axe_audit import login,must
ROLES=("Student","Faculty","Coordinator","HOD","Admin")

def run():
    must(os.getenv("SMARTPRO_KEYBOARD_APPROVAL")=="VERIFY_READ_ONLY_SIGNED_KEYBOARD_STAGING",
        "Explicit isolated read-only keyboard acceptance required")
    accounts=json.loads(os.getenv("SMARTPRO_HOSTED_TEST_ACCOUNTS") or "{}")
    must(all(accounts.get(r,{}).get("alias") and accounts.get(r,{}).get("password") for r in ROLES),
        "Private synthetic role credentials missing")
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        try:
            for role in ROLES:
                context,page=login(browser,role,accounts[role])
                try:
                    page.reload(wait_until="domcontentloaded",timeout=60000)
                    page.locator("aside.sidebar nav").wait_for(state="visible",timeout=60000)
                    page.locator("a.skip[href='#main']").wait_for(state="attached")
                    page.keyboard.press("Tab")
                    focused=page.evaluate("""() => ({
                      target: document.activeElement?.getAttribute('href'),
                      tag: document.activeElement?.tagName
                    })""")
                    must(focused["tag"]=="A" and focused["target"]=="#main",
                        role+": keyboard Tab did not focus Skip to workspace link")
                    page.keyboard.press("Enter")
                    must(page.evaluate("() => location.hash==='#main'"),
                        role+": keyboard Enter did not activate skip link")
                    page.goto(BASE+"/",wait_until="domcontentloaded",timeout=60000)
                    page.locator("aside.sidebar nav").wait_for(state="visible",timeout=60000)
                    found=False
                    for _ in range(40):
                        page.keyboard.press("Tab")
                        state=page.evaluate("""() => {
                          const a=document.activeElement;
                          const inNav=Boolean(a?.closest?.('aside.sidebar nav'));
                          const st=a?getComputedStyle(a):null;
                          return {inNav,tag:a?.tagName,outline:st?.outlineStyle};
                        }""")
                        if state["inNav"] and state["tag"]=="BUTTON":
                            found=True
                            must(state["outline"]!="none",role+": keyboard focus is visually missing")
                            break
                    must(found,role+": no reachable navigation button by keyboard")
                    page.keyboard.press("Enter")
                    page.locator("aside.sidebar nav").wait_for(state="visible",timeout=40000)
                    print("PASS_KEYBOARD_SIGNED_ROLE "+role+
                          " skip_focus=true skip_activation=true nav_tab_reachable=true nav_enter=true",
                          flush=True)
                finally:
                    context.close()
        finally:
            browser.close()
    print("PASS_HOSTED_BOUNDED_KEYBOARD_FIVE_ROLE_NO_ACADEMIC_WRITES; not screen reader certification",flush=True)
if __name__=="__main__":
    run()
