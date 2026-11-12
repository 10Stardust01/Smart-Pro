"""Actual reviewer private PDF byte retrieval, independent checksum and local restore.

One-time read-only CI audit. Uses only current existing authorized synthetic HOD,
never downloads anonymous documents, never logs private contents, never uploads
PDF artifacts, and never changes Neon/Render or academic records.
"""
import asyncio
import hashlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import httpx
from pypdf import PdfReader

from hosted_mixed_academic_pilot import wait_for_free_staging_readiness
from hosted_synthetic_https_writes import Reviewer, case_from, json_success, require
from verify_hosted_pdf_recovery import verify_and_copy

DEPT="10000000-0000-4000-8000-000000000001"
PROJECT_COUNT=125
PDF_COUNT=41
EXPECTED_DIGEST="7d41099173b2eedefe7c8f39c710277a"
MAX_PROJECTS=150
MAX_PDFS=60

def fingerprint(items):
    pairs=sorted(items)
    return hashlib.md5("|".join(f"{vid}:{sha}:{size}" for vid,sha,size in pairs).encode("ascii")).hexdigest()

def inspect(data):
    try:
        pdf=PdfReader(io.BytesIO(data), strict=False)
        root=pdf.trailer["/Root"]
        mark=root.get("/MarkInfo")
        mark=mark.get_object() if mark else {}
        tagged=bool(root.get("/StructTreeRoot")) and bool(mark.get("/Marked"))
        text=any((p.extract_text() or "").strip() for p in pdf.pages[:3])
        return int(tagged),int(text),0
    except Exception:
        return 0,0,1

async def run():
    require(os.getenv("SMARTPRO_PDF_RESTORE_CHECK")=="READ_ONLY_PRIVATE_PDF_RESTORE","Read-only approval gate absent")
    accounts=json.loads(os.getenv("SMARTPRO_HOSTED_TEST_ACCOUNTS") or "{}")
    require(isinstance(accounts.get("HOD"),dict),"Private HOD account missing")
    await wait_for_free_staging_readiness()
    hod=Reviewer("HOD",accounts["HOD"])
    try:
        await hod.login()
        base=f"/api/v1/documents/departments/{DEPT}"
        first=json_success(await hod.get(base+"?listing=1&page=1"),"HOD project page")
        total=first.get("total")
        require(type(total)==int and total==PROJECT_COUNT and total<=MAX_PROJECTS,
                "Project population changed; no recovery acceptance")
        require(first.get("pageSize")==25,"Unexpected project page size")
        projects=[]
        for n in range(1,(total+24)//25+1):
            page=first if n==1 else json_success(await hod.get(base+f"?listing=1&page={n}"),
                                                   "HOD project page")
            require(page.get("page")==n,"Unexpected project page sequence")
            projects.extend(page.get("projects") or [])
        ids=[p["id"] for p in projects]
        require(len(ids)==total and len(set(ids))==total,"Project enumeration incomplete")
        print(f"RECOVERY_AUTHORIZED_PROJECTS count={len(ids)} pages={(total+24)//25}",flush=True)
        found={}
        for pid in ids:
            scope=json_success(await hod.get(base+"?project="+pid),"Authorized HOD project scope")
            case=case_from(scope,pid)
            if case:
                for entry in case.get("versions") or []:
                    vid=entry.get("id")
                    require(isinstance(vid,str) and vid not in found,"Duplicate/missing PDF version identity")
                    found[vid]=entry
                require(len(found)<=MAX_PDFS,"PDF bound exceeded")
        require(len(found)==PDF_COUNT,"Project-scoped PDF inventory not equal to DB checkpoint")
        with tempfile.TemporaryDirectory(prefix="smartpro-private-restore-") as folder:
            root=Path(folder); src=root/"originals"; src.mkdir(mode=0o700)
            manifest=[]; tuples=[]; tags=texts=errors=total_bytes=0
            for vid,info in sorted(found.items()):
                res=await hod.get(f"/api/v1/document-versions/{vid}/content?download=1")
                require(res.status_code==200,"Authorized private PDF request denied")
                require(res.headers.get("content-type","").startswith("application/pdf"),
                        "Recovered content type invalid")
                data=res.content
                require(0<len(data)<=2*1024*1024 and data.startswith(b"%PDF") and
                        data.rstrip().endswith(b"%%EOF"),"Recovered file envelope/size invalid")
                if type(info.get("bytes")) is int:
                    require(len(data)==info["bytes"],"Response bytes differ from project metadata")
                sha=hashlib.sha256(data).hexdigest()
                key=vid+".pdf"
                (src/key).write_bytes(data)
                manifest.append({"key":key,"sha256":sha,"size_bytes":len(data)})
                tuples.append((vid,sha,len(data)))
                total_bytes+=len(data)
                a,b,c=inspect(data);tags+=a;texts+=b;errors+=c
                del data
            require(fingerprint(tuples)==EXPECTED_DIGEST,
                    "Original downloaded SHA-256 data does not match independent Neon DB checkpoint")
            mf=root/"manifest.json";mf.write_text(json.dumps({"objects":manifest}),encoding="utf-8")
            restored=verify_and_copy(mf,src,root/"restore")
            require(restored["count"]==PDF_COUNT and restored["bytes"]==total_bytes,
                    "Local independent restore failed")
            print(f"PASS_PRIVATE_PDF_BYTE_RESTORE files={PDF_COUNT} bytes={total_bytes} "
                  "neon_manifest_match=true fresh_local_copy=true no_artifacts_uploaded=true",flush=True)
            print(f"PDF_ACCESSIBILITY_AUDIT files={PDF_COUNT} structure_tagged={tags} "
                  f"extractable_text={texts} parser_errors={errors} "
                  "human_screenreader_acceptance=false",flush=True)
    finally:
        await hod.close()

def self_test():
    assert fingerprint([("b","0"*64,15),("a","f"*64,10)])==hashlib.md5(
        ("a:"+"f"*64+":10|b:"+"0"*64+":15").encode()).hexdigest()
    assert PROJECT_COUNT==125 and PDF_COUNT==41 and MAX_PDFS==60
    print("PASS_PRIVATE_RECOVERY_OFFLINE_GUARDS no_network=true",flush=True)

if __name__=="__main__":
    if sys.argv[1:]==["--self-test"]:self_test()
    elif sys.argv[1:]:sys.exit("Only --self-test or approved read-only run")
    else:
        try:asyncio.run(run())
        except (ValueError,KeyError,RuntimeError,httpx.HTTPError,asyncio.TimeoutError) as exc:
            print("PRIVATE_RECOVERY_BLOCKED "+type(exc).__name__+": "+str(exc)[:160],file=sys.stderr)
            sys.exit(1)
