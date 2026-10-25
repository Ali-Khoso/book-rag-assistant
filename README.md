# Book-Based RAG Assistant

An AI study assistant that answers questions from books and learning documents. Upload a book, ask a question in natural language, and receive an answer grounded in retrieved passages with page citations so the reader can verify it.

## Problem

Readers often need a clear explanation or a specific fact from a long book. Searching manually takes time, while a general-purpose chatbot may answer from outside knowledge or invent details. This project aims to make book question answering useful and verifiable.

## Proposed solution

The application processes an uploaded PDF, extracts text and page metadata, divides it into searchable chunks, and indexes those chunks. For each question, it retrieves relevant passages and supplies them to a language model as context. The response cites the source pages and states when the book does not provide enough evidence to answer.

> This project uses Retrieval-Augmented Generation (RAG). It does not train or fine-tune a model on each uploaded book. The book is indexed for retrieval, then relevant passages are provided to the model at question time.

## Core user flow

1. Upload a PDF book or learning document.
2. See its processing status and, when ready, open it from a personal library.
3. Ask a question about one selected book or a chosen group of books.
4. Read an answer with page citations and supporting excerpts.
5. Open a citation to check the original passage.

## MVP features

- PDF upload with file validation and clear processing states
- Text extraction that preserves page numbers and document metadata
- Chunking, embedding, and semantic retrieval
- Answers grounded in retrieved passages
- Page citations and expandable source excerpts
- A clear “not found in the uploaded book” response when evidence is insufficient
- Private document library with delete controls

## Later features

- Chapter summaries, flashcards, and quizzes generated from cited passages
- Search across multiple selected books
- Hybrid search combining semantic and keyword matching
- Retrieval evaluation dashboard and feedback on answer quality
- Support for additional formats such as EPUB, subject to reliable text and page handling

## Proposed architecture

```text
Web application
    → API and document-processing pipeline
        → PDF text extraction with page metadata
        → chunking and embeddings
        → PostgreSQL with vector search
    → retrieval and answer generation
        → grounded answer with citations
```

One practical implementation is a Next.js interface, a Python API for ingestion and retrieval, and PostgreSQL with `pgvector` for document chunks and embeddings. The model and embedding provider should be configured through environment variables so they can be changed without changing the product flow.

## Reliability and privacy goals

- Keep each user's documents and conversations isolated.
- Validate upload type and size; do not execute uploaded content.
- Store source name, page number, chunk position, and document ownership with each chunk.
- Return citations only for passages actually retrieved for the answer.
- Treat book text as untrusted input; it must not override application instructions.
- Provide deletion that removes the document and its indexed chunks.
- Measure retrieval quality and citation correctness with a small set of reviewed questions.

## Example questions

- “Explain the main idea of Chapter 3 in simple words.”
- “What does the author say about customer retention?”
- “Compare the two methods discussed in this book.”
- “Summarize Chapter 5 and cite the pages you used.”
- “Create five quiz questions from Chapter 2.”
- “Does this book explain concept X? If so, show me where.”

## Project status

**Planning / initial build.** The repository should be updated as implementation decisions are made. Document any working features, setup commands, environment variables, screenshots, and deployment details here rather than claiming planned features are already complete.

## Learning resource

See [`RAG_CONCEPTS_AND_INTERVIEW_QUESTIONS.md`](RAG_CONCEPTS_AND_INTERVIEW_QUESTIONS.md) for plain-language explanations of key RAG concepts and interview questions with sample answers.
