# Book-Based RAG Assistant

An AI study assistant that lets users upload books and ask questions about their contents. It retrieves relevant passages and generates answers with page citations, so readers can verify information in the original source.

This project uses Retrieval-Augmented Generation (RAG). It indexes uploaded books for search; it does not train a new language model on each book.

## Project goal

Make it easier to understand and search long books while keeping answers traceable to the source pages.

## Core user flow

1. Upload a PDF book or learning document.
2. The application extracts text and page numbers, then prepares the document for search.
3. Ask a question in natural language.
4. Read an answer based on relevant passages, with citations to the book pages.
5. Open the cited passage to check the source.

## MVP features

- PDF upload and processing status
- Page-aware text extraction
- Chunking, embeddings, and semantic search
- Answers grounded in retrieved passages
- Page citations and source excerpts
- An insufficient-evidence response when the book does not answer the question
- Private document library and deletion controls

## Example questions

- “Explain the main idea of Chapter 3 in simple words.”
- “What does the author say about customer retention?”
- “Summarize Chapter 5 and cite the pages you used.”
- “Does this book explain concept X? Show me where.”
