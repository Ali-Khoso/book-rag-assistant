# Phase 1 — Technical and Conceptual Questions

Keep this as a learning and interview-preparation note. Answers describe the current Phase 1 design.

## Conceptual questions

### 1. What does Phase 1 deliver?

It delivers the application foundation: sign-in, private PDF upload, a personal book library, and a database record for each uploaded book. It does not yet read or answer questions from books.

### 2. Why is a book marked “Queued” if it has not been processed?

The status means the upload is saved and waiting for the ingestion pipeline. Phase 2 will change it to `processing`, then `ready` or `failed`.

### 3. What is the difference between authentication and authorization?

Authentication checks who the user is. Authorization checks what that user may access. Supabase Auth verifies identity; owner filters and RLS limit access to that user's records.

### 4. What is RAG, and is it used in Phase 1?

RAG retrieves relevant passages from a knowledge source and gives them to a language model as context. Phase 1 does not implement RAG yet; it securely stores a book so Phase 2 can index it.

### 5. Does uploading a book train the AI model?

No. Later phases extract and index its text, then retrieve relevant passages when a question is asked. That is retrieval, not fine-tuning.

### 6. Why do the pages look different?

The landing page introduces the product, the login page focuses on account access, and the library page focuses on uploads and document status. They share typography, color, glass surfaces, and spacing rules.

## Technical questions

### 7. What frameworks and views are used?

Next.js App Router provides routes and server rendering; React and TypeScript build interactive views. The main views are `/`, `/login`, and protected `/library`. FastAPI provides the Python API; Pydantic models shape document responses; Supabase provides Auth, PostgreSQL, RLS, and Storage.

### 8. Why does the backend verify the access token with Supabase Auth?

A browser-supplied token must not be trusted just because it looks like a JWT. FastAPI sends it to Supabase Auth's user endpoint, which validates it and returns the authenticated user's ID. The backend uses that ID for ownership filters.

### 9. Why is the user ID not accepted from the upload form?

If the client could choose `user_id`, a user could try to save a book under someone else's account. FastAPI derives the owner from the verified token instead.

### 10. What is the Supabase publishable key?

It identifies the project for browser-side Supabase requests. It is intended to be public when RLS policies are correctly enabled. It does not replace authentication or row-level security.

### 11. What is the Supabase secret key, and where is it stored?

It is a privileged server key that can bypass RLS. It is stored only in `backend/.env` and used by FastAPI. It must never appear in frontend source, `NEXT_PUBLIC_` variables, screenshots, or Git history.

### 12. Why is the Storage bucket private?

Books are user documents and should not have public URLs. The backend uploads to the private bucket after verifying the user. Phase 1 does not expose direct browser download or upload permissions.

### 13. Why check the extension, content type, and PDF signature?

Each check catches a different class of mistake or spoofed request. The browser checks improve feedback, while FastAPI enforces the rule. The PDF signature check looks for `%PDF-` near the beginning of the file bytes.

### 14. Why limit uploads to 50 MiB?

The 50 MiB limit accommodates larger PDF books while bounding memory and storage use. The limit is checked in the browser, enforced again by FastAPI, and configured on the Supabase bucket. The project-wide Storage limit must also allow this size. Standard uploads support these files, but Supabase recommends resumable uploads above 6 MB for reliability; adding resumable uploads remains a later improvement.

### 15. Is CORS a security boundary?

No. CORS tells browsers which web origins may read responses. Other clients can still call the API, so every protected backend route must verify authentication and ownership.

### 16. What does the Next.js proxy do?

It refreshes the cookie-based Supabase session and redirects unauthenticated visitors away from `/library`. It protects the page experience, but FastAPI still performs its own authentication checks for API access.

### 17. Why use `getClaims()` instead of `getSession()` in server code?

The session object may come from a cookie and should not be trusted as verified server identity on its own. `getClaims()` verifies the token claims before the proxy uses them to protect a route.

### 18. How does the upload animation work?

CSS keyframes animate the floating book artwork and upload card. The progress bar uses a `cubic-bezier()` timing curve so movement eases naturally. Reduced-motion preferences disable continuous motion.

### 19. What happens if saving the database row fails after the file upload?

FastAPI makes a best-effort attempt to remove the just-uploaded object so an orphaned file is not left behind. Later production work should add monitored retries for cleanup failures.

### 20. What should Phase 2 add?

Page-aware PDF extraction, chunking, embeddings, and owner-filtered semantic search. After retrieval works, Phase 3 can add language-model answers and citations.
