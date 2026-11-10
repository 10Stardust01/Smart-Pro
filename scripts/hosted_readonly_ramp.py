#!/usr/bin/env python3
"""Bounded, non-destructive load ramp against the *deployed* Render reviewer.

Exactly 3 warmup GETs plus 30 concurrent GETs (1+2+4+8 workers x 2).
No login attempts, credentials, cookies, writes, retries, automatic scheduling,
or paid load service. Fail closed if status, latency or availability is unsafe.

This verifies only public/anonymous paths under a small real HTTP burst. It
is not authenticated acceptance, academic write/load testing or a peak SLA.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.message import Message
import json
import os
import statistics
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE = "https://smartpro-reviewer-25775915.onrender.com"
USER_AGENT = "SMARTPRO-bounded-readonly-staging-check/20261110"
WAVES = (1, 2, 4, 8)
DEADLINE_SECONDS = 180
REQUEST_TIMEOUT = 15
MAX_P95_MS = 10000
MAX_ERRORS = 0
HEADERS = {"User-Agent": USER_AGENT, "Cache-Control": "no-cache"}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get(path: str, timeout=REQUEST_TIMEOUT, body_limit=260000):
    start = time.perf_counter()
    # Separate opener per worker and no redirect to external domains.
    opener = build_opener(NoRedirect())
    req = Request(BASE + path, headers=HEADERS, method="GET")
    try:
        try:
            response = opener.open(req, timeout=timeout)
        except HTTPError as err:
            response = err
        with response:
            status = response.status
            body = response.read(body_limit)
            loc = response.headers.get("Location", "")
            ctype = response.headers.get("Content-Type", "")
    except (URLError, TimeoutError, OSError) as exc:
        return {"path": path, "status": None, "ms": round((time.perf_counter()-start)*1000),
                "error": type(exc).__name__, "body": b"", "location": "", "content_type": ""}
    return {"path": path, "status": status, "ms": round((time.perf_counter()-start)*1000),
            "error": None, "body": body, "location": loc, "content_type": ctype}


def accepted(result):
    status = result["status"]
    path = result["path"]
    if result["error"]:
        return False
    if path in ("/health/live", "/health/ready"):
        try:
            return status == 200 and json.loads(result["body"]) == {"status": "ok"}
        except (ValueError, TypeError):
            return False
    if path == "/":
        return status == 302 and result["location"] == "/reviewer/login"
    if path == "/reviewer/login":
        return (status == 200 and b"csrfmiddlewaretoken" in result["body"] and
                b'name="username"' in result["body"] and
                b'name="password"' in result["body"])
    if path in ("/api/v1/workspace", "/api/v1/me/published-corrections"):
        return status in (401, 403)
    if path == "/demo-assets/documents.js":
        return status == 200 and b"guide-stage-evidence-correction" in result["body"]
    return False


def compact(result):
    return {key: result[key] for key in ("path", "status", "ms", "error")}


def worker(start: threading.Barrier):
    start.wait(timeout=15)
    return [get("/reviewer/login", body_limit=15000),
            get("/api/v1/workspace", body_limit=1200)]


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered)-1, int((len(ordered)-1)*fraction + 0.999999)))]


def summarize(label, results):
    times = [r["ms"] for r in results]
    failures = [compact(r) for r in results if not accepted(r)]
    return {
        "step": label,
        "requests": len(results),
        "successes": len(results) - len(failures),
        "failures": failures,
        "latency_ms": {
            "p50": percentile(times, 0.50),
            "p95": percentile(times, 0.95),
            "max": max(times) if times else None,
        },
        "status": {str(s): sum(r["status"] == s for r in results)
                   for s in sorted(set(r["status"] for r in results), key=lambda x: -1 if x is None else x)},
    }


def main():
    print("TARGET: actual existing Render Free reviewer deployment")
    print("SAFE: read-only, no credentials, 3 warmups + <=30 requests, 8 workers max")
    print("ERROR POLICY: stop on first unexpected status, network error, or wave p95 >10s", flush=True)
    begin = time.monotonic()
    checks = ["/health/live", "/health/ready", "/demo-assets/documents.js"]
    warmups = [get(path, timeout=75) for path in checks]
    report = {
        "date_utc": datetime.now(timezone.utc).isoformat(),
        "target": BASE,
        "scope": "anonymous actual-hosted read-only ramp",
        "expected_requests": 33,
        "max_workers": 8,
        "waves": [],
        "warmup": summarize("warmup", warmups),
    }
    if report["warmup"]["failures"]:
        report["outcome"] = "STOP_WARMUP"
    else:
        for concurrent in WAVES:
            if time.monotonic() - begin > DEADLINE_SECONDS:
                report["outcome"] = "STOP_DEADLINE"
                break
            barrier = threading.Barrier(concurrent)
            wave = []
            with ThreadPoolExecutor(max_workers=concurrent) as pool:
                futures = [pool.submit(worker, barrier) for _ in range(concurrent)]
                for future in as_completed(futures):
                    try:
                        wave.extend(future.result(timeout=REQUEST_TIMEOUT * 2 + 20))
                    except Exception as exc:
                        wave.append({"path": "worker", "status": None, "ms": 0,
                                     "error": type(exc).__name__, "body": b""})
            item = summarize(f"{concurrent} concurrent clients", wave)
            report["waves"].append(item)
            print(f"Wave {concurrent}: {item['successes']}/{item['requests']} expected responses, "
                  f"p50 {item['latency_ms']['p50']} ms, p95 {item['latency_ms']['p95']} ms",
                  flush=True)
            if item["failures"]:
                report["outcome"] = "STOP_ERRORS"
                break
            if item["latency_ms"]["p95"] > MAX_P95_MS:
                report["outcome"] = "STOP_LATENCY"
                break
        else:
            report["outcome"] = "PASS_BOUNDED_READONLY_RAMP"
    report["actual_requests"] = report["warmup"]["requests"] + sum(
        wave["requests"] for wave in report["waves"])
    report["duration_seconds"] = round(time.monotonic()-begin, 2)
    print("REPORT_BEGIN")
    print(json.dumps(report, indent=2))
    print("REPORT_END", flush=True)
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as file:
            file.write("## SMART-PRO actual hosted read-only load ramp\n\n")
            file.write(f"Outcome: **{report['outcome']}**. Requests: "
                       f"{report['actual_requests']}/33. "
                       f"Elapsed: {report['duration_seconds']} s.\n\n")
            file.write("| Step | Requests OK | P50 | P95 |\n|---|---:|---:|---:|\n")
            for item in [report["warmup"], *report["waves"]]:
                file.write(f"| {item['step']} | {item['successes']}/{item['requests']} | "
                           f"{item['latency_ms']['p50']} ms | "
                           f"{item['latency_ms']['p95']} ms |\n")
            file.write("\n**Not authenticated acceptance, academic write load, or peak SLA.**\n")
    return 0 if report["outcome"] == "PASS_BOUNDED_READONLY_RAMP" else 1


if __name__ == "__main__":
    sys.exit(main())
