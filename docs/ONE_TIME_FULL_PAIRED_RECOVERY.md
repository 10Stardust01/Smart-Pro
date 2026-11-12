# Final independent paired local recovery — secure manual run

> **Verified audit side effect (12 Nov 2026):** The completed authorized 41-file recovery download appended exactly **41 `DOCUMENT_ACCESSED` entries** to live Neon audit history between 02:03–02:06 UTC. The total audit rows increased from **435 to 476** without changing projects, final marks, or PDF assets. The independent database restore compares its captured audit row count and full row digests across source/destination *at execution time*; it now checks a **minimum preserved history of 435**, rather than requiring the obsolete exact count. Subsequent authorized document reads may increase it further. The DB dump itself is read-only; the PDF content endpoint intentionally audits authorized access.


**Prepared but not yet run.** The original private PDF byte check already PASSED on the actual Render Free reviewer: [run #43138537587](https://github.com/10Stardust01/Smart-Pro/actions/runs/43138537587), **41 files, 9,224,709 bytes**, exact independent Neon SHA-256 manifest, fresh verified local copy and no artifacts. This separate workflow adds the missing **full database dump and local PostgreSQL 16 restore**.

The recovery uses one disposable free GitHub Actions runner with PostgreSQL 16 container. It reads the current existing Neon PostgreSQL database through a **database URL saved as an encrypted GitHub Actions repository secret**, exports a private custom-format dump, restores it to a new disposable local PostgreSQL 16 database, and compares every public table's full content-hash multiset and row count, the public schema/constraint/routine counts and the published result/PDF manifest against source. It then independently downloads and restores all 41 original private PDFs with the previously passing authorized HOD checker, confirming the same manifest. Nothing is uploaded as a GitHub artifact or committed; never puts a database URL in workflow inputs, issue comments or chat.

## One essential secure setup action

In GitHub repository **Settings → Secrets and variables → Actions → New repository secret**, create **`SMARTPRO_RECOVERY_DATABASE_URL`** whose value is the **direct (unpooled) Neon PostgreSQL connection string** obtained securely from the existing SMART-PRO Neon project. Do not paste this URL into ChatGPT, workflow inputs, code or terminal logs. The connection must have permission to read all source public tables so `pg_dump` can work, and ideally should be restricted to backup-read access. It must not be a new paid Neon project or trial.

Then in **Actions**, select **SMART-PRO one-time independent PostgreSQL plus private PDF restore (manual, Free)**, branch `main`, enter the exact approval `RESTORE_TO_LOCAL_POSTGRES_ONLY` and run **once**. No further paid services, additional GitHub accounts or hosting changes are required. If absent/invalid secret or different source counts, the workflow fails closed without deleting/replacing the original database.

## Acceptance scope

Only a run containing **both** `PASS_INDEPENDENT_POSTGRES_DB_RESTORE` and `PASS_PRIVATE_PDF_BYTE_RESTORE` closes a **paired independent local DB+private bytes recovery** gate. App boot against a separate restored hosted instance, restored destination S3 authorization/download, operational RPO/RTO and human institution sign-off are separate gates; never conflate them. Avoid unnecessary reruns, uncontrolled traffic, browser credits, paid upgrades or free trials.
