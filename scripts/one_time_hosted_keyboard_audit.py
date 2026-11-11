"""Bounded five-role hosted keyboard navigation smoke; no writes.

This is NOT a screen-reader audit or complete manual accessibility approval.
"""
import json
import os
import re
from playwright.sync_api import sync_playwright

BASE="https://smartpro-reviewer-25775915.onrender.com"
ROLES=("Student","Faculty","Coordinator","HOD","Admin")

def must(ok,message):
    if not ok: raise AssertionError(message)

def sign_in(browser,role,account):
    ctx=browser.new_context(viewport={"width":1280,"height":900},ignore_https_errors=False)
    page=ctx.new_page()
    page.set_default_timeout(35000)
    page.goto(BASE+"/reviewer/login",wait_until="domcontentloaded",timeout=90000)
    page.locator('input[name="username"]').fill(account["alias"])
    page.locator('input[name="password"]').fill(account["password"])
    page.get_by_role("button",name="Sign in").click()
    page.wait_for_url(BASE+"/",timeout=60000)
    page.locator('button[data-action="login"][data-alias="'+account["alias"]+'"]').click()
    page.wait_for_function("() => !!document.querySelector('button[data-action=choose-role]') || !!document.querySelector('aside.sidebar nav')",timeout=60000)
    choose=page.locator('button[data-action="choose-role"][data-role="'+role+'"]')
    if choose.count(): choose.click()
    elif page.locator("#activeRole").count():page.locator("#activeRole").select_option(role)
    page.locator("aside.sidebar nav").wait_for(state="visible",timeout=60000)
    page.wait_for_function("() => document.querySelector('main#main') && document.querySelector('main#main').getAttribute('aria-busy')==='false'",timeout=60000)
    return ctx,page

def verify_keyboard(page,role):
    must(page.locator('a.skip[href="#main"]').count()==1,role+": skip link missing")
    must(page.locator('main#main').count()==1,role+": main landmark missing")
    must(page.locator('aside.sidebar nav[aria-label="Main navigation"]').count()==1,
         role+": named navigation missing")
    # This targets only the skip-link and keyboard focus mechanics. No forms,
    # navigation actions, hidden controls or academic commands are invoked.
    page.evaluate("() => { if(document.activeElement instanceof HTMLElement) document.activeElement.blur(); document.body.setAttribute('tabindex','-1'); document.body.focus(); }")
    page.keyboard.press("Tab")
    first=page.evaluate("() => ({tag:document.activeElement.tagName,cls:document.activeElement.className,href:document.activeElement.getAttribute('href'),outline:getComputedStyle(document.activeElement).outlineWidth})")
    must(first["tag"]=="A" and "skip" in first["cls"] and first["href"]=="#main",
         role+": keyboard focus cannot reach skip-to-main link first")
    must(float(first["outline"].replace("px","")) >= 3,
         role+": skip link keyboard focus indicator invisible")
    page.keyboard.press("Enter")
    page.wait_for_function("() => location.hash === '#main'",timeout=15000)
    must(page.evaluate("() => document.getElementById('main').contains(document.activeElement) || document.activeElement.id==='main' || document.activeElement===document.body"),
         role+": skip link did not navigate to main content")
    page.keyboard.press("Tab")
    valid=page.evaluate("() => { const a=document.activeElement;return a && a!==document.body && a.getAttribute('aria-hidden')!=='true' && getComputedStyle(a).visibility!=='hidden'; }")
    must(valid,role+": focus does not continue into interactive content")
    print("PASS_HOSTED_KEYBOARD_ROLE "+role+" skip_link=true visible_focus=true main_anchor=true subsequent_tab=true",flush=True)

def main():
    must(os.getenv("SMARTPRO_KEYBOARD_APPROVAL")=="RUN_READONLY_FIVE_ROLE_KEYBOARD","One-time keyboard permission absent")
    accounts=json.loads(os.getenv("SMARTPRO_HOSTED_TEST_ACCOUNTS") or "{}")
    must(all(isinstance(accounts.get(r),dict) and re.fullmatch(r"[a-z][a-z0-9-]{1,39}",accounts[r].get("alias","")) and accounts[r].get("password") for r in ROLES),"Private reviewer roles missing")
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        try:
            for role in ROLES:
                ctx,page=sign_in(browser,role,accounts[role])
                try:verify_keyboard(page,role)
                finally:ctx.close()
        finally:browser.close()
    print("PASS_HOSTED_FIVE_ROLE_KEYBOARD_SMOKE only_keyboard_mechanics=true manual_screenreader_and_PDF_open=true",flush=True)

if __name__=="__main__": main()
