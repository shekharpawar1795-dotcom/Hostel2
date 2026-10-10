# HostelCare — Hostel Complaint & Maintenance Management Website

A **runnable, responsive browser-only MVP** for exactly 5 roles: Student, Rector, Maintenance Staff, Dean, System Admin. No mobile APK/PWA required. Supports multiple hostels, rooms, URN student login, individual temporary passwords, mandatory password change, limited self-edited profile, complaint lifecycle, photos, scoped permissions, Dean 48h escalation, and student confirmation after repair.

## Quick start (local)

Requirements: Python 3.11+, pip. PostgreSQL recommended for production; local default SQLite requires no setup.

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SESSION_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
python scripts/bootstrap_admin.py
uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000**, sign in with the printed admin ID and unique password, then immediately change it. In another terminal, run `python scripts/worker.py` for automatic reminders/Dean escalation and email dispatch. On Windows, use `set SESSION_SECRET=...` or the equivalent PowerShell environment variable and `.venv\\Scripts\\activate`.

### Admin setup

1. Add hostels, then rooms with capacities.
2. Create a Rector, Dean and maintenance worker and **grant each scope for the relevant hostel**.
3. Import or create students by URN. Each student receives a **different randomly generated one-time initial password** (visible to Admin once only). Distribute privately; never use one shared default password across all students.
4. Allocate each student to their assigned room, then have students sign in with URN and their temporary password and change it before using the website.
5. Create a student complaint; Rector assigns maintenance worker; staff accepts, starts, completes; student confirms or disputes.
6. The worker checks each work cycle for a verified start at 48h and creates Dean escalation records if missing. At 24h after reported completion it reminds students, and at 48h it auto-closes *eligible ordinary* cases. Escalated/emergency cases require Rector verification.

### Deleting a hostel

An unused hostel can be deleted. Hostels with rooms, staff grants or complaint history **cannot be hard deleted**; archive them instead. A hostel with open complaints cannot be archived until resolved. History remains available to authorized people.

### Profile editing

Students can change their own password and preferred name/phone. URN, role, legal name and room allocation are admin-controlled. Forgot password: an Admin can issue a fresh temporary password and revoke active sessions after identity verification.

### Quick validation

```
pytest -q
python -m compileall -q app scripts
```

## Architecture

- FastAPI + Jinja2 website, small JavaScript progressive enhancement, responsive CSS.
- SQLAlchemy database schema. SQLite for local/demo, PostgreSQL on college infrastructure.
- Database-backed sessions (HttpOnly cookie); Argon2id password hashing; CSRF for forms; backend access checks.
- Separate administrator audit records for hostel, room, account, scope and allocation actions.
- Configurable per-hostel emergency contact displayed on the New Complaint screen.
- Private on-disk photo storage and authenticated read endpoint; upload dir must be backed up and mounted persistently for production.
- Background worker (`scripts/worker.py`), PostgreSQL-backed idempotent escalation events, durable in-app notices and optional SMTP.

## Important disclosure

This is a **working initial implementation / pilot**, not a guarantee of bug-free or regulatory-compliant production software. Features such as SSO, administrator MFA, independently verified staff work-start proof, antivirus scanning of uploads, production database migrations, fully reliable email retry queues, centralized monitoring and backups require further engineering before official campus rollout. See `docs/DEPLOYMENT.md`.

## Website screenshots

Actual browser-rendered sample UI previews (fictional accounts/data):

- `docs/screenshots/login_desktop.png`
- `docs/screenshots/admin_desktop.png`
- `docs/screenshots/student_mobile.png`
- `docs/screenshots/new_complaint_mobile.png`

## Original specification

The user-provided 25-page report proposed a different Next.js/NestJS/Redis/S3 stack. This implementation preserves the principal workflows and five-role rules but uses a simpler integrated Python server for local executability. It does not deploy on Cloudflare Pages unchanged. The free test deployment stage can be local; connecting a college domain requires IT-authorized hosting with a continuously running worker.
