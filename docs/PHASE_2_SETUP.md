# Phase 2 — Book processing and passage retrieval

Phase 2 extracts text from uploaded PDFs, creates overlapping passages, generates semantic embeddings, and searches the selected owner's book. It returns source text and physical PDF page numbers. Generated answers and conversational Q&A belong to Phase 3.

## Setup

1. Apply `supabase/migrations/0003_phase2_retrieval.sql` in the Supabase SQL Editor after the two Phase 1 migrations. A successful run returns no rows. The migration adds processing fields, fixes embeddings at 256 dimensions, and creates backend-only processing/search functions. Keep the existing ownership policies and private bucket.
2. From the repository root, install the backend dependencies:

   ```powershell
   cd backend
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. Keep the existing credentials in `backend/.env`. The new settings have defaults, so do not overwrite your environment with the example. Optional settings are documented in `backend/.env.example`.
4. Start the API from the `backend` directory:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

   Start the frontend with `npm run dev` in `frontend`, then open `http://localhost:3000`. Running without API auto-reload avoids interrupting an active book during development. If you use `--reload`, add `--reload-dir app` so package installation and tests do not restart processing.

The first local embedding request downloads a pinned model revision into `backend/.cache/models`. Later requests reuse that cache. This directory is ignored by Git. Local inference does not need a paid API key and book text stays on your machine apart from its existing private Supabase storage/index.

## PDF text extraction

`backend/app/processing/pdf.py` uses pypdf to extract each page's text. Page numbers are one-based physical PDF pages, including blank pages in the count; they can differ from page numbers printed inside a book. Empty pages are skipped without renumbering subsequent pages.

Damaged, password-protected, empty, and fully scanned PDFs produce useful failure messages. Scanned PDFs need OCR before upload. Mixed PDFs index pages that have extractable text; image-only pages are not searchable. OCR is not implemented in this phase.

Default limits are 2,000 pages and five million extracted characters, in addition to the existing 50 MiB upload limit. These bound normal processing work; hostile PDF sandboxing and production resource isolation remain hardening work.

## Text chunking

`backend/app/processing/chunking.py` creates passages of up to 1,400 characters with approximately 200 characters of overlap, preferring whitespace boundaries. Every passage stores its book, verified owner, page range, position, embedding model, and processing run.

Character limits keep this implementation provider-independent. Changing chunk settings requires reprocessing books. A document can have at most 5,000 passages by default.

## Embeddings

`backend/app/processing/embeddings.py` loads `minishlab/potion-base-8M` using Model2Vec. The model's published revision is pinned, and passage/query vectors are normalized and validated as finite, nonzero, 256-dimensional vectors. The model identity is stored alongside every index so different embedding spaces cannot be mixed.

The default model is a small English semantic embedding model suitable for CPU development. Retrieval quality varies with language, book structure, and question wording. It can be evaluated or replaced as the application grows.

For an optional hosted, OpenAI-compatible embedding endpoint, configure only `backend/.env`:

```text
EMBEDDING_PROVIDER=api
EMBEDDING_API_URL=https://your-provider.example/v1/embeddings
EMBEDDING_API_KEY=your_private_key
EMBEDDING_MODEL=your_embedding_model
EMBEDDING_REVISION=v1
```

The endpoint must support 256-dimensional embeddings and the `input`, `model`, and `dimensions` request fields. Its response must contain indexed vectors in `data`. Hosted inference sends passage/question text to that configured provider and can incur provider charges. Reprocess existing books after changing the embedding provider, model, endpoint, or revision. Never add a real key to an example file, frontend variable, or Git.

## Vector storage and search

`backend/app/repository.py` stores embeddings in Supabase pgvector. `POST /api/documents/{id}/search` takes a question and `top_k` from 1 to 10. It verifies the access token and document owner before embedding the question, then passes the verified owner into the backend-only SQL function.

The SQL function independently scopes passages to that owner, selected book, current processing run, ready status, and embedding model. It uses exact cosine distance within that small book-specific set to avoid filtered approximate-search omissions. An HNSW index is available for future larger-corpus query plans. Similarity is a ranking score, not answer confidence.

The library's **Search book** panel displays the retrieved text and page ranges. It does not ask a language model to produce an answer.

## Processing status and retry

`backend/app/processing/worker.py` polls queued document rows outside the upload request. Existing Phase 1 uploads are picked up automatically after startup. The library polls active books and shows `Queued`, `Processing`, `Ready`, or `Failed`, including progress and actionable failures.

`pipeline.py` coordinates extraction, chunking, embedding batches, and storage. SQL atomically claims one job and assigns a run ID. Each batch checks that run ID, so a deleted or superseded task cannot recreate a book's index. Failed runs remove partial chunks. A book becomes ready only after all expected sequential chunks are present.

**Retry** requeues a failed book. **Reprocess** rebuilds a ready book's index. Repeated indexing replaces existing chunks rather than duplicating them. A request cannot replace an actively processing job. Worker crashes leave a database lease that can be reclaimed after 15 minutes. This is a local in-process worker backed by persisted queue state; separate worker deployment, monitoring, rate limits, and production job controls remain Phase 4 work.

## Retrieval testing

Install test dependencies and run the offline suite:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
```

The tests cover extraction/page numbering, scanned/encrypted/invalid files, overlap, resource limits, model normalization, failure handling, lost leases, authentication, ownership, request validation, and retry behavior. They do not require network access or send documents to an embedding provider.

With the migration and API running, opt into live tests:

```powershell
$env:PHASE2_LIVE_TEST = '1'
.\.venv\Scripts\python.exe -m scripts.verify_phase2
```

This creates two temporary, auto-confirmed test accounts without sending email, uploads synthetic PDFs, and cleans up those accounts/files in a `finally` block. It verifies four known facts and their source pages, cross-user API isolation, direct-table RLS, blocked client execution of backend RPCs, idempotent reprocessing, and scanned-PDF retries. Never use these temporary test credentials as normal accounts.

An optional real-browser check is also available:

```powershell
$env:PHASE2_LIVE_TEST = '1'
.\.venv\Scripts\python.exe -m scripts.verify_phase2_ui
```

It uses installed Microsoft Edge on Windows. Elsewhere, install Playwright's Chromium with `python -m playwright install chromium`. Override `PHASE2_BROWSER_CHANNEL` if needed. The check uses an isolated headless browser, creates and removes its own account/book, exercises the library workflow, and saves desktop/mobile screenshots in the ignored `backend/.cache` directory.

For a manual check, upload a text-based book, wait for **Ready**, select **Search book**, and ask a question whose answer/page you know. Inspect the returned excerpts against the original PDF. Repeat with a second user; the first user's books must be absent.

## API routes added in Phase 2

| Route | Purpose |
| --- | --- |
| `GET /api/documents` | Include stage, error, page count, and passage count |
| `POST /api/documents/{id}/retry` | Queue a retry or reprocess an inactive book |
| `POST /api/documents/{id}/search` | Return ranked source passages from one owned book |
| `GET /api/health` | Report Phase 2 and worker state |

## References

- [pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)
- [Model2Vec](https://github.com/MinishLab/model2vec)
- [Pinned model's model card](https://huggingface.co/minishlab/potion-base-8M)
- [Supabase pgvector](https://supabase.com/docs/guides/database/extensions/pgvector)
