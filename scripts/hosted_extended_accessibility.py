"""One-time read-only hosted keyboard and WCAG automated acceptance sampling.

Five signed synthetic reviewer roles, ten live screens. No academic commands,
no CSS overrides, no browser trial and no screen-reader-certification claims.
"""
import json
import os
import re
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE="https://smartpro-reviewer-25775915.onrender.com"
ROLES=("Student","Faculty","Coordinator","HOD","Admin")
DEST={"Student":"documents","Faculty":"documents","Coordinator":"courses",
      "HOD":"courses","Admin":"setup"}
AXE=Path("/tmp/smartpro-audit-node/node_modules/axe-core/axe.min.js")
TAGS=["wcag2a","wcag2aa","wcag21a","wcag21aa","wcag22aa"]

def must(ok,msg):
    if not ok:raise AssertionError(msg)

def login(browser,role,account):
    ctx=browser.new_context(viewport={"width":1280,"height":900},ignore_https_errors=False)
    page=ctx.new_page();page.set_default_timeout(35000)
    page.goto(BASE+"/reviewer/login",wait_until="domcontentloaded",timeout=90000)
    page.locator('input[name="username"]').fill(account["alias"])
    page.locator('input[name="password"]').fill(account["password"])
    page.get_by_role("button",name="Sign in").click()
    page.wait_for_url(BASE+"/",timeout=60000)
    page.locator('button[data-action="login"][data-alias="'+account["alias"]+'"]').click()
    page.wait_for_function("() => !!document.querySelector('button[data-action=choose-role]') || !!document.querySelector('aside.sidebar nav')",timeout=60000)
    picker=page.locator('button[data-action="choose-role"][data-role="'+role+'"]')
    if picker.count():picker.click()
    elif page.locator("#activeRole").count():page.locator("#activeRole").select_option(role)
    page.locator("aside.sidebar nav").wait_for(state="visible",timeout=60000)
    return ctx,page

def ready(page):
    page.wait_for_function("() => document.querySelector('main#main') && document.querySelector('main#main').getAttribute('aria-busy')==='false'",timeout=60000)

def scan(page,label):
    ready(page)
    findings=page.evaluate("""() => {
      const visible=e=>{const s=getComputedStyle(e);return s.display!=='none'&&s.visibility!=='hidden'&&!!e.getClientRects().length};
      const ids=[...document.querySelectorAll('[id]')].map(e=>e.id);
      const dupe=[...new Set(ids.filter((x,i)=>ids.indexOf(x)!==i))];
      const fields=[...document.querySelectorAll('input,select,textarea')].filter(e=>e.type!=='hidden'&&!e.disabled&&visible(e));
      const unnamed=fields.filter(e=>{
        if((e.getAttribute('aria-label')||'').trim())return false;
        const refs=(e.getAttribute('aria-labelledby')||'').split(/\\s+/).filter(Boolean);
        if(refs.length&&refs.every(id=>document.getElementById(id)))return false;
        if(e.labels && [...e.labels].some(l=>l.textContent.trim()))return false;
        if((e.title||'').trim())return false;
        return !['button','submit','reset'].includes(e.type);
      }).map(e=>e.tagName.toLowerCase()+':'+(e.name||e.id||'unnamed'));
      return {duplicates:dupe.length,fields:fields.length,unnamed,lang:document.documentElement.lang,
          mains:document.querySelectorAll('main#main').length,
          navs:document.querySelectorAll('nav[aria-label="Main navigation"]').length};
    }""")
    must(findings["duplicates"]==0,label+": duplicate IDs")
    must(findings["lang"] and findings["mains"]==1 and findings["navs"]==1,
         label+": document landmarks/language broken")
    must(not findings["unnamed"],label+": unnamed visible fields: "+str(findings["unnamed"][:8]))
    url=BASE+"/demo-assets/__smartpro_readonly_axe.js"
    page.route("**/demo-assets/__smartpro_readonly_axe.js",
               lambda route:route.fulfill(status=200,content_type="application/javascript",body=AXE.read_bytes()))
    page.add_script_tag(url=url)
    violations=page.evaluate("""async tags=>{
       const r=await axe.run(document,{runOnly:{type:'tag',values:tags}});
       return r.violations.map(x=>({id:x.id,impact:x.impact,count:x.nodes.length}));
    }""",TAGS)
    print(f"A11Y_SCREEN {label} visible_fields={findings['fields']} "
          f"violations={len(violations)} rules={','.join(v['id'] for v in violations)}",flush=True)
    return violations

def keyboard(page,role):
    must(page.locator('a.skip[href="#main"]').count()==1,role+": skip missing")
    page.evaluate("""() => {if(document.activeElement instanceof HTMLElement)document.activeElement.blur();
      document.body.setAttribute('tabindex','-1');document.body.focus();}""")
    page.keyboard.press("Tab")
    f=page.evaluate("""() => {const e=document.activeElement;return {tag:e.tagName,skip:e.classList.contains('skip'),outline:getComputedStyle(e).outlineWidth}}""")
    must(f["tag"]=="A" and f["skip"] and float(f["outline"].replace("px",""))>=3,role+": skip focus not visible")
    page.keyboard.press("Enter")
    page.wait_for_function("() => location.hash==='#main'",timeout=15000)
    targets=set()
    for _ in range(12):
        page.keyboard.press("Tab")
        v=page.evaluate("""() => {const e=document.activeElement;const s=getComputedStyle(e);
          return {tag:e.tagName,id:e.id||'',txt:(e.textContent||'').trim().slice(0,14),
           visible:s.visibility!=='hidden'&&s.display!=='none',hidden:e.getAttribute('aria-hidden')==='true'}}""")
        must(v["visible"] and not v["hidden"],role+": hidden focused control")
        targets.add((v["tag"],v["id"],v["txt"]))
    must(len(targets)>=3,role+": keyboard focus did not traverse controls")
    print(f"A11Y_KEYBOARD {role} distinct_tab_controls={len(targets)}",flush=True)

def dialog(page):
    page.evaluate("""() => {const d=document.getElementById('action-confirmation');
      if(!d||!d.showModal)throw Error('No dialog');
      document.getElementById('confirmation-message').textContent='Accessibility only';
      d.showModal();}""")
    must(page.locator('dialog#action-confirmation[open][aria-labelledby="confirmation-title"]').count()==1,
         "Modal did not open with name")
    must(page.evaluate("() => document.querySelector('#action-confirmation').contains(document.activeElement)"),
         "Modal focus outside dialog")
    page.keyboard.press("Escape")
    must(page.locator('dialog#action-confirmation[open]').count()==0,"Escape did not close dialog")
    print("A11Y_MODAL focus_and_escape=PASS",flush=True)

def run():
    must(os.getenv("SMARTPRO_EXTENDED_A11Y")=="READ_ONLY_EXTENDED_A11Y","Explicit one-time run gate missing")
    must(AXE.is_file(),"Pinned axe-core unavailable")
    accounts=json.loads(os.getenv("SMARTPRO_HOSTED_TEST_ACCOUNTS") or "{}")
    must(all(isinstance(accounts.get(role),dict) and accounts[role].get("password") and
        re.fullmatch(r"[a-z][a-z0-9-]{1,39}",accounts[role].get("alias",""))
        for role in ROLES),"Existing synthetic reviewer accounts missing")
    issues=[];screens=0
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        try:
            for role in ROLES:
                ctx,page=login(browser,role,accounts[role])
                try:
                    issues.extend((role,v) for v in scan(page,role+":overview"));screens+=1
                    keyboard(page,role)
                    if role=="Student":dialog(page)
                    dest=DEST[role]
                    nav=page.locator('aside.sidebar nav button[data-go="'+dest+'"]')
                    must(nav.count()==1 and nav.is_visible(),role+": destination not available: "+dest)
                    nav.click()
                    issues.extend((role,v) for v in scan(page,role+":"+dest));screens+=1
                finally:ctx.close()
        finally:browser.close()
    severe=[x for x in issues if x[1].get("impact") in ("serious","critical")]
    print(f"A11Y_SUMMARY screens={screens} wcag_rule_violations={len(issues)} "
          f"severe={len(severe)} five_role_keyboard=true human_screen_reader_not_tested=true",flush=True)
    must(screens==10 and not severe,"Expanded automated axe audit serious/critical finding")
    print("PASS_HOSTED_EXPANDED_A11Y only_automated_and_keyboard_scope=true",flush=True)

def self_test():
    assert len(ROLES)==5 and len(DEST)==5 and len(TAGS)==5
    print("PASS_A11Y_OFFLINE_PREFLIGHT no_network=true",flush=True)

if __name__=="__main__":
    if sys.argv[1:]==["--self-test"]:self_test()
    elif sys.argv[1:]:sys.exit("Only --self-test or approved one-time run")
    else:run()
