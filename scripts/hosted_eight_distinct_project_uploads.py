"""One-time bounded eight separate-project synthetic HTTPS upload performance probe.

Eight sessions use one existing synthetic Student identity, but projects and
document locks are distinct. No retries, no existing records edited.
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
from hosted_synthetic_https_writes import (
    BASE,TIMEOUT,PHRASE,Reviewer,require,ready,pdf_bytes,json_success,
    simultaneous,case_from
)

DEPT="10000000-0000-4000-8000-000000000001"
OFFERING="8b40a6e1-419d-43c8-b625-279f82713b02"
TEAM="04da071d-f86b-415d-a580-123ba8f2236b"
GUIDE="00000000-0000-4000-8000-000000000003"
ORIGINAL="67b0acd3-914f-4063-97db-8b8a75359104"
STUDENT_ID="00000000-0000-4000-8000-000000000001"
COUNT=8
MAX_P95=10.0

async def run():
    require(os.getenv("SMARTPRO_EIGHT_PROJECT_APPROVAL")=="RUN_EIGHT_DISTINCT_SYNTHETIC_PROJECT_UPLOADS","Exact one-time approval missing")
    creds=json.loads(os.getenv("SMARTPRO_HOSTED_TEST_ACCOUNTS") or "{}")
    for role in ("Student","Coordinator"):
        require(isinstance(creds.get(role),dict) and creds[role].get("alias") and creds[role].get("password"),"Existing signed synthetic accounts required")
    students=[Reviewer("Student",creds["Student"]) for _ in range(COUNT)]
    coord=Reviewer("Coordinator",creds["Coordinator"])
    nonce=uuid.uuid4().hex[:10]
    created=[]
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT,verify=True) as c: await ready(c)
        for person in students+[coord]: await person.login()
        student=students[0]
        offerings=json_success(await student.get("/api/v1/me/curriculum-offerings"),"Current Student offerings")
        require(any(x.get("id")==OFFERING for x in offerings.get("results",[])),"Synthetic offering not eligible")
        memberships=json_success(await student.get("/api/v1/me/memberships"),"Memberships")
        require(any(x.get("teamId")==TEAM and x.get("offeringId")==OFFERING and "synthetic" in str(x.get("teamName","")).lower() and x.get("scheduledEndAt") is None for x in memberships.get("results",[])),"Only explicitly synthetic current team permitted")
        before=json_success(await student.get(f"/api/v1/documents/departments/{DEPT}?project={ORIGINAL}"),"Original result preflight")
        orig=next((x for x in before.get("projects",[]) if x.get("id")==ORIGINAL),None)
        require(orig and len(orig.get("overallResults",[]))==1,"Original published project not expected")
        original_fingerprint=json.dumps(orig["overallResults"],sort_keys=True)
        for i in range(COUNT):
            project=json_success(await student.post("/api/v1/projects",{
                "offeringId":OFFERING,"teamId":TEAM,
                "title":f"[SYNTHETIC-EIGHT-DISTINCT-UPLOAD] {nonce}-{i}",
                "description":"Isolated Free reviewer load exercise: own project, no coursework"
            },key=f"distinct-{nonce}-project-{i}"),f"Create synthetic project {i}",(201,))
            pid=str(uuid.UUID(project["id"]))
            created.append(pid)
            json_success(await coord.post(f"/api/v1/staff/departments/{DEPT}/projects/{pid}/guide",{
                "facultyId":GUIDE,"expectedGuideId":None
            },key=f"distinct-{nonce}-guide-{i}"),f"Guide appointment {i}")
        require(len(set(created))==COUNT,"All projects must be independent")
        async with httpx.AsyncClient(timeout=TIMEOUT,verify=True) as c: await ready(c)
        pdfs=[pdf_bytes(f"SMARTPRO EIGHT PROJECTS {nonce} PDF {i}",padding_bytes=256*1024) for i in range(COUNT)]
        results=await simultaneous([
            (lambda i=i: students[i].post(
                f"/api/v1/documents/departments/{DEPT}/projects/{created[i]}/uploads",
                None,key=f"distinct-{nonce}-upload-{i}",
                files={"file":(f"synthetic-{nonce}-{i}.pdf",pdfs[i],"application/pdf")}))
            for i in range(COUNT)
        ])
        times=sorted(duration for _,duration,_ in results)
        p95=times[ceil(.95*COUNT)-1]
        code_counts={str(code):sum(x[0]==code for x in results) for code in sorted(set(x[0] for x in results))}
        print(f"DISTINCT_PROJECT_UPLOAD_8 clients={COUNT} p95={p95:.3f}s max={times[-1]:.3f}s statuses={json.dumps(code_counts,sort_keys=True)}",flush=True)
        require(all(code==200 for code,_,_ in results),"Some independent project uploads were rejected; do not retry")
        require(p95<=MAX_P95,"Independent project upload p95 exceeded 10s threshold")
        for i,(_,_,res) in enumerate(results):
            version=json_success(res,f"Result {i}")["documentVersionId"]
            downloaded=await student.get(f"/api/v1/document-versions/{version}/content?download=1")
            require(downloaded.status_code==200 and hashlib.sha256(downloaded.content).digest()==hashlib.sha256(pdfs[i]).digest(),
                    f"Private PDF {i} byte verification failed")
        after=json_success(await student.get(f"/api/v1/documents/departments/{DEPT}?project={ORIGINAL}"),"Original result after")
        historic=next((x for x in after.get("projects",[]) if x.get("id")==ORIGINAL),None)
        require(historic and json.dumps(historic["overallResults"],sort_keys=True)==original_fingerprint,"Original published result changed")
        print("PASS_EIGHT_DISTINCT_PROJECT_PRIVATE_PDF_UPLOADS all_8_ok=true SHA256_8_of_8=true original_result_unchanged=true no_retry=true",flush=True)
    finally:
        for person in students+[coord]:await person.close()
        if created:
            print(f"SYNTHETIC_8_PROJECT_FIXTURE_RETAINED created={len(created)} no deletion or historical edits",flush=True)

if __name__=="__main__":
    try: asyncio.run(run())
    except Exception as exc:
        print(f"DISTINCT_8_UPLOAD_FAILED {type(exc).__name__}: {str(exc)[:150]}",file=sys.stderr)
        sys.exit(1)
