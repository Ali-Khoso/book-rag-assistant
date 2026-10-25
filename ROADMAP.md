# Project Roadmap

This roadmap breaks the Book-Based RAG Assistant into four build phases. Complete and review each phase before expanding scope. These are planned milestones, not a claim that the features are already implemented.

## Phase 1 — Foundation and secure book library

**Goal:** Create the application foundation and let a user safely manage uploaded books.

**Deliverables**

- Set up the Next.js frontend, Python API, and Supabase project.
- Add environment configuration and an example environment file without real secrets.
- Create database migrations for the six tables in [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md).
- Enable Row Level Security and ownership checks.
- Create a private book storage bucket.
- Add sign-in, PDF upload, document listing, status display, and deletion.

**Complete when:** A signed-in user can upload a PDF, see it in their library with a queued status, and cannot access another user's records.

## Phase 2 — PDF ingestion and retrieval

**Goal:** Turn an uploaded book into searchable, page-aware passages.

**Deliverables**

- Extract selectable PDF text while preserving page numbers.
- Split extracted text into chunks and keep document, page, and chunk-order metadata.
- Generate embeddings and save them with the chunks.
- Implement vector search filtered to the user's selected books.
- Update document status through processing, ready, or failed.
- Prepare a small set of questions with known supporting passages for retrieval checks.

**Complete when:** Search returns the expected book passages and page metadata for the reviewed questions.

## Phase 3 — Grounded answers and user experience

**Goal:** Let users ask questions and verify answers against the book.

**Deliverables**

- Add a chat interface for asking about one selected book.
- Retrieve relevant chunks and provide them to the language model as evidence.
- Build citations from stored chunk metadata and show supporting excerpts.
- Return an insufficient-evidence response when the book does not support an answer.
- Save conversation messages and their citation links.
- Show useful loading and error states.

**Complete when:** A demo shows a supported answer with a correct page citation and an unsupported question that receives a clear abstention.

## Phase 4 — Production readiness and deployment

**Goal:** Make the MVP safer, more reliable, and available online.

**Deliverables**

- Move longer document processing to an asynchronous worker or job service.
- Add idempotent processing, bounded retries, upload limits, rate limits, and per-user quotas.
- Review database and storage access policies; verify deletion removes files, chunks, and citation links.
- Monitor ingestion failures, answer latency, and model usage without logging sensitive book contents unnecessarily.
- Use a reviewed evaluation set to check retrieval, groundedness, citation correctness, and abstention.
- Deploy the frontend, API, database, storage, and worker with separate development and production secrets.
- Update the README with setup instructions, screenshots, and the features that are actually working.

**Complete when:** The deployed app passes the documented access-control and evaluation checks, and users can upload a book and receive verifiable answers reliably.

## Scope after the four phases

Add OCR for scanned PDFs, multi-book search, summaries, quizzes, and flashcards after the core upload-to-cited-answer flow is reliable. Do not fine-tune a model on each book; RAG supplies retrieved book passages at question time.
