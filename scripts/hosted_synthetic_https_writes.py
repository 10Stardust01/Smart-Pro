"""Bounded, authenticated HTTPS academic-write acceptance on Render reviewer staging.

Creates a new uniquely named synthetic team/project. No existing project is edited.
Manual-only. No password/cookie/file body logged. One short 2/4-client PDF wave,
one 2-client submission wave, and 2-client marks/finalization/publication races.
Uses free GitHub Actions and existing Render Free service. No retries on failures.
"""
import asyncio
import hashlib
import json
import os
import re
import sys
import time
import uuid
from decimal import Decimal
from math import ceil
from urllib.parse import urljoin

import httpx

BASE = "https://smartpro-reviewer-25775915.onrender.com"
PHRASE = "RUN_SYNTHETIC_HOSTED_WRITES"
SESSION_COOKIE = "smartpro_staging_session"
THRESHOLD_SECONDS = 10
TIMEOUT = httpx.Timeout(25.0, connect=15.0)


class AcceptanceFailure(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise AcceptanceFailure(message)


def get_config():
    require(os.getenv("SMARTPRO_HOSTED_WRITE_APPROVAL") == PHRASE,
            "Manual synthetic-write approval phrase missing")
    accounts = json.loads(os.environ.get("SMARTPRO_HOSTED_TEST_ACCOUNTS") or "{}")
    for role in ("Student", "Faculty", "Coordinator"):
        entry = accounts.get(role)
        require(isinstance(entry, dict) and isinstance(entry.get("alias"), str)
                and isinstance(entry.get("password"), str) and entry["password"],
                f"Private {role} reviewer account not configured")
    values = {}
    for field in ("DEPARTMENT_ID", "OFFERING_ID", "GUIDE_USER_ID", "TEAM_ID"):
        value = os.getenv("SMARTPRO_WRITE_" + field, "")
        values[field] = str(uuid.UUID(value))
    count = int(os.getenv("SMARTPRO_WRITE_UPLOAD_CLIENTS", "2"))
    require(count in (2, 4), "Only two or four concurrent upload clients allowed")
    stage_key = os.getenv("SMARTPRO_WRITE_STAGE_KEY", "evidence")
    require(bool(re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", stage_key)),
            "Approved stage key required")
    return accounts, values, count, stage_key


def pdf_bytes(label):
    require(bool(re.fullmatch(r"[A-Za-z0-9 _-]{1,90}", label)), "Safe PDF label required")
    content = f"BT /F1 12 Tf 72 720 Td ({label}) Tj ET\n".encode("ascii")
    parts = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    data = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for index, obj in enumerate(parts, 1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    at = len(data)
    data.extend(f"xref\n0 {len(parts)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(parts)+1} /Root 1 0 R >>\nstartxref\n{at}\n%%EOF\n".encode())
    return bytes(data)


class Reviewer:
    def __init__(self, role, entry):
        self.role = role
        self.entry = entry
        self.client = httpx.AsyncClient(
            base_url=BASE, follow_redirects=False, verify=True,
            timeout=TIMEOUT, headers={"User-Agent": "SMARTPRO-bounded-academic-acceptance/20261110"})
        self.csrf = None

    async def close(self):
        await self.client.aclose()

    async def login(self):
        page = await self.client.get("/reviewer/login")
        require(page.status_code == 200, f"{self.role} login form HTTP {page.status_code}")
        found = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.text)
        require(found, f"{self.role} login CSRF missing")
        reply = await self.client.post(
            "/reviewer/login",
            data={"username": self.entry["alias"], "password": self.entry["password"],
                  "csrfmiddlewaretoken": found.group(1)},
            headers={"Referer": BASE + "/reviewer/login"})
        require(reply.status_code == 302 and reply.headers.get("location") == "/",
                f"{self.role} login not accepted: HTTP {reply.status_code}; check private reviewer aliases")
        self.csrf = self.client.cookies.get("csrftoken")
        require(self.csrf and self.client.cookies.get(SESSION_COOKIE),
                f"{self.role} signed session or CSRF cookie missing")
        who = await self.get("/api/v1/workspace")
        require(who.status_code == 200, f"{self.role} scoped workspace HTTP {who.status_code}")
        return who.json()

    def headers(self, *, key=None):
        result = {"X-Smartpro-Role": self.role, "Referer": BASE + "/",
                  "X-CSRFToken": self.csrf}
        if key:
            result["Idempotency-Key"] = key
        return result

    async def get(self, path):
        return await self.client.get(path, headers={"X-Smartpro-Role": self.role})

    async def post(self, path, data, *, key, files=None):
        headers = self.headers(key=key)
        if files is not None:
            return await self.client.post(path, files=files, headers=headers)
        return await self.client.post(path, json=data, headers=headers)


def json_success(response, label, codes=(200,)):
    require(response.status_code in codes, f"{label} unexpected HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise AcceptanceFailure(f"{label} non-JSON response") from None


def case_from(value, pid):
    if isinstance(value, dict):
        if isinstance(value.get("case"), dict) and (
                value.get("id") == pid or value.get("projectId") == pid or
                isinstance(value.get("project"), dict) and value["project"].get("id") == pid):
            return value["case"]
        for child in value.values():
            result = case_from(child, pid)
            if result is not None:
                return result
    if isinstance(value, list):
        for child in value:
            result = case_from(child, pid)
            if result is not None:
                return result
    return None


def wave_summary(name, results):
    """Each result is (status, elapsed seconds, optional response bytes)."""
    times = sorted(t for _, t, _ in results)
    p95 = times[ceil(.95 * len(times)) - 1]
    print(f"HTTPS_WAVE {name}: {len(results)} clients; p95={p95:.3f}s; max={times[-1]:.3f}s",
          flush=True)
    require(all(status < 500 for status, _, _ in results), f"{name}: server error")
    require(p95 <= THRESHOLD_SECONDS, f"{name}: p95 exceeded bounded acceptance threshold")


async def ready(client):
    response = await client.get(BASE + "/health/ready")
    require(response.status_code == 200, f"Hosted readiness HTTP {response.status_code}")


async def simultaneous(jobs):
    gate = asyncio.Event()

    async def call(fn):
        await gate.wait()
        started = time.monotonic()
        response = await fn()
        return response.status_code, time.monotonic() - started, response

    tasks = [asyncio.create_task(call(job)) for job in jobs]
    gate.set()
    return await asyncio.gather(*tasks)


def score_rows(review, candidate):
    result = []
    for criterion in review["criteria"]:
        maximum = Decimal(str(criterion["maximum"]))
        require(maximum > 0, "Rubric maximum must be positive")
        marks = min(Decimal(candidate), maximum)
        recipients = [None] if criterion["scope"] == "TEAM" else [x["id"] for x in review["roster"]]
        for student_id in recipients:
            result.append({"criterionId": criterion["id"], "studentId": student_id,
                           "marks": str(marks)})
    require(result, "Frozen rubric or roster is empty")
    return result


async def run():
    accounts, targets, uploads, stage_key = get_config()
    dept, offering, guide, team_id = (targets[k] for k in ("DEPARTMENT_ID", "OFFERING_ID", "GUIDE_USER_ID", "TEAM_ID"))
    nonce = uuid.uuid4().hex[:10]
    clients = [Reviewer("Student", accounts["Student"]) for _ in range(uploads)]
    faculty = [Reviewer("Faculty", accounts["Faculty"]) for _ in range(2)]
    coordinators = [Reviewer("Coordinator", accounts["Coordinator"]) for _ in range(2)]
    synthetic_project = None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, verify=True) as public:
            await ready(public)
        # Sign in sequentially to avoid unnecessarily stressing the reviewer login.
        for user in clients + faculty + coordinators:
            await user.login()
        student, coordinator = clients[0], coordinators[0]
        offerings = json_success(await student.get("/api/v1/me/curriculum-offerings"), "Student offerings")
        require(any(x.get("id") == offering for x in offerings.get("results", [])),
                "Chosen offering is not listed for this Student; no writes were attempted")
        details = json_success(await coordinator.get(f"/api/v1/courses/offerings/{offering}/details"), "Course details")
        frameworks = details.get("frameworks") or []
        plans = details.get("plans") or []
        require(frameworks and plans, "Chosen offering has no approved framework and plan")
        require(any(x.get("key") == stage_key for f in frameworks
                    for x in (f.get("configuration", {}).get("stages") or [])),
                "Selected stage key does not exist in approved framework")
        # Use the pre-existing verified synthetic team. The staging Student
        # already has an active membership and cannot join another team in the
        # same offering; creating another would fail before testing anything.
        # Never transfer/end any membership or modify an existing project.
        memberships = json_success(await student.get("/api/v1/me/memberships"),
                                   "Student current memberships")
        current_team = json.dumps(memberships, separators=(",", ":"))
        require(team_id in current_team and offering in current_team,
                "Configured synthetic team is not in the signed-in Student's memberships")
        project = json_success(await student.post("/api/v1/projects",
            {"offeringId": offering, "teamId": team_id,
             "title": f"[SYNTHETIC-HTTPS-ACCEPTANCE] {nonce}",
             "description": "Dedicated automated HTTPS contention verification; not student coursework"},
            key=f"accept-{nonce}-project"), "Create new synthetic project", (201,))
        synthetic_project = str(uuid.UUID(project["id"]))
        require(project["id"] == synthetic_project, "Invalid new project")
        require(project.get("teamId") == team_id, "Project not registered to the verified synthetic team")
        print(f"CREATED_SYNTHETIC_PROJECT {synthetic_project}; marker={nonce}; retained for audit", flush=True)
        assigned = await coordinator.post(f"/api/v1/staff/departments/{dept}/projects/{synthetic_project}/guide",
            {"facultyId": guide, "expectedGuideId": None}, key=f"accept-{nonce}-guide")
        json_success(assigned, "Assign synthetic project's Guide")
        async with httpx.AsyncClient(timeout=TIMEOUT, verify=True) as public:
            await ready(public)
        # Genuine HTTPS multipart uploads; each Student session uses a distinct client and key.
        pdfs = [pdf_bytes(f"SMARTPRO ACCEPTANCE {nonce} PDF {i}") for i in range(uploads)]
        url = f"/api/v1/documents/departments/{dept}/projects/{synthetic_project}/uploads"
        uploading = await simultaneous([
            (lambda i=i: clients[i].post(url, None, key=f"accept-{nonce}-pdf-{i}",
                files={"file": (f"synthetic-{nonce}-{i}.pdf", pdfs[i], "application/pdf")}))
            for i in range(uploads)
        ])
        wave_summary("concurrent_private_pdf_uploads", uploading)
        versions = []
        for i, (code, _, response) in enumerate(uploading):
            version = json_success(response, f"Upload {i}")["documentVersionId"]
            versions.append(str(uuid.UUID(version)))
        require(len(set(versions)) == uploads, "Concurrent upload versions were not distinct")
        for i, vid in enumerate(versions):
            downloaded = await student.get(f"/api/v1/document-versions/{vid}/content?download=1")
            require(downloaded.status_code == 200, f"Private PDF download {i} HTTP {downloaded.status_code}")
            require(hashlib.sha256(downloaded.content).digest() == hashlib.sha256(pdfs[i]).digest(),
                    f"Private PDF bytes differ from uploaded PDF {i}")
        print(f"PASS private_pdf_sha256: {len(versions)}/{uploads} HTTPS downloads byte-identical", flush=True)

        snapshot = json_success(await student.get(
            f"/api/v1/documents/departments/{dept}?project={synthetic_project}"),
            "Student document case")
        case = case_from(snapshot, synthetic_project)
        require(case and str(case.get("version", "")).isdigit(),
                "Cannot obtain scoped document case revision; stop before submission race")
        case_revision = int(case["version"])
        submit_path = f"/api/v1/documents/departments/{dept}"
        contenders = await simultaneous([
            (lambda i=i: clients[i].post(submit_path,
                {"action": "SUBMIT", "projectId": synthetic_project,
                 "documentVersionId": versions[i], "expectedCaseVersion": case_revision},
                key=f"accept-{nonce}-submit-{i}"))
            for i in range(2)
        ])
        wave_summary("simultaneous_student_submissions", contenders)
        require(sorted(code for code, _, _ in contenders) == [200, 409],
                f"Competing submission statuses {[code for code, _, _ in contenders]}")
        print("PASS competing_student_submissions: one accepted, one stale rejected", flush=True)

        async with httpx.AsyncClient(timeout=TIMEOUT, verify=True) as public:
            await ready(public)
        stage = json_success(await coordinator.post(f"/api/v1/courses/offerings/{offering}/commands",
            {"action": "CREATE_STAGE", "projectId": synthetic_project,
             "stageKey": stage_key, "facultyIds": []},
            key=f"accept-{nonce}-stage"), "Create synthetic review stage")
        review_id = str(uuid.UUID(stage.get("reviewId") or stage["id"]))
        workspace = json_success(await faculty[0].get("/api/v1/workspace"), "Faculty assessment workspace")
        review = next((x for x in workspace.get("reviews", [])
                       if x.get("id") == review_id and x.get("projectId") == synthetic_project), None)
        require(review is not None, "New synthetic review missing from assigned Faculty workspace")
        entries = [x for x in review["assessments"] if x.get("state") == "DRAFT"]
        require(len(entries) == 1, "Expected one fresh draft assessment")
        assessment_id = str(uuid.UUID(entries[0]["id"]))
        draft_version = entries[0]["version"]
        mark_path = f"/api/v1/academic/departments/{dept}/assessments/{assessment_id}"
        drafts = await simultaneous([
            (lambda i=i: faculty[i].post(mark_path + "/draft",
                {"expectedAssessmentVersion": draft_version,
                 "scores": score_rows(review, 1 if i == 0 else 2)},
                key=f"accept-{nonce}-marks-{i}"))
            for i in range(2)
        ])
        wave_summary("concurrent_faculty_marks", drafts)
        require(sorted(code for code, _, _ in drafts) == [200, 409],
                f"Competing marks statuses {[code for code, _, _ in drafts]}")
        winner = next(response.json() for code, _, response in drafts if code == 200)
        require(winner.get("state") == "DRAFT", "Winning save did not remain draft")
        next_version = winner["assessmentVersion"]
        finals = await simultaneous([
            (lambda i=i: faculty[i].post(mark_path + "/finalize",
                {"expectedAssessmentVersion": next_version},
                key=f"accept-{nonce}-final-{i}"))
            for i in range(2)
        ])
        wave_summary("concurrent_faculty_finalization", finals)
        require(sorted(code for code, _, _ in finals) == [200, 409],
                f"Competing finalize statuses {[code for code, _, _ in finals]}")
        current = json_success(await faculty[0].get("/api/v1/workspace"), "Faculty final state")
        updated = next(x for x in current["reviews"] if x["id"] == review_id)
        verified = next(x for x in updated["assessments"] if x["id"] == assessment_id)
        require(verified["state"] == "FINALIZED",
                "Assessment not finalized after concurrent update")
        require(verified["version"] == next_version + 1, "Assessment version was not advanced once")
        print("PASS marks and finalize: one success and one stale rejection per wave", flush=True)

        async with httpx.AsyncClient(timeout=TIMEOUT, verify=True) as public:
            await ready(public)
        published = await simultaneous([
            (lambda i=i: coordinators[i].post(
                f"/api/v1/academic/departments/{dept}/reviews/{review_id}/publish",
                {"expectedReviewRevision": review["revision"]},
                key=f"accept-{nonce}-publish-{i}"))
            for i in range(2)
        ])
        wave_summary("concurrent_stage_publication", published)
        require(sorted(code for code, _, _ in published) == [200, 409],
                f"Competing publish statuses {[code for code, _, _ in published]}")
        result = json_success(await coordinator.get(
            f"/api/v1/academic/departments/{dept}/reviews/{review_id}/results"),
            "Published stage result")
        require(len(result.get("results", [])) == 1,
                "Expected exactly one published result on synthetic review")
        print("PASS synthetic stage publication: exactly one released result", flush=True)
        print("PASS_HOSTED_HTTPS_ACADEMIC_WRITES all bounded waves; synthetic project retained for audit",
              flush=True)
    finally:
        for user in clients + faculty + coordinators:
            await user.close()
        if synthetic_project:
            print("SYNTHETIC_FIXTURE_RETAINED: academic audit history is not deleted", flush=True)


def self_test():
    for label in ("SMARTPRO ACCEPTANCE ABC123 PDF 0", "SMARTPRO ACCEPTANCE ABC123 PDF 1"):
        data = pdf_bytes(label)
        require(data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF"),
                "PDF construction failed")
        require(b"/Type /Page " in data and len(data) < 2048, "PDF is not bounded")
    assert case_from({"projects": [{"id": "one", "case": {"version": 1}}]}, "one") == {"version": 1}
    require(len(score_rows({"criteria": [{"id": "a", "scope": "TEAM", "maximum": "60"}],
                            "roster": [{"id": "student"}]}, 2)) == 1,
            "Marks construction failed")
    print("PASS harness preflight: bounded PDF, document scope, score generation")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    elif not sys.argv[1:]:
        try:
            asyncio.run(run())
        except (AcceptanceFailure, httpx.HTTPError, asyncio.TimeoutError, ValueError, KeyError) as error:
            # Never print raw HTTP responses or stored credentials.
            print(f"HOSTED_TEST_FAILED: {type(error).__name__}: {str(error)[:180]}", file=sys.stderr)
            sys.exit(1)
    else:
        sys.exit("Only --self-test or the explicit manual configured run is supported")
