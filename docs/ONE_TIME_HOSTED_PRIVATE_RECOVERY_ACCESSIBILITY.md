# One-time actual hosted private PDF recovery and expanded accessibility audit

**State: PREPARED, NOT YET EXECUTED.** This workflow launches once on a reviewed merge to `main` that adds its own workflow file. It is not manual-click dependent, scheduled, recurring, or a load test. No paid services, browser credits, trials, new accounts, academic writes, change to Render/Neon routing, or private PDF download artifacts.

## Private PDF originals — protected read-only gate

An independent read-only Neon checkpoint on 12 Nov 2026 found 125 projects, **41 READY private PDF file assets** and 41 document versions. Its `md5(string_agg(version UUID:SHA-256:size, '|' ORDER BY version UUID))` digest was `7d41099173b2eedefe7c8f39c710277a`. The one-time audit signs in as the **existing authorized synthetic HOD** through the actual Render Free reviewer, enumerates exactly 125 authorized projects in 25-project pages, requests scoped project document-version metadata, then downloads at most 60 original PDFs (expected exactly 41). Every byte stream is verified by the application against its database SHA-256 before the HTTPS response, and separately rehashed in CI against the independent Neon checkpoint. The script then uses `verify_hosted_pdf_recovery.py` to create and verify a fresh private local copy, printing only counts and total bytes.

All PDF bytes and JSON manifest remain in an ephemeral temporary directory, never an Actions artifact, issue, commit or logs; failures do not weaken access checks or become passes. The script stops on changed live project/PDF counts, missing HOD entitlement, invalid PDF, checksum mismatch or duplicate version. This **can close byte-level original private PDF retrieval and independent local-copy recovery** if fully successful. It **cannot close full independent DB dump + object-storage restoration**, historical RPO/RTO, or end-to-end app boot from a separately restored database; an isolated Neon branch copy was verified earlier but is not equivalent.

The PDF checker also samples tagged structure trees and extractable text. An untagged source PDF is an authoring/accessibility issue: the platform must not silently rewrite academic evidence.

## Hosted accessibility

Five real signed-in synthetic roles, ten screens, pinned free axe-core WCAG 2.0/2.1/2.2 A/AA sampling, all visible input/select/textarea label associations, unique IDs and landmarks, non-destructive native confirmation-dialog Escape/focus, and 12 Tab steps per role with visible focus checks. Automated checks do not verify actual NVDA/VoiceOver speech, every offscreen/error form, zoom reflow or accessibility of documents authored by students. The original PDF inspection separately provides source-document text/tag evidence. These human/third-party content checks remain explicitly distinct and require human participation if requested for institutional acceptance.

## Scope

No paid tools, free trials, extra named identities, login creation, heavy stress ramp, repeated probes, extra hosted test project or repository secret disclosure. Do not rerun unless the one-time job reveals an actionable defect. Keep historical/failed findings in register without marking them passed prematurely.
