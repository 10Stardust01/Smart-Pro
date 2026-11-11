"""Signed HTTPS read-only safety audit after Neon database routing was restored."""
import asyncio,json,os
from hosted_synthetic_https_writes import Reviewer,require,ready,json_success,TIMEOUT
import httpx
D="10000000-0000-4000-8000-000000000001"
P="f7d7676d-9ffb-4b8c-b53d-257c07fc9d5e"
ORIGINAL="67b0acd3-914f-4063-97db-8b8a75359104"
S="00000000-0000-4000-8000-000000000001"
async def run():
    require(os.getenv("SMARTPRO_READ_ONLY_ROUTE_AUDIT")=="VERIFY_ORIGINAL_RESTORED_NEON_ROUTING",
        "Explicit read-only route check required")
    accounts=json.loads(os.getenv("SMARTPRO_HOSTED_TEST_ACCOUNTS") or "{}")
    student=Reviewer("Student",accounts["Student"]);admin=Reviewer("Admin",accounts["Admin"])
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT,verify=True) as http:
            await ready(http)
        w=await student.login()
        require(w["actor"]["id"]==S,"Synthetic Student identity mismatch")
        projects=json_success(await student.get(f"/api/v1/documents/departments/{D}?project={P}"),"recent synthetic handover project")
        require(any(x.get("id")==P for x in projects.get("projects",[])),
            "Live site does not expose newest project from original Neon branch")
        old=json_success(await student.get(f"/api/v1/documents/departments/{D}?project={ORIGINAL}"),"historical published project")
        record=next((x for x in old.get("projects",[]) if x.get("id")==ORIGINAL),None)
        require(record is not None and len(record.get("overallResults",[]))==1,
            "Historical published result not preserved")
        await admin.login()
        person=json_success(await admin.get(f"/api/v1/staff/departments/{D}/records/{S}"),
            "Administrative handover record")
        terms=person.get("facultyAdmin",{}).get("terms",[])
        require(terms and not any(x.get("active") for x in terms),
            "Original branch's test-only Faculty termination absent")
        print("PASS_REVIEWER_ORIGINAL_NEON_ROUTING: newest_synthetic_project=true historical_overall_v1=true student_identity=true faculty_terminated=true no_writes=true",flush=True)
    finally:
        await student.close();await admin.close()
if __name__=="__main__":asyncio.run(run())
