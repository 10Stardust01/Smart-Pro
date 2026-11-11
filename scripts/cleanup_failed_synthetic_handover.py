"""One-time fail-closed cleanup of the specifically created synthetic Faculty term.
Keeps the original Student role. Does not change other faculty or assignments.
"""
import asyncio, json, os, uuid
from hosted_synthetic_https_writes import Reviewer, json_success, require
DEPT="10000000-0000-4000-8000-000000000001"
STUDENT="00000000-0000-4000-8000-000000000001"
TERM="4ce8ebeb-80f8-48b2-9b34-d83ae86b0dae"
async def run():
    require(os.environ.get("SMARTPRO_CLEANUP_APPROVAL")=="CLEANUP_EXACT_FAILED_SYNTHETIC_FACULTY_TERM_20261111",
            "Explicit exact-term safety cleanup approval required")
    accounts=json.loads(os.getenv("SMARTPRO_HOSTED_TEST_ACCOUNTS") or "{}")
    admin=Reviewer("Admin",accounts["Admin"])
    student=Reviewer("Student",accounts["Student"])
    try:
        await admin.login(); await student.login()
        path=f"/api/v1/staff/departments/{DEPT}/records/{STUDENT}"
        response=json_success(await admin.get(path),"Authorized exact synthetic student record")
        active=[x for x in response.get("facultyAdmin",{}).get("terms",[])
                if x.get("active")]
        require(len(active)==1 and active[0]["id"]==TERM,
                "Faculty term changed; refuse to affect any other term")
        result=await admin.post(path,{
            "action":"TERMINATE","termId":TERM,
            "expectedAuthorityRevision":active[0]["staff_authority_revision"],
            "reason":"Cleanup of temporary test Faculty access after aborted synthetic handover run"
        },key="exact-failed-handover-cleanup-"+TERM)
        json_success(result,"Terminate exactly failed synthetic Faculty grant")
        after=json_success(await admin.get(path),"Read back cleaned test Faculty")
        require(not any(t.get("active") for t in after.get("facultyAdmin",{}).get("terms",[])),
                "Temporary Faculty still active")
        still=json_success(await student.get("/api/v1/workspace"),"Preserved Student scope")
        require(still.get("actor",{}).get("id")==STUDENT,"Student identity changed")
        print("PASS_CLEANUP_EXACT_SYNTHETIC_FACULTY_TERM student_retained=true",flush=True)
    finally:
        await admin.close();await student.close()
if __name__=="__main__":
    asyncio.run(run())
