"""Actual Render Free staging stress ramp, strictly read-only and capped.

Launch once from GitHub Actions. No credentials, academic write operations,
session cookies, self-scheduling, cloud scaling, retries, or third-party meters.
Target is a fixed allowlisted HTTPS origin. Each wave is gated by outcomes of
the preceding wave, and stops on unexpected status or p95 >10 seconds.

Measures response behavior for login, authorization rejection and database
readiness, NOT authenticated project workflows or concurrent academic writes.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
import statistics
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE = "https://smartpro-reviewer-25775915.onrender.com"
AGENT = "SMARTPRO-owned-staging-peak-ramp/20261110"
WAVES = (50, 100, 200, 300)
PER_REQUEST_TIMEOUT = 20
MAX_P95_MS = 10000
MAX_WALL_SECONDS = 220
HEADERS = {"User-Agent": AGENT, "Cache-Control": "no-cache"}
ALLOWED = {
    "/health/live": 200,
    "/health/ready": 200,
    "/reviewer/login": 200,
    "/api/v1/workspace": 401,
}
NO_REDIRECT = None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, url):
        return None


def fetch(path):
    assert path in ALLOWED
    t0 = time.perf_counter()
    try:
        opener = build_opener(NoRedirect())
        try:
            response = opener.open(Request(BASE + path, method="GET", headers=HEADERS),
                                   timeout=PER_REQUEST_TIMEOUT)
        except HTTPError as http_error:
            response = http_error
        with response:
            code = response.status
            body = response.read(16000)
        success = code == ALLOWED[path]
        if path in ("/health/live", "/health/ready"):
            try:
                success = success and json.loads(body) == {"status": "ok"}
            except (ValueError, UnicodeDecodeError, TypeError):
                success = False
        elif path == "/reviewer/login":
            success = success and all(
                term in body for term in (b'name="username"', b'name="password"',
                                         b"csrfmiddlewaretoken"))
        return {"endpoint": path, "status": code, "ok": success,
                "duration_ms": round((time.perf_counter() - t0) * 1000)}
    except (OSError, URLError, TimeoutError) as error:
        return {"endpoint": path, "status": None, "ok": False,
                "error": type(error).__name__,
                "duration_ms": round((time.perf_counter() - t0) * 1000)}


def client(barrier, client_index):
    barrier.wait(timeout=35)
    first = "/api/v1/workspace" if client_index % 3 == 0 else "/reviewer/login"
    # Database-backed readiness is exercised by *each* simultaneous client.
    return (fetch(first), fetch("/health/ready"))


def pct(samples, probability):
    values = sorted(samples)
    return values[max(0, min(len(values)-1, int((len(values)-1)*probability+0.999999)))]


def summary(label, rows, concurrency):
    durations = [r["duration_ms"] for r in rows]
    failures = [
        {key: row.get(key) for key in ("endpoint", "status", "duration_ms", "error")}
        for row in rows if not row["ok"]
    ]
    return {
        "label": label, "clients": concurrency, "requests": len(rows),
        "expected_responses": len(rows)-len(failures),
        "unexpected_responses": len(failures),
        "http_statuses": {
            str(s): sum(r["status"] == s for r in rows)
            for s in sorted({r["status"] for r in rows}, key=lambda s: -1 if s is None else s)
        },
        "p50_ms": pct(durations, .50), "p95_ms": pct(durations, .95),
        "p99_ms": pct(durations, .99), "max_ms": max(durations),
        "failures_sample": failures[:8],
    }


def main():
    print("ACTUAL HOST: " + BASE, flush=True)
    print("LOAD SAFETY: 4 waves, clients 50/100/200/300, max 1303 GETs, 300 threads, "
          "only GET /health/ready, /health/live, /reviewer/login, /api/v1/workspace",
          flush=True)
    print("STOP: any unexpected response, p95 >10 sec, or global 220sec deadline",
          flush=True)
    t0 = time.monotonic()
    warm = [fetch("/health/live"), fetch("/health/ready"), fetch("/reviewer/login")]
    data = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "host": BASE,
        "deployed_scope": "REAL HOSTED anonymous read-only with SQL-backed readiness",
        "warmup": summary("warmup", warm, 1),
        "waves": [],
        "expected_total_request_cap": 1303,
        "max_concurrent_clients": max(WAVES),
    }
    if data["warmup"]["unexpected_responses"]:
        data["result"] = "HALTED_WARMUP"
    else:
        for n in WAVES:
            if time.monotonic()-t0 >= MAX_WALL_SECONDS:
                data["result"] = "HALTED_DEADLINE"
                break
            barrier = threading.Barrier(n)
            results = []
            start_wave = time.monotonic()
            with ThreadPoolExecutor(max_workers=n, thread_name_prefix="staging-load") as pool:
                futures = [pool.submit(client, barrier, i) for i in range(n)]
                for task in as_completed(futures):
                    try:
                        results.extend(task.result())
                    except Exception as error:
                        results.append({"endpoint": "worker", "status": None,
                                        "ok": False, "error": type(error).__name__,
                                        "duration_ms": round((time.monotonic()-start_wave)*1000)})
            wave = summary(f"{n} clients", results, n)
            wave["elapsed_s"] = round(time.monotonic()-start_wave, 2)
            data["waves"].append(wave)
            print(
                f"Wave {n}: {wave['expected_responses']}/{wave['requests']} expected, "
                f"p50={wave['p50_ms']}ms, p95={wave['p95_ms']}ms, "
                f"p99={wave['p99_ms']}ms, max={wave['max_ms']}ms",
                flush=True,
            )
            if wave["unexpected_responses"]:
                data["result"] = f"HALTED_UNEXPECTED_HTTP_AT_{n}"
                break
            if wave["p95_ms"] > MAX_P95_MS:
                data["result"] = f"HALTED_SLOW_P95_AT_{n}"
                break
        else:
            data["result"] = "ALL_WAVES_COMPLETED"
    data["requests_observed"] = data["warmup"]["requests"] + sum(
        r["requests"] for r in data["waves"])
    data["elapsed_s"] = round(time.monotonic()-t0, 2)
    print("LOAD_RESULT_BEGIN")
    print(json.dumps(data, indent=2))
    print("LOAD_RESULT_END", flush=True)
    report = os.getenv("GITHUB_STEP_SUMMARY")
    if report:
        with open(report, "a", encoding="utf-8") as f:
            f.write(f"### Actual hosted SMART-PRO load ramp: {data['result']}\n\n")
            f.write(f"Requests: {data['requests_observed']} / 1303 max; no academic writes.\n\n")
            f.write("| Clients | Expected / Total | P50 (ms) | P95 (ms) | P99 (ms) |\n")
            f.write("|--:|--:|--:|--:|--:|\n")
            for w in data["waves"]:
                f.write(f"| {w['clients']} | {w['expected_responses']}/{w['requests']} | "
                        f"{w['p50_ms']} | {w['p95_ms']} | {w['p99_ms']} |\n")
            f.write("\nThis is real hosted anonymous GET/DB-readiness traffic, "
                    "not authenticated academic operation or a sustained peak capacity SLA.\n")
    return 0 if data["result"] == "ALL_WAVES_COMPLETED" else 1


if __name__ == "__main__":
    sys.exit(main())
