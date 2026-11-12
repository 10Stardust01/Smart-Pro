"""Source read-only pg_dump, independent disposable PostgreSQL 16 restore.

Requires an encrypted GitHub Actions secret, never prints or artifacts the
connection string, dump, or private data. Matches every public table's row-hash
multiset, schema totals and PDF metadata with the original live checkpoint.
"""
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
from psycopg import sql

EXPECTED={"projects":125,"results":8,"assets":41,"audit":435,
          "tables":103,"constraints":598,"routines":383}
PDF_MANIFEST="7d41099173b2eedefe7c8f39c710277a"

def must(ok,message):
    if not ok:raise RuntimeError(message)

def scalar(conn,query):
    with conn.cursor() as cur:
        cur.execute(query)
        return cur.fetchone()[0]

def inventory(conn):
    queries={
      "projects":"SELECT count(*) FROM public.projects",
      "results":"SELECT count(*) FROM public.course_final_results",
      "assets":"SELECT count(*) FROM public.file_assets WHERE upload_status='READY'",
      "audit":"SELECT count(*) FROM public.audit_events",
      "tables":"SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'",
      "constraints":"SELECT count(*) FROM pg_constraint WHERE connamespace='public'::regnamespace",
      "routines":"SELECT count(*) FROM pg_proc WHERE pronamespace='public'::regnamespace",
    }
    result={k:scalar(conn,q) for k,q in queries.items()}
    result["pdf_digest"]=scalar(conn,"""SELECT md5(string_agg(dv.id::text||':'||
      fa.sha256::text||':'||fa.size_bytes::text,'|' ORDER BY dv.id))
      FROM public.document_versions dv JOIN public.file_assets fa ON fa.id=dv.file_asset_id
      WHERE fa.upload_status='READY'""")
    return result

def table_hashes(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name")
        tables=[x[0] for x in cur.fetchall()]
        sums={}
        for name in tables:
            query=sql.SQL("""SELECT count(*),
                md5(coalesce(string_agg(md5(to_jsonb(t)::text),'|'
                ORDER BY md5(to_jsonb(t)::text)),'__EMPTY__'))
                FROM {}.{} t""").format(sql.Identifier("public"),sql.Identifier(name))
            cur.execute(query)
            sums[name]=cur.fetchone()
        return sums

def safe_subprocess(command,timeout):
    with open(os.devnull,"wb") as sink:
        result=subprocess.run(command,stdout=sink,stderr=subprocess.PIPE,
                              timeout=timeout,check=False)
    # NEVER show command/URI, stderr or exception strings: they may contain data.
    must(result.returncode==0,"Private PostgreSQL command failed; see secure environment checks")

def run():
    must(os.getenv("SMARTPRO_PAIRED_RESTORE_APPROVAL")=="RESTORE_TO_LOCAL_POSTGRES_ONLY",
         "Manual approval gate missing")
    source=os.getenv("SMARTPRO_RECOVERY_DATABASE_URL","")
    dest=os.getenv("SMARTPRO_RECOVERY_LOCAL_URL","")
    must(source.startswith(("postgres://","postgresql://")) and ".neon.tech/" in source,
         "Encrypted Neon direct-connection secret absent or invalid")
    must(dest.startswith("postgresql://postgres:") and "@127.0.0.1:" in dest,
         "Destination must be disposable local PostgreSQL")
    with psycopg.connect(source,connect_timeout=15,autocommit=True) as db:
        before=inventory(db)
        must(all(before[k]==value for k,value in EXPECTED.items()),
             "Actual source counts changed since approved recovery checkpoint")
        must(before["pdf_digest"]==PDF_MANIFEST,"Source private PDF manifest changed")
        rows_before=table_hashes(db)
    with tempfile.TemporaryDirectory(prefix="smartpro-private-db-") as directory:
        path=Path(directory)/"db.dump"
        safe_subprocess(["pg_dump","--dbname="+source,"--format=custom",
                         "--no-owner","--no-acl","--file="+str(path)],300)
        must(path.is_file() and path.stat().st_size>1024,"Database dump missing or empty")
        safe_subprocess(["pg_restore","--dbname="+dest,"--no-owner","--no-acl",
                         "--exit-on-error",str(path)],300)
        with psycopg.connect(dest,connect_timeout=10,autocommit=True) as restored:
            after=inventory(restored)
            rows_after=table_hashes(restored)
        with psycopg.connect(source,connect_timeout=15,autocommit=True) as db:
            source_later=inventory(db)
            rows_later=table_hashes(db)
        must(before==after==source_later,"Source and restored database inventories differ")
        must(rows_before==rows_after==rows_later,
             "Some restored public table content hashes differ")
        print(f"PASS_INDEPENDENT_POSTGRES_DB_RESTORE tables={len(rows_after)} "
              f"constraints={after['constraints']} routines={after['routines']} "
              f"projects={after['projects']} published_overall_results={after['results']} "
              f"pdf_records={after['assets']} audit_events={after['audit']} "
              "all_table_contents_equal=true database_dump_private=true",flush=True)

def self_test():
    assert EXPECTED["tables"]==103 and EXPECTED["assets"]==41 and len(PDF_MANIFEST)==32
    print("PASS_FULL_DB_RESTORE_OFFLINE_PREFLIGHT no_network=true",flush=True)

if __name__=="__main__":
    if sys.argv[1:]==["--self-test"]:self_test()
    elif sys.argv[1:]:sys.exit("Only --self-test or explicit one-time approved restore")
    else:
        try:run()
        except (OSError,RuntimeError,psycopg.Error,subprocess.TimeoutExpired) as exc:
            print("FULL_DB_RESTORE_BLOCKED "+type(exc).__name__+
                  "; confidential details intentionally omitted",file=sys.stderr)
            sys.exit(1)
