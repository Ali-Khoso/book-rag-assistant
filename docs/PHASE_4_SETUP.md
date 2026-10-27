# Phase 4 — Operate and deploy Bookwise

Phase 4 adds a separately runnable worker, bounded processing retries, durable deletion cleanup, shared usage budgets, production HTTP/browser hardening, monitoring, evaluation data, and CI/deployment configuration. The intended frontend target is Vercel; see [Vercel Deployment](VERCEL_DEPLOYMENT.md). A live production deployment still needs the user's Vercel project and a persistent backend host.

## Database and local start

Apply `supabase/migrations/0005_phase4_operations.sql` after migrations 0001–0004. The migration retains existing books/indexes and backfills file sizes from Supabase Storage metadata. It can be run again. Start the Phase 4 API only after this migration is available; operational limits fail closed if their RPCs are missing.

For normal local work, the API can still run its convenience worker. To verify the actual production separation, use two terminals:

```powershell
# Terminal 1: API only
cd backend
$env:PROCESSING_ENABLED = 'false'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

```powershell
# Terminal 2: durable worker
cd backend
.\.venv\Scripts\python.exe -m app.worker
```

Start the local Ollama helper as described in Phase 3, and start the frontend with `npm.cmd run dev` from `frontend`. `/api/health` reports phase `4`; `/api/live` is liveness, and `/api/ready` returns 200 only when the required services are ready.

## Worker retries and recovery

Postgres leases survive API/worker restarts. A worker claims only completed uploads whose scheduled time has arrived. Each claim increments a persisted attempt counter. A crashed processing lease can be reclaimed after 15 minutes; exhausted crashed jobs become failed instead of looping forever.

Transient failures retry with bounded exponential delay, up to three total attempts by default. Invalid/scanned/encrypted/oversized PDFs fail without automatic retries because they need user action. The library shows scheduled retries and the user can start a fresh attempt with **Retry**. **Reprocess** replaces a ready index while preserving older citation snapshots.

The separate worker sends a lightweight heartbeat while processing long PDFs. It prioritizes private file cleanup and periodically removes expired operational counters/heartbeats. Multiple workers use the same database claims; do not add an in-memory queue or start a worker in every production API instance.

Useful operator commands:

```powershell
python -m app.worker --check
python -m app.worker --once
python -m app.worker --retry-cleanup DOCUMENT_UUID --once
```

The last command resets one blocked deletion and processes one available job. It is an operator command using the backend's service credentials, not a browser action.

## Reliable deletion and incomplete uploads

Deleting a book first stores a durable deletion request and hides the book, chunks, history, and citations through both the API and RLS. The worker removes the private object, then deletes the database row so its dependent records cascade. HTTP 204 acknowledges the deletion request; physical removal can finish shortly afterward.

If Storage is unavailable, the leased row remains and cleanup is retried. Eight failed attempts by default leave a blocked cleanup visible to private monitoring. An operator must fix the storage problem and retry that exact deletion. Never delete the database row first when recovering a real failed cleanup: doing so would lose the durable link to the original object.

Uploads reserve their quota slot before sending bytes to Storage. An incomplete upload is not processed. A reservation abandoned for 15 minutes becomes a cleanup job, including a file that may have been stored before a client/server interruption.

Pending deletions continue to count toward storage/book quotas until purged. This prevents an outage from allowing unbounded physical storage growth. The library displays pending cleanup in its private usage summary.

## Shared usage controls

| Default | Limit |
| --- | --- |
| Books per user | 20, including pending reservations/deletions |
| Stored PDF bytes per user | 500 MiB |
| Single PDF | 50 MiB; 2,000 pages; extracted text/chunk bounds retained |
| Reads per minute | 120 |
| Upload requests per minute/day | 5 / 20 |
| Searches per minute/day | 20 / 1,000 |
| Question requests per minute/day | 5 / 100 |
| Concurrent answers per user | 1 |
| Retry requests per minute/day | 5 / 30 |

Counters are stored in Postgres, use UTC daily windows, and are shared by every API instance. Repeated request UUIDs use the minute budget but do not spend the same day's question budget again. Budgets count admitted requests, including metadata/insufficient-evidence questions; they are not a billable-token meter.

HTTP 429 includes `Retry-After`. A database outage returns 503 instead of bypassing limits. HTTP JSON bodies are capped at 32 KiB by default, and upload requests are bounded while streaming even without Content-Length. Existing file type/signature/size validation remains in place.

All settings are in `backend/.env.example`. Production configuration requires HTTPS origins, enabled controls, and an explicit trusted-host list.

## Browser and API hardening

The frontend generates a fresh CSP nonce for every dynamic HTML response. Production scripts require the matching nonce; the policy does not permit unsafe inline scripts or `eval`. Inline styles remain allowed for the existing interface. Source text and model responses render as plain text. Auth cookies are Secure in production with SameSite=Lax. Responses prevent framing and MIME sniffing and avoid shared caching of private pages.

The backend verifies the Supabase token before charging per-user budgets, then checks book/conversation ownership. New operational RPCs are executable only by the service role. Deletion RLS prevents direct browser reads during cleanup. Production API docs are disabled. Container examples run the API/worker and frontend as non-root users and expose only the HTTPS edge publicly.

## Monitoring without book contents

Application logs are structured JSON. Request records contain a generated correlation UUID, method, route template, status, and latency. They exclude questions, tokens, headers, filenames, excerpts, and raw document IDs. Model events record provider, success, latency, and provider-reported input/output token counts without prompts or responses.

`GET /api/metrics` is disabled with 404 unless `MONITORING_TOKEN` is configured. When enabled it requires `Authorization: Bearer YOUR_PRIVATE_TOKEN`. Generate at least 32 random characters and keep the token only in the backend environment. Production rejects the example placeholder.

Metrics include bounded per-process request/model counters and database-backed queue/failed/cleanup counts. Scrape each API instance if you run several; in-memory counters restart with that process. Database usage budgets and job state persist. Monitor non-200 readiness, queued backlog, failed processing, blocked cleanup, and repeated provider errors. Logs are ready for the hosting platform's collector; no external collector account is provisioned by the code.

Hosted model credentials are not probed with a paid inference call during readiness. Local Ollama readiness verifies that the configured model is present, not the latency of its next answer.

## Reproducible builds and CI

`backend/requirements.lock` pins runtime packages with integrity hashes. Regenerate it deliberately after a dependency change:

```powershell
cd backend
uv pip compile requirements.txt --python-version 3.12 --universal --generate-hashes --output-file requirements.lock
```

The application is checked against Python 3.12 deployment dependencies as well as the existing development environment. The frontend uses its committed npm lockfile. Docker build contexts exclude local environments, secrets, caches, and model files; private keys are never build arguments.

GitHub Actions checks backend tests, actual PostgreSQL/pgvector behavior, evaluation-data validity, the Vercel frontend build, production images, and deployment syntax. Actions are pinned to verified commit SHAs, use read-only repository permissions, and receive only placeholder configuration. Dependabot proposes dependency updates; review them and regenerate the Python lockfile before merging.

## Evaluation and verification

```powershell
cd backend
python -m pytest -q
python -m scripts.evaluate --validate-only
```

The maintained JSON dataset checks title/author metadata, four factual questions, correct source quotes/pages, a pronoun follow-up, out-of-book abstention, and an instruction-override request. Reports contain case IDs/checks/timings, not book excerpts or credentials. Literal quote validation establishes provenance, not perfect logical entailment; extend the set with representative reviewed questions before expanding usage.

Run the real model/database suite with the API in external-worker mode and the standalone worker running:

```powershell
$env:PHASE4_LIVE_TEST = '1'
python -m scripts.evaluate
```

It creates confirmed synthetic accounts without sending email, evaluates real answers, checks live minute/day budgets and owner isolation, tests an interrupted job's scheduled recovery, and confirms immediate deletion hiding followed by physical cleanup. Temporary accounts/files are removed afterward. The content-free report is `.cache/phase4-evaluation.json`; failures retain a partial report.

The isolated SQL checks require the optional PGlite test packages documented in Phase 3:

```powershell
node scripts/verify_phase3_sql.mjs
node scripts/verify_phase4_sql.mjs
```

To check the actual production frontend build (with a temporary auth account and fixture responses for controlled XSS/retry tests):

```powershell
$env:PHASE3_LIVE_TEST = '1'
$env:PHASE3_TEST_FRONTEND_URL = 'http://localhost:3001'
python -m scripts.verify_web_security
```

## Deployment, backup, and rollback

For Vercel follow [Vercel Deployment](VERCEL_DEPLOYMENT.md). The optional full-server stack is `deploy/compose.yaml`: copy its two example environment files, fill real production values privately, and validate with `docker compose --env-file deploy/production.env -f deploy/compose.yaml config --quiet` before building. Only the edge exposes ports; Ollama stays private. Runtime memory caps bound resource use, including hostile/complex PDF extraction in the separate worker.

Keep development and production Supabase projects/credentials separate. Back up both database records and private Storage objects according to your retention policy; a schema dump alone does not restore PDFs. Test restore into an isolated environment. Protect backup files and never commit them to this repository.

Record each deployed source/image version. Roll back to a previously verified application version compatible with migration 0005. Do not blindly drop operational tables or restore an older database over new user messages. A rollback to pre-Phase-4 code needs an explicit compatibility review, including pending deletion rows.

This workspace does not have a Docker daemon or access to a production hosting account. Local service/production-web tests and committed deployment configuration do not constitute an online production deployment; verify the real URLs with the preflight command after hosting is configured.
