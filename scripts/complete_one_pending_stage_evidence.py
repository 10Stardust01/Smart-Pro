"""Complete ONLY the single preflighted synthetic stage-evidence request left pending.

Fail closed on any changed project/request state. Never create a project,
rewrite stage marks, alter an academic policy, or retry a successful decision.
"""
import asyncio
import json
import os
import sys
from hosted_synthetic_https_writes import Reviewer,require,ready,TIMEOUT
from hosted_published_correction_journey import DEPT,ORIGINAL_PROJECT,STUDENT_ID,one_project,released_values,checked,fetch,send
import httpx

OFFERING="67c6d09c-22d4-42d0-8608-7deb73e72691"
PROJECT="4139b790-1f98-4d70-8fb4-2f0ccd5a2a65"
REQUEST="656aba35-bc59-436d-9083-b6c8ccadb6d0"

async def main():
    require(os.environ.get("SMARTPRO_STAGE_COMPLETE_APPROVAL")=="COMPLETE_PENDING_STAGE_EVIDENCE_656ABA35","Exact request authorization missing")
    accounts=json.loads(os.environ.get("SMARTPRO_HOSTED_TEST_ACCOUNTS") or "{}")
    require(all(isinstance(accounts.get(role),dict) and accounts[role].get("alias") and accounts[role].get("password") for role in ("Student","Coordinator","Faculty")),"Signed synthetic accounts required")
    users={role:Reviewer(role,accounts[role]) for role in ("Student","Coordinator","Faculty")}
    student,coord,guide=users["Student"],users["Coordinator"],users["Faculty"]
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT,verify=True) as client: await ready(client)
        for user in users.values(): await user.login()
        old=await fetch(student,f"/api/v1/documents/departments/{DEPT}?project={ORIGINAL_PROJECT}","Original benchmark")
        original=released_values(one_project(old,ORIGINAL_PROJECT) or {})
        require(len(original)==1 and original[0][0]==1,"Historical project state not expected")
        before=await fetch(student,f"/api/v1/documents/departments/{DEPT}?project={PROJECT}","Pending synthetic")
        entry=one_project(before,PROJECT)
        require(entry and released_values(entry)==[(1,"40.00")],"Expected one synthetic overall v1 40.00")
        details=await fetch(coord,f"/api/v1/courses/offerings/{OFFERING}/details","Correction offering details")
        result=[v for v in details.get("overallResults",[]) if v.get("project_id")==PROJECT]
        require(len(result)==1 and result[0]["version"]==1,"Synthetic prior release changed")
        old_source=result[0]["sources"]
        plan=next((p for p in details.get("plans",[]) if p["id"]==result[0]["plan_id"]),None)
        framework=next((f for f in details.get("frameworks",[]) if plan and f["id"]==plan["framework_id"]),None)
        require(framework and framework["configuration"]["allowFinalCorrections"] is True,"Synthetic framework not correction enabled")
        queue=await fetch(coord,f"/api/v1/courses/offerings/{OFFERING}/final-revisions?page=1","Current correction queue")
        # The queue response may place type inside the nested snapshot or omit it
        # in the listing. Check exact pending request ID and authoritative state.
        item=next((r for r in queue.get("requests",[]) if r.get("id")==REQUEST),None)
        require(item is not None,"Exactly-targeted pending correction not present on first page")
        require(item.get("approved") is None and not item.get("decidedAt") and item.get("status","PENDING") in ("PENDING",None),"Already decided; stop")
        print("PASS_EXACT_PENDING_REQUEST_PREFLIGHT synthetic_only=true prior_overall_version=1",flush=True)
        decision=await send(coord,f"/api/v1/courses/offerings/{OFFERING}/commands",{
            "action":"AUTHORIZE_FINAL_REVISION",
            "requestId":REQUEST,"approved":True,
            "reason":"Approve already corrected synthetic stage evidence; finish single pending request"
        },"Single Coordinator decision on exact existing request","stage-pending-"+REQUEST[:8]+"-decision")
        require(decision.get("newVersion")==2,"Stage evidence did not release v2; DO NOT RETRY")
        after=await fetch(student,f"/api/v1/documents/departments/{DEPT}?project={PROJECT}","Student preserved result history")
        require(released_values(one_project(after,PROJECT) or {})==[(1,"40.00"),(2,"42.00")],
                "Student exact old and new overall totals incorrect")
        new_details=await fetch(coord,f"/api/v1/courses/offerings/{OFFERING}/details","Overall original/successor audit")
        versions=sorted((v for v in new_details.get("overallResults",[]) if v.get("project_id")==PROJECT),key=lambda v:v["version"])
        require(len(versions)==2 and versions[0]["sources"]==old_source
                and versions[0]["id"]==result[0]["id"]
                and versions[1]["supersedes_id"]==result[0]["id"]
                and versions[1]["sources"]!=old_source,"Stage source correction or historical lineage lost")
        original_after=await fetch(student,f"/api/v1/documents/departments/{DEPT}?project={ORIGINAL_PROJECT}","Original academic result immutability")
        require(released_values(one_project(original_after,ORIGINAL_PROJECT) or {})==original,
                "Historical academic results changed")
        print("PASS_HOSTED_GENUINE_STAGE_EVIDENCE_RERELEASE synthetic_only=true stage_versions=2 overall_versions=2 original_score=40.00 successor_score=42.00 stage_sources_changed=true original_project_unchanged=true",flush=True)
    finally:
        for user in users.values(): await user.close()

if __name__=="__main__":
    try: asyncio.run(main())
    except Exception as exc:
        print(f"EXACT_PENDING_STAGE_COMPLETION_FAILED {type(exc).__name__}: {str(exc)[:150]}",file=sys.stderr)
        sys.exit(1)
