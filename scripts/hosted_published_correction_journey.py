"""Bounded actual-Render signed-role published correction acceptance.

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
    BASE, PHRASE, TIMEOUT, AcceptanceFailure, Reviewer, json_success,
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
    require(os.getenv("SMARTPRO_HOSTED_CORRECTION_APPROVAL") == "RUN_SYNTHETIC_PUBLISHED_CORRECTION",
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
        name = "SYN-CORR-" + nonce.upper()
        created_type = await send(admin, setup_path, {
            "action": "RECORD", "kind": "TYPE",
            "configuration": {"code": name, "label": "Synthetic correction acceptance only"},
            "authority": authority, "reason": "Synthetic reviewer workflow acceptance"
        }, "Create separate synthetic curriculum type", "corr-" + nonce + "-type")
        type_id = str(uuid.UUID(created_type["id"]))
        config = dict(original_config, curriculumTypeId=type_id,
                      adminRoleId=admin_role)
        offering_created = await send(admin, setup_path, {
            "action": "RECORD", "kind": "OFFERING",
            "configuration": config, "authority": authority,
            "reason": "Dedicated synthetic correction-enabled reviewer offering"
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
        # HOD establishes a NEW versioned policy; never flip the original
        # framework's correction flag in place.
        cfg = dict(source_framework["configuration"], allowFinalCorrections=True)
        cmd = f"/api/v1/courses/offerings/{offering_id}/commands"
        framework = await send(hod, cmd, {
            "action": "FRAMEWORK", "expectedVersion": 0,
            "configuration": cfg, "authority": None,
            "reason": "Synthetic correction-enabled acceptance scheme"
        }, "HOD creates versioned correction-enabled framework",
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
        corrected = new_marks(v1[0][1])
        correction = await send(guide, cmd, {
            "action": "REQUEST_FINAL_REVISION", "projectId": project_id,
            "expectedVersion": 1, "studentId": STUDENT_ID,
            "marks": corrected, "reason": "Synthetic test: verified overall total correction"
        }, "Assigned Guide requests exact published correction",
           "corr-" + nonce + "-request")
        request_id = str(uuid.UUID(correction["id"]))
        pending = await fetch(coord,
            f"/api/v1/courses/offerings/{offering_id}/final-revisions?page=1",
            "Coordinator published correction queue")
        require(any(x.get("id") == request_id for x in pending.get("requests", [])),
                "Coordinator cannot see pending Guide correction")
        denial = await student.post(cmd, {
            "action": "AUTHORIZE_FINAL_REVISION", "requestId": request_id,
            "approved": True
        }, key="corr-" + nonce + "-forbidden")
        require(denial.status_code in (401, 403),
                "Student must not authorize own published correction")
        decided = await send(coord, cmd, {
            "action": "AUTHORIZE_FINAL_REVISION", "requestId": request_id,
            "approved": True,
            "reason": "Synthetic acceptance decision"
        }, "Coordinator approves and publishes successor",
           "corr-" + nonce + "-decision")
        require(decided.get("newVersion") == 2, "Successor release version missing")
        after_student = await fetch(student,
            f"/api/v1/documents/departments/{DEPT}?project={project_id}",
            "Student versioned release history")
        versions = released_values(one_project(after_student, project_id) or {})
        require(versions == [(1, v1[0][1]), (2, corrected)],
                f"Student original/successor history incorrect: {[v for v, _ in versions]}")
        details = await fetch(coord, f"/api/v1/courses/offerings/{offering_id}/details",
                              "Coordinator final release read")
        releases = [x for x in details.get("overallResults", [])
                    if x.get("project_id") == project_id]
        require(len(releases) == 2, "Both overall releases must be retained")
        releases.sort(key=lambda x: x["version"])
        require(releases[0]["id"] == source_result_id and
                releases[1]["supersedes_id"] == source_result_id and
                releases[0]["sources"] == releases[1]["sources"],
                "Original published release and stage sources must be immutable")
        guide_read = await fetch(guide,
            f"/api/v1/me/published-corrections?projectId={project_id}&page=1",
            "Guide correction history")
        require(any(x.get("id") == request_id for x in guide_read.get("requests", [])),
                "Guide cannot see authorized request history")
        existing_after = await fetch(student,
            f"/api/v1/documents/departments/{DEPT}?project={ORIGINAL_PROJECT}",
            "Existing published project unchanged")
        require(released_values(one_project(existing_after, ORIGINAL_PROJECT) or {}) == original_old,
                "Original historical result was modified by synthetic workflow")
        print(f"PASS_HOSTED_PUBLISHED_CORRECTION original_project_unchanged=true "
              f"synthetic_offering={offering_id} synthetic_project={project_id} "
              f"original_version=1 successor_version=2 student_history=2 "
              f"stage_sources_immutable=true signed_guide_coordinator_student=true",
              flush=True)
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
    print("PASS hosted correction diagnostic no-network preflight")


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
            print(f"HOSTED_CORRECTION_FAILED {type(exc).__name__}: {str(exc)[:180]}",
                  file=sys.stderr)
            sys.exit(1)
