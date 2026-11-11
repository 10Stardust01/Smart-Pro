"""Read-only signed-in keyboard focus/navigation smoke on actual Render Free staging.

Does NOT claim human screen-reader/assistive-technology conformance or PDF
accessibility. No passwords, student record text, or screenshots are logged.
"""
import json,os
from playwright.sync_api import sync_playwright
BASE="https://smartpro-reviewer-25775915.onrender.com"
def must(ok,msg):
    if not ok: raise AssertionError(msg)

def login(browser,role,creds):
    context=browser.new_context(ignore_https_errors=False,viewport={"width":1280,"height":900})
    page=context.new_page()
    page.set_default_timeout(35000)
    page.goto(BASE+"/reviewer/login",wait_until="domcontentloaded",timeout=90000)
    page.locator('input[name="username"]').fill(creds["alias"])
    page.locator('input[name="password"]').fill(creds["password"])
    page.get_by_role("button",name="Sign in").click()
    page.wait_for_url(BASE+"/",timeout=60000)
    page.locator('button[data-action="login"][data-alias="'+creds["alias"]+'"]').click()
    page.wait_for_function("() => !!document.querySelector('button[data-action=choose-role]') || !!document.querySelector('aside.sidebar nav')",timeout=60000)
    choice=page.locator('button[data-action="choose-role"][data-role="'+role+'"]')
    if choice.count(): choice.click()
    elif page.locator("#activeRole").count(): page.locator("#activeRole").select_option(role)
    page.locator("aside.sidebar nav").wait_for(state="visible",timeout=60000)
    return context,page
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
