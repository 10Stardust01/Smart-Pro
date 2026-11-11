"""Bounded 2-minute five-role authenticated HTTPS read-only soak.

Five signed synthetic actors, one GET per actor every two seconds, zero writes.
Maximum 300 scope-checked GETs, no retries, no credential logs. This is not a
mixed-write peak-load or production-capacity certification.
"""
import asyncio
import json
import os
import statistics
import time
from math import ceil

from hosted_synthetic_https_writes import BASE, Reviewer, ready, require, TIMEOUT

ROLES = ("Student", "Faculty", "Coordinator", "HOD", "Admin")
EXPECTED_APPROVAL = "RUN_FIVE_ROLE_BOUNDED_READ_SOAK"
DURATION_SECONDS = 120
INTERVAL_SECONDS = 2.0
ROUNDS = 60
MAX_TOTAL_GETS = 300
MAX_P95_SECONDS = 10.0
EXPECTED_DEPARTMENT = "10000000-0000-4000-8000-000000000001"


async def worker(role, user, start, results):
    for n in range(ROUNDS):
        due = start + n * INTERVAL_SECONDS
        await asyncio.sleep(max(0, due - time.monotonic()))
        moment = time.monotonic()
        try:
            response = await user.get("/api/v1/workspace")
            duration = time.monotonic() - moment
            if response.status_code != 200:
                raise AssertionError(f"{role}: workspace HTTP {response.status_code}")
            doc = response.json()
            if not isinstance(doc, dict) or not doc.get("actor") or not doc.get("access"):
                raise AssertionError(f"{role}: signed scope response contract invalid")
            results.append((role, duration))
        except Exception as exc:
            raise AssertionError(f"{role}: failed authenticated GET round {n+1}: {type(exc).__name__}") from None


async def main():
    require(os.getenv("SMARTPRO_SOAK_APPROVAL") == EXPECTED_APPROVAL,
            "Explicit bounded synthetic authentication soak authorization absent")
    users_json = json.loads(os.getenv("SMARTPRO_HOSTED_TEST_ACCOUNTS") or "{}")
    require(all(isinstance(users_json.get(x), dict)
                and users_json[x].get("alias") and users_json[x].get("password")
                for x in ROLES), "Private five-role signed test accounts missing")
    users = [Reviewer(role, users_json[role]) for role in ROLES]
    results = []
    try:
        import httpx
        async with httpx.AsyncClient(timeout=TIMEOUT, verify=True) as public:
            await ready(public)
        for user in users:
            await user.login()
        print("PRECHECK_READY 5 real synthetic reviewer roles signed; zero academic writes", flush=True)
        start = time.monotonic() + 1.0
        await asyncio.gather(*(worker(user.role, user, start, results) for user in users))
        durations = sorted(sec for _, sec in results)
        require(len(results) == MAX_TOTAL_GETS, "Expected 300 authenticated responses")
        p50 = durations[ceil(len(durations)*0.50)-1]
        p95 = durations[ceil(len(durations)*0.95)-1]
        p99 = durations[ceil(len(durations)*0.99)-1]
        print(f"BOUNDED_SIGNED_READ_SOAK responses={len(durations)} unique_roles=5 "
              f"p50={p50:.3f}s p95={p95:.3f}s p99={p99:.3f}s "
              f"max={durations[-1]:.3f}s rate_target=2.5_get_per_second "
              "no_retries=true no_writes=true", flush=True)
        require(p95 <= MAX_P95_SECONDS, "p95 >10 seconds: do not certify capacity")
        print("PASS_BOUND_AUTHENTICATED_READ_SOAK (NOT write/deadline peak-load acceptance)",
              flush=True)
    finally:
        for user in users:
            await user.close()


if __name__ == "__main__":
    asyncio.run(main())
