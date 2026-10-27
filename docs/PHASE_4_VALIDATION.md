# Phase 4 validation — 28 October 2026

## Backend and database

- **109 offline tests pass** in the isolated Python 3.12 environment using the hashed production runtime lockfile.
- The pinned local embedding model loads under those dependencies and returns valid 256-dimensional vectors.
- Actual PostgreSQL/pgvector tests pass for all migrations, idempotent migration reruns, quotas, ownership, retry delays, stale-worker recovery, cleanup leases, blocked-cleanup visibility, and cascading deletion.
- Migration `0005_phase4_operations.sql` is applied to the current Supabase project. Existing PDF sizes were backfilled; the existing Pickwick Papers index was retained.
- The API runs with its inline worker disabled. A separate Python worker handles uploads, retries, heartbeats, and private object cleanup.

## Real model and service checks

The opt-in full live suite passes with temporary, confirmed accounts and synthetic PDFs. No email is sent, and its accounts/files are removed afterward.

| Reviewed case | Verified result |
| --- | --- |
| Title | Field Notes, metadata citation, no invented page |
| Author | Ada Reader, metadata citation |
| Largest planet | Jupiter, supporting physical page 1 |
| Eruption cause | Magma, supporting physical page 2 |
| Photosynthesis gas | Oxygen, supporting physical page 3 |
| Bird navigation | Magnetic field, supporting physical page 4 |
| Pronoun follow-up | “They” resolves to birds with supporting page 4 evidence |
| Out-of-book question | Insufficient evidence, no fabricated citations |
| Instruction-override question | Insufficient evidence, no fabricated citations |

Each supported answer is checked against the stored owner's chunk, selected book, exact normalized quote, citation ranks, and physical page range. The report contains checks/timings rather than questions, answers, source excerpts, or credentials: ignored `backend/.cache/phase4-evaluation.json`.

Live operational checks also pass:

- Upload through an API without an inline worker reaches Ready through the standalone worker.
- Minute/day limits return HTTP 429 with Retry-After, remain isolated between users, and do not double-charge a completed request UUID's daily budget.
- Per-user concurrent inference is bounded; another user cannot read or delete the test book/history.
- A controlled interrupted processing attempt persists a scheduled retry and finishes on attempt two through the worker.
- A deletion request immediately hides the book, chunks, conversations, and citations while the row still exists pending cleanup. Releasing the synthetic cleanup lease allows the worker to remove the private file and cascade the database records.

## Browser security and production output

- TypeScript, the standalone production build, and the Vercel production build pass.
- Actual production HTML uses a fresh matching nonce on executable scripts for each request. Its script policy has neither unsafe-inline nor unsafe-eval, and private/security headers are present.
- The production browser test confirms Secure/SameSite=Lax auth cookies, protected chat, source expansion, history reload/resume/delete, and desktop/mobile layouts without JavaScript errors.
- The Vercel-mode production server also passes the live browser flow against Supabase and the real model: cited answers, insufficient-evidence responses, persisted history, private usage counts, and book deletion. Temporary accounts and PDFs are removed afterward.
- Fixture tests force a provider error to check safe retries and render hostile-looking answer/source markup literally; no injected image or handler executes.

## Dependency review and CI

- npm reports **zero known production dependency vulnerabilities**.
- pip-audit checks the pinned Python runtime dependencies and reports **zero known vulnerabilities**.
- CI configuration uses pinned action commits and read-only repository permissions. It checks tests, SQL behavior, the evaluation data, dependency audits, the Vercel build branch, Docker image builds, Compose configuration, and the HTTPS edge configuration.

An advisory scan is a point-in-time result, not a guarantee against every vulnerability. Rerun it and the reviewed quality set after dependency, prompt, or retrieval changes.

## Deployment boundary

The frontend is prepared for Vercel using root directory `frontend` and its default `.vercel.app` address. The API, worker, and local answer model need a separate persistent backend host and an HTTPS API URL.

No Vercel project or backend hosting account is connected in this workspace, and no online production URL has been deployed or verified. Docker is not installed locally; container runtime checks are supplied in CI. Local production-web and service checks do not claim to be a deployed cloud test. Follow [Vercel Deployment](VERCEL_DEPLOYMENT.md) and run the HTTPS preflight/smoke checks against the actual URLs before sharing the application.
