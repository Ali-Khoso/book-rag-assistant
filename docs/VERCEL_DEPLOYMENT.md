# Deploy the frontend on Vercel

The frontend is configured for Vercel. A custom domain is optional: Vercel assigns a project address ending in `.vercel.app`. The Python API, durable processing worker, and local Ollama service run on a separate persistent backend host. Supabase remains the authentication, database, and private Storage service.

## Frontend project settings

### Dashboard setup checklist

1. Push your local commit to GitHub with `git push origin main` from the repository root.
2. Open [Vercel New Project](https://vercel.com/new), connect GitHub, and import `Ali-Khoso/book-rag-assistant`.
3. Set **Root Directory** to `frontend`, **Framework Preset** to **Next.js**, and **Node.js Version** to **24.x**. Use `npm ci` for installation and `npm run build` for the build. Leave **Output Directory** at its framework default.
4. Add the three `NEXT_PUBLIC_*` variables listed below with your production Supabase values and the public HTTPS backend origin, then click **Deploy**. The backend must be hosted separately; a successful frontend deployment alone does not make uploads or answers work.
5. Copy the stable production URL from the project's **Domains** settings. Use that URL, rather than a per-commit preview URL, for the backend's `FRONTEND_ORIGIN`.
6. In Supabase, open **Authentication > URL Configuration**. Set **Site URL** to the stable production URL and add the same URL followed by `/auth/callback` to **Redirect URLs**. Apply migrations 0001 through 0005 to the production project if they are not already applied.
7. Restart or redeploy the backend after changing its environment. Wait for `/api/ready` to return HTTP 200, then test sign-in, PDF upload, processing, and cited answers through Vercel.
8. If a Vercel environment variable changes, redeploy the frontend: public values are embedded during the build. Future pushes to the connected production branch trigger deployments automatically when Git integration is enabled.

If deployment fails, check the build log first. A missing Next.js dependency usually means the root directory is wrong. If the page loads but API calls fail, check the backend HTTPS URL, readiness, exact `FRONTEND_ORIGIN`, and `ALLOWED_HOSTS`. If email confirmation redirects to localhost, correct Supabase's Site URL and Redirect URLs.

Import `Ali-Khoso/book-rag-assistant` into your Vercel account and set:

| Setting | Value |
| --- | --- |
| Root Directory | `frontend` |
| Framework | Next.js |
| Install Command | `npm ci` |
| Build Command | `npm run build` |
| Node.js | 24.x |

`frontend/vercel.json` contains the framework/build configuration. Vercel uses its own Next.js deployment adapter; standalone output is retained for Docker and other hosts.

Create the project to obtain its stable production `.vercel.app` address. Set these **Production** variables before the final deployment:

```text
NEXT_PUBLIC_SUPABASE_URL=https://YOUR_PRODUCTION_PROJECT.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_REPLACE_ME
NEXT_PUBLIC_API_URL=https://YOUR_PUBLIC_BACKEND_HOST
```

The API URL is the backend's actual HTTPS origin, without an extra `/api` suffix. Do not use `localhost` or `127.0.0.1` in a deployed frontend. Changes to public variables require a new frontend build.

Only the URL and publishable key belong in Vercel's public variables. Keep `SUPABASE_SECRET_KEY`, `OPENAI_API_KEY`, and `MONITORING_TOKEN` in the backend environment. The browser calls the backend directly; PDF uploads are not proxied through Vercel Functions. This preserves the application's 50 MiB upload limit independently of function request-size limits.

## Backend requirements

Use a backend host that supports the services below. A provider-generated HTTPS address is sufficient; you do not need to buy a custom domain. No backend hosting account is created or billed by this repository.

| Service | Image/start command | Required behavior |
| --- | --- | --- |
| API | `backend/Dockerfile`, default command | Public HTTPS endpoint; `PROCESSING_ENABLED=false`; readiness `/api/ready` |
| Worker | Same image, `python -m app.worker` | Persistent background process; shares Supabase configuration and embedding cache |
| Local answer model | Ollama with `qwen2.5:3b` | Private network endpoint; persistent model disk; no public port |

The repository also includes `deploy/compose.yaml` for an optional full Docker server deployment. That stack includes its own frontend and HTTPS edge; it is a separate hosting option from the Vercel frontend setup.

For the API and worker, configure the production settings in [Phase 4 Setup](PHASE_4_SETUP.md). In particular:

```text
ENVIRONMENT=production
FRONTEND_ORIGIN=https://YOUR_PROJECT.vercel.app
ALLOWED_HOSTS=["YOUR_PUBLIC_BACKEND_HOST","localhost","127.0.0.1"]
PROCESSING_ENABLED=false
LIMITS_ENABLED=true
WARM_MODELS=true
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:3b
OLLAMA_URL=http://ollama:11434
```

`ALLOWED_HOSTS` contains backend hostnames, without `https://` or a path. `FRONTEND_ORIGIN` is the exact stable Vercel production origin. If the backend platform gives Ollama another private hostname, add that exact hostname to `OLLAMA_ALLOWED_HTTP_HOSTS` and use it in `OLLAMA_URL`. An HTTPS model endpoint is also supported.

An OpenAI answer provider can replace the local model through the existing private backend configuration. It does not replace the API or background worker. Hosted model requests may incur provider charges; no hosted model key is enabled by this setup.

## Supabase production project

Use separate production credentials and storage from development. Apply migrations `0001` through `0005` to that project in order. In Supabase Auth, set the Site URL to the stable Vercel production origin and allow:

```text
https://YOUR_PROJECT.vercel.app/auth/callback
```

The local project's successful migrations do not apply themselves to a different production project. Configure Vercel Preview deployments with a separate development backend/project if you use them. Avoid a wildcard API CORS policy for every `*.vercel.app` site.

## Verify before sharing

Wait until the backend's `/api/ready` endpoint returns HTTP 200. It checks database access, a fresh worker heartbeat, embeddings, and availability of the configured local answer model.

From a trusted machine with the matching production backend settings:

```powershell
cd backend
$env:BOOKWISE_ENV_FILE = '../deploy/backend.env'
.\.venv\Scripts\python.exe -m scripts.preflight --api-url https://YOUR_PUBLIC_BACKEND_HOST --frontend-url https://YOUR_PROJECT.vercel.app --check-live
```

Then sign in through Vercel, upload a text-based PDF, wait for **Ready**, ask a question with a known answer, and open its citation. Test a second account: it must not see the first account's books or history. Delete the test book and confirm private file cleanup completes.

The code and local checks can be completed before hosting is configured. An online deployment is verified only after these checks pass against the actual Vercel and backend URLs.

## References

- [Vercel generated domains](https://vercel.com/docs/domains/working-with-domains)
- [Vercel function limits](https://vercel.com/docs/functions/limitations)
- [Next.js deployment](https://nextjs.org/docs/app/getting-started/deploying)
- [Next.js environment variables](https://nextjs.org/docs/app/guides/environment-variables)
