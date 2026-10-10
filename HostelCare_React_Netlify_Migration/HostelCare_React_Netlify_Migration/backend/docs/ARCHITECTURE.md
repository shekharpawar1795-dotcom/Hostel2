# Deployed System Architecture — HostelCare

This is the architecture implemented in this repository, which replaces the earlier Node/Nest and Supabase proposals with a standalone FastAPI application. It is a browser-based website only.

```mermaid
flowchart TD
   B[Browser: Five Role Dashboards] -->|HTTPS| P[Reverse Proxy / TLS]
   P --> W[FastAPI Website]
   W --> S[DB Sessions and Argon2id Authentication]
   W --> A[Role- and Hostel-Scoped Business Logic]
   A --> DB[(PostgreSQL in production)]
   W --> UP[(Private Persistent Photo Storage)]
   BK[Background Scheduler Every 5m] --> DB
   BK --> EM[SMTP Email Adapter]
   B <-->|Ticket and notification views| W
```

## Five-role boundary

- STUDENT — URN-based own-record access; room populated from active assignment.
- RECTOR — all scoped hostel complaints; assign/reassign and classification.
- MAINTENANCE_STAFF — only assigned complaint work and notes/photos.
- DEAN — escalations scoped to institution-approved hostels; directives, not repairs.
- SYSTEM_ADMIN — institution hostels/rooms/users and scopes; no ordinary complaint-content access.

## Complaint state workflow

```mermaid
flowchart TD
  SUB[SUBMITTED] --> REVIEW[UNDER_REVIEW]
  REVIEW --> ASSIGN[ASSIGNED]
  ASSIGN --> ACCEPT[ACCEPTED]
  ACCEPT --> PROG[IN_PROGRESS]
  PROG --> DONE[AWAITING_CONFIRMATION]
  PROG --> HOLD[ON_HOLD]
  HOLD --> PROG
  DONE -->|Student confirms ordinary repair| CLOSE[CLOSED]
  DONE -->|Student disputes| REOP[REOPENED]
  REOP --> REVIEW
  DONE -->|48 hours no response; eligible| AUTO[AUTO_CLOSED]
  AUTO -->|Within seven days| REOP
```

## Non-interfering timers

1. No-start/Dean deadline is `work_cycle.started_at + 48h`. Reading, reviewing, assigning, or accepting does not stop this timer. Start of work AFTER the deadline still counts as overdue. Per-cycle unique escalation records are never discarded.
2. Post-repair student reminder is `work_completed_at + 24h`, auto-closure of *eligible ordinary cases* at +48h, and reopening for seven days after auto-closure.
3. The scheduler is a separate process. The website is not used as a timer. Losing the worker does not lose deadlines or database events; on restart it reconciles overdue work.

## Security/durability boundaries

- Mandatory first-login password update for accounts provisioned by Admin with one-time unique temporary passwords.
- Sessions are opaque database-backed token hashes; server controls URN, role and hostel-room assignment.
- CSRF anti-forgery form tokens, secure cookies and HTTP security headers; production HTTPS required.
- Photographs stored in a non-public directory and served only after authorization.
- PostgreSQL authoritative data; backups, migrations and alerting must be implemented and reviewed for college use.
