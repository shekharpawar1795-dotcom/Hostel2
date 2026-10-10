# Deployment and migration plan

This release is a working **Python FastAPI website + SQLAlchemy + PostgreSQL** codebase, not a Cloudflare Pages static site. The prior architecture proposals included NestJS and later Supabase; this running implementation is deliberately self-contained so its backend can be verified locally. **Cloudflare Pages cannot host this Python backend.** Do not claim it can be deployed there unchanged.

## Local demo (free, no cloud account)

```
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
export SESSION_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
python scripts/bootstrap_admin.py
uvicorn app.main:app --reload
# separate terminal (with same env): python scripts/worker.py
```

Go to http://127.0.0.1:8000 . Use the bootstrap administrator login and its one-time password. The database is a local SQLite file for development only. See root README.

## Institutional server (Docker/PostgreSQL)

1. Request a small Linux VM/VPS or college server with Docker, TLS termination and durable storage; obtain written approval to store actual student records.
2. Copy repository to server. Set strong `POSTGRES_PASSWORD`, `SESSION_SECRET`, `SECURE_COOKIES=true` and SMTP credentials in `.env` (never commit the file).
3. Run `docker compose up -d --build` and `docker compose exec web python scripts/bootstrap_admin.py` and record one-time credential privately.
4. Configure a reverse proxy (Caddy/nginx) to terminate HTTPS on `hostel.college.edu` and proxy to `127.0.0.1:8000`. Restrict direct access to port 8000.
5. Verify the web and worker processes remain running. The worker must be running independently for Dean escalation and student-confirmation timers.
6. Perform real SMTP delivery tests to all Deans. Monitor worker health and escalation lag.
7. Set up encrypted, automated PostgreSQL backups and private uploads backups, store copies offsite and test restoring them. Test simultaneous requests and permission boundaries.
8. Before onboarding real students, implement and independently test security hardening (MFA for privileged users, recovery, stronger CSRF/origin checks, staff identity validation, upload scanning, retention and college policy compliance). Obtain privacy/institutional approval.

## Free testing options

Run locally at no charge, or use a temporary free hosting provider **only for pilot data**. Free web services that suspend idle workloads are unsafe for reliable Dean alerts unless an independent worker remains online. Do not use ephemeral disks for SQLite or complaint photos. A custom college domain can later point to any approved host, but domain changes do not automatically move data or services. Cloudflare Pages alone is **not** a deployment option for this backend.

## Data portability

- Migrate from SQLite to PostgreSQL before official release; SQLAlchemy is cross-database, but data copying needs a tested migration script and valid backups.
- For multi-hostel records, hostel IDs remain stable when names change. Archive used hostels instead of deleting history.
- PostgreSQL schema changes must be versioned with Alembic migrations before multiple production upgrades; `create_all` in this MVP is for initial provisioning and demo only.

## Production gates still outstanding

This source is not certified for student data or uninterrupted college operations. An external auditor and the college IT department must review security, backup/restoration, availability, data-retention, accessibility and disaster recovery before official rollout. Budget for reliable hosting if the project becomes mission critical.
