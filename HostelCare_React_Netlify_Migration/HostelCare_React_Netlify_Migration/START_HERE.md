# HostelCare — React frontend migration and Netlify package

## Read this first

This is a **real React rewrite of HostelCare's screens** with an API adapter that delegates changes to the **original FastAPI backend**, preserving existing server-side validation, role scopes, state transitions and reconciliation rules. The Python backend is NOT rewritten in JavaScript or deployed to Netlify Functions.

- `frontend/` — React 18 + Vite, deployable on Netlify Free as static assets.
- `backend/` — original FastAPI/Jinja system with all original routes, models, scripts, worker, tests, plus new `app/react_api.py` exposing scoped JSON for React.
- Frontend and backend talk through one same-origin `/api/*` URL, proxied in development by Vite and in production by Netlify's proxy rewrite.
- Existing SQLite records are not included or transferred. Data stays in the backend database; image uploads remain on backend storage.

**Not a full Netlify-only deployment**: a separately running HTTPS backend + PostgreSQL + photo storage + scheduled worker is still required. Netlify hosting React does not make Python/SQLite/a 5-minute daemon run on Netlify. For zero-cost experiments, the existing backend Docker Compose config can be run on an Always Free-eligible VM if one is available. Production service is not guaranteed for free.

## Beginner instructions: run locally on Windows

You need Python 3.12 or newer, Node.js 20+ and npm.

**Terminal 1 — FastAPI backend** (Windows CMD):

```cmd
cd backend
py -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
for /f "delims=" %A in ('python -c "import secrets; print(secrets.token_urlsafe(48))"') do @set "SESSION_SECRET=%A"
python scripts\bootstrap_admin.py
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Save the generated session secret in a safe place and reuse it when restarting the backend. `bootstrap_admin.py` is for initial setup only and generates an individual temporary admin password. If you already have a backend database, do not recreate admin users and do not delete that database. The commands above assume a fresh project.

**Terminal 2 — Background worker** (Windows CMD, same backend directory):

```cmd
.venv\Scripts\activate.bat
python scripts\worker.py
```

**Terminal 3 — React UI** (Windows CMD):

```cmd
cd frontend
npm install
npm run dev
```

Start from the project's root in all three terminals, or adjust `cd` to the actual location. React is at **http://127.0.0.1:5173**. Open the React URL, **not port 8000** (port 8000 also still serves the old templates). The Vite proxy automatically sends `/api/` calls to port 8000, including session cookies. Log in with your System Admin credentials.

### Restart commands (after dependencies already installed)

In the `backend` folder, activate `.venv`, set the **same** `SESSION_SECRET`, run `python -m uvicorn app.main:app --reload`. In the second terminal, activate `.venv` and run `python scripts\worker.py`. In the `frontend` folder run `npm run dev`.

## Netlify: deploy the React frontend

1. Put this project in a **private GitHub repository**. Never commit `.env`, database records, credentials, or private uploads. This repository's root contains `frontend/` and `backend/`.
2. You must first host the separate backend at an **HTTPS URL** (e.g. `https://hostelcare-api.duckdns.org`). Its `web`, `db`, and `worker` must be running, and HTTPS must be valid. `backend/docker-compose.yml` + `backend/docker-compose.public.yml` + `backend/Caddyfile` support a Docker VM deployment. See original `backend/docs/DEPLOYMENT.md` and `backend/docs/RELEASE_STATUS.md` for pilot limitations.
3. On **https://app.netlify.com/** select Add new project → Import from Git, select your repository.
4. Set **Base directory** = `frontend`. Build command = `npm run build`; Publish directory = `dist` (relative to base directory).
5. Under **Site configuration → Environment variables**, set **`BACKEND_ORIGIN`** to the backend HTTPS **origin only**, e.g. `https://hostelcare-api.duckdns.org`. Do not put `/api`, a trailing slash, or `:8000` here. **This is not a database secret.**
6. Deploy or trigger a new deploy after saving the environment variable. The build script generates `dist/_redirects` with (a) an API proxy and (b) an SPA fallback.
7. Open your `https://<site-name>.netlify.app` link. If a login or session check fails, inspect Netlify's generated `dist/_redirects`, backend HTTPS/health, and browser Network logs. Uploads and cookies **must be verified over the actual Netlify URL**—we cannot guarantee a proxy configuration works in every environment without deployment testing.

No custom domain is required for the Netlify frontend. A DNS hostname for the *backend* is still a convenient way to make its HTTPS endpoint reachable; a free subdomain can suffice.

### Example generated redirects

```text
/api/*  https://hostelcare-api.duckdns.org/api/:splat  200
/*  /index.html  200
```

In local `npm run dev` builds, the Vite development proxy handles `/api` instead. This prevents cross-site session cookies and browser CORS issues for the React client. All authentication and roles are still validated by FastAPI.

## What's supported

React includes: login using URN/staff ID; forced first-login password change; student dashboard and room details; submit complaint with photo evidence; student confirmation/rating/reopening; Rector filtered hostel queue, classification, review, assignment/reassignment, rejection and exceptional verification; maintenance accept/start/hold/resume/progress/complete and evidence; Dean escalation queue/directives; notifications; profile edits; password changes; admin hostels/rooms/users/bulk CSV imports/scopes/room allocations/password reset/disable; and activity/audit/feedback/Dean history.

Original `backend/scripts/worker.py` continues to process both **separate** 48-hour rules. The React code does not duplicate this timer logic. Existing application permissions are checked on every backend request; hiding a React button is not an authorization boundary.

## What hasn't been delivered or verified

- **Not** a Node.js/Netlify Functions or Supabase backend migration. Hosting the frontend alone will show an API connectivity error until the FastAPI backend is reachable.
- **Not** a production-readiness/security audit. Privileged MFA, tested offsite backup and restoration, reliable email transport, production migrations and monitoring still need work.
- **Not** a migration of existing SQLite rows or uploaded photos. Do not copy these accidentally into a public repository.
- **Not** verified by live Netlify deployment, real browser end-to-end automation, or a Vite production build in this sandbox: npm's package registry was unreachable during packaging. Source JSX syntax was parsed successfully, and Python workflow / API tests passed, but you should run `npm install && npm run build` yourself.
- **Not** guaranteed to keep your site online without charges if either platform exceeds its free-plan capacity. Netlify currently enforces a finite monthly free usage credit limit and pauses projects that exhaust it.

## Developer validation performed

```
cd backend
pytest -q
python -m scripts.smoke_react_api
python -m scripts.smoke_react_workflow
```

3 original backend tests passed; two new API workflow smoke scripts passed. See `FEATURE_CHECKLIST.md` for detailed coverage.
