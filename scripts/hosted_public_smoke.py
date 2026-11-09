"""Read-only HTTPS public smoke for the deployed SMART-PRO reviewer site.
Never signs in, writes academic data, or accesses reviewer credentials.
"""
import json, os, time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, url):
        return None

OPENER=build_opener(NoRedirect())
BASE=os.getenv('SMARTPRO_HOSTED_SMOKE_URL','https://smartpro-reviewer-25775915.onrender.com').rstrip('/')
if not BASE.startswith('https://'):raise SystemExit('HTTPS is mandatory for hosted smoke')

def get(path):
    for attempt in range(5):
        try:
            try:resp=OPENER.open(Request(BASE+path,headers={'User-Agent':'SMARTPRO-ReadOnly-Smoke/1.0'}),timeout=25)
            except HTTPError as exc:resp=exc
            with resp:
                status=resp.status;body=resp.read(250000).decode('utf-8','replace');headers=dict(resp.headers)
            if status>=500 and attempt<4:time.sleep(5);continue
            return status,body,headers
        except (URLError,TimeoutError):
            if attempt==4:raise
            time.sleep(5)

def main():
    status,body,_=get('/health/live')
    assert status==200 and json.loads(body)['status']=='ok',('liveness',status)
    status,body,_=get('/health/ready')
    assert status==200 and json.loads(body)['status']=='ok',('readiness',status)
    status,_,headers=get('/')
    assert status==302 and headers.get('Location')=='/reviewer/login',('redirect',status,headers.get('Location'))
    status,body,headers=get('/reviewer/login')
    assert status==200 and all(s in body for s in ['csrfmiddlewaretoken','name="username"','name="password"']),('login',status)
    assert 'no-store' in headers.get('Cache-Control',''),('login cache',headers.get('Cache-Control'))
    for path in ['/api/v1/workspace','/api/v1/me/published-corrections']:
        status,_,_=get(path)
        assert status in (401,403),('anonymous API unexpectedly accessible',path,status)
    status,body,_=get('/demo-assets/documents.js')
    assert status==200 and 'guide-stage-evidence-correction' in body,('deployed stage evidence UI',status)
    print('PASS hosted HTTPS: liveness, readiness, reviewer login, CSRF, anonymous scope denial, correction UI asset')
    print('No credentials used, no academic writes performed')

if __name__=='__main__':main()
