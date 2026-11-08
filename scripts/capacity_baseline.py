"""Loopback-only synthetic capacity harness. Never point this at smartpro_dev."""

import argparse
import asyncio
import json
import math
import os
import re
import secrets
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import Event, Lock, Thread, local
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

import psycopg
from application import create_workspace
from department_demo import COORD, CSE, FACULTY, ROOT, settings
from psycopg.conninfo import make_conninfo
from synthetic_synopsis import pdf_bytes

from db_setup import execute_file

ADMIN = ("department-admin", "Admin")
HOD = ("staff-policy", "HOD")
COORDINATOR = ("coordinator", "Coordinator")
GUIDE = ("faculty-a", "Faculty")
STAFF = f"/api/v1/staff/departments/{CSE}"
ACADEMIC = f"/api/v1/academic/departments/{CSE}"
DOC = f"/api/v1/documents/departments/{CSE}"
COURSES = "/api/v1/courses/offerings"
PREFIX = "smartpro_test_demo_acceptance_"
ROOT_TEST = ROOT / ".test-data"


def identity(n):
    return f"capacity-{n}", str(UUID(int=(1 << 120) + n))


def load_target(path):
    path = path.resolve()
    target = json.loads(path.read_text(encoding="utf8"))
    name = target["database"]
    if (
        target.get("purpose") != "ISOLATED_BROWSER_ACCEPTANCE"
        or not re.fullmatch(PREFIX + r"[a-f0-9]{12}", name)
        or path != ROOT_TEST / (name + ".json")
        or Path(target["storage"]).resolve() != ROOT_TEST / name
    ):
        raise ValueError("Expected a fresh application.py isolated workspace manifest")
    _, owner, runtime = settings(ROOT_TEST / "pg-memberships.env.json")
    if any(c["host"] not in ("localhost", "127.0.0.1") for c in (owner, runtime)):
        raise ValueError("PostgreSQL must be on loopback")
    return target, dict(owner, dbname=name), dict(runtime, dbname=name)


def serve(path, port, students, threads, conn_age, profile_sql, trace_http=False):
    import uvicorn
    from uvicorn.middleware.wsgi import WSGIMiddleware

    target, _, runtime = load_target(path)
    os.environ.update(
        DATABASE_URL=make_conninfo(**runtime),
        DJANGO_SETTINGS_MODULE="smartpro.settings",
        DJANGO_SECRET_KEY=secrets.token_hex(32),
        SMARTPRO_DEPLOYMENT="test",
        SMARTPRO_ENV="demo",
        SMARTPRO_DEMO_AUTH="YES",
        SMARTPRO_DEPARTMENT_DEMO="YES",
        SMARTPRO_UI="YES",
        SMARTPRO_DATA_DIR=target["storage"],
        SMARTPRO_DB_CONN_MAX_AGE=str(conn_age),
        SMARTPRO_IDENTITY_RESOLVER="",
    )
    for gate in (
        "CURRICULUM",
        "TEAM",
        "MEMBERSHIP",
        "PROJECT",
        "STAFF",
        "ACADEMIC",
        "DOCUMENT",
        "COURSE",
    ):
        os.environ[f"SMARTPRO_{gate}_API"] = "YES"
    sys.path.insert(0, str(ROOT / "backend"))
    from django.db import connection
    from smartpro.identity import DEMO_USERS
    from smartpro.wsgi import application

    DEMO_USERS.update(identity(n) for n in range(1, students + 1))

    def scoped_application(environ, start_response):
        started = time.perf_counter()
        count = 0
        sql_time = 0.0

        def trace(execute, statement, params, many, context):
            nonlocal count, sql_time
            start = time.perf_counter()
            try:
                return execute(statement, params, many, context)
            finally:
                count += 1
                sql_time += time.perf_counter() - start

        # A benchmark client must prove this is the intended isolated server.
        def respond(status, headers, exc_info=None):
            extra = [("X-Smartpro-Capacity-Target", target["database"])]
            if profile_sql:
                extra.append(
                    (
                        "X-Smartpro-Capacity-SQL",
                        f"{count},{sql_time * 1000:.3f},{(time.perf_counter() - started) * 1000:.3f}",
                    )
                )
            return start_response(
                status,
                [*headers, *extra],
                exc_info,
            )

        if profile_sql:
            with connection.execute_wrapper(trace):
                response = application(environ, respond)
        else:
            response = application(environ, respond)
        try:
            yield from response
        finally:
            # The installed Uvicorn WSGI adapter does not call iterable.close().
            # Ensure Django releases request resources according to CONN_MAX_AGE.
            response.close()

    bridge = WSGIMiddleware(scoped_application, workers=threads)
    in_flight = 0

    async def traced(scope, receive, send):
        nonlocal in_flight
        if scope["type"] != "http":
            return await bridge(scope, receive, send)
        headers = dict(scope["headers"])
        rid = headers.get(b"x-smartpro-benchmark-id", b"").decode("ascii", errors="replace")
        record = bool(re.fullmatch("[a-f0-9]{32}", rid))
        delay = record and headers.get(b"x-smartpro-benchmark-delay") == b"after-commit"
        status = None
        in_flight += 1
        at_entry = in_flight

        async def respond(message):
            nonlocal status, delay
            if message["type"] == "http.response.start":
                status = message["status"]
                if record:
                    print(
                        json.dumps({"request": rid, "django_status": status, "in_flight_at_entry": at_entry}),
                        flush=True,
                    )
            elif delay and status in (200, 201):
                delay = False
                await asyncio.sleep(3)
            await send(message)

        try:
            await bridge(scope, receive, respond)
        finally:
            in_flight -= 1

    uvicorn.run(
        traced if trace_http else bridge,
        host="127.0.0.1",
        port=port,
        access_log=False,
        limit_concurrency=threads * 4,
        log_level="error",
    )


class Client:
    def __init__(self, port, database):
        self.base = f"http://127.0.0.1:{port}"
        self.database = database
        self.samples = []
        self.sql = []
        self.outcomes = []
        self.current = local()

    def request(
        self,
        actor,
        path,
        body=None,
        *,
        key=None,
        mime="application/json",
        expected=(200, 201),
        timeout=25,
        delay=False,
    ):
        data = json.dumps(body).encode() if isinstance(body, dict) else body
        rid = uuid4().hex
        headers = {"X-Demo-User": actor[0], "X-Smartpro-Role": actor[1], "X-Smartpro-Benchmark-Id": rid}
        if delay:
            headers["X-Smartpro-Benchmark-Delay"] = "after-commit"
        if data is not None:
            headers.update({"Content-Type": mime, "Idempotency-Key": key or uuid4().hex})
        start = time.perf_counter()
        label = re.sub(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", ":id", path.split("?")[0])
        label += ":" + body["action"] if isinstance(body, dict) and "action" in body else ""
        status = 0
        outcome = "other"
        try:
            try:
                response = urlopen(Request(self.base + path, data, headers), timeout=timeout)
            except HTTPError as exc:
                response = exc
            with response:
                status = response.code
                raw = response.read()
                if profile := response.headers.get("X-Smartpro-Capacity-SQL"):
                    self.sql.append(tuple(map(float, profile.split(","))))
                if response.headers.get("X-Smartpro-Capacity-Target") != self.database:
                    if (
                        status == 503
                        and response.headers.get("Server") == "uvicorn"
                        and raw == b"Service Unavailable"
                    ):
                        outcome = "admission"
                        raise RuntimeError("Uvicorn admission limit (HTTP 503 before Django)")
                    raise RuntimeError(f"Unconfirmed benchmark server (HTTP {status})")
            if status not in expected:
                outcome = "server_timeout" if status == 504 else "http_error"
                raise RuntimeError(f"{actor[1]} {path}: HTTP {status} {raw[:300]!r}")
            value = json.loads(raw) if raw.startswith((b"{", b"[")) else raw
            outcome = "success" if 200 <= status < 300 else "expected_denial"
        except OSError as exc:
            outcome = (
                "client_timeout"
                if isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError)
                else "transport_error"
            )
            raise
        finally:
            elapsed = (time.perf_counter() - start) * 1000
            self.samples.append((label, status, elapsed))
            self.outcomes.append(
                {
                    "request": rid,
                    "outcome": outcome,
                    "status": status,
                    "operation": label,
                    "elapsed_ms": round(elapsed, 3),
                }
            )
            self.current.outcome = outcome if outcome not in ("success", "expected_denial") else None
        return value, (time.perf_counter() - start) * 1000

    def call(self, *args, **kwargs):
        return self.request(*args, **kwargs)[0]


def student(n):
    return identity(n)[0], "Student"


def seed(client, owner, count):
    with psycopg.connect(**owner, autocommit=True) as db:
        if db.execute("SELECT count(*) FROM projects").fetchone()[0]:
            raise RuntimeError("Seeding requires an empty capacity database")
        mandate = db.execute(
            "SELECT id FROM academic_hod_mandates WHERE department_id=%s AND enabled",
            (CSE,),
        ).fetchone()[0]
        admin = db.execute(
            "SELECT id FROM department_role_assignments WHERE department_id=%s AND role_code='ACADEMIC_ADMIN'",
            (CSE,),
        ).fetchone()[0]
        with db.transaction(), db.cursor() as cursor:
            people = [
                (
                    identity(n)[1],
                    f"Synthetic student {n:05d}",
                    f"capacity-{n}@example.invalid",
                )
                for n in range(1, count * 2 + 1)
            ]
            cursor.executemany("INSERT INTO users(id,display_name,email) VALUES(%s,%s,%s)", people)
            cursor.executemany(
                "INSERT INTO department_role_assignments(user_id,department_id,role_code) VALUES(%s,%s,'STUDENT')",
                [(uid, CSE) for uid, _, _ in people],
            )
            cursor.executemany(
                "INSERT INTO student_profiles(user_id,usn,section,semester_key,department_id) VALUES(%s,%s,'A','SEM-3',%s)",
                [(uid, f"CAP-{n:05d}", CSE) for n, (uid, _, _) in enumerate(people, 1)],
            )
        authority = {
            "hodMandateId": str(mandate),
            "source": "EXTERNAL_INSTRUCTION",
            "confirmed": True,
            "reference": "",
        }

        def record(kind, configuration):
            return client.call(
                ADMIN,
                STAFF + "/setup",
                {
                    "action": "RECORD",
                    "kind": kind,
                    "configuration": configuration,
                    "authority": authority,
                },
            )

        cycle = record(
            "CYCLE",
            {"code": "CAP-2026", "startsOn": "2025-01-01", "endsOn": "2029-12-31"},
        )["id"]
        kind = record("TYPE", {"code": "CAP-STUDIO", "label": "Synthetic capacity studio"})["id"]
        policy = record(
            "PROJECT_POLICY",
            {
                "label": "Capacity project policy",
                "projectType": "MINI",
                "allowStudentRegistration": True,
            },
        )["id"]
        policy = record(
            "REVIEW_BLUEPRINT",
            {
                "policyVersionId": policy,
                "cycleId": cycle,
                "label": "Capacity evidence plan",
                "stages": [
                    {
                        "code": "CHECK",
                        "label": "Evidence review",
                        "mode": "TEAM",
                        "criteria": [{"label": "Evidence", "scope": "TEAM", "maximum": "100"}],
                    }
                ],
            },
        )["id"]
        team = record(
            "TEAM_POLICY",
            {
                "label": "Capacity teams",
                "allowJoin": True,
                "allowLeave": True,
                "allowTransfer": True,
                "minimumMembers": 1,
                "maximumMembers": 4,
                "sizeMode": "ADVISORY",
            },
        )["id"]
        config = {
            "curriculumTypeId": kind,
            "cycleId": cycle,
            "semester": "SEM-3",
            "projectPolicyId": policy,
            "teamPolicyId": team,
            "adminRoleId": str(admin),
            "visibleFrom": "2025-01-01T00:00:00Z",
            "visibleUntil": "2029-06-01T00:00:00Z",
            "submissionOpensAt": "2025-01-01T00:00:00Z",
            "submissionClosesAt": "2029-06-01T00:00:00Z",
            "maxBytes": 2097152,
            "facultyApprovalEnabled": True,
            "teamCreationEnabled": True,
        }
        offering = record("OFFERING", config)["offeringId"]
        command = f"{COURSES}/{offering}/commands"
        client.call(
            ADMIN,
            f"{COURSES}/{offering}/coordinators",
            {
                "userId": COORD,
                "expectedVersion": 0,
                "active": True,
                "validUntil": config["visibleUntil"],
                "responsibilities": [
                    "OVERVIEW",
                    "REQUIREMENTS",
                    "PLAN",
                    "GUIDE",
                    "EVALUATORS",
                    "SUBMISSIONS",
                    "DEADLINES",
                    "RESULTS",
                    "CORRECTIONS",
                    "HISTORY",
                ],
                "authority": None,
            },
        )
        availability, rev = db.execute(
            "SELECT availability,management_revision FROM curriculum_offerings WHERE id=%s",
            (offering,),
        ).fetchone()
        if availability != "ACTIVE":
            client.call(
                ADMIN,
                STAFF + "/offering-management",
                {
                    "action": "AVAILABILITY",
                    "offeringId": offering,
                    "expectedRevision": rev,
                    "availability": "ACTIVE",
                    "authority": authority,
                },
            )
        evaluation = client.call(
            HOD,
            ACADEMIC + "/policies",
            {
                "expectedRevision": 0,
                "evaluatorQuorum": 1,
                "aggregation": "MEAN",
                "evaluatorWeights": {},
            },
        )["id"]
        scheme, mode = db.execute(
            "SELECT v.id,m.id FROM review_definitions d JOIN scheme_versions v ON v.review_definition_id=d.id "
            "JOIN scheme_modes m ON m.scheme_version_id=v.id WHERE d.policy_version_id=%s",
            (policy,),
        ).fetchone()
        stages = [
            {
                "key": f"stage-{i}",
                "name": f"Evidence review {i}",
                "schemeVersionId": str(scheme),
                "schemeModeId": str(mode),
                "policyId": evaluation,
                "weight": "50",
                "required": True,
                "opensAt": config["submissionOpensAt"],
                "deadline": config["submissionClosesAt"],
            }
            for i in (1, 2)
        ]
        framework = client.call(
            HOD,
            command,
            {
                "action": "FRAMEWORK",
                "expectedVersion": 0,
                "authority": None,
                "configuration": {
                    "stages": stages,
                    "method": "WEIGHTED_NORMALIZED",
                    "rounding": "HALF_UP",
                    "decimalPlaces": 2,
                    "scale": "100",
                    "allowFinalCorrections": False,
                    "outsidePanelAuthorizer": True,
                    "maxExtensionDays": 10,
                    "publicationRoles": ["Coordinator", "HOD"],
                },
            },
        )["id"]
        client.call(
            COORDINATOR,
            command,
            {
                "action": "PLAN",
                "expectedVersion": 0,
                "frameworkId": framework,
                "schedules": {s["key"]: "2027-02-01T09:00:00Z" for s in stages},
            },
        )

    def project(n):
        actor = student(n)
        team_id = client.call(
            actor,
            "/api/v1/teams",
            {"offeringId": offering, "name": f"Capacity team {n:05d}"},
        )["id"]
        client.call(student(count + n), f"/api/v1/teams/{team_id}/memberships", {})
        pid = client.call(
            actor,
            "/api/v1/projects",
            {
                "offeringId": offering,
                "teamId": team_id,
                "title": f"Capacity project {n:05d}",
                "description": "Disposable academic capacity fixture",
            },
        )["id"]
        client.call(
            COORDINATOR,
            STAFF + f"/projects/{pid}/guide",
            {"facultyId": FACULTY, "expectedGuideId": None},
        )
        return pid

    with ThreadPoolExecutor(max_workers=8) as pool:
        projects = list(pool.map(project, range(1, count + 1)))
    return {"database": client.database, "offering": offering, "projects": projects}


def distribution(values):
    if not values:
        return {}
    ordered = sorted(values)
    return {
        f"p{p}": round(ordered[math.ceil(len(ordered) * p / 100) - 1], 1)
        for p, minimum in ((50, 1), (95, 20), (99, 100))
        if len(ordered) >= minimum
    }


def run_wave(client, owner, jobs, users, arrival, think=0.2):
    client.samples.clear()
    client.sql.clear()
    client.outcomes.clear()
    stop = Event()
    connections = []
    errors = []
    lock = Lock()
    active = peak = 0
    start_lags = []
    failures = {}
    job_context = client.current
    # A worker's failed request is the last one it recorded, independently of other workers.
    request = client.outcomes

    def observe():
        with psycopg.connect(**dict(owner, dbname="postgres"), autocommit=True) as db:
            while not stop.is_set():
                connections.append(
                    db.execute(
                        """
                    SELECT count(*),count(*) FILTER (WHERE state='active'),
                      count(*) FILTER (WHERE wait_event_type='Lock')
                    FROM pg_stat_activity WHERE datname=%s
                    """,
                        (owner["dbname"],),
                    ).fetchone()
                )
                stop.wait(0.25)

    def run(index, job):
        nonlocal active, peak
        stop_at = started + index / arrival
        time.sleep(max(0, stop_at - time.perf_counter()))
        start = time.perf_counter()
        with lock:
            active += 1
            peak = max(peak, active)
            start_lags.append((start - stop_at) * 1000)
        try:
            job_context.outcome = None
            job(think)
        except Exception as exc:  # noqa: BLE001 - retain per-workflow errors while measuring the entire wave
            errors.append(f"{type(exc).__name__}: {exc}")
            with lock:
                failures[index] = job_context.outcome or "other"
            return None
        finally:
            with lock:
                active -= 1
        return (time.perf_counter() - start) * 1000

    sampler = Thread(target=observe, daemon=True)
    sampler.start()
    cpu_started = time.process_time()
    started = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=users) as pool:
            workflows = [value for value in pool.map(run, range(len(jobs)), jobs) if value is not None]
        elapsed = time.perf_counter() - started
    finally:
        stop.set()
        sampler.join()
    per_operation = {}
    for label, status, ms in client.samples:
        durations, statuses = per_operation.setdefault(label, ([], {}))
        durations.append(ms)
        statuses[status] = statuses.get(status, 0) + 1
    return {
        "workflows": len(jobs),
        "successful": len(workflows),
        "users": users,
        "peak_workflows": peak,
        "start_lag_ms": distribution(start_lags),
        "scheduled_arrivals_per_s": arrival,
        "seconds": round(elapsed, 2),
        "generator_cpu_seconds": round(time.process_time() - cpu_started, 2),
        "workflow_ms": distribution(workflows),
        "successful_workflows_per_s": round(len(workflows) / elapsed, 2),
        "requests": len(client.samples),
        "requests_per_s": round(len(client.samples) / elapsed, 2),
        "request_ms": distribution([item[2] for item in client.samples]),
        "django_profile": {
            key: distribution([row[i] for row in client.sql])
            for i, key in enumerate(("query_count", "sql_ms", "handler_ms"))
        }
        if client.sql
        else {},
        "peak_db": dict(zip(("connections", "active", "lock_waiters"), map(max, zip(*connections))))
        if connections
        else {},
        "operations": {
            label: {"ms": distribution(durations), "statuses": statuses}
            for label, (durations, statuses) in per_operation.items()
        },
        "failures": len(errors),
        "workflow_outcomes": {"success": len(workflows), **Counter(failures.values())},
        "request_outcomes": dict(Counter(item["outcome"] for item in request)),
        "request_ms_by_outcome": {
            outcome: distribution([item["elapsed_ms"] for item in request if item["outcome"] == outcome])
            for outcome in {item["outcome"] for item in request}
        },
        "errors": errors[:8],
    }


def mixed_jobs(client, fixture, count, import_rows=0):
    offering, projects = fixture["offering"], fixture["projects"]
    catalog = f"/api/v1/courses/departments/{CSE}"

    def task(i, think):
        if import_rows and i == count // 2:
            intake(client, import_rows, "xlsx")
            return
        pid, actor = projects[i % len(projects)], student(i % len(projects) + 1)
        role = i % 20
        if role < 12:
            steps = [
                (actor, "/api/v1/workspace", None),
                (actor, DOC + "?project=" + pid, None),
            ]
        elif role < 16:
            steps = [
                (GUIDE, DOC + f"?listing=1&q=Capacity&page={i % 4 + 1}", None),
                (GUIDE, DOC + "?project=" + pid, None),
            ]
        elif role < 18:
            steps = [
                (COORDINATOR, f"{COURSES}/{offering}/details", None),
                (
                    COORDINATOR,
                    f"{COURSES}/{offering}/evaluation-queue?page={i % 4 + 1}",
                    None,
                ),
            ]
        elif role == 18:
            steps = [
                (
                    ADMIN,
                    STAFF + "/intake",
                    {
                        "action": "DIRECTORY",
                        "kind": "FACULTY" if (i // 20) % 2 else "STUDENT",
                        "q": "Synthetic" if (i // 20) % 2 else "CAP-",
                        "page": i % 4 + 1,
                    },
                ),
                (ADMIN, STAFF + "/appointment-candidates", {"q": "Anika", "page": 1}),
            ]
        else:
            steps = [
                (HOD, "/api/v1/workspace", None),
                (HOD, catalog + "?page=1", None),
                (HOD, STAFF + "/leadership", {"action": "HISTORY", "page": 1, "q": ""}),
            ]
        for index, (who, path, body) in enumerate(steps):
            if index:
                time.sleep(think)
            client.call(who, path, body)

    return [lambda think, i=i: task(i, think) for i in range(count)]


def pdf_upload(client, actor, pid, pdf, key, expected=(200, 201), **transport):
    boundary = "smartpro" + uuid4().hex
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="synopsis.pdf"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
        ).encode()
        + pdf
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return client.call(
        actor,
        f"{DOC}/projects/{pid}/uploads",
        body,
        key=key,
        mime="multipart/form-data; boundary=" + boundary,
        expected=expected,
        **transport,
    )


def lost_receipt(client, fixture, offset, owner, storage):
    """Withhold only the success body on the traced isolated server."""
    pid, actor = fixture["projects"][offset], student(offset + 1)
    pdf = pdf_bytes("Lost receipt test " + "x" * 262144)
    with psycopg.connect(**owner) as db:
        assert db.execute("SELECT count(*) FROM document_versions WHERE project_id=%s", (pid,)).fetchone()[0] == 0

        def after_commit(operation):
            try:
                operation()
            except TimeoutError:
                receipt = client.outcomes[-1]
                assert receipt["outcome"] == "client_timeout" and receipt["status"] == 200
                return receipt["request"]
            raise AssertionError("Expected a client body timeout after success headers")

        key = uuid4().hex
        upload_id = after_commit(lambda: pdf_upload(client, actor, pid, pdf, key, timeout=2, delay=True))
        rows = db.execute(
            """SELECT v.id,a.storage_key FROM document_versions v JOIN file_assets a
                           ON a.id=v.file_asset_id WHERE v.project_id=%s""",
            (pid,),
        ).fetchall()
        assert len(rows) == 1
        vid, file_key = str(rows[0][0]), rows[0][1]
        assert sha256((storage / "files" / file_key).read_bytes()).digest() == sha256(pdf).digest()
        assert pdf_upload(client, actor, pid, pdf, key)["documentVersionId"] == vid
        case = client.call(actor, DOC + "?project=" + pid)["projects"][0]["case"]
        command = {
            "action": "SUBMIT",
            "projectId": pid,
            "documentVersionId": vid,
            "expectedCaseVersion": case["version"],
        }
        key = uuid4().hex
        submit_id = after_commit(lambda: client.call(actor, DOC, command, key=key, timeout=2, delay=True))
        assert db.execute("SELECT count(*) FROM submission_attempts WHERE project_id=%s", (pid,)).fetchone()[0] == 1
        client.call(actor, DOC, command, key=key)
        case = client.call(actor, DOC + "?project=" + pid)["projects"][0]["case"]
        assert len(case["attempts"]) == len(case["versions"]) == 1
    return {
        "committed_before_retry": 2,
        "upload_request": upload_id,
        "submit_request": submit_id,
        "versions": 1,
        "attempts": 1,
        "checksum_verified": True,
    }


def documents(client, fixture, start, count, storage):
    projects = fixture["projects"]
    expected = []

    def case(actor, pid):
        return client.call(actor, DOC + "?project=" + pid)["projects"][0]["case"]

    def upload(i, think):
        pid, actor = projects[i], student(i + 1)
        pdf = pdf_bytes(f"Capacity project {i} " + "x" * (16384, 262144, 1048576)[i % 3])
        key = uuid4().hex
        receipt = pdf_upload(client, actor, pid, pdf, key)
        if i % 3 == 0:
            assert receipt == pdf_upload(client, actor, pid, pdf, key)
        time.sleep(think)
        current = case(actor, pid)
        vid = receipt["documentVersionId"]
        command = {
            "action": "SUBMIT",
            "projectId": pid,
            "documentVersionId": vid,
            "expectedCaseVersion": current["version"],
        }
        key = uuid4().hex
        submitted = client.call(actor, DOC, command, key=key)
        if i % 3 == 0:
            assert submitted == client.call(actor, DOC, command, key=key)
        expected.append((i, vid, sha256(pdf).hexdigest(), len(pdf)))

    def verify():
        files = [p for p in storage.rglob("*") if p.is_file()]
        hashes = [sha256(p.read_bytes()).hexdigest() for p in files]
        for i, vid, digest, _ in expected:
            pid = projects[i]
            current = case(student(i + 1), pid)
            assert len(current["attempts"]) == len(current["versions"]) == 1, pid
            assert hashes.count(digest) == 1, pid
            assert sha256(client.call(GUIDE, f"/api/v1/document-versions/{vid}/content")).hexdigest() == digest
        return {
            "verified": len(expected),
            "accepted_bytes": sum(row[3] for row in expected),
            "storage_files": len(files),
            "storage_bytes": sum(p.stat().st_size for p in files),
        }

    return [lambda think, i=i: upload(i, think) for i in range(start, start + count)], verify


def shared_team(client, fixture, offset, owner, storage):
    projects = fixture["projects"]
    pid = projects[offset]
    actors = student(offset + 1), student(len(projects) + offset + 1)
    pdfs = [pdf_bytes(f"Shared-team document {i} " + "x" * 262144) for i in range(2)]
    with psycopg.connect(**owner) as db:
        assert db.execute("SELECT count(*) FROM document_versions WHERE project_id=%s", (pid,)).fetchone()[0] == 0
    with ThreadPoolExecutor(max_workers=2) as pool:
        versions = list(
            pool.map(
                lambda args: pdf_upload(client, args[0], pid, args[1], uuid4().hex)["documentVersionId"],
                zip(actors, pdfs),
            )
        )
    case = client.call(actors[0], DOC + "?project=" + pid)["projects"][0]["case"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda args: client.call(
                    args[0],
                    DOC,
                    {
                        "action": "SUBMIT",
                        "projectId": pid,
                        "documentVersionId": args[1],
                        "expectedCaseVersion": case["version"],
                    },
                    expected=(200, 409),
                ),
                zip(actors, versions),
            )
        )
    assert sum("detail" in result for result in outcomes) == 1
    outsider = student(offset if offset else 2)
    client.call(outsider, f"/api/v1/document-versions/{versions[0]}/content", expected=(403, 404))
    with psycopg.connect(**owner) as db:
        rows = db.execute(
            """SELECT v.version_no, v.id, a.sha256, a.storage_key
                          FROM document_versions v JOIN file_assets a ON a.id=v.file_asset_id
                          WHERE v.project_id=%s ORDER BY v.version_no""",
            (pid,),
        ).fetchall()
        attempts = db.execute("SELECT count(*) FROM submission_attempts WHERE project_id=%s", (pid,)).fetchone()[0]
    assert [r[0] for r in rows] == [1, 2] and attempts == 1
    for _, vid, digest, key in rows:
        assert sha256((storage / "files" / key).read_bytes()).hexdigest() == digest
        assert sha256(pdfs[versions.index(str(vid))]).hexdigest() == digest
    return {"versions": len(rows), "attempts": attempts, "outsider_denied": True}


def evaluations(client, fixture, start, count, owner):
    offering, projects = fixture["offering"], fixture["projects"]
    command = f"{COURSES}/{offering}/commands"
    completed = []

    def task(i, think):
        pid = projects[i]
        document = client.call(GUIDE, DOC + "?project=" + pid)["projects"][0]["case"]
        if document and document["state"] == "AWAITING_REVIEW":
            client.call(
                GUIDE,
                DOC,
                {
                    "action": "DECIDE",
                    "projectId": pid,
                    "attemptId": document["attempts"][0]["id"],
                    "expectedCaseVersion": document["version"],
                    "decision": "APPROVE",
                    "comment": "Synthetic evidence",
                },
            )
        ids = []
        for stage in (1, 2):
            rid = client.call(
                COORDINATOR,
                command,
                {
                    "action": "CREATE_STAGE",
                    "projectId": pid,
                    "stageKey": f"stage-{stage}",
                    "facultyIds": [],
                },
            )["id"]
            review = next(r for r in client.call(GUIDE, "/api/v1/workspace")["reviews"] if r["id"] == rid)
            assessment = review["assessments"][0]
            scores = [
                {"criterionId": c["id"], "studentId": None, "marks": str(60 + stage)} for c in review["criteria"]
            ]
            path = ACADEMIC + f"/assessments/{assessment['id']}"
            draft = client.call(
                GUIDE,
                path + "/draft",
                {"expectedAssessmentVersion": assessment["version"], "scores": scores},
            )
            time.sleep(think)
            client.call(
                GUIDE,
                path + "/finalize",
                {"expectedAssessmentVersion": draft["assessmentVersion"]},
            )
            client.call(
                COORDINATOR,
                ACADEMIC + f"/reviews/{rid}/publish",
                {"expectedReviewRevision": review["revision"]},
            )
            ids.append(rid)
        client.call(
            COORDINATOR,
            command,
            {"action": "PUBLISH_FINAL", "projectId": pid, "expectedVersion": 0},
        )
        completed.append((pid, ids))

    def verify():
        for pid, ids in completed:
            queue = client.call(COORDINATOR, f"{COURSES}/{offering}/evaluation-queue?q={pid}")
            row = next(p for p in queue["projects"] if p["id"] == pid)
            assert row["overallVersion"] == 1
            assert all(s["publishedVersion"] == 1 for s in row["stages"])
            for rid in ids:
                assert len(client.call(COORDINATOR, ACADEMIC + f"/reviews/{rid}/results")["results"]) == 1
            with psycopg.connect(**owner) as db:
                release = db.execute(
                    "SELECT version, results FROM course_final_results WHERE project_id=%s",
                    (pid,),
                ).fetchall()
                assert len(release) == 1 and release[0][0] == 1
                assert len(release[0][1]) == 2 and set(release[0][1].values()) == {"61.50"}
        return {"verified": len(completed)}

    return [lambda think, i=i: task(i, think) for i in range(start, start + count)], verify


def intake(client, rows, kind):
    fields = ["Ref", "Name", "Dept"]
    data = [(f"capacity-intake-{kind}-{i}", f"Synthetic import {kind} {i:05}", "CSE") for i in range(rows)]
    if kind == "xlsx":
        from openpyxl import Workbook

        book = Workbook(write_only=True)
        sheet = book.create_sheet()
        sheet.append(fields)
        for row in data:
            sheet.append(row)
        stream = BytesIO()
        book.save(stream)
        upload = stream.getvalue()
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        upload = ("\n".join(",".join(row) for row in [fields, *data]) + "\n").encode()
        content_type = "text/csv"
    base = {
        "mapping": json.dumps({"key": "Ref", "name": "Name", "department": "Dept"}),
        "source": "OFFICIAL",
        "kind": "FACULTY",
    }

    def request(action, **extra):
        boundary = "capacity" + uuid4().hex
        parts = "".join(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
            for key, value in dict(action=action, **base, **extra).items()
        ).encode()
        parts += (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="capacity.{kind}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
            + upload
            + f"\r\n--{boundary}--\r\n".encode()
        )
        return client.request(
            ADMIN,
            STAFF + "/intake",
            parts,
            mime="multipart/form-data; boundary=" + boundary,
        )

    preview, preview_ms = request("PREVIEW")
    applied, apply_ms = request("APPLY", reference="Synthetic capacity export", confirmed="true")
    assert preview["count"] == rows and applied["batchId"]
    return {
        "format": kind,
        "rows": rows,
        "file_bytes": len(upload),
        "preview_ms": round(preview_ms, 1),
        "apply_ms": round(apply_ms, 1),
        "preview_fields": sorted(preview),
        "preview_counts": preview["counts"],
        "result": {key: value for key, value in applied.items() if isinstance(value, (int, bool, str))},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "create",
            "serve",
            "seed",
            "mixed",
            "documents",
            "evaluations",
            "intake",
            "shared",
            "lost-receipt",
            "install-fix",
        ],
    )
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--port", type=int, default=8051)
    parser.add_argument("--projects", type=int, default=100)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--conn-age", type=int, default=0)
    parser.add_argument("--profile-sql", action="store_true")
    parser.add_argument("--trace-http", action="store_true")
    parser.add_argument("--request-ledger", type=Path)
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--jobs", type=int, default=60)
    parser.add_argument("--arrival", type=float, default=5)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--format", choices=["csv", "xlsx"], default="csv")
    parser.add_argument("--mixed-import-rows", type=int, choices=(0, 1000), default=0)
    args = parser.parse_args()
    if args.action == "create":
        create_workspace()
        return
    if not args.manifest or args.port < 1024 or not 1 <= args.threads <= 32 or not 1 <= args.projects <= 2000:
        parser.error("Supply an isolated manifest, 1–2000 projects, 1–32 threads and an unprivileged port")
    if args.action == "serve":
        serve(
            args.manifest,
            args.port,
            args.projects * 2,
            args.threads,
            args.conn_age,
            args.profile_sql,
            args.trace_http,
        )
        return
    target, owner, _ = load_target(args.manifest)
    if args.action == "install-fix":
        signature = "public.smartpro_course_command(uuid,uuid,text,jsonb,text)"
        inspect = "SELECT proowner,proacl,prosecdef,proconfig FROM pg_proc WHERE oid=%s::regprocedure"
        with psycopg.connect(**owner, autocommit=True) as db:
            before = db.execute(inspect, (signature,)).fetchone()
            execute_file(db, ROOT / "proposals/curriculum/058_course_command_lock_order.sql")
            if db.execute(inspect, (signature,)).fetchone() != before:
                raise RuntimeError("Unexpected privilege change in course command candidate")
        return
    client = Client(args.port, target["database"])
    client.call(HOD, "/api/v1/workspace")
    if args.action == "intake":
        if not 1 <= args.jobs <= 5000:
            parser.error("Use 1–5000 synthetic intake rows")
        print(json.dumps(intake(client, args.jobs, args.format), sort_keys=True))
        return
    output = args.manifest.with_suffix(".capacity.json")
    if args.action == "seed":
        fixture = seed(client, owner, args.projects)
        with output.open("x", encoding="utf8") as file:
            json.dump(fixture, file)
        print(output)
        return
    fixture = json.loads(output.read_text(encoding="utf8"))
    if args.action in ("shared", "lost-receipt"):
        if fixture["database"] != target["database"] or not 0 <= args.offset < len(fixture["projects"]):
            parser.error("Invalid isolated fixture or project offset")
        check = shared_team if args.action == "shared" else lost_receipt
        print(json.dumps(check(client, fixture, args.offset, owner, Path(target["storage"]))))
        return
    if (
        fixture["database"] != target["database"]
        or not 1 <= args.users <= 200
        or not 1 <= args.jobs <= 2000
        or not 0 < args.arrival <= 200
        or args.offset < 0
        or args.action != "mixed"
        and args.offset + args.jobs > len(fixture["projects"])
    ):
        parser.error("Invalid isolated fixture or workload limits")
    ledger = args.request_ledger.resolve() if args.request_ledger else None
    if ledger and (not ledger.is_relative_to(ROOT_TEST) or not ledger.parent.is_dir() or ledger.exists()):
        parser.error("Use a new request ledger under .test-data")
    verify = None
    if args.action == "mixed":
        jobs = mixed_jobs(client, fixture, args.jobs, args.mixed_import_rows)
    elif args.action == "documents":
        jobs, verify = documents(client, fixture, args.offset, args.jobs, Path(target["storage"]))
    else:
        jobs, verify = evaluations(client, fixture, args.offset, args.jobs, owner)
    result = run_wave(client, owner, jobs, args.users, args.arrival)
    if ledger:
        with ledger.open("x", encoding="utf8") as stream:
            json.dump(client.outcomes, stream)
    if verify:
        result["integrity"] = verify()
    print(json.dumps(result, sort_keys=True))
    if result["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
