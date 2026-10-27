# Phase 3 verification — 28 October 2026

## Checks completed

- All **87 offline backend tests pass**, covering PDF extraction, processing/retrieval, metadata, answer validation, strict provider request contracts, context limits, idempotent response reuse, retry cleanup, book/conversation ownership, and isolation of standalone questions from unrelated previous topics.
- TypeScript checking with `frontend/node_modules/.bin/tsc --noEmit` passes.
- The optimized Next.js production build passes, including the protected `/library/books/[bookId]` route.
- The actual local Qwen2.5 3B model and hosted API pass all four synthetic PDF questions and a pronoun follow-up, with verified supporting quotes and the expected physical page ranges. Out-of-book and instruction-override questions abstain. Factual answers took approximately 21–97 seconds in the final run, which overlapped the browser test; these CPU timings are not a deployment benchmark.
- The isolated PostgreSQL/pgvector check passes: all migrations apply, migration 0004 reruns safely, and actual SQL verifies atomic turns, cached retries, foreign/fabricated source denial, metadata citation labels, active leases, index-generation changes, two-user RLS, snapshot retention, and cascading deletion. Auth/Storage fixtures in this check are separate from the hosted Supabase tests.
- The live chat browser checks pass in installed Edge at 1440×1000 and 390×844 using a temporary confirmed Supabase account, the real book/chat API, and the local model. They verify the protected chat route, a factual question after a title answer, expandable source citations, insufficient-evidence display, reload/resume history, and new/delete conversation. No email is sent.
- Separate browser fixture checks verify a retryable provider error, retry with the same request UUID, and one visible saved turn. The live API also verifies that repeating a completed UUID returns its saved response without duplicating messages.
- The browser reported no JavaScript page errors and no horizontal overflow at either viewport. Screenshots are kept locally in ignored `backend/.cache`.

## Hosted verification

Migration `0004_phase3_answers.sql` has been applied to the hosted project and its new columns are verified. Both `scripts.verify_phase3` and `scripts.verify_phase3_ui` pass on 28 October 2026. The test accounts and PDFs were removed afterward; the existing uploaded book and its index were retained.

Repeat the checks using [Phase 3 Setup](PHASE_3_SETUP.md), with `PHASE3_UI_FIXTURES` removed for live browser verification. The completed live API checks are:

| Passed check | Verified result |
| --- | --- |
| “What is the title?” | PDF metadata title, labeled metadata source, no invented page |
| Largest planet | Jupiter, a supporting quote on physical page 1 |
| Volcano eruption cause | Magma/pressure, supporting source on page 2 |
| Gas released during photosynthesis | Oxygen, supporting source on page 3 |
| Migratory bird navigation | Magnetic field, supporting source on page 4 |
| Pronoun follow-up | The previous bird question resolves “they,” with supporting page 4 evidence |
| Cryptocurrency / instruction override | Insufficient evidence, no invented citations |
| Duplicate request UUID | Same saved response and one question/answer pair |
| Other user / foreign conversation | API denial and empty owner-protected table reads |
| Forged-owner RPC / foreign chunk | Browser execution denied; SQL rejects foreign evidence |
| Reprocessing | Old messages and quoted source/page snapshots retained |
| Deleting a conversation | Messages, citations, and request records removed |

All live accounts and PDFs are synthetic and scoped to each test run. The existing uploaded book is not replaced by these tests. The four-question set is a small development check, not a broad quality benchmark.

## Practical limits

Literal quote/source validation proves where a quote came from. It does not prove every generated interpretation logically follows from it. Conservative wording/number checks and model instructions reduce obvious unsupported claims but can also abstain on valid paraphrases. Review source excerpts and evaluate representative questions from the actual books before production use.

The default embedding model is primarily suited to English. Context and answer lengths are bounded, one selected book is searched at a time, and complex multi-step or whole-book synthesis can require passages beyond the retrieval window. Physical PDF page ranges can differ from printed page labels. Metadata may be missing or inaccurate and is explicitly labeled.

Production rate limits, usage controls, a separate worker deployment, monitoring, cleanup retries, larger adversarial/quality evaluations, and online deployment remain Phase 4 work. OCR and multi-book answers are not included in this phase.
