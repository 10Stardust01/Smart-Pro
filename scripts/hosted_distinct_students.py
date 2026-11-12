"""One controlled genuine distinct-Student hosted staging HTTPS acceptance.

Eight signed synthetic Student actor UUIDs + existing Coordinator (and Faculty).
Generates eight new audit-labeled projects/teams, verifies private PDF bytes,
eight independent submissions, then 480 bounded, paced read probes over ~2m.
No academic history edits, no retry, no paid resources. Manual authorization only.
"""
import asyncio
import hashlib
import json
import os
import sys
import time
import uuid
from math import ceil
import httpx

from hosted_synthetic_https_writes import Reviewer, case_from, json_success, pdf_bytes, require
from hosted_mixed_academic_pilot import wait_for_free_staging_readiness

DEPT="10000000-0000-4000-8000-000000000001"
OFFERING="8b40a6e1-419d-43c8-b625-279f82713b02"
GUIDE="00000000-0000-4000-8000-000000000003"
COUNT=8
WAVES=60
SPACING_S=2.0
MAX_READS=480
UPLOAD_KIB=128
MAX_UPLOAD_P95_S=5.0
MAX_READ_P95_S=2.0

def p95(xs):
    require(bool(xs),"No latency samples")
    vals=sorted(xs)
    return vals[ceil(len(vals)*.95)-1]

def expected_actor(n):
    return str(uuid.uuid5(uuid.NAMESPACE_DNS,f"smartpro-load-test-{n}"))

def validate_config():
    require(os.getenv("SMARTPRO_DISTINCT_LOAD_APPROVAL")=="RUN_DISTINCT_SYNTHETIC_STUDENTS_ONCE",
            "Manual-only approval phrase required")
    secret=json.loads(os.getenv("SMARTPRO_HOSTED_DISTINCT_STUDENTS") or "{}")
    students=secret.get("students")
    require(type(students) is list and len(students)==COUNT,"Exactly eight private student accounts required")
    aliases=set()
    for n,item in enumerate(students,1):
        require(isinstance(item,dict) and set(item)=={"alias","actor","password"},
                "Account fields must be alias,actor,password")
        require(item["alias"]==f"test-load-{n:02d}" and
                item["actor"]==expected_actor(n) and
                isinstance(item["password"],str) and len(item["password"])>=24,
                f"Distinct Student {n} identity configuration invalid")
        aliases.add(item["alias"])
    require(len(aliases)==COUNT and len({x["actor"] for x in students})==COUNT,
            "Student aliases or actors are not distinct")
    common=json.loads(os.getenv("SMARTPRO_HOSTED_TEST_ACCOUNTS") or "{}")
    require(isinstance(common.get("Coordinator"),dict) and
            isinstance(common["Coordinator"].get("password"),str),
            "Existing authorized synthetic Coordinator credentials required")
    return students,common

async def simultaneous(jobs):
    gate=asyncio.Event()
    async def worker(fn):
        await gate.wait()
        now=time.monotonic()
        response=await fn()
        return response,time.monotonic()-now
    tasks=[asyncio.create_task(worker(j)) for j in jobs]
    gate.set()
    return await asyncio.gather(*tasks)

async def run():
    students,common=validate_config()
    await wait_for_free_staging_readiness()
    users=[Reviewer("Student",x) for x in students]
    coordinator=Reviewer("Coordinator",common["Coordinator"])
    nonce=uuid.uuid4().hex[:10]
    created=[]
    try:
        # Avoid hammering password hash login: authenticate 9 identities sequentially.
        for n,person in enumerate(users,1):
            details=await person.login()
            require(details.get("actor",{}).get("id")==students[n-1]["actor"],
                    f"Distinct Student {n}: session bound to wrong underlying actor")
            require(details.get("access",{}).get("student") is True,
                    f"Distinct Student {n}: effective Student scope missing")
        await coordinator.login()
        print("DISTINCT_LOGIN_PASS students=8 independent_actor_uuids=true "
              "coordinator_existing=true no_credentials_logged=true",flush=True)
        for n,user in enumerate(users,1):
            offered=json_success(await user.get("/api/v1/me/curriculum-offerings"),
                                 "Student eligible offering")
            require(any(item.get("id")==OFFERING for item in offered.get("results",[])),
                    "Chosen synthetic offering is not visible to a new student")
            team=json_success(await user.post("/api/v1/teams",
                {"offeringId":OFFERING,"name":f"Synthetic hosted load team {nonce} {n:02d}"},
                key=f"distinct-{nonce}-{n}-team"),"Create isolated synthetic team",(201,))
            tid=str(uuid.UUID(team["id"]))
            project=json_success(await user.post("/api/v1/projects",
                {"offeringId":OFFERING,"teamId":tid,
                 "title":f"[SYNTHETIC-DISTINCT-LOAD] {nonce}-{n:02d}",
                 "description":"Staging-only independent student HTTPS capacity evidence"},
                key=f"distinct-{nonce}-{n}-project"),"Register isolated synthetic project",(201,))
            pid=str(uuid.UUID(project["id"]))
            require(project.get("teamId")==tid,"Student project not bound to owned synthetic team")
            json_success(await coordinator.post(
                f"/api/v1/staff/departments/{DEPT}/projects/{pid}/guide",
                {"facultyId":GUIDE,"expectedGuideId":None},
                key=f"distinct-{nonce}-{n}-guide"),"Assign guide for synthetic evidence")
            created.append((user,pid))
        require(len(created)==COUNT and len({pid for _,pid in created})==COUNT,
                "Not all distinct Student projects were registered")
        print(f"DISTINCT_FIXTURE_PASS projects={len(created)} each_owned_by_separate_student=true "
              f"marker={nonce} retained_for_audit=true",flush=True)

        pdfs=[pdf_bytes(f"SYNTHETIC DISTINCT {nonce} FILE {n}",padding_bytes=UPLOAD_KIB*1024-1024)
              for n in range(1,COUNT+1)]
        pending=await simultaneous([
            (lambda user=u,pid=pid,idx=n: user.post(
                f"/api/v1/documents/departments/{DEPT}/projects/{pid}/uploads",
                None,key=f"distinct-{nonce}-{idx}-upload",
                files={"file":(f"distinct-{nonce}-{idx}.pdf",pdfs[idx-1],"application/pdf")}))
            for n,(u,pid) in enumerate(created,1)])
        versions=[]
        for n,(response,delay) in enumerate(pending,1):
            version=json_success(response,"Independent Student PDF upload")["documentVersionId"]
            versions.append(str(uuid.UUID(version)))
        require(len(set(versions))==COUNT,"Eight uploaded document version IDs not unique")
        upload_p95=p95([elapsed for _,elapsed in pending])
        print(f"DISTINCT_UPLOADS total={COUNT} p95_s={upload_p95:.3f} "
              "all_different_student_actors=true",flush=True)
        for (user,_),version,pdf in zip(created,versions,pdfs):
            reply=await user.get(f"/api/v1/document-versions/{version}/content?download=1")
            require(reply.status_code==200 and hashlib.sha256(reply.content).digest()==
                    hashlib.sha256(pdf).digest(),
                    "Original private PDF retrieval did not match independent upload")
        print("DISTINCT_PRIVATE_PDFS_SHA256_PASS files=8",flush=True)

        cases=[]
        for user,pid in created:
            scoped=json_success(await user.get(f"/api/v1/documents/departments/{DEPT}?project={pid}"),
                                "Current own project evidence case")
            case=case_from(scoped,pid)
            require(case is not None and type(case.get("version")) is int,
                    "Versioned document case not available")
            cases.append(case["version"])
        posted=await simultaneous([
            (lambda user=u,pid=pid,vid=versions[n],rev=cases[n],idx=n:
                user.post(f"/api/v1/documents/departments/{DEPT}",
                {"action":"SUBMIT","projectId":pid,"documentVersionId":vid,
                 "expectedCaseVersion":rev},
                key=f"distinct-{nonce}-{idx}-submit"))
            for n,(u,pid) in enumerate(created)])
        for response,delay in posted:
            json_success(response,"Independent Student submission")
        submit_p95=p95([elapsed for _,elapsed in posted])
        print(f"DISTINCT_SUBMISSIONS total={COUNT} p95_s={submit_p95:.3f} "
              "all_separate_projects=true",flush=True)
        for (user,pid),vid in zip(created,versions):
            scoped=json_success(await user.get(f"/api/v1/documents/departments/{DEPT}?project={pid}"),
                                "Post-submit scoped version history")
            case=case_from(scoped,pid)
            require(case and any(x.get("versionId")==vid for x in case.get("attempts",[])),
                    "Submitted own document version absent from history")
        print("DISTINCT_HISTORY_PASS checked_student_histories=8 "
              "no_existing_project_modified=true",flush=True)

        read_delays=[]
        for wave in range(WAVES):
            started=time.monotonic()
            paths=["/api/v1/me/projects?page=1" if wave%2==0
                   else f"/api/v1/documents/departments/{DEPT}?listing=1&page=1"]*COUNT
            replies=await simultaneous([
                (lambda u=user,path=paths[n]:u.get(path)) for n,(user,_) in enumerate(created)])
            if any(res.status_code!=200 for res,_ in replies):
                raise RuntimeError(f"DISTINCT_READ_STOP unexpected signed read wave={wave+1}")
            delays=[duration for _,duration in replies]
            if sum(duration>5 for duration in delays)>=2:
                raise RuntimeError(f"DISTINCT_READ_STOP multiple reads >5s wave={wave+1}")
            read_delays+=delays
            remaining=SPACING_S-(time.monotonic()-started)
            if remaining>0 and wave+1<WAVES:
                await asyncio.sleep(remaining)
        require(len(read_delays)==MAX_READS,"Paced independent Student read window incomplete")
        read_p95=p95(read_delays)
        print(f"DISTINCT_READS performed={len(read_delays)} waves={WAVES} "
              f"p95_s={read_p95:.3f} max_s={max(read_delays):.3f} errors=0",flush=True)
        print("DISTINCT_FUNCTIONAL_PASS signed_student_actors=8 "
              "uploads=8 submissions=8 document_sha256_verified=true",flush=True)
        if upload_p95>MAX_UPLOAD_P95_S or submit_p95>3 or read_p95>MAX_READ_P95_S:
            print("DISTINCT_PERFORMANCE_GAP exceeded_provisional_objective "
                  f"upload_p95={upload_p95:.3f} submit_p95={submit_p95:.3f} "
                  f"read_p95={read_p95:.3f}",flush=True)
            raise RuntimeError("Signed distinct Student profile exceeds provisional latency objectives")
        print("PASS_HOSTED_DISTINCT_STUDENT_WRITES eight_signed_actors=true "
              "no_campus_peak_sla=true no_sustained_fifty_or_hundreds_users=true",flush=True)
    finally:
        for person in users+[coordinator]:
            await person.close()

def self_test():
    require(COUNT==8 and WAVES==60 and MAX_READS==480 and SPACING_S>=2,
            "Load safety bound modified without review")
    require(len({expected_actor(i) for i in range(1,COUNT+1)})==COUNT,
            "Distinct Student IDs are not independent")
    print("PASS_DISTINCT_STUDENT_HARNESS_OFFLINE_PREFLIGHT",flush=True)

if __name__=="__main__":
    if sys.argv[1:]==["--self-test"]:self_test()
    elif sys.argv[1:]:sys.exit("Only --self-test or explicit one-time manual pilot")
    else:
        try:asyncio.run(run())
        except (RuntimeError,ValueError,KeyError,httpx.HTTPError,asyncio.TimeoutError) as exc:
            print("DISTINCT_HOSTED_PILOT_FAILED "+type(exc).__name__+": "
                  +str(exc)[:145],file=sys.stderr)
            sys.exit(1)
