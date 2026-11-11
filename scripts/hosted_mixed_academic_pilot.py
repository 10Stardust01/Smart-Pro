"""One opt-in bounded mixed-role hosted pilot on owned Render Free reviewer staging.

Reuses the established write-race harness (one NEW synthetic project only), while
three additional signed read sessions observe the live app during those writes.
Never reads or logs passwords/tokens, bypasses no academic authorization, and
never changes the historical published project. One execution, no retry/ramp.

This uses three EXISTING synthetic identities, not three independent students.
Neither 2-writer timings nor <=45 read samples establish a campus-scale SLA.
"""
import asyncio
import os
import re
import sys
import time
from math import ceil

import httpx

from hosted_synthetic_https_writes import (
    PHRASE, Reviewer, get_config, ready, require,
)

APPROVAL = "RUN_ONE_BOUNDED_MIXED_PILOT"
MAX_ROUNDS = 15
ROLES = ("Student", "Faculty", "Coordinator")
READ_TARGET_SECONDS = 1.5
WRITE_TARGET_SECONDS = 3.0
PDF_TARGET_SECONDS = 5.0
READ_HALT_SECONDS = 5.0
STAGE_NAMES = (
    "concurrent_private_pdf_uploads", "simultaneous_student_submissions",
    "concurrent_faculty_marks", "concurrent_faculty_finalization",
    "concurrent_stage_publication",
)
STAGE_PATTERN = re.compile(
    r"^HTTPS_WAVE ([a-z_]+): (\d+) clients; p95=(\d+\.\d+)s; max=(\d+\.\d+)s$",
    re.MULTILINE,
)


def p95(values):
    require(values, "No observations to summarize")
    ordered = sorted(values)
    return ordered[ceil(.95 * len(ordered)) - 1]


def parse_waves(output):
    waves = {name: {"writers": int(n), "p95_s": float(p), "max_s": float(m)}
             for name, n, p, m in STAGE_PATTERN.findall(output)}
    require(set(waves) == set(STAGE_NAMES), "Write acceptance did not complete all five waves")
    require(all(waves[name]["writers"] == 2 for name in STAGE_NAMES),
            "Unexpected number of concurrent synthetic writers")
    return waves


async def probe(person):
    start = time.monotonic()
    try:
        reply = await person.get("/api/v1/workspace")
        return (person.role, reply.status_code, time.monotonic() - start)
    except (httpx.HTTPError, asyncio.TimeoutError):
        return (person.role, None, time.monotonic() - start)


async def run():
    require(os.getenv("SMARTPRO_MIXED_PILOT_APPROVAL") == APPROVAL,
            "Explicit one-time pilot approval missing")
    require(os.getenv("SMARTPRO_HOSTED_WRITE_APPROVAL") == PHRASE,
            "Existing synthetic write-approval gate is required")
    accounts, ids, clients, stage_key = get_config()
    require(clients == 2 and stage_key == "evidence", "Pilot permits two writers and approved evidence stage only")
    require(os.getenv("SMARTPRO_WRITE_PDF_SIZE_KIB") == "256",
            "Pilot must use bounded 256 KiB PDFs")
    require(ids["DEPARTMENT_ID"] == "10000000-0000-4000-8000-000000000001" and
            ids["OFFERING_ID"] == "8b40a6e1-419d-43c8-b625-279f82713b02" and
            ids["TEAM_ID"] == "04da071d-f86b-415d-a580-123ba8f2236b" and
            ids["GUIDE_USER_ID"] == "00000000-0000-4000-8000-000000000003",
            "Pilot refuses an unreviewed target; no writes made")
    readers = [Reviewer(role, accounts[role]) for role in ROLES]
    child = None
    output_task = None
    readings = []
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=True) as public:
            await ready(public)
        # Do not stress the reviewer login: establish the three readers sequentially.
        for person in readers:
            await person.login()
        print("PILOT_START one_synthetic_project=true uploaded_pdfs=2 each_kib=256 "
              "write_clients=2 read_clients=3 max_read_gets=45 no_retries=true", flush=True)
        child = await asyncio.create_subprocess_exec(
            sys.executable, "scripts/hosted_synthetic_https_writes.py",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        output_task = asyncio.create_task(child.communicate())
        for round_id in range(MAX_ROUNDS):
            if output_task.done():
                break
            batch = await asyncio.gather(*(probe(person) for person in readers))
            readings.extend(batch)
            if any(code != 200 for _, code, _ in batch):
                print("PILOT_READ_HALT unexpected signed workspace HTTP response", flush=True)
                break
            if all(duration > READ_HALT_SECONDS for _, _, duration in batch):
                print("PILOT_READ_HALT all signed readers exceeded 5s", flush=True)
                break
            if round_id + 1 < MAX_ROUNDS:
                await asyncio.sleep(.5)
        output_bytes, _ = await asyncio.wait_for(output_task, timeout=300)
        output = output_bytes.decode("utf-8", errors="replace")
        # Child uses audited, sanitized logging: no response bodies or credentials.
        print(output, end="" if output.endswith("\n") else "\n", flush=True)
        statuses = {role: [duration for r, code, duration in readings if r == role and code == 200]
                    for role in ROLES}
        read_failures = sum(code != 200 for _, code, _ in readings)
        all_reads = [duration for _, code, duration in readings if code == 200]
        print(f"PILOT_READS performed={len(readings)}/45 HTTP_failures={read_failures} "
              f"p95_s={p95(all_reads):.3f} max_s={max(all_reads):.3f}" if all_reads else
              f"PILOT_READS performed={len(readings)}/45 HTTP_failures={read_failures} no_successful_read", flush=True)
        for role in ROLES:
            if statuses[role]:
                print(f"PILOT_READER role={role} requests={len(statuses[role])} "
                      f"p95_s={p95(statuses[role]):.3f}", flush=True)
        require(child.returncode == 0, "Verified synthetic academic write sequence failed")
        require("PASS_HOSTED_HTTPS_ACADEMIC_WRITES" in output,
                "Write acceptance did not print its final integrity verdict")
        require(all_reads and read_failures == 0, "Concurrent scoped reads were not reliable")
        waves = parse_waves(output)
        performance_failures = []
        if p95(all_reads) > READ_TARGET_SECONDS:
            performance_failures.append(f"read observed p95 {p95(all_reads):.3f}s > {READ_TARGET_SECONDS}s")
        for name, record in waves.items():
            goal = PDF_TARGET_SECONDS if name == "concurrent_private_pdf_uploads" else WRITE_TARGET_SECONDS
            print(f"PILOT_WRITE_PHASE name={name} p95_s={record['p95_s']:.3f} "
                  f"provisional_goal_s={goal:.1f}", flush=True)
            if record["p95_s"] > goal:
                performance_failures.append(f"{name} observed p95 {record['p95_s']:.3f}s > {goal}s")
        print("PILOT_FUNCTIONAL_PASS 2 signed writers per race; 3 signed-role read observers; "
              "one synthetic audit project preserved", flush=True)
        if performance_failures:
            for failure in performance_failures:
                print("PILOT_PERFORMANCE_GAP " + failure, flush=True)
            raise RuntimeError("Bounded pilot exceeded provisional latency objectives; inspect evidence")
        print("PASS_BOUNDED_MIXED_PILOT only_this_profile=true no_institutional_SLA=true", flush=True)
    finally:
        if child is not None and child.returncode is None:
            child.terminate()
            try:
                await asyncio.wait_for(child.wait(), timeout=5)
            except asyncio.TimeoutError:
                child.kill()
                await child.wait()
        for person in readers:
            await person.close()


def self_test():
    require(p95([0.1, 0.2, 0.3, 0.4]) == 0.4, "Nearest-rank p95 calculation")
    lines = "\n".join(f"HTTPS_WAVE {name}: 2 clients; p95=1.100s; max=1.100s"
                      for name in STAGE_NAMES)
    waves = parse_waves(lines)
    require(len(waves) == 5 and waves[STAGE_NAMES[0]]["p95_s"] == 1.1,
            "Write-metric parsing")
    require(MAX_ROUNDS == 15 and len(ROLES) == 3 and MAX_ROUNDS * len(ROLES) == 45,
            "Read cap changed without review")
    print("PASS_BOUNDED_MIXED_PILOT_OFFLINE_PREFLIGHT no_HTTPS no_writes")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    elif not sys.argv[1:]:
        try:
            asyncio.run(run())
        except (RuntimeError, ValueError, KeyError, httpx.HTTPError, asyncio.TimeoutError) as error:
            print(f"MIXED_PILOT_FAILED {type(error).__name__}: "
                  f"{str(error)[:160]}", file=sys.stderr)
            sys.exit(1)
    else:
        sys.exit("Only --self-test or one explicitly authorized pilot is supported")
