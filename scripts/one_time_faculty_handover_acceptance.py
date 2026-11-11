"""One-time, synthetic-only real HTTPS Faculty access handover acceptance.

Uses the existing signed-in Student test identity as a *temporary* Faculty term
on an isolated synthetic project. It does not revoke any established Faculty.
Admin terminates that temporary term, Coordinator explicitly assigns the
ordinary existing Faculty as replacement, and original history is retained.
Every action is identity-scoped with a unique idempotency key; no retry.
"""
import asyncio
import json
import os
import uuid
import httpx
from hosted_synthetic_https_writes import BASE, TIMEOUT, Reviewer, require, json_success, ready

DEPT="10000000-0000-4000-8000-000000000001"
STUDENT="00000000-0000-4000-8000-000000000001"
REPLACEMENT="00000000-0000-4000-8000-000000000003"
OFFERING="8b40a6e1-419d-43c8-b625-279f82713b02"
TEAM="04da071d-f86b-415d-a580-123ba8f2236b"
APPROVAL="RUN_SYNTHETIC_FACULTY_HANDOVER_ON_EXISTING_FREE_STAGING"

async def read(person,path,where):
    return json_success(await person.get(path),where)
async def write(person,path,body,label,nonce):
    return json_success(await person.post(path,body,key="handover-"+nonce+"-"+label),label)
async def run():
    require(os.getenv("SMARTPRO_FACULTY_HANDOVER_APPROVAL")==APPROVAL,
            "Explicit one-time isolated synthetic handover authority missing")
    accounts=json.loads(os.getenv("SMARTPRO_HOSTED_TEST_ACCOUNTS") or "{}")
    for role in ("Student","Faculty","Coordinator","HOD","Admin"):
        require(isinstance(accounts.get(role),dict) and accounts[role].get("alias")
                and accounts[role].get("password"),f"Missing private {role} reviewer")
    persons={role:Reviewer(role,accounts[role])
             for role in ("Student","Faculty","Coordinator","HOD","Admin")}
    student,coordinator,admin=(persons[role] for role in ("Student","Coordinator","Admin"))
    nonce=uuid.uuid4().hex[:10]
    temp_faculty=Reviewer("Faculty",accounts["Student"])
    grant_done=False
    terminated=False
    term=None
    project_id=None
    guide_id=None
    recordpath=f"/api/v1/staff/departments/{DEPT}/records/{STUDENT}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT,verify=True) as client:
            await ready(client)
        for person in persons.values():
            await person.login()
        pre=await read(student,"/api/v1/workspace","Student preflight")
        require(pre["actor"]["id"]==STUDENT, "Only the fixed synthetic Student may be temporary Faculty")
        require("Faculty" not in pre.get("roleChoices",[]),
                "Synthetic Student already has Faculty: fail closed, do not modify that account")
        memberships=await read(student,"/api/v1/me/memberships","Synthetic team preflight")
        require(any(x.get("teamId")==TEAM and x.get("offeringId")==OFFERING
                    and not x.get("scheduledEndAt") and "synthetic" in str(x.get("teamName","")).lower()
                    for x in memberships.get("results",[])),
                "Existing explicitly synthetic team membership missing")
        setup=await read(admin,f"/api/v1/staff/departments/{DEPT}/setup","Admin authority setup")
        sources=setup["instructionSources"]
        authority={"hodMandateId":sources["hods"][0]["id"],"source":"EXTERNAL_INSTRUCTION",
                   "confirmed":True,"reference":"SYNTHETIC-ONLY-HANDOVER-"+nonce}
        # Create a first-access Faculty term only for existing synthetic Student actor;
        # no other Faculty identity, term or assignment is touched.
        grant=await write(admin,f"/api/v1/staff/departments/{DEPT}/setup",
            {"action":"RECORD","kind":"FACULTY_ACCESS",
             "configuration":{"userId":STUDENT,"validUntil":"2027-06-01T00:00:00Z"},
             "authority":authority,"reason":"One-time synthetic academic handover acceptance"},
            "faculty-first-access",nonce)
        grant_done=True
        print("PASS_TEMP_SYNTHETIC_FACULTY_ACCESS_GRANTED",flush=True)
        signed=await temp_faculty.login()
        require(signed["actor"]["id"]==STUDENT, "Temporary Faculty sign-in identity mismatch")
        assert "Faculty" in signed.get("roleChoices",[])
        project=await write(student,"/api/v1/projects",
            {"offeringId":OFFERING,"teamId":TEAM,
             "title":"[SYNTHETIC-FACULTY-HANDOVER] "+nonce,
             "description":"Reviewer staging only; no institutional marks or personal data"},
            "project",nonce)
        project_id=str(uuid.UUID(project["id"]))
        require(project.get("teamId")==TEAM, "Unexpected synthetic project team")
        assigned=await write(coordinator,f"/api/v1/staff/departments/{DEPT}/projects/{project_id}/guide",
            {"facultyId":STUDENT,"expectedGuideId":None},"assign-temp-guide",nonce)
        guide_id=str(uuid.UUID(assigned["id"]))
        visible=await read(temp_faculty,"/api/v1/workspace","Active temporary guide")
        require(any(p.get("id")==project_id for p in visible.get("projects",[]))
                or any(r.get("projectId")==project_id for r in visible.get("reviews",[])),
                "Temporary Faculty does not see assigned synthetic project")
        rec=await read(admin,recordpath,"Admin faculty term history")
        terms=rec.get("facultyAdmin",{}).get("terms",[])
        effective=[x for x in terms if x.get("active")]
        require(len(effective)==1,"Exactly one temporary Faculty term expected")
        term=effective[0]
        termid=str(uuid.UUID(term["id"]))
        end=await write(admin,recordpath,
            {"action":"TERMINATE","termId":termid,
             "expectedAuthorityRevision":term["staff_authority_revision"],
             "reason":"Synthetic test: immediate Faculty access removal and academic handover"},
            "terminate",nonce)
        terminated=True
        print("PASS_ADMIN_TERMINATED_TEMP_SYNTHETIC_FACULTY",flush=True)
        faculty_after=await temp_faculty.get("/api/v1/workspace")
        require(faculty_after.status_code in (401,403),
                "Faculty access was not denied immediately after Admin termination")
        student_after=await read(student,"/api/v1/workspace","Student remained authorized")
        require(student_after["actor"]["id"]==STUDENT,
                "Existing Student role unexpectedly lost during Faculty termination")
        replacement=await write(coordinator,
            f"/api/v1/staff/departments/{DEPT}/projects/{project_id}/guide",
            {"facultyId":REPLACEMENT,"expectedGuideId":None},
            "assign-replacement",nonce)
        replacement_guide=str(uuid.UUID(replacement["id"]))
        require(replacement_guide!=guide_id,"Replacement assignment must be new version")
        newrec=await read(admin,recordpath,"Terminated Faculty record and handover history")
        terms=newrec.get("facultyAdmin",{}).get("terms",[])
        require(not any(x.get("active") for x in terms),
                "Terminated Faculty term unexpectedly still active")
        require(any(x.get("id")==termid for x in terms),
                "Terminated Faculty term was not preserved")
        print("PASS_HOSTED_SYNTHETIC_FACULTY_HANDOVER",
            "project="+project_id,
            "original_assignment="+guide_id,
            "new_assignment="+replacement_guide,
            "original_faculty_term="+termid,
            "student_login_preserved=true",
            "faculty_login_revoked=true",
            "coordinator_reassigned_explicitly=true",flush=True)
    finally:
        if grant_done and not terminated and term:
            try:
                await write(admin,recordpath,
                  {"action":"TERMINATE","termId":str(uuid.UUID(term["id"])),
                   "expectedAuthorityRevision":term["staff_authority_revision"],
                   "reason":"Safety cleanup: terminate test-only temporary Faculty term"},
                  "safety-cleanup",nonce)
                print("PASS_SAFETY_CLEANUP_TEMP_FACULTY_TERM",flush=True)
            except Exception as exc:
                print("ATTENTION_TEMP_FACULTY_TERM_CLEANUP_NOT_CONFIRMED "+type(exc).__name__,flush=True)
        for person in persons.values():
            await person.close()
        await temp_faculty.close()

if __name__=="__main__":
    asyncio.run(run())
