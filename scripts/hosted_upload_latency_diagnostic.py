"""Manual-only, bounded real HTTPS PDF upload latency sampling on synthetic reviewer staging.

This is NOT a capacity claim or load ramp. Creates one new clearly synthetic
project and permanent immutable document versions, using existing synthetic
membership. Each wave uses 2 or 4 signed-in Student sessions. No retries,
deletions, credentials, filenames, document contents or cookies in logs.
"""
import asyncio
import hashlib
import os
import statistics
import sys
import uuid
from math import ceil

import httpx

from hosted_synthetic_https_writes import (
    TIMEOUT,
    AcceptanceFailure,
    Reviewer,
    get_config,
    json_success,
    pdf_bytes,
    ready,
    require,
    simultaneous,
)


def params():
    accounts, ids, clients, _ = get_config()
    size_kib = int(os.getenv("SMARTPRO_UPLOAD_PERF_SIZE_KIB", "256"))
    rounds = int(os.getenv("SMARTPRO_UPLOAD_PERF_ROUNDS", "5"))
    require(size_kib in (64, 256, 1024), "Approved file size must be 64, 256 or 1024 KiB")
    require(rounds in (3, 5), "Approved number of rounds must be 3 or 5")
    require(clients * rounds <= 20, "No more than 20 synthetic uploads permitted")
    require(clients * rounds * size_kib <= 20480, "No more than 20 MiB of PDF test data")
    return accounts, ids, clients, size_kib, rounds


def percentile_nearest_rank(values, fraction):
    require(bool(values), "Cannot summarize an empty measurement")
    ordered = sorted(values)
    return ordered[ceil(len(ordered) * fraction) - 1]


async def run():
    accounts, ids, clients_count, size_kib, rounds = params()
    department = ids["DEPARTMENT_ID"]
    offering = ids["OFFERING_ID"]
    team = ids["TEAM_ID"]
    guide = ids["GUIDE_USER_ID"]
    nonce = uuid.uuid4().hex[:10]
    clients = [Reviewer("Student", accounts["Student"]) for _ in range(clients_count)]
    coordinator = Reviewer("Coordinator", accounts["Coordinator"])
    synthetic_project = None
    results = []
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, verify=True) as public:
            await ready(public)
        for user in clients + [coordinator]:
            await user.login()
        student = clients[0]
        offerings = json_success(await student.get("/api/v1/me/curriculum-offerings"),
                                 "Student offerings")
        require(any(x.get("id") == offering for x in offerings.get("results", [])),
                "Chosen synthetic offering is not available; no writes performed")
        memberships = json_success(await student.get("/api/v1/me/memberships"),
                                   "Student current memberships")
        require(any(item.get("teamId") == team and item.get("offeringId") == offering
                    and item.get("scheduledEndAt") is None
                    and "synthetic" in str(item.get("teamName", "")).lower()
                    for item in memberships.get("results", [])),
                "Membership is not the verified active synthetic team; no writes performed")
        project = json_success(await student.post("/api/v1/projects",
            {"offeringId": offering, "teamId": team,
             "title": f"[SYNTHETIC-UPLOAD-PERF] {nonce}",
             "description": "Bounded HTTPS diagnostic uploads only; permanently retained for audit"},
            key=f"perf-{nonce}-project"), "Create synthetic diagnostic project", (201,))
        synthetic_project = str(uuid.UUID(project["id"]))
        require(project.get("teamId") == team, "Unexpected new project team")
        print(f"CREATED_SYNTHETIC_DIAGNOSTIC_PROJECT {synthetic_project}; retained for audit",
              flush=True)
        json_success(await coordinator.post(
            f"/api/v1/staff/departments/{department}/projects/{synthetic_project}/guide",
            {"facultyId": guide, "expectedGuideId": None},
            key=f"perf-{nonce}-guide"), "Assign synthetic Guide")
        async with httpx.AsyncClient(timeout=TIMEOUT, verify=True) as public:
            await ready(public)

        padding = size_kib * 1024 - 1024
        url = (f"/api/v1/documents/departments/{department}/"
               f"projects/{synthetic_project}/uploads")
        print(f"UPLOAD_PERF_START clients={clients_count} rounds={rounds} "
              f"nominal_size_kib={size_kib} max_immutable_objects={clients_count * rounds}",
              flush=True)
        for number in range(rounds):
            pdfs = [pdf_bytes(f"SMARTPRO PERF {nonce} ROUND {number} CLIENT {i}",
                              padding_bytes=padding)
                    for i in range(clients_count)]
            actual_bytes = len(pdfs[0])
            require(0 < actual_bytes <= 2 * 1024 * 1024,
                    "Synthetic PDF exceeds the document limit")
            wave = await simultaneous([
                (lambda i=i: clients[i].post(
                    url, None, key=f"perf-{nonce}-r{number}-c{i}",
                    files={"file": (f"synthetic-perf-{nonce}-r{number}-c{i}.pdf",
                                    pdfs[i], "application/pdf")}))
                for i in range(clients_count)
            ])
            require(all(status == 200 for status, _, _ in wave),
                    f"Unexpected HTTP statuses in round {number + 1}: "
                    f"{[status for status, _, _ in wave]}")
            for i, (_, elapsed, response) in enumerate(wave):
                result = json_success(response, f"Round {number + 1} upload {i}")
                version_id = str(uuid.UUID(result["documentVersionId"]))
                fetched = await student.get(
                    f"/api/v1/document-versions/{version_id}/content?download=1")
                require(fetched.status_code == 200,
                        f"Private PDF read-back HTTP {fetched.status_code}")
                require(hashlib.sha256(fetched.content).digest() ==
                        hashlib.sha256(pdfs[i]).digest(),
                        "Private uploaded PDF bytes did not match")
                results.append(elapsed)
            rounded = [round(elapsed, 3) for _, elapsed, _ in wave]
            print(f"UPLOAD_PERF_ROUND round={number + 1}/{rounds} "
                  f"actual_bytes={actual_bytes} "
                  f"client_seconds={rounded} "
                  f"median_s={statistics.median(rounded):.3f} "
                  f"max_s={max(rounded):.3f}; "
                  f"sha256_verified={clients_count}/{clients_count}", flush=True)

        p50 = percentile_nearest_rank(results, .5)
        p95 = percentile_nearest_rank(results, .95)
        maximum = max(results)
        print(f"UPLOAD_PERF_RESULT sample_size={len(results)} "
              f"clients={clients_count} rounds={rounds} size_bytes={actual_bytes} "
              f"median_s={statistics.median(results):.3f} "
              f"nearest_rank_p50_s={p50:.3f} "
              f"nearest_rank_p95_s={p95:.3f} max_s={maximum:.3f} "
              f"error_count=0 read_back_sha256={len(results)}/{len(results)}",
              flush=True)
        print("UPLOAD_PERF_NOT_CAPACITY_CLAIM: small diagnostic sample; "
              "performance depends on server warm-up, network, backend and file sizes",
              flush=True)
    finally:
        for user in clients + [coordinator]:
            await user.close()
        if synthetic_project:
            print("SYNTHETIC_PERF_FIXTURE_RETAINED: no academic evidence was deleted",
                  flush=True)


def self_test():
    for size_kib in (64, 256, 1024):
        pdf = pdf_bytes(f"SMARTPRO PERF TEST {size_kib}",
                        padding_bytes=size_kib * 1024 - 1024)
        require(pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF"),
                "PDF envelope not valid")
        require(size_kib * 1024 - 1024 <= len(pdf) <= size_kib * 1024,
                "Diagnostic PDF not in approved representative size band")
    require(percentile_nearest_rank([.1, .2, .3, .4], .95) == .4,
            "Nearest-rank percentile contract is invalid")
    print("PASS upload latency diagnostic preflight: bounded valid PDF envelopes, percentiles")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    elif not sys.argv[1:]:
        try:
            asyncio.run(run())
        except (AcceptanceFailure, httpx.HTTPError, asyncio.TimeoutError,
                ValueError, KeyError) as error:
            print(f"UPLOAD_PERF_FAILED: {type(error).__name__}: {str(error)[:180]}",
                  file=sys.stderr)
            sys.exit(1)
    else:
        sys.exit("Only --self-test or the explicit manual configured run is supported")
