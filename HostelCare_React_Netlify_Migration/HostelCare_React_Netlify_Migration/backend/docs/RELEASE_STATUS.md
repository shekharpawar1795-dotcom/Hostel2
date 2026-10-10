# Release status — 2026-10-09

## What is implemented and runnable

- Responsive browser website with login, role-based navigation, status displays, forms and mobile-friendly complaint cards.
- Exactly five roles: STUDENT, RECTOR, MAINTENANCE_STAFF, DEAN, SYSTEM_ADMIN.
- Multi-hostel management: add a hostel; permanently delete only an unused hostel; archive populated hostels after resolving work and transferring residents. Hostels can be reactivated. Per-hostel emergency phone can be stored.
- Rooms, capacities, student room allocations and scoped Rector/Dean/worker access.
- Student URN login and unique system-generated initial password, forced first password change, later password changes, and preferred name/phone editing.
- Student complaint entry with category, priority, description, optional JPEG/PNG/WebP photos and authenticated private image viewing.
- Rector assignment/reassignment, status history and selected priority/category changes.
- Maintenance task acceptance, start, progress, hold/resume, completion notes and repair evidence attachments.
- Two independent 48-hour rules: unique Dean no-start escalation for each work cycle and student post-repair response window; seven-day reopening after eligible automatic closure.
- In-app notification center, SMTP adapter, background reconciler, admin audit table and complaint event history.
- PostgreSQL Docker Compose configuration (not exercised in this sandbox), local SQLite demo mode and written college deployment procedure.

## Verification actually performed

- Python compilation for application and scripts.
- Automated HTTP/database test suite with all five roles, cross-hostel access denials, URN temporary password change, photo authorization, hostel creation/deletion protection, staff repair workflow, student closure and reopening, exactly-once Dean escalation and late-start escalation.
- The template HTML and CSS were rendered in Chromium at desktop and mobile viewports; screenshots are in `docs/screenshots/`.

## Not yet proven or production-ready

- This chat environment has not deployed a live public website, connected to an actual college server, used the college domain, sent authenticated SMTP to real Deans, or exercised the Docker/PostgreSQL stack.
- Production still needs independent security review, privileged MFA, college-approved account recovery and privacy policies, tested PostgreSQL schema migrations, encryption/backups and off-site recovery drills, stronger upload security (malware scanning), end-to-end browser interaction tests, load testing and uptime monitoring.
- Hosting has a real cost if the worker, database, photo storage and email must remain consistently available. A free sleeping web service is unsuitable for the 48h escalation guarantee.
- No software can honestly be guaranteed to have zero errors. The code is a tested initial pilot, not a certified institution-wide production release.

## Deployment choice clarification

The attached requirements report proposed Next.js/NestJS/PostgreSQL/Redis, and a later discussion mentioned Cloudflare Pages/Supabase. The code delivered here implements the core workflows using FastAPI, Jinja2 and SQLAlchemy, with PostgreSQL support via Docker. This permits running the entire website locally without external account credentials. It is **not deployable to Cloudflare Pages as-is** because it includes a Python server.

To make it official: secure written college IT approval, choose reliable 24/7 hosting, provision production PostgreSQL and private file storage, enable TLS, wire the independent worker, test email, implement hardening and backup/recovery, conduct a controlled pilot using fake accounts, then import real URNs and connect the college domain.
