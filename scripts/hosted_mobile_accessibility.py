"""Read-only mobile reflow, accessible login validation and browser control audit.

Runs on the actual signed-in HTTPS five-role reviewer with no academic writes.
Automated browser semantics cannot certify human screen-reader announcement.
"""
import asyncio
import json
import os
import re
import sys
from playwright.sync_api import sync_playwright
from hosted_extended_accessibility import BASE, DEST, ROLES, login, ready, must
from hosted_mixed_academic_pilot import wait_for_free_staging_readiness

MOBILE_WIDTH=320
HEIGHT=680
MAX_OVERFLOW_PX=16

def mobile_screen(page,role,where):
    ready(page)
    result=page.evaluate("""() => {
        const de=document.documentElement;
        const width=Math.round(de.clientWidth);
        const max=Math.round(Math.max(de.scrollWidth,document.body.scrollWidth));
        const main=document.querySelector('#main');
        const nav=document.querySelector('aside.sidebar nav');
        const links=[...document.querySelectorAll('input,textarea,select')].filter(e=>e.type!=='hidden'&&e.getClientRects().length>0);
        return {width,max,nav:!!nav,main:!!main,
          unnamed:links.filter(e=>!e.labels?.length&&!e.getAttribute('aria-label')&&
              !e.getAttribute('aria-labelledby')&&!e.title).length};
    }""")
    print(f"REFLOW_SCREEN role={role} area={where} width={result['width']} "
          f"document_scroll_width={result['max']} visible_unnamed_fields={result['unnamed']}",flush=True)
    must(result["width"]==MOBILE_WIDTH,role+": unexpected CSS viewport")
    must(result["nav"] and result["main"] and result["unnamed"]==0,
         role+": missing mobile navigation/main or unlabeled fields")
    must(result["max"] <= result["width"]+MAX_OVERFLOW_PX,
         role+":"+where+": global horizontal overflow exceeds 16px")

def login_form_validation(browser):
    ctx=browser.new_context(viewport={"width":MOBILE_WIDTH,"height":HEIGHT})
    try:
        page=ctx.new_page()
        page.goto(BASE+"/reviewer/login",wait_until="domcontentloaded",timeout=90000)
        form=page.locator("form[action='/reviewer/login']")
        must(form.count()==1,"Reviewer login form missing")
        # HTML native required validation: no login POST ever sent.
        page.get_by_role("button",name="Sign in").click()
        must(page.evaluate("() => document.activeElement?.id==='username'"),
             "Empty required username did not receive validation focus")
        must(not page.locator("#username").evaluate("(el) => el.validity.valid"),
             "Empty login username should be invalid")
        page.locator("#username").fill("test-synthetic")
        page.get_by_role("button",name="Sign in").click()
        must(page.evaluate("() => document.activeElement?.id==='password'"),
             "Empty required password did not receive validation focus")
        must(not page.locator("#password").evaluate("(el) => el.validity.valid"),
             "Empty login password should be invalid")
        print("MOBILE_LOGIN_NATIVE_VALIDATION required_focus=username,password no_post=true",flush=True)
    finally:ctx.close()

def run():
    must(os.getenv("SMARTPRO_MOBILE_ACCESSIBILITY")=="ONE_SHOT_MOBILE_AUDIT",
         "Mobile accessibility gate absent")
    accounts=json.loads(os.getenv("SMARTPRO_HOSTED_TEST_ACCOUNTS") or "{}")
    must(all(isinstance(accounts.get(r),dict) and
             re.fullmatch(r"[a-z][a-z0-9-]{1,39}",accounts[r].get("alias",""))
             for r in ROLES),"Five existing test accounts needed")
    # Render Free can return a warming splash page before /reviewer/login exists.
    # Read-only readiness probes are outside mobile accessibility measurements.
    asyncio.run(wait_for_free_staging_readiness())
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        try:
            login_form_validation(browser)
            screens=0
            for role in ROLES:
                ctx,page=login(browser,role,accounts[role])
                try:
                    page.set_viewport_size({"width":MOBILE_WIDTH,"height":HEIGHT})
                    mobile_screen(page,role,"overview");screens+=1
                    # Native Tab navigation remains keyboard-addressable at narrow width.
                    first=page.locator("aside.sidebar nav button[data-go]").first
                    must(first.count()==1 and first.is_visible(),
                         role+": navigation cannot be focused at mobile width")
                    first.focus()
                    must(first.evaluate("(e) => e===document.activeElement"),
                         role+": mobile navigation focus inaccessible")
                    target=DEST[role]
                    nav=page.locator(f'aside.sidebar nav button[data-go="{target}"]')
                    must(nav.count()==1,role+": expected destination not available")
                    nav.click()
                    mobile_screen(page,role,target);screens+=1
                finally:ctx.close()
        finally:browser.close()
    must(screens==10,"Expected 10 mobile role screens")
    print("PASS_HOSTED_MOBILE_REFLOW screens=10 roles=5 "
          "native_form_validation=true human_screen_reader_not_tested=true",flush=True)

def self_test():
    assert MOBILE_WIDTH==320 and MAX_OVERFLOW_PX==16 and len(ROLES)==5
    print("PASS_MOBILE_A11Y_OFFLINE_PREFLIGHT no_network=true",flush=True)

if __name__=="__main__":
    if sys.argv[1:]==["--self-test"]:self_test()
    elif sys.argv[1:]:sys.exit("Only --self-test or explicitly approved run")
    else:run()
