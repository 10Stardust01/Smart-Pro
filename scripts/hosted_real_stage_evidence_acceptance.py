"""Bounded signed-role genuine stage-result correction and re-release acceptance.

Manual staging only. Creates a new explicitly synthetic TYPE + offering +
framework/plan, team and project. Never changes the preexisting offering,
its pinned correction-disabled framework, or original published result.
"""
import asyncio
import os
import sys
import uuid
from decimal import Decimal

import httpx

from hosted_synthetic_https_writes import (
    PHRASE, TIMEOUT, AcceptanceFailure, Reviewer, json_success,
    require, ready, score_rows,
)

DEPT = "10000000-0000-4000-8000-000000000001"
OLD_OFFERING = "8b40a6e1-419d-43c8-b625-279f82713b02"
ORIGINAL_PROJECT = "67b0acd3-914f-4063-97db-8b8a75359104"
STUDENT_ID = "00000000-0000-4000-8000-000000000001"
GUIDE_ID = "00000000-0000-4000-8000-000000000003"
COORDINATOR_ID = "00000000-0000-4000-8000-000000000008"
MAX_NEW_PROJECTS = 1


def checked(data, label):
    require(isinstance(data, dict), f"{label}: JSON object required")
    return data


async def send(person, path, body, label, key, codes=(200,)):
    return checked(json_success(await person.post(path, body, key=key), label, codes), label)


async def fetch(person, path, label):
    return checked(json_success(await person.get(path), label), label)


def one_project(data, project_id):
    require(isinstance(data.get("projects"), list), "Scoped project results missing")
    return next((p for p in data["projects"] if p.get("id") == project_id), None)


def released_values(entry):
    rows = entry.get("overallResults") or []
    require(isinstance(rows, list), "Student overall result history unavailable")
    return [(v["version"], v["results"][STUDENT_ID]) for v in rows
            if STUDENT_ID in v.get("results", {})]


def new_marks(old_marks):
    value = Decimal(str(old_marks))
    candidate = value + Decimal("1.00")
    if candidate > Decimal("100"):
        candidate = value - Decimal("1.00")
    require(candidate >= 0 and candidate != value, "Test total cannot be adjusted safely")
    return f"{candidate:.2f}"


async def run():
    require(os.getenv("SMARTPRO_HOSTED_CORRECTION_APPROVAL") == "RUN_SYNTHETIC_REAL_STAGE_EVIDENCE",
            "Explicit one-run correction acceptance approval required")
    require(os.getenv("SMARTPRO_HOSTED_WRITE_APPROVAL") == PHRASE,
            "Synthetic staging writes approval required")
    import json
    accounts = json.loads(os.getenv("SMARTPRO_HOSTED_TEST_ACCOUNTS") or "{}")
    for role in ("Student", "Faculty", "Coordinator", "HOD", "Admin"):
        entry = accounts.get(role)
        require(isinstance(entry, dict) and entry.get("alias") and entry.get("password"),
                f"Signed {role} account secret missing")
    nonce = uuid.uuid4().hex[:10]
    persons = {role: Reviewer(role, accounts[role])
               for role in ("Student", "Faculty", "Coordinator", "HOD", "Admin")}
    student, guide, coord, hod, admin = (persons[role] for role in
                                         ("Student", "Faculty", "Coordinator", "HOD", "Admin"))
    created = {}
    original_old = None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, verify=True) as public:
            await ready(public)
        for user in persons.values():
            await user.login()
        # Verify the existing published project and policy before ANY new write.
        old = await fetch(student, f"/api/v1/documents/departments/{DEPT}?project={ORIGINAL_PROJECT}",
                          "Original published project")
        previous = one_project(old, ORIGINAL_PROJECT)
        require(previous is not None, "Existing published benchmark project is missing")
        original_old = released_values(previous)
        require(len(original_old) == 1 and original_old[0][0] == 1,
                "Original published result must have exactly one version")
        original_course = await fetch(coord, f"/api/v1/courses/offerings/{OLD_OFFERING}/details",
                                      "Existing original course")
        frameworks = original_course.get("frameworks", [])
        plans = original_course.get("plans", [])
        require(len(frameworks) >= 1 and len(plans) >= 1,
                "Original versioned academic framework/plan missing")
        source_framework = next((x for x in frameworks
                                 if x["id"] == plans[0]["framework_id"]), None)
        require(source_framework and
                source_framework["configuration"]["allowFinalCorrections"] is False,
                "Original published framework must remain correction-disabled")
        original_framework_id = source_framework["id"]
        admin_setup = await fetch(admin, f"/api/v1/staff/departments/{DEPT}/setup",
                                  "Admin setup authority")
        sources = admin_setup["instructionSources"]
        mandate = sources["hods"][0]["id"]
        admin_role = sources["adminRoleId"]
        previous_offerings = await fetch(admin,
            f"/api/v1/staff/departments/{DEPT}/offering-management", "Prior offering config")
        original_config = next((x["configuration"] for x in previous_offerings["offerings"]
                                if x["id"] == OLD_OFFERING), None)
        require(original_config and original_config["semester"] == "SEM-3",
                "Synthetic student eligibility cannot be inferred")
        authority = {"hodMandateId": mandate, "source": "EXTERNAL_INSTRUCTION",
                     "confirmed": True,
                     "reference": f"SYNTHETIC-ONLY-REVIEWER-CORRECTION-{nonce}"}
        setup_path = f"/api/v1/staff/departments/{DEPT}/setup"
        # Isolated curriculum type permits a new offering with the same
        # synthetic student's semester; do not alter existing TYPE or offering.
        name = "SYN-STAGE-" + nonce.upper()
        created_type = await send(admin, setup_path, {
            "action": "RECORD", "kind": "TYPE",
            "configuration": {"code": name, "label": "Synthetic stage evidence correction acceptance only"},
            "authority": authority, "reason": "Synthetic reviewer workflow acceptance"
        }, "Create separate synthetic curriculum type", "stage-" + nonce + "-type")
        type_id = str(uuid.UUID(created_type["id"]))
        config = dict(original_config, curriculumTypeId=type_id,
                      adminRoleId=admin_role)
        offering_created = await send(admin, setup_path, {
            "action": "RECORD", "kind": "OFFERING",
            "configuration": config, "authority": authority,
            "reason": "Dedicated synthetic reviewer overall correction offering"
        }, "Create separate synthetic offering", "corr-" + nonce + "-offering")
        offering_id = str(uuid.UUID(offering_created.get("offeringId") or offering_created["id"]))
        created["offering"] = offering_id
        print("CREATED_SYNTHETIC_CORRECTION_OFFERING", offering_id, flush=True)
        await send(admin, f"/api/v1/courses/offerings/{offering_id}/coordinators", {
            "userId": COORDINATOR_ID, "expectedVersion": 0, "active": True,
            "validUntil": "2027-06-01T00:00:00Z",
            "responsibilities": ["OVERVIEW", "REQUIREMENTS", "PLAN", "GUIDE",
                                 "EVALUATORS", "SUBMISSIONS", "DEADLINES",
                                 "RESULTS", "CORRECTIONS", "HISTORY"],
            "authority": None, "reason": "Synthetic offering coordination"
        }, "Appoint synthetic Coordinator", "corr-" + nonce + "-appointment")
        management = await fetch(admin,
            f"/api/v1/staff/departments/{DEPT}/offering-management",
            "New offering management")
        entry = next((x for x in management.get("offerings", [])
                      if x["id"] == offering_id), None)
        require(entry is not None and entry["availability"] == "PAUSED",
                "New offering must begin paused")
        await send(admin,
            f"/api/v1/staff/departments/{DEPT}/offering-management", {
                "action": "AVAILABILITY", "offeringId": offering_id,
                "expectedRevision": entry["management_revision"],
                "availability": "ACTIVE", "authority": authority,
                "reason": "Activate synthetic reviewer correction offering"
            }, "Activate separate synthetic offering", "corr-" + nonce + "-active")
        # HOD pins a new, separate synthetic stage-correction-enabled framework.
        # Never touch the original project or its correction-disabled policy.
        cfg = dict(source_framework["configuration"])
        cfg["allowFinalCorrections"] = True  # New synthetic framework only; old historical framework never edited.
        require(cfg["allowFinalCorrections"] is True,
                "New synthetic project must have explicitly enabled stage correction policy")
        cmd = f"/api/v1/courses/offerings/{offering_id}/commands"
        framework = await send(hod, cmd, {
            "action": "FRAMEWORK", "expectedVersion": 0,
            "configuration": cfg, "authority": None,
            "reason": "Synthetic unchanged stage restrictions; exceptional overall correction acceptance"
        }, "HOD creates separately pinned stage-restricted framework",
           "corr-" + nonce + "-framework")
        framework_id = str(uuid.UUID(framework["id"]))
        require(framework_id != original_framework_id, "Original framework cannot be reused")
        await send(coord, cmd, {
            "action": "PLAN", "expectedVersion": 0, "frameworkId": framework_id,
            "schedules": dict(plans[0]["schedules"]),
            "reason": "Synthetic-only stage schedule"
        }, "Coordinator creates correction plan", "corr-" + nonce + "-plan")
        info = await fetch(student, "/api/v1/me/curriculum-offerings",
                           "Synthetic Student offerings")
        require(any(x.get("id") == offering_id for x in info.get("results", [])),
                "New offering not eligible for synthetic Student")
        team = await send(student, "/api/v1/teams", {
            "offeringId": offering_id, "name": "Synthetic correction acceptance " + nonce
        }, "Create separate synthetic team", "corr-" + nonce + "-team", (201,))
        team_id = str(uuid.UUID(team["id"]))
        project = await send(student, "/api/v1/projects", {
            "offeringId": offering_id, "teamId": team_id,
            "title": "[SYNTHETIC-CORRECTION] " + nonce,
            "description": "Staging-only published-result correction acceptance"
        }, "Register one synthetic project", "corr-" + nonce + "-project", (201,))
        project_id = str(uuid.UUID(project["id"]))
        created["project"] = project_id
        require(project.get("teamId") == team_id, "Wrong synthetic project team")
        await send(coord, f"/api/v1/staff/departments/{DEPT}/projects/{project_id}/guide", {
            "facultyId": GUIDE_ID, "expectedGuideId": None
        }, "Assign current synthetic Guide", "corr-" + nonce + "-guide")
        stage_key = cfg["stages"][0]["key"]
        stage = await send(coord, cmd, {
            "action": "CREATE_STAGE", "projectId": project_id,
            "stageKey": stage_key, "facultyIds": []
        }, "Create synthetic evaluation stage", "corr-" + nonce + "-stage")
        review_id = str(uuid.UUID(stage.get("reviewId") or stage["id"]))
        faculty_workspace = await fetch(guide, "/api/v1/workspace",
                                       "Guide marks workspace")
        review = next((r for r in faculty_workspace.get("reviews", [])
                       if r.get("id") == review_id and r.get("projectId") == project_id), None)
        require(review and len(review["assessments"]) == 1,
                "Assigned Guide evaluation not in signed Faculty workspace")
        assessment = review["assessments"][0]
        assessment_id = str(uuid.UUID(assessment["id"]))
        mark_path = (f"/api/v1/academic/departments/{DEPT}/assessments/"
                     f"{assessment_id}")
        saved = await send(guide, mark_path + "/draft", {
            "expectedAssessmentVersion": assessment["version"],
            "scores": score_rows(review, 20)
        }, "Guide saves synthetic marks", "corr-" + nonce + "-marks")
        await send(guide, mark_path + "/finalize", {
            "expectedAssessmentVersion": saved["assessmentVersion"]
        }, "Guide finalizes synthetic marks", "corr-" + nonce + "-finalize")
        await send(coord,
            f"/api/v1/academic/departments/{DEPT}/reviews/{review_id}/publish", {
            "expectedReviewRevision": review["revision"]
        }, "Publish synthetic stage", "corr-" + nonce + "-stage-publish")
        original_release = await send(coord, cmd, {
            "action": "PUBLISH_FINAL", "projectId": project_id,
            "expectedVersion": 0
        }, "Publish synthetic overall result", "corr-" + nonce + "-overall")
        source_result_id = str(uuid.UUID(original_release["id"]))
        before_student = await fetch(student,
            f"/api/v1/documents/departments/{DEPT}?project={project_id}",
            "Student original result")
        v1 = released_values(one_project(before_student, project_id) or {})
        require(len(v1) == 1 and v1[0][0] == 1,
                "Student must see original overall release")
        require(v1[0][1] == "40.00", "Unanticipated initial stage calculation; stop before correction")
        # Read the freshly published stage's current review revision from the
        # signed Faculty workspace, not from direct owner SQL or a seeded fixture.
        work = await fetch(guide, "/api/v1/workspace", "Stage correction current Faculty workspace")
        current_review = next((x for x in work.get("reviews", [])
                               if x.get("id") == review_id and x.get("projectId") == project_id), None)
        require(current_review is not None, "Current Faculty stage review not accessible")
        require(current_review.get("revision") is not None, "Current stage revision required")
        changed_scores = score_rows(current_review, 21)
        correction = await send(guide, cmd, {
            "action": "REQUEST_CORRECTION",
            "reviewId": review_id,
            "assessmentId": assessment_id,
            "expectedReviewRevision": current_review["revision"],
            "scores": changed_scores,
            "reason": "Separate synthetic finalized stage criterion correction",
            "exceptional": True
        }, "Guide requests real corrected stage marks", "stage-" + nonce + "-stage-request")
        request_id = str(uuid.UUID(correction["id"]))
        unauthorized = await student.post(cmd, {
            "action": "AUTHORIZE_CORRECTION", "requestId": request_id,
            "approved": True, "exceptional": True
        }, key="stage-" + nonce + "-student-denied")
        require(unauthorized.status_code in (401,403),
                "Student must not authorize finalized stage mark corrections")
        await send(coord, cmd, {
            "action": "AUTHORIZE_CORRECTION", "requestId": request_id,
            "approved": True, "exceptional": True,
            "reason": "Synthetic updated evaluator stage evidence authorized"
        }, "Coordinator authorizes corrected stage evidence", "stage-" + nonce + "-stage-approve")
        await send(guide, cmd, {
            "action": "APPLY_CORRECTION", "requestId": request_id,
            "exceptional": True,
            "reason": "Apply authorized synthetic stage criterion update"
        }, "Guide applies authorized stage evidence", "stage-" + nonce + "-stage-apply")
        still_old = await fetch(student,
            f"/api/v1/documents/departments/{DEPT}?project={project_id}",
            "Student result remains unchanged until Guide re-release")
        require(released_values(one_project(still_old,project_id) or {}) == v1,
                "Published overall total changed before a fresh Guide request")
        change_request = await send(guide, cmd, {
            "action": "REQUEST_FINAL_REVISION",
            "projectId": project_id, "expectedVersion": 1,
            "mode": "STAGE_EVIDENCE",
            "reason": "Release completed and authorized synthetic corrected stage evidence"
        }, "Guide explicitly requests updated-stage-sources re-release",
           "stage-" + nonce + "-overall-request")
        overall_request = str(uuid.UUID(change_request["id"]))
        listing = await fetch(coord,
            f"/api/v1/courses/offerings/{offering_id}/final-revisions?page=1",
            "Coordinator stage-evidence request queue")
        require(any(x.get("id") == overall_request
                    and x.get("type") == "STAGE_EVIDENCE_OVERALL_CORRECTION"
                    for x in listing.get("requests", [])),
                "Actual stage evidence request missing from Coordinator queue")
        deny = await student.post(cmd,{
            "action":"AUTHORIZE_FINAL_REVISION","requestId":overall_request,
            "approved":True
        },key="stage-" + nonce + "-student-publish-denied")
        require(deny.status_code in (401,403),
                "Student must not approve stage-evidence overall re-release")
        decision = await send(coord,cmd,{
            "action":"AUTHORIZE_FINAL_REVISION","requestId":overall_request,
            "approved":True,"reason":"Synthetic prior corrected stage evidence re-release"
        },"Coordinator approves corrected stage-based new overall result",
           "stage-" + nonce + "-overall-approve")
        require(decision.get("newVersion")==2,"Successor overall result missing")
        student_after=await fetch(student,
            f"/api/v1/documents/departments/{DEPT}?project={project_id}",
            "Student previous and re-released total history")
        actual_versions=released_values(one_project(student_after,project_id) or {})
        require(actual_versions==[(1,"40.00"),(2,"42.00")],
                "Student results do not reflect the real changed stage evidence")
        details=await fetch(coord,
            f"/api/v1/courses/offerings/{offering_id}/details",
            "Coordinator stage source audit")
        releases=sorted((x for x in details.get("overallResults",[])
                         if x.get("project_id")==project_id),key=lambda x:x["version"])
        require(len(releases)==2 and releases[0]["id"]==source_result_id
                and releases[1]["supersedes_id"]==source_result_id
                and releases[0]["sources"]!=releases[1]["sources"],
                "Updated stage sources or original overall lineage not preserved")
        existing_after=await fetch(student,
            f"/api/v1/documents/departments/{DEPT}?project={ORIGINAL_PROJECT}",
            "Verify original historical result unchanged")
        require(released_values(one_project(existing_after,ORIGINAL_PROJECT) or {})==original_old,
                "Historical academic project unexpectedly changed")
        print("PASS_HOSTED_GENUINE_STAGE_EVIDENCE_CORRECTION "
              "stage_correction_through_signed_faculty_coordinator_api=true "
              "overall_v1=40.00 overall_v2=42.00 "
              "stage_sources_changed=true original_historical_project_unchanged=true "
              "one_synthetic_project=true",flush=True)
    finally:
        for user in persons.values():
            await user.close()
        if created:
            print("SYNTHETIC_CORRECTION_FIXTURE_RETAINED: "
                  "no historical records modified or deleted; " +
                  ",".join(created.keys()), flush=True)


def self_test():
    require(new_marks("40.00") == "41.00", "Test mark increment contract")
    require(new_marks("100.00") == "99.00", "Test mark upper bound contract")
    entry = {"overallResults": [
        {"version": 1, "results": {STUDENT_ID: "40.00"}},
        {"version": 2, "results": {STUDENT_ID: "41.00"}},
    ]}
    require(released_values(entry) == [(1, "40.00"), (2, "41.00")],
            "Released history parser contract")
    require(MAX_NEW_PROJECTS == 1 and DEPT != OLD_OFFERING,
            "Bounded synthetic fixture safety contract")
    print("PASS genuine stage-evidence correction diagnostic no-network preflight")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    elif sys.argv[1:]:
        sys.exit("Only --self-test or explicit manual approved run supported")
    else:
        try:
            asyncio.run(run())
        except (AcceptanceFailure, httpx.HTTPError, asyncio.TimeoutError, ValueError, KeyError) as exc:
            # Never log response bodies or authentication secrets.
            print(f"HOSTED_STAGE_EVIDENCE_FAILED {type(exc).__name__}: {str(exc)[:180]}",
                  file=sys.stderr)
            sys.exit(1)
