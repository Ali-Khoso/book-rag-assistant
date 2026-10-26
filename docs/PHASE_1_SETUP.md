# Phase 1 — Setup and Run Guide

Phase 1 delivers a responsive frontend, secure sign-in, private PDF upload, and a personal book library. Uploaded books are saved with status `queued`; PDF extraction and AI answers are built in Phases 2 and 3.

## Frameworks, pages, and data models

- **Frontend:** Next.js App Router, React, and TypeScript.
- **Authentication:** Supabase Auth with cookie-based sessions through `@supabase/ssr`.
- **Backend:** Python FastAPI. Every protected request verifies its bearer token with Supabase Auth.
- **Database and storage:** Supabase PostgreSQL and a private Storage bucket.
- **Views:** Landing page (`/`), sign-in and sign-up page (`/login`), and protected book library (`/library`). They have separate layouts and responsive styles.
- **Data model:** The Phase 1 API response model is `DocumentResponse`; database tables are defined in `supabase/migrations/0001_phase1_schema.sql`.
- **Animation:** CSS keyframes and `cubic-bezier()` timing animate the floating book scene and upload progress. Reduced-motion settings are respected.

## Security rules

1. The browser receives only the Supabase **publishable** key. It never receives the secret key.
2. The Next.js proxy verifies cookie claims to protect the library page. FastAPI separately validates every bearer token with Supabase Auth.
3. FastAPI gets the owner ID from the verified Supabase user. It never accepts `user_id` from a form field or JSON body.
4. FastAPI filters document lists, lookup, and deletion by that verified owner ID.
5. The Storage bucket is private. The browser does not read or write Storage directly; FastAPI uses its server-only secret key.
6. RLS is enabled. Authenticated browser reads are owner-scoped. Writes go through FastAPI.
7. The browser checks PDF extension, content type, and size. The API repeats those checks and checks the PDF signature. Browser checks improve feedback; server checks enforce the rule.
8. The API rejects files over 50 MiB and stores each file at a random ID under the verified user's folder. The first iteration uses a standard upload request. Supabase recommends resumable uploads above 6 MB for reliability; resumable uploads remain a later improvement.
9. CORS allows only the configured frontend origin. CORS is not authentication.
10. Never commit `.env`, `.env.local`, or a secret key. The publishable key is designed for client use with RLS; the secret key is server-only.

FastAPI's Storage client uses a privileged key, which bypasses Storage RLS. Keep that key only in the backend and keep API routes owner-scoped. Do not make the bucket public or add broad browser Storage policies.

## Step 1 — Create your Supabase project

1. Open [Supabase](https://supabase.com/dashboard) and create a project.
2. Choose a database password and save it privately.
3. Open **Project Settings → API Keys** (or the project's Connect/API details panel).
4. Copy the **Project URL**, **Publishable key**, and **Secret key**. Do not put the secret key in chat, the README, or a `NEXT_PUBLIC_` variable.

## Step 2 — Configure email sign-in

1. In the Supabase dashboard, open **Authentication → URL Configuration**.
2. Set the local Site URL to `http://localhost:3000`.
3. Add this Redirect URL: `http://localhost:3000/auth/callback`.
4. Keep email/password sign-in enabled. If email confirmation is enabled, sign-up shows a message to check the inbox before signing in.

## Step 3 — Create the database and private bucket

1. Open **SQL Editor → New query** in Supabase.
2. Open `supabase/migrations/0001_phase1_schema.sql` in VS Code and copy the entire file.
3. Paste it into the SQL Editor and select **Run**.
4. Run `supabase/migrations/0002_increase_pdf_upload_limit.sql` to raise the bucket's PDF limit to 50 MiB. For an existing project with the first migration already applied, run only this new migration.
5. Open **Storage** and confirm the `books-private` bucket exists, is private, and allows files up to 52,428,800 bytes (50 MiB). In **Storage Settings**, also ensure the global file size limit permits this size; a bucket limit cannot exceed the global limit.
6. The first migration creates a profile row automatically after a user signs up through the app.

The migration creates six logical tables and owner-scoped read policies. It creates no browser Storage policies because the browser uploads only through FastAPI.

## Step 4 — Set frontend environment values

In PowerShell, from the repository root:

```powershell
Copy-Item frontend/.env.example frontend/.env.local
```

Open `frontend/.env.local` and replace the placeholders:

```text
NEXT_PUBLIC_SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_YOUR_VALUE
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

Only the URL, publishable key, and API address belong in this frontend file. Never add the secret key here.

## Step 5 — Set backend environment values

Open a second PowerShell window at the repository root:

```powershell
Copy-Item backend/.env.example backend/.env
```

Edit `backend/.env` with the same Project URL and publishable key, plus the Secret key:

```text
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_YOUR_VALUE
SUPABASE_SECRET_KEY=sb_secret_YOUR_VALUE
FRONTEND_ORIGIN=http://localhost:3000
BOOKS_BUCKET=books-private
MAX_PDF_SIZE_BYTES=52428800
```

Keep `backend/.env` private. The root `.gitignore` excludes it.

## Step 6 — Install and start the frontend

The current Next.js documentation requires Node.js 20.9 or newer. In PowerShell at the repository root:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. Keep this terminal running.

## Step 7 — Install and start FastAPI

Open a second PowerShell window at the repository root:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

If PowerShell blocks virtual-environment activation, run this in the current terminal, then activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Open `http://127.0.0.1:8000/api/health` to see the API status. Interactive API docs are at `http://127.0.0.1:8000/api/docs`.

## Step 8 — Try the Phase 1 flow

1. Open `http://localhost:3000` and select **Open my library**.
2. Create an account with an email address and password. Confirm the email if Supabase requires it.
3. Sign in and open **My library**.
4. Select a PDF (50 MiB or less) and watch the upload progress animation. Include a book larger than 10 MB when verifying the increased limit.
5. Confirm the book appears with status **Queued**.
6. In Supabase, confirm the row belongs to your test user and the file is in the private bucket under that user's ID folder.
7. Sign out. Visiting `/library` should redirect to `/login`.
8. Try a non-PDF and a file larger than 50 MiB; both should be rejected. FastAPI is the enforcement point.

## What Phase 1 does not do yet

Phase 1 stores a validated PDF and its metadata. It does not extract pages, create embeddings, or answer questions. `queued` means the book is ready for Phase 2 ingestion.
