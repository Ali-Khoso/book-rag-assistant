# Four-Phase Implementation Plan

This document turns the project design into a build sequence. The plan uses a Next.js frontend, a Python FastAPI backend, and Supabase for authentication, PostgreSQL with pgvector, and private file storage. It starts with text-based PDFs and one selected book per question. Each phase defines its completion criteria; implementation notes identify the features now available.

## Phase 1 — Build the secure application foundation

**Goal:** A signed-in user can upload and manage their own book.

1. Create the frontend and backend folders and add local run instructions.
2. Add an environment example file for database, storage, embedding, and language-model settings. Keep real secrets out of Git.
3. Create the first database migration from DATABASE_SCHEMA.md: users, documents, chunks, conversations, messages, and message_citations.
4. Enable the pgvector extension and add database ownership policies for user-owned records.
5. Create a private storage bucket and policies that restrict each file to its owner.
6. Implement sign-in, upload, document listing, status display, and delete actions.

**Done when:** A user can sign in, upload a text-based PDF, see its queued document record, and only access or delete their own books.

## Phase 2 — Process books and retrieve passages

**Goal:** Turn an uploaded PDF into searchable passages that retain their source pages.

1. Add a PDF text extractor that reads text page by page and detects empty or unsupported files.
2. Split extracted text into chunks with a small overlap; save document ID, user ID, page range, and chunk order with every chunk.
3. Connect an embedding provider through a backend service and store each embedding with its chunk.
4. Implement semantic search in PostgreSQL with pgvector, filtering by owner and selected document.
5. Update document status through processing, ready, or failed and provide a safe retry for eligible failures.
6. Create a small set of questions with known source pages and inspect the top retrieved passages.

**Done when:** For the reviewed questions, retrieval returns the supporting passage with the correct book and page metadata, and users cannot retrieve another user's chunks.

**Implementation:** PDF extraction, overlapping chunks, pinned local embeddings, owner-scoped pgvector search, processing status/retry, and the library passage-search panel are implemented. See [Phase 2 Setup](docs/PHASE_2_SETUP.md) for migration, configuration, and repeatable verification. Production worker deployment and OCR remain outside this phase.

## Phase 3 — Add grounded question answering

**Goal:** Answer questions from retrieved book passages and let users verify the answer.

1. Add a chat page where the user selects a book and asks a question.
2. Build the answer endpoint: retrieve passages, construct a grounded prompt, call the language model, and return the response.
3. Require the model to refer to retrieved chunk IDs; build page citations from stored metadata rather than trusting model-generated page numbers.
4. Return a clear insufficient-evidence answer when retrieval does not find useful support.
5. Save questions and answers in messages and link each answer to its evidence through message_citations.
6. Add source excerpts, loading states, and useful upload or answer error messages.

**Done when:** A demo question receives an answer with a citation that supports it, and an out-of-book question receives an honest insufficient-evidence response.

## Phase 4 — Harden and deploy the application

**Goal:** Make the complete upload-to-cited-answer flow reliable enough to use online.

1. Move longer PDF processing into an asynchronous worker or job service; make jobs idempotent and add bounded retries.
2. Add file size and page limits, request rate limits, and per-user usage controls.
3. Review authentication, database ownership policies, private file access, and deletion of files, chunks, embeddings, and citation links.
4. Maintain an evaluation set for retrieval quality, answer groundedness, citation correctness, and abstention; rerun it after prompt or search changes.
5. Monitor processing failures, response latency, and model usage while avoiding unnecessary logs of book contents.
6. Deploy the frontend, backend, database, storage, and worker with separate development and production secrets.
7. Update setup instructions and screenshots to show only features that are actually working.

**Done when:** The deployed app passes the access-control and answer-quality checks and can process a book and return verifiable answers reliably.

## Keep out of the first MVP

Add OCR for scanned PDFs, multi-book search, summaries, quizzes, and flashcards after the core flow is reliable. RAG indexes books and supplies relevant passages at question time; it does not fine-tune a model for each upload.
