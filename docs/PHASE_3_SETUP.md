# Phase 3 — Grounded book conversations

Phase 3 adds generated answers to Phase 2's passage search. Open a ready book with **Ask book**, ask a question, and expand its numbered sources. Conversations stay bound to one private book. **Search book** still shows the original retrieval results separately.

## 1. Apply the database migration

Run the complete contents of `supabase/migrations/0004_phase3_answers.sql` in the Supabase SQL Editor after migrations 0001–0003. A successful run returns `Success. No rows returned.` The migration uses a transaction and can be run again. It retains existing books and indexes.

Do this **before starting the Phase 3 API**. New document fields, chat RPCs, and source snapshots require this migration. A service key cannot execute arbitrary SQL through the normal REST API; the SQL Editor is the setup step for this hosted project.

## 2. Choose the answer model

### Local default: no paid API key

The default uses Ollama with `qwen2.5:3b`. From the backend directory:

```powershell
cd backend
.\.venv\Scripts\python.exe -m scripts.setup_local_llm
```

On Windows, this reuses an installed Ollama server or downloads a pinned official runtime into ignored `backend/.cache`. It verifies the archive's SHA-256 before extracting the CPU files, launches the local server without opening a window, and pulls the approximately 1.9 GB model. Allow roughly 4 GB of free space during first setup. Downloads can take several minutes; later runs reuse cached files. Other operating systems should install Ollama using its official instructions first, then run the helper.

The helper binds the server to `127.0.0.1:11434`, disables cloud features, and stores its models/logs under the project cache when it launches a new server. An existing server keeps its own configuration. Start the helper again after restarting your computer. Model weights and runtime files are never committed.

These defaults already exist in the backend settings; optionally set them explicitly in ignored `backend/.env`:

```text
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:3b
OLLAMA_URL=http://127.0.0.1:11434
LLM_TIMEOUT_SECONDS=180
ANSWER_RETRIEVAL_K=6
ANSWER_CONTEXT_CHARS=9000
ANSWER_MIN_SIMILARITY=0.25
CONVERSATION_HISTORY_TURNS=4
```

CPU answers can take longer than hosted inference, particularly on the first request. A stopped or unavailable model returns a retryable service error; it does not produce a fabricated answer.

### Optional OpenAI provider

Set these only in ignored `backend/.env`, using a model that supports structured outputs through the Responses API:

```text
LLM_PROVIDER=openai
LLM_MODEL=your_structured_output_model
OPENAI_API_KEY=your_private_key
```

Restart the API after changing configuration. Never put this key in a `NEXT_PUBLIC_` variable, frontend file, example file, or commit. This option sends the question, selected source excerpts, and bounded recent conversation context to OpenAI and can incur provider charges. Responses use `store=false`; this is not a promise about every aspect of provider retention. Changing the answer model does not require re-embedding the book.

## 3. Run the application

Run the model helper, then start the API in a terminal:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Start the frontend in another terminal:

```powershell
cd frontend
npm.cmd run dev
```

Open `http://localhost:3000/library`. Sign in, wait for a book to show **Ready**, and choose **Ask book**. The API health endpoint is `http://127.0.0.1:8000/api/health`; it reports phase `3` and the configured answer provider. This endpoint reports API configuration, not a model-readiness probe.

## Answer generation and evidence checks

1. The API verifies the Supabase access token and selected book owner before retrieving any text.
2. Direct title/author questions use the PDF's stated metadata. Previously uploaded books read and cache that metadata on their first question, without rebuilding their index. If metadata is absent, opening passages are supplied to the model. Filenames are not treated as authoritative titles.
3. Other questions retrieve up to six current-generation passages from the selected book. Low-similarity results and obvious topic mismatches can abstain before a model call. Similarity is a retrieval score, not answer confidence.
4. The model receives only selected evidence, a bounded history, and instructions to treat source text/history as untrusted data. It must produce structured statements with supplied source IDs and exact supporting quotes.
5. The answer validator rejects unknown IDs, nonexistent quotes, model-written page citations, invented numbers, and obvious disjoint statements. Missing support returns **More evidence needed**. The wording check is deliberately conservative and can reject valid paraphrases; it is not a complete proof of logical entailment.
6. SQL independently verifies chunk owner, book, current processing generation, and quoted text. It constructs page numbers and source snapshots from stored records. Metadata sources are labeled **PDF metadata**, with no invented page number.
7. The question, answer, and citations save together. The browser renders plain text and expandable excerpts, never executable model HTML.

Source page ranges are the physical PDF pages retained by Phase 2 chunks. A passage can span multiple pages; its citation identifies that range, not a separately located line within the range. Metadata itself can be inaccurate, so the interface identifies it as metadata evidence.

## Conversation history and retry

Each conversation belongs to one owner and one book. The interface lists the 30 most recently updated conversations and loads the latest 100 messages, with **Show earlier messages** for older pages. Up to four recent turns help interpret questions with pronouns or continuation requests. Standalone questions omit unrelated prior topics from the model input. The current question appears after the source context, and earlier assistant claims are never book evidence.

A browser-generated UUID identifies each question. Retrying the same request returns its stored result rather than inserting another turn. Changing the question while keeping its request ID is rejected. A short database lease prevents simultaneous answers from interleaving; abandoned leases expire after five minutes. Provider errors release the lease for retry. There is no partial saved question/answer pair.

Reprocessing replaces chunks but retains saved source text and page snapshots in old conversations. Deleting a conversation removes its messages, source snapshots, and request records. Deleting a book removes its conversations as well as its index; the API also removes the original private PDF.

## Code map

| File | Purpose |
| --- | --- |
| `backend/app/processing/metadata.py` | Clean and read stated PDF title/author |
| `backend/app/answers/models.py` | Request, answer, history, and citation contracts |
| `backend/app/answers/llm.py` | Structured local/OpenAI generation and bounded prompts |
| `backend/app/answers/grounding.py` | Metadata answers, quote checks, and abstention |
| `backend/app/answers/service.py` | Owner-scoped retrieval and answer orchestration |
| `backend/app/answers/repository.py` | Atomic chat RPCs and ordered history |
| `supabase/migrations/0004_phase3_answers.sql` | Chat leases, validation, snapshots, and RLS |
| `frontend/src/components/chat-panel.tsx` | Conversation controls, retry, answer/source display |
| `frontend/src/components/book-chat.tsx` | Selected book loading and readiness states |

## API routes

| Route | Behavior |
| --- | --- |
| `GET /api/documents/{id}` | Read one owned book |
| `POST /api/documents/{id}/ask` | Ask with `question`, optional `conversation_id`, and UUID `request_id` |
| `GET /api/documents/{id}/conversations` | List the owner's recent conversations for this book |
| `GET /api/conversations/{id}` | Load ordered messages and saved citations |
| `GET /api/conversations/{id}?before_sequence=101` | Load an earlier message page |
| `DELETE /api/conversations/{id}` | Delete the owner's conversation |

## Verification

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
$env:PHASE3_LIVE_TEST = '1'
.\.venv\Scripts\python.exe -m scripts.verify_phase3
.\.venv\Scripts\python.exe -m scripts.verify_phase3_ui
```

Live checks create temporary confirmed accounts without sending email and remove their own accounts/files afterward. They require the migration, API, frontend (for browser checks), and model. On Windows the browser script uses installed Edge; elsewhere install Playwright Chromium. Desktop/mobile screenshots go into ignored `.cache`.

You can verify actual extraction, retrieval, model answers, source-page provenance, and abstention without writing to Supabase:

```powershell
$env:PHASE3_MODEL_TEST = '1'
.\.venv\Scripts\python.exe -m scripts.verify_phase3_model
```

This uses synthetic PDF facts and the configured embedding/answer providers. It is a model-pipeline check; it does not verify hosted SQL, RLS, or conversation storage.

To test the interface before the migration/model is available, set `$env:PHASE3_UI_FIXTURES='1'` before running the browser script. This keeps real authentication but replaces book/chat API responses with explicit fixtures, including a retryable failure. **This mode does not verify live retrieval, generation, or database persistence.** Remove that environment variable before the full live test:

```powershell
Remove-Item Env:PHASE3_UI_FIXTURES -ErrorAction SilentlyContinue
```

An optional isolated SQL check applies all four migrations to an in-memory PostgreSQL runtime and exercises idempotency, ownership, quote validation, leases, RLS, reprocessing snapshots, and deletion. It uses minimal Auth/Storage fixtures and never connects to the hosted database:

```powershell
# From the repository root; test dependencies stay in the ignored cache.
npm.cmd install --prefix backend/.cache/phase3-sql --no-save --ignore-scripts @electric-sql/pglite@0.5.12 @electric-sql/pglite-pgvector@0.0.13
node.exe backend/scripts/verify_phase3_sql.mjs
```

This is complementary to the live Supabase checks. See the [PGlite extension documentation](https://pglite.dev/extensions/) for the PostgreSQL/pgvector test runtime.

See [Phase 3 Validation](PHASE_3_VALIDATION.md) for recorded checks and remaining deployment work.

## Official provider references

- [Ollama on Windows](https://docs.ollama.com/windows)
- [Ollama chat API](https://docs.ollama.com/api/chat)
- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [Qwen2.5 3B model information and license](https://ollama.com/library/qwen2.5:3b)
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
