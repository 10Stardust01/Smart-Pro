# SMART-PRO — actual Render HTTPS concurrency acceptance (free-only)

This is the real, signed-in **HTTPS** write test, not a local SQL mock or a
read-only test. It is deliberately **manual-only**, limited to 2 or 4
simultaneous uploads and two competing academic writes per phase. The existing
Render and Neon services must remain on their **Free** plans; do not enable a
paid service, trial, metered credit or TinyFish.

## 1. Verify the intended environment

- GitHub repository: `10Stardust01/Smart-Pro` (public repository).
- Render existing Free service: `smartpro-reviewer-25775915`; URL:
  `https://smartpro-reviewer-25775915.onrender.com`.
- Neon Free reviewer staging `main` retains actual persistent synthetic
  projects. This test **creates a new synthetic project and permanent audit
  records**. It does not delete or change prior published projects.
- Use the current synthetic department
  `10000000-0000-4000-8000-000000000001`, offering
  `8b40a6e1-419d-43c8-b625-279f82713b02`, existing Student team
  `04da071d-f86b-415d-a580-123ba8f2236b`, Guide
  `00000000-0000-4000-8000-000000000003`, and stage key `evidence`
  **only while these are verified synthetic fixtures**. Do not point this
  workflow at an institutional/real-data offering.

## 2. Create reviewer credentials privately on your computer

Use the repository's `scripts/generate_reviewer_test_accounts.py` script with
your local Python 3.12 (Python standard library only; no pip install needed).

```bash
python scripts/generate_reviewer_test_accounts.py
```

Enter five new, distinct, staging-only passwords of 16+ characters.
**Never paste passwords into ChatGPT, GitHub issues, commits or PR comments.**

The generator writes two private files outside the repository under your home
folder's `.smartpro-reviewer-private` directory:

- `render-reviewer-test-accounts.json` maps `test-*-https` aliases to
  synthetic actor IDs and **salted PBKDF2 password hashes**.
- `github-actions-test-accounts.json` maps `Student`, `Faculty`,
  `Coordinator`, `HOD`, and `Admin` to the matching aliases and private
  **plaintext staging-only passwords**.

These are **not** genuine institutional users; they map to existing synthetic
actors with already-authorized effective roles. The generated JSON files
remain on your own computer; do not commit them.

## 3. Configure Render safely (owner action)

Open the existing Render Free service → **Environment** →
**Add Environment Variable**. Set exactly:

- Key: `SMARTPRO_REVIEWER_TEST_ACCOUNTS`
- Value: the entire JSON object from `render-reviewer-test-accounts.json`

**Merge/add this variable only; never replace/delete all existing variables.**
Save and deploy the same reviewer-staging branch if Render requires a restart.
Do not enable auto-deploy or change plans. This only provisions supplemental
`test-` aliases; it does not replace primary reviewer logins.

## 4. Configure the private GitHub secret (owner action)

GitHub → `10Stardust01/Smart-Pro` → **Settings** →
**Secrets and variables** → **Actions** → **New repository secret**.

- Name: `SMARTPRO_HOSTED_TEST_ACCOUNTS`
- Value: entire JSON object from `github-actions-test-accounts.json`

Do not put this JSON in a workflow input: workflow inputs and logs can be
visible. Keep it exclusively in the **Actions secret**.

## 5. Run first the read-only signed-in smoke

Once the credential setup is saved, GitHub → **Actions** →
**SMART-PRO hosted reviewer authenticated smoke (manual, free)** →
**Run workflow** → `main`.

Ensure all five roles pass (login, secure signed cookie, own workspace and
cross-role denial). Do not run the writes if this fails.

## 6. Run the bounded HTTPS academic writes

GitHub → **Actions** →
**SMART-PRO bounded authenticated HTTPS academic writes (MANUAL, free)** →
**Run workflow** → `main`, then enter exactly
`RUN_SYNTHETIC_HOSTED_WRITES` into the approval field.
Use the already verified synthetic IDs from section 1 and select **2**
upload clients for the first run. Do not run 4 clients unless the 2-client
test passed and the Free service stayed healthy.

The workflow will:

1. Sign in each role over HTTPS with CSRF/signed session handling.
2. Verify the existing synthetic offering, Student membership and approved
   assessment stage; abort before academic writes if those are missing.
3. Create one clearly labeled synthetic project within the existing Student
   team and assign its Guide.
4. Run two simultaneous full PDF multipart uploads; read the private PDFs
   back through the application and compare actual SHA-256 bytes.
5. Race two distinct versioned submission commands (one accepted, one stale
   request denied).
6. Create its approved assessment stage; race two Faculty draft mark saves,
   then two finalizations (exactly one success in each case).
7. Race stage publication and confirm one released version.
8. Check readiness and response time around each wave. Stop on unexpected
   5xx, failures, or p95 over 10 seconds. **No automatic retries**.

The new project, document versions, scores and audit trail are **retained for
evidence** and NOT silently deleted. Do not run on real coursework. The Free
Render service's cold start may itself exceed 10 seconds; report such failures
as measured outcomes rather than overriding them.

## 7. Remove supplemental test access after evidence is saved

After testing and collecting GitHub Actions output:

- Remove ONLY `SMARTPRO_REVIEWER_TEST_ACCOUNTS` from Render Environment;
  save/redeploy if needed. Do not remove normal reviewer identities or any
  existing app secrets.
- Delete ONLY the `SMARTPRO_HOSTED_TEST_ACCOUNTS` GitHub Actions secret.
- Keep completed test project results/audit history. Securely delete local
  private credential files when no longer needed.

**Never claim the test passed before the GitHub workflow actually executes.**
The existence of this document and workflow alone is not hosted concurrency
acceptance, and it is not institutional production approval.
