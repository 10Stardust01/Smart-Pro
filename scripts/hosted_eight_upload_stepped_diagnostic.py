"""One diagnostic eight-distinct-Student HTTPS upload and stepped read-concurrency run.

Eight signed synthetic Student actor UUIDs + existing Coordinator (and Faculty).
Uses eight existing audit-labeled projects via an authorized Guide request for changes,
verifies private PDF bytes,
eight independent submissions, then 480 bounded, paced read probes over ~2m.
Synthetic-only audited Guide revision decisions, no retry or paid resources.
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
EXISTING_SYNTHETIC_PROJECTS=["279b6649-e628-4041-9061-79f886ed5fca","dac806c5-a598-4839-8f37-336873306ce7","3cdb87a4-1888-43a1-b1ec-bba5341b0aae","55aca111-f0fa-4f2f-95f9-c6294297e40f","22370b5c-c1d7-49f1-a341-923a007ac495","0ae642ab-db4f-4f2d-bba7-ae46ba8d579d","32bc9040-a159-44fc-89ea-3883abf7408f","ca69295e-04a8-429b-914d-6d35f76b2fe9"]
WAVES=30
SPACING_S=2.0
MAX_READS=480
READER_SESSIONS_PER_STUDENT=3
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
    require(isinstance(common.get("Faculty"),dict) and
            isinstance(common["Faculty"].get("password"),str),
            "Existing authorized synthetic Faculty/Guide credentials required")
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
    faculty=Reviewer("Faculty",common["Faculty"])
    nonce=uuid.uuid4().hex[:10]
    created=[]
    extras=[]
    try:
        # Avoid hammering password hash login: authenticate nine identities sequentially.
        for n,person in enumerate(users,1):
            details=await person.login()
            require(details.get("actor",{}).get("id")==students[n-1]["actor"],
                    f"Distinct Student {n}: session bound to wrong underlying actor")
            require(details.get("access",{}).get("student") is True,
                    f"Distinct Student {n}: effective Student scope missing")
        await faculty.login()
        print("DISTINCT_LOGIN_PASS students=8 independent_actor_uuids=true "
              "guide_existing=true no_credentials_logged=true",flush=True)
        # Reuse precisely the eight existing, audit-labeled synthetic projects.
        # This avoids an invalid second team per Student within the same offering.
        # Each project is AWAITING_REVIEW with one existing SUBMITTED attempt.
        decisions=[]
        for n,user in enumerate(users,1):
            pid=EXISTING_SYNTHETIC_PROJECTS[n-1]
            owned=json_success(await user.get(f"/api/v1/documents/departments/{DEPT}?project={pid}"),
                               "Own existing synthetic project scope")
            case=case_from(owned,pid)
            require(case and case.get("state")=="AWAITING_REVIEW" and
                    len(case.get("attempts",[]))==1 and case["attempts"][0]["state"]=="SUBMITTED" and
                    len(case.get("versions",[]))==1,
                    f"Synthetic project {n}: expected one awaiting-review submission")
            reviewed=json_success(await faculty.get(f"/api/v1/documents/departments/{DEPT}?project={pid}"),
                                  "Assigned Guide scoped project")
            projects=reviewed.get("projects") or []
            require(len(projects)==1 and projects[0].get("id")==pid and
                    projects[0].get("canReview") is True and
                    (projects[0].get("guide") or {}).get("facultyId")==GUIDE,
                    f"Synthetic project {n}: assigned Guide authority missing")
            require(case.get("version")==projects[0].get("case",{}).get("version"),
                    f"Synthetic project {n}: case revisions inconsistent")
            decisions.append((pid,case["attempts"][0]["id"],case["version"]))
            created.append((user,pid))
        require(len({pid for pid,_,_ in decisions})==COUNT,
                "Distinct historical synthetic projects must not overlap")
        print("DIAGNOSTIC_EXISTING_FIXTURE_PASS projects=8 "
              "new_teams=0 new_projects=0 awaiting_guide_review=true",flush=True)
        # Legitimate Guide REQUEST_CHANGES: this creates an audited new revision
        # opportunity rather than bypassing the existing team/member policy.
        for n,(pid,aid,case_version) in enumerate(decisions,1):
            result=json_success(await faculty.post(f"/api/v1/documents/departments/{DEPT}",
                {"action":"DECIDE","projectId":pid,"attemptId":aid,
                 "expectedCaseVersion":case_version,"decision":"REQUEST_CHANGES",
                 "comment":"Synthetic capacity diagnostic: please resubmit a new document version"},
                key=f"diag-{nonce}-{n}-guide-request-changes"),
                "Authorized Guide request changes")
            require(result.get("status")=="CHANGES_REQUESTED",
                    "Synthetic Guide did not request changes")
        for n,(user,pid) in enumerate(created,1):
            current=json_success(await user.get(f"/api/v1/documents/departments/{DEPT}?project={pid}"),
                                 "Student new revision authorization")
            case=case_from(current,pid)
            require(case and case.get("state")=="CHANGES_REQUESTED" and
                    case.get("attempts",[])[0]["state"]=="CHANGES_REQUESTED",
                    f"Synthetic project {n}: revision not available")
        print("DIAGNOSTIC_GUIDE_REVISION_PASS projects=8 "
              "prior_submission_history_retained=true",flush=True)

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
        measured=[round(elapsed,3) for _,elapsed in pending]
        print(f"DISTINCT_DIAGNOSTIC_UPLOADS total={COUNT} p95_s={upload_p95:.3f} "
              f"client_wall_seconds={json.dumps(measured)} "
              "server_substep_timings_in_private_render_logs=true",flush=True)
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

        # Keep all eight original students, but create two more authenticated
        # sessions per identity. This is 24 sessions, NOT 24 distinct students.
        for extra_round in range(READER_SESSIONS_PER_STUDENT-1):
            for n,item in enumerate(students):
                clone=Reviewer("Student",item)
                extras.append(clone)
                identity=await clone.login()
                require(identity.get("actor",{}).get("id")==item["actor"],
                        f"Extra read session {extra_round+1} of student {n+1} actor mismatch")
        read_delays=[]
        read_summary=[]
        for wave in range(WAVES):
            started=time.monotonic()
            active=(users if wave<10 else users+extras[:8] if wave<20 else users+extras)
            paths=["/api/v1/me/projects?page=1" if wave%2==0
                   else f"/api/v1/documents/departments/{DEPT}?listing=1&page=1"]*len(active)
            replies=await simultaneous([
                (lambda u=user,path=paths[n]:u.get(path)) for n,user in enumerate(active)])
            if any(res.status_code!=200 for res,_ in replies):
                raise RuntimeError(f"DIAGNOSTIC_READ_STOP non-200 wave={wave+1} concurrency={len(active)}")
            delays=[duration for _,duration in replies]
            if sum(duration>5 for duration in delays)>=2:
                raise RuntimeError(f"DIAGNOSTIC_READ_STOP multiple reads >5s wave={wave+1} concurrency={len(active)}")
            read_delays+=delays
            read_summary.append((len(active),delays))
            remaining=SPACING_S-(time.monotonic()-started)
            if remaining>0 and wave+1<WAVES:
                await asyncio.sleep(remaining)
        require(len(read_delays)==MAX_READS,"Stepped signed-read window incomplete")
        read_p95=p95(read_delays)
        for level in (8,16,24):
            observations=[delay for n,ds in read_summary if n==level for delay in ds]
            print(f"DIAGNOSTIC_READ_STEP sessions={level} student_actors=8 "
                  f"requests={len(observations)} p95_s={p95(observations):.3f} "
                  f"max_s={max(observations):.3f}",flush=True)
        print(f"DIAGNOSTIC_READS performed={len(read_delays)} waves={WAVES} "
              f"p95_s={read_p95:.3f} max_s={max(read_delays):.3f} errors=0",flush=True)
        print("DIAGNOSTIC_FUNCTIONAL_PASS signed_student_actors=8 "
              "uploads=8 submissions=8 document_sha256_verified=true",flush=True)
        if upload_p95>MAX_UPLOAD_P95_S or submit_p95>3 or read_p95>MAX_READ_P95_S:
            print("DISTINCT_PERFORMANCE_GAP exceeded_provisional_objective "
                  f"upload_p95={upload_p95:.3f} submit_p95={submit_p95:.3f} "
                  f"read_p95={read_p95:.3f}",flush=True)
            raise RuntimeError("Signed distinct Student profile exceeds provisional latency objectives")
        print("PASS_EIGHT_UPLOAD_AND_24_SESSION_READ_DIAGNOSTIC eight_signed_actors=true "
              "sessions_peak=24 campus_scale_not_proven=true",flush=True)
    finally:
        for person in users+[faculty]:
            await person.close()
        for person in extras:
            await person.close()

def self_test():
    require(COUNT==8 and WAVES==30 and MAX_READS==480 and SPACING_S>=2 and READER_SESSIONS_PER_STUDENT==3,
            "Load safety bound modified without review")
    require(len(EXISTING_SYNTHETIC_PROJECTS)==COUNT and len(set(EXISTING_SYNTHETIC_PROJECTS))==COUNT,
            "Historical synthetic project fixture changed")
    require(len({expected_actor(i) for i in range(1,COUNT+1)})==COUNT,
            "Distinct Student IDs are not independent")
    print("PASS_EIGHT_UPLOAD_STEPPED_READ_DIAGNOSTIC_PREFLIGHT",flush=True)

if __name__=="__main__":
    if sys.argv[1:]==["--self-test"]:self_test()
    elif sys.argv[1:]:sys.exit("Only --self-test or explicit one-time manual pilot")
    else:
        try:asyncio.run(run())
        except (RuntimeError,ValueError,KeyError,httpx.HTTPError,asyncio.TimeoutError) as exc:
            print("DISTINCT_HOSTED_PILOT_FAILED "+type(exc).__name__+": "
                  +str(exc)[:145],file=sys.stderr)
            sys.exit(1)
