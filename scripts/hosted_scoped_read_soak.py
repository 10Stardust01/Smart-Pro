"""One-shot real-HTTPS sustained scoped-reads pilot, five distinct *existing roles*.

No writes, no new identities, no logged secrets, no retry/ramp. Student identity
count is ONE: explicitly not distinct-student hosted concurrency acceptance.
"""
import asyncio
import json
import os
import statistics
import sys
import time
from math import ceil
import httpx
from hosted_synthetic_https_writes import Reviewer, require
from hosted_mixed_academic_pilot import wait_for_free_staging_readiness

DEPT = "10000000-0000-4000-8000-000000000001"
OFFERING = "8b40a6e1-419d-43c8-b625-279f82713b02"
ROLES = ("Student","Faculty","Coordinator","HOD","Admin")
WAVES = 60
MAX_REQUESTS = 300
INTERVAL_SECONDS = 2.0
READ_P95_OBJECTIVE_SECONDS = 2.0
STOP_AFTER_SECONDS = 5.0
PATHS = {
 "Student": ("/api/v1/me/projects?page=1", f"/api/v1/documents/departments/{DEPT}?listing=1&page=1"),
 "Faculty": (f"/api/v1/documents/departments/{DEPT}?listing=1&page=1", "/api/v1/workspace"),
 "Coordinator": (f"/api/v1/courses/departments/{DEPT}",f"/api/v1/courses/offerings/{OFFERING}/evaluation-queue?page=1"),
 "HOD": (f"/api/v1/documents/departments/{DEPT}?listing=1&page=1", "/api/v1/workspace"),
 "Admin": ("/api/v1/workspace",f"/api/v1/staff/departments/{DEPT}/setup"),
}

def percentile(xs,p):
    require(bool(xs),"Cannot summarize empty observations")
    x=sorted(xs)
    return x[ceil(p*len(x))-1]

async def check(person,path):
    start=time.perf_counter()
    try:
        answer=await person.get(path)
        duration=time.perf_counter()-start
        return (person.role,path,answer.status_code,duration,answer)
    except (httpx.HTTPError,asyncio.TimeoutError):
        return (person.role,path,None,time.perf_counter()-start,None)

async def run():
    require(os.getenv("SMARTPRO_SCOPED_READ_APPROVAL")=="ONE_SHOT_READ_ONLY_SCOPED_SOAK",
            "One-time read-only gate is required")
    accounts=json.loads(os.getenv("SMARTPRO_HOSTED_TEST_ACCOUNTS") or "{}")
    require(all(isinstance(accounts.get(role),dict) for role in ROLES),
            "Five existing synthetic role account entries required")
    require(MAX_REQUESTS == WAVES*len(ROLES) == 300 and
            INTERVAL_SECONDS >= 2.0 and len(ROLES)==5,
            "Request/concurrency cap changed")
    await wait_for_free_staging_readiness()
    clients=[Reviewer(role,accounts[role]) for role in ROLES]
    try:
        for c in clients:
            await c.login()
        for c in clients:
            for path in PATHS[c.role]:
                role,_,code,delay,answer=await check(c,path)
                require(code==200,f"{role}: scoped route preflight HTTP {code}; no load sent")
                require(answer is not None and
                        answer.headers.get("Content-Type","").startswith("application/json"),
                        f"{role}: scoped route must return JSON")
        print("SOAK_PREFLIGHT_PASS five_verified_roles=true all_scoped_paths=HTTP_200 "
              "one_student_identity=true write_requests=0",flush=True)
        logs=[];start=time.monotonic()
        print("SOAK_BEGIN max_requests=300 waves=60 max_parallel=5 seconds_between_waves=2 "
              "only_existing_synthetic_identities=true academic_writes=0",flush=True)
        for wave in range(WAVES):
            tick=time.monotonic()
            queries=[(c,PATHS[c.role][wave%len(PATHS[c.role])]) for c in clients]
            sample=await asyncio.gather(*(check(c,path) for c,path in queries))
            logs.extend((r,path,code,elapsed) for r,path,code,elapsed,_ in sample)
            bad=[(r,path,code) for r,path,code,_,_ in sample if code!=200]
            if bad:
                raise RuntimeError(f"SOAK_HALTED non-200 replies count={len(bad)}; wave={wave+1}")
            if sum(elapsed>=STOP_AFTER_SECONDS for _,_,_,elapsed,_ in sample)>=2:
                raise RuntimeError(f"SOAK_HALTED two or more signed reads above 5s at wave={wave+1}")
            rest=INTERVAL_SECONDS-(time.monotonic()-tick)
            if rest>0 and wave+1<WAVES:await asyncio.sleep(rest)
        elapsed=time.monotonic()-start
        require(len(logs)==MAX_REQUESTS,"Sustained profile sample incomplete")
        all_times=[elapsed for _,_,_,elapsed in logs]
        p95=percentile(all_times,.95)
        print(f"SOAK_OVERALL requests={len(logs)} duration_s={elapsed:.2f} "
              f"p50_s={statistics.median(all_times):.3f} p95_s={p95:.3f} "
              f"p99_s={percentile(all_times,.99):.3f} max_s={max(all_times):.3f} http_errors=0",flush=True)
        for role in ROLES:
            xs=[d for r,_,_,d in logs if r==role]
            print(f"SOAK_ROLE role={role} requests={len(xs)} p95_s={percentile(xs,.95):.3f}",flush=True)
        for role in ROLES:
            for path in PATHS[role]:
                xs=[d for r,p,_,d in logs if r==role and p==path]
                print(f"SOAK_ENDPOINT role={role} path={path.split('?')[0]} "
                      f"requests={len(xs)} p95_s={percentile(xs,.95):.3f}",flush=True)
        if p95 > READ_P95_OBJECTIVE_SECONDS:
            print(f"SOAK_PERFORMANCE_GAP observed_p95={p95:.3f}s "
                  f"goal={READ_P95_OBJECTIVE_SECONDS}s",flush=True)
            raise RuntimeError("Scoped hosted read p95 outside provisional objective")
        print("PASS_SCOPED_HTTPS_SUSTAINED_READS five_role_scope=true "
              "distinct_student_hosted_writes=false campus_peak_sla=false",flush=True)
    finally:
        for c in clients:await c.close()

def self_test():
    require(percentile([.1,.2,.3,.4],.95)==.4,"p95 nearest rank regression")
    require(MAX_REQUESTS==300 and len(PATHS)==5 and WAVES==60,"Request ceiling violated")
    print("PASS_SCOPED_SOAK_OFFLINE_PREFLIGHT no_network=true",flush=True)

if __name__=="__main__":
    if sys.argv[1:]==["--self-test"]:self_test()
    elif sys.argv[1:]:sys.exit("Only --self-test or approved one-time read-only run")
    else:
        try:asyncio.run(run())
        except (RuntimeError,ValueError,KeyError,httpx.HTTPError,asyncio.TimeoutError) as exc:
            print("SCOPED_SOAK_FAILED "+type(exc).__name__+": "+str(exc)[:150],file=sys.stderr)
            sys.exit(1)
