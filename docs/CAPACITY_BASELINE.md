# SMART-PRO local capacity baseline

8 November 2026 · Base 2e06cd0f4e771d4cc82500fb0150176b632f5782.
These local measurements do not establish institutional capacity.

## Hardening follow-up

Candidate 058 was subsequently aligned with local `smartpro_dev` on
loopback PostgreSQL port 55439. The 8 November backup was restored into a
disposable database first. All 101 public table fingerprints, constraints
and the private PDF matched; only the course command definition changed,
with identical owner, grants, SECURITY DEFINER and search path. The
development service was restarted and all five workspace reads returned 200.

The original 300-workflow run produced **141 complete and 159 incomplete**.
Its aggregate ledger contained 371 successful HTTP requests and 159 HTTP
503 responses (530 total). There were no recorded transport timeouts or
unfinished workers. This was a read workflow, including POST-based search
and history, so a partly completed workflow did not imply a lost write.
The old run did not retain request IDs. A traced repeat independently
matched every client response: Uvicorn admission rejects had no WSGI/Django
trace, and all other requests matched Django's status. Uvicorn's h11
implementation checks both open connections and tasks before routing; the
configured limit was 48 and the WSGI thread pool was 12.

The comparison changed only Django connection age, from 0 to 60 seconds
(health checks enabled). It reused the 500-project fixture, Windows host,
12 threads, admission cap, think time, and workload schedule. The generator,
application and database shared the host. Counts below are **workflows**;
latencies include all HTTP outcomes. Every incomplete workflow in the
comparison was rejected by admission. No other failures, client or server
timeouts, or cancellations were observed.

| Worker cap / offered jobs/s | Connection age | Seconds | Complete / attempted | Admission rejects | HTTP p50 / p95 / p99 ms | Requests/s | DB peak connections / active / lock waiters |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 / 5 | 0 s | 21.03 | 100/100 | 0 | 314 / 434 / 457 | 9.75 | 4 / 4 / 0 |
| 10 / 5 | 60 s | 20.49 | 100/100 | 0 | 80 / 173 / 204 | 10.00 | 3 / 2 / 0 |
| 25 / 10 | 0 s | 41.12 | 400/400 | 0 | 358 / 518 / 594 | 19.94 | 8 / 8 / 1 |
| 25 / 10 | 60 s | 40.57 | 400/400 | 0 | 71 / 166 / 213 | 20.21 | 6 / 4 / 1 |
| 50 / 18 | 0 s | 13.56 | 137/180 | 43 | 1,603 / 2,275 / 2,604 | 25.08 | 12 / 12 / 3 |
| 50 / 18 | 60 s | 10.68 | 180/180 | 0 | 73 / 167 / 207 | 34.55 | 7 / 5 / 1 |
| 100 / 30 | 0 s | 14.69 | 106/300 | 194 | 1,042 / 2,539 / 2,983 | 33.98 | 12 / 12 / 3 |
| 100 / 30 | 60 s | 10.79 | 300/300 | 0 | 77 / 191 / 262 | 56.98 | 12 / 9 / 1 |
| 100 / 100, burst | 60 s | 5.65 | 196/400 | 204 | 338 / 627 / 1,019 | 123.54 | 12 / 12 / 6 |
| Sequential recovery | 60 s | 8.09 | 20/20 | 0 | 87 / 197 / — | 5.07 | 12 / 1 / 0 |

At 30 offered jobs/s, completed workflow throughput rose from 7.22 to
27.79/s; actual peak workflows fell from 54 to 17. The application used
6.58 versus 3.64 CPU seconds and peaked at 102.6 versus 76.6 MiB working set.
The generator used 1.55 versus 1.47 CPU seconds. The 41-second 10 jobs/s
run is the steady comparison; 30 jobs/s is only a short successful wave.
At 100 offered jobs/s, 494 HTTP requests succeeded and 204 were rejected
before Django. Rejected request p95 was 30 ms and successful request p95
731 ms. The highest measured ASGI in-flight count was 47. The application
used 3.13 CPU seconds and peaked at 88.3 MiB; the
generator used 1.31 CPU seconds. No connection exhaustion occurred.

On the reused profile, 24 PDF workflows completed in 2.13 seconds
(11.25/s), including 8 upload and 8 submit retries. Uploaded bytes were
10,631,280 and upload HTTP p95 was 156 ms. The 12 concurrent evaluation
workflows completed in 10.59 seconds (1.13/s), with both students'
marks and stage/overall versions checked. Academic command contention
still reached nine lock waiters; neither retry tuning nor a higher
admission cap would fix that. A fault injection withheld the HTTP body
after success headers for both an upload and a submission. Both client
timeouts matched Django 200 traces; the committed rows existed before
retry, and the same keys recovered one version and one attempt. Final
inventory matched all 37 stored PDFs to their PostgreSQL hashes and byte
counts (16,209,654 bytes), with 37 versions, 37 attempts and 18 overall
releases in the disposable fixture. The five targeted course regressions
and the frontend upload response checks passed.

Use `--profile-sql --trace-http --conn-age 0` or `--conn-age 60` with
`serve` and `--request-ledger .test-data/<wave>.json` with `mixed`.
Match the ledger's request ID to the server's JSON trace. Use
`lost-receipt --offset <unused-project-index>` only on the traced disposable
server; this deliberately delays the success body. Example steady profile:
`mixed --users 25 --jobs 400 --arrival 10`; short profile:
`mixed --users 100 --jobs 300 --arrival 30`.
See [runtime operating guidance](DEPLOYMENT_AND_RECOVERY.md#provisional-capacity-settings)
for deployment limits and retry behavior.

## Environment and method

- Windows build 26300, Intel Core Ultra 7 155H (22 logical CPUs), 15.5 GiB
  RAM; Python 3.12.14, Django 5.2.18, PostgreSQL 16.15, Uvicorn 0.54.0.
  The server, generator, database and private file storage shared one machine.
  PostgreSQL: 100 max connections, 128 MB shared buffers; application
  connection/statement/lock limits 5/10/5 seconds.
- One Uvicorn process with a 12-thread WSGI executor and 48-connection/task
  admission limit, without auto-reload, proxy, external storage, TLS, real
  authentication or the notification worker. The installed Uvicorn WSGI
  bridge buffers request bodies and does not close the WSGI iterable. The
  harness closes it explicitly in the profiled runs, using Django's default
  connection age of zero.
- Two schema-only disposable databases with candidates through 057 and
  separate private file roots. Fixture creation used scoped APIs for
  offerings, teams, memberships, guides and projects. The 100- and 500-project
  datasets each had two students per team, one offering and a pinned two-stage
  TEAM assessment plan. A subset acquired submissions, approvals and results
  through the API. Staff identities were shared by role. Several thousand
  projects, multiple departments and historical cycles remain unmeasured.
- Mixed arrivals were 60% Student, 20% Faculty, 10% Coordinator, 5% Admin and
  5% HOD, with two or three authorized calls and 200 ms think time. The worker
  cap is not a claim of continuously active users. Request percentiles are
  nearest rank (p95 with at least 20 samples, p99 with at least 100). The
  monitor sampled connections and lock waiters every 250 ms. HTTP includes
  queueing and response transfer. Django SQL timing counts cursor executions,
  including waits, without splitting SQL function internals.

## Initial HTTP results

These runs used the original WSGI adapter, before response cleanup. The
[Chrome navigation measurements](REPOSITORY_STATUS.md#local-navigation-performance)
are separate browser evidence against the development server.

| 100-project workload | Worker cap / scheduled jobs/s | Seconds | Workflows passed | Requests/s | HTTP p50 / p95 / p99, ms | Peak DB connections / lock waiters |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Sequential mixed | 1 / 20 | 18.35 | 20/20 | 2.23 | 300 / 478 / — | 9 / 0 |
| Mixed | 10 / 5 | 20.90 | 100/100 | 9.81 | 323 / 451 / 483 | 10 / 1 |
| Mixed | 25 / 10 | 16.87 | 160/160 | 19.44 | 248 / 377 / 402 | 12 / 1 |
| Mixed | 50 / 18 | 12.72 | 180/180 | 29.02 | 764 / 1,430 / 1,671 | 12 / 4 |
| Document burst | 25 / 15 | 4.67 | 30/30 | 23.56 | 588 / 796 / 850 | 12 / 0 |
| Evaluations, before 058 | 10 / 4 | 14.41 | 1/12 | 4.86 | 463 / 5,417 / — | 12 / 10 |
| Evaluations, after 058 | 10 / 4 | 19.38 | 12/12 | 7.43 | 914 / 2,066 / 2,547 | 12 / 9 |
| Mixed overload after 058 | 100 / 30 | 13.52 | 141/300 | 39.21 | 1,248 / 1,857 / 2,044 | 12 / 3 |
| Sequential recovery | 1 / 20 | 16.01 | 20/20 | 2.56 | 267 / 440 / — | 12 / 0 |

Sequential median HTTP times were 257 ms workspace, 435 ms document views,
329 ms offering details and 395 ms evaluation queue. Admin directory,
candidates and leadership were sampled once (196, 184 and 247 ms).
Cold-start percentiles were not measured. The 100-worker wave had 159
failed workflows from HTTP 503 before Django; PostgreSQL did not exhaust
connections. The next sequential wave recovered. The local ceiling made a
200-worker run uninformative.

## Profiled runs with request cleanup

| Workload | Worker cap / actual peak | Jobs/s offered | Seconds | Workflows passed | Requests/s | HTTP p50 / p95 / p99, ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Mixed, 100 projects | 25 / 11 | 8 | 63.50 | 500/500 | 16.14 | 317 / 571 / 647 |
| Mixed, 100 projects | 25 / 13 | 10 | 16.98 | 160/160 | 19.31 | 332 / 606 / 681 |
| Mixed, 500 projects | 25 / 11 | 10 | 17.16 | 160/160 | 19.11 | 334 / 468 / 498 |
| Mixed with one 1,000-row XLSX import, 500 projects | 25 / 12 | 10 | 17.06 | 160/160 | 19.23 | 338 / 480 / 532 |
| Documents, 500 projects | 10 / 10 | 8 | 2.76 | 12/12 | 15.93 | 329 / 407 / — |
| Evaluation, 500 projects | 5 / 5 | 2 | 11.04 | 6/6 | 7.07 | 416 / 924 / — |

The one-minute wave completed 7.87 workflows/s (workflow p95 1,188 ms).
The 500-project mixed wave reached seven active database connections and
one sampled lock waiter. It had a median four cursor executions per request,
281 ms SQL and 327 ms Django handler time. The application used 4.41 CPU
seconds over the 17.16-second wave and a 75 MiB process-lifetime peak working
set. Endpoint snapshots showed about 354 MiB aggregate PostgreSQL working
set; sampled process CPU deltas exclude transient backends and are not
cluster CPU utilization. Generator CPU, sustained memory growth and
disk-write time were not isolated.

Standalone 30-row CSV preview/apply took 180/190 ms; 1,000-row XLSX
preview/apply took 657/261 ms. Both returned batch receipts. The controlled
import wave showed no errors, with mixed p95 480 ms versus 468 ms without it.
One run per case cannot establish a statistically reliable import penalty.

## Integrity and corrective change

- The document burst accepted 30 distinct teams, 40 upload and 40 submit
  requests including retries. Exactly 30 PDF files remained, totalling
  13,289,090 bytes. Authorized downloads matched every source SHA-256.
  PDFs were roughly 16 KiB, 256 KiB and 1 MiB. Upload HTTP p95 was 796 ms;
  submit p95 was 724 ms. File-only write timing was not isolated.
- In the shared-team race, two authorized students uploaded distinct PDFs
  concurrently. Both immutable versions remained in order, exactly one
  competing submit succeeded, and an outsider could not read the file.
  PostgreSQL asset checksums matched both private files.
- Post-run database/storage inventory matched every ready asset: 58 PDFs
  in the 100-project fixture and 12 in the 500-project fixture, with
  30,286,996 total bytes and no unregistered PDFs in either private file
  directory. The fixtures held 25 and 6 overall release records, respectively.
- PostgreSQL logged deadlocks: stage creation resolved the acting role
  (which locks Coordinator mandates) before locking departmental governance.
  Publication took governance first. Candidate 058 moves governance before
  role resolution without removing authority checks or weakening locks.
  Owner, grants, definer setting and search path were unchanged. Preflight
  rejects unexpected or already updated function text. During the initial
  baseline, candidate 058 was installed only in disposable databases.
- The comparable rerun used unused projects of the same offering. Per-request
  distributions differ in operation mix because failed workflows stop early.
  After response cleanup, another 12 workflows included Guide approval,
  both stage releases and overall publication. All passed; both students'
  marks were verified as 61.50, with one release per stage and one overall
  release. Django recorded 3 median cursor executions and 670 ms median SQL
  time versus 722 ms median handler time.
- Up to nine evaluation lock waiters remained after the fix. Narrowing the
  shared academic locks requires separate authority and publication testing.
  Raising timeouts would not remove contention.

The course suite passed 29 existing contracts; the initial new probe failed
to identify the blocked backend. Its corrected PID-based regression fails
without 058 (the command holds a Coordinator mandate while blocked) and
passes with 058 in a fresh database. The document suite passed all 57 tests,
including shared submission/deadline and storage failure cases. The frontend
workflow test, Python compilation and harness lint passed. Actual deadline
boundary stress and interrupted transport under load were not reproduced.

## Reproduce

Use the locked virtual environment and existing loopback PostgreSQL test
configuration. Keep generated manifests, PDFs, datasets and JSON reports
in ignored .test-data. The harness rejects the persistent development database.

```powershell
$python = '.venv/Scripts/python.exe'
& $python scripts/capacity_baseline.py create
$manifest = '.test-data/<generated-isolated-database>.json'
# Server terminal: use --projects 500 for the larger fixture.
& $python scripts/capacity_baseline.py serve --manifest $manifest --projects 100 --profile-sql
# Client terminal:
& $python scripts/capacity_baseline.py seed --manifest $manifest --projects 100
& $python scripts/capacity_baseline.py mixed --manifest $manifest --users 25 --jobs 500 --arrival 8
& $python scripts/capacity_baseline.py documents --manifest $manifest --users 25 --jobs 30 --arrival 15
& $python scripts/capacity_baseline.py evaluations --manifest $manifest --users 10 --jobs 12 --arrival 4
& $python scripts/capacity_baseline.py install-fix --manifest $manifest
# Use unused project offsets and seed corresponding PDFs for write comparisons.
& $python scripts/capacity_baseline.py shared --manifest $manifest --offset 60
& $python scripts/capacity_baseline.py intake --manifest $manifest --jobs 1000 --format xlsx
```

## Provisional objectives and follow-up

Explore p95 targets of 500 ms for ordinary warm API reads, 2 s for ordinary
page transitions and 1 MiB uploads, and 3 s for academic commands at an
agreed normal arrival rate. Target zero lost writes, under 1% unexpected
responses within the measured envelope and 30% worker/connection headroom.
Measure controlled rejection and recovery within 30 seconds after bursts.
For bulk import, explore preview and apply each under 5 seconds for 1,000
clean rows. These are proposed engineering thresholds.

Repeat on intended deployment hardware with the selected WSGI server,
proxy limits, identity provider and real storage topology. Agree expected
class sizes, departments and burst rates. Run a longer soak with more
faculty and offerings, more history, actual deadline boundary races,
interrupted uploads and restart recovery. Use a separate generator host
and measure request buffering, resource headroom and storage latency.
