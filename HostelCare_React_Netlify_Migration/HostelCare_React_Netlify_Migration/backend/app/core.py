from __future__ import annotations
import os, secrets, hashlib, hmac, re, smtplib, base64, io
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from sqlalchemy import create_engine, select, func, and_, delete
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session as DBSession, sessionmaker
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from PIL import Image, UnidentifiedImageError
from fastapi import HTTPException, Request
from starlette.responses import RedirectResponse
from .models import *

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = (
    URL.create('postgresql+psycopg',
        username=os.getenv('DB_USER','hcms'),
        password=os.getenv('DB_PASSWORD',''),
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT','5432')),
        database=os.getenv('DB_NAME','hcms'))
    if os.getenv('DB_HOST') else
    os.getenv('DATABASE_URL', f'sqlite:///{BASE_DIR / "hcms.sqlite3"}')
)
SESSION_SECRET = os.getenv('SESSION_SECRET', '')
SECURE_COOKIES = os.getenv('SECURE_COOKIES', 'false').lower() == 'true'
if os.getenv('ENVIRONMENT','development').lower() == 'production':
    if not SESSION_SECRET or len(SESSION_SECRET) < 32:
        raise RuntimeError('SESSION_SECRET must be set to a strong random value in production.')
    if not SECURE_COOKIES:
        raise RuntimeError('SECURE_COOKIES=true is required behind HTTPS in production.')
UPLOAD_DIR = Path(os.getenv('UPLOAD_DIR', BASE_DIR / 'private_uploads'))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
if str(DATABASE_URL).startswith('sqlite:'):
    engine = create_engine(DATABASE_URL, connect_args={'check_same_thread': False})
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=10)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
CATEGORIES = ('ELECTRICAL','PLUMBING','FURNITURE','CLEANING','INTERNET','DOOR_LOCK','BATHROOM','PEST_CONTROL','OTHER')
PRIORITIES = ('NORMAL','URGENT','EMERGENCY')
ROLES = ('STUDENT','RECTOR','MAINTENANCE_STAFF','DEAN','SYSTEM_ADMIN')
OPEN_STATES = ('SUBMITTED','UNDER_REVIEW','ASSIGNED','ACCEPTED','IN_PROGRESS','ON_HOLD','AWAITING_CONFIRMATION','REOPENED')


def init_db():
    Base.metadata.create_all(engine)


def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def normalize_login(s):
    return s.strip().upper()


def strong_password(password):
    return len(password) >= 12 and len(password) <= 128 and bool(re.search(r'[a-zA-Z]', password)) and bool(re.search(r'\d', password))


def temp_password():
    return 'HC-' + secrets.token_urlsafe(15) + '8a'


def hash_token(t):
    return hashlib.sha256(t.encode()).hexdigest()


def create_session(db, user):
    token = secrets.token_urlsafe(48)
    db.add(Session(user_id=user.id, token_hash=hash_token(token), expires_at=utcnow()+timedelta(hours=12)))
    db.commit()
    return token


def get_current_user(request, db):
    raw = request.cookies.get('hcms_session')
    if not raw:
        return None
    session = db.scalar(select(Session).where(Session.token_hash == hash_token(raw), Session.revoked_at.is_(None)))
    if not session or as_utc(session.expires_at) <= utcnow():
        return None
    user = db.get(User, session.user_id)
    return user if user and user.active else None


def as_utc(d):
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def csrf_token(raw_session):
    return hmac.new(SESSION_SECRET.encode(), raw_session.encode(), hashlib.sha256).hexdigest()


def initial_csrf():
    return secrets.token_urlsafe(32)


def require_csrf(request, form):
    raw = request.cookies.get('hcms_session')
    if raw:
        expected = csrf_token(raw)
        supplied = str(form.get('csrf_token',''))
    else:
        expected = request.cookies.get('hcms_login_csrf','')
        supplied = str(form.get('csrf_token',''))
    if not expected or not hmac.compare_digest(expected, supplied):
        raise HTTPException(403, 'Invalid CSRF token. Refresh the page.')


def require_role(user, *roles):
    if not user or user.role not in roles:
        raise HTTPException(403, 'Not authorized')


def user_hostel_ids(db, user):
    return set(db.scalars(select(Scope.hostel_id).where(Scope.user_id == user.id)).all())


def can_view(db, user, complaint):
    if not user or not complaint:
        return False
    if user.role == 'STUDENT':
        return complaint.student_id == user.id
    if user.role == 'RECTOR':
        return complaint.hostel_id in user_hostel_ids(db,user)
    if user.role == 'MAINTENANCE_STAFF':
        return db.scalar(select(Assignment.id).where(Assignment.complaint_id == complaint.id, Assignment.staff_id == user.id).limit(1)) is not None
    if user.role == 'DEAN':
        return complaint.hostel_id in user_hostel_ids(db,user) and db.scalar(select(Escalation.id).where(Escalation.complaint_id == complaint.id).limit(1)) is not None
    return False


def event(db, complaint, user, action, detail=''):
    db.add(Event(complaint_id=complaint.id, actor_id=user.id if user else None, action=action, detail=str(detail)[:2000]))


def alert(db, recipients, complaint, title, body):
    unique = set()
    for user in recipients:
        if user and user.active and user.id not in unique:
            db.add(Notification(recipient_id=user.id, complaint_id=complaint.id if complaint else None,
                title=title[:180], body=body[:2000]))
            unique.add(user.id)


def scoped_users(db, role, hostel_id):
    return db.scalars(select(User).join(Scope, Scope.user_id == User.id).where(
        User.role == role, User.active.is_(True), Scope.hostel_id == hostel_id)).all()


def student_room(db, user):
    return db.execute(select(Allocation,Room,Hostel).join(Room, Allocation.room_id == Room.id)
        .join(Hostel, Room.hostel_id == Hostel.id)
        .where(Allocation.student_id == user.id, Allocation.active.is_(True), Room.active.is_(True), Hostel.active.is_(True))).first()


def complaint_cycle(db, complaint):
    return db.scalar(select(WorkCycle).where(WorkCycle.complaint_id == complaint.id, WorkCycle.number == complaint.cycle_number))


def new_cycle(db, complaint, now=None):
    now = now or utcnow()
    db.add(WorkCycle(complaint_id=complaint.id, number=complaint.cycle_number, started_at=now))


def reopen(db, complaint, actor, reason):
    if len(reason.strip()) < 5:
        raise ValueError('Please explain why the issue is not resolved (at least 5 characters).')
    prior = complaint.status
    complaint.status = 'REOPENED'
    complaint.cycle_number += 1
    complaint.current_staff_id = None
    complaint.work_started_at = None
    complaint.work_completed_at = None
    complaint.confirmation_reminded_at = None
    complaint.closed_at = None
    complaint.closure_reason = None
    new_cycle(db, complaint)
    event(db, complaint, actor, 'REOPENED', f'Previous status: {prior}; Reason: {reason}')
    alert(db, scoped_users(db,'RECTOR',complaint.hostel_id), complaint, 'Complaint reopened', f'{complaint.number}: {reason}')


def process_due(db, now=None):
    """Database-backed reconciler. Safe to rerun, one escalation per work cycle."""
    now = now or utcnow()
    stats = {'escalated':0, 'reminded':0, 'auto_closed':0}
    # Escalation is based on the actual work-start timestamp, not today's status.
    # Starting work after the deadline MUST still create a historical escalation.
    cycles = db.scalars(select(WorkCycle).where(WorkCycle.started_at <= now - timedelta(hours=48)).with_for_update(skip_locked=True)).all()
    for cy in cycles:
        complaint = db.get(Complaint, cy.complaint_id)
        if not complaint:
            continue
        due = as_utc(cy.started_at) + timedelta(hours=48)
        if cy.work_started_at is not None and as_utc(cy.work_started_at) < due:
            continue
        # Invalid and duplicate complaints closed by Rector are excluded.
        if complaint.status in ('REJECTED','DUPLICATE') and complaint.cycle_number == cy.number:
            continue
        present = db.scalar(select(Escalation).where(Escalation.complaint_id==complaint.id, Escalation.cycle_number==cy.number, Escalation.reason=='NO_WORK_STARTED_48H'))
        if present:
            continue
        db.add(Escalation(complaint_id=complaint.id,cycle_number=cy.number,reason='NO_WORK_STARTED_48H',escalated_at=now))
        event(db, complaint, None, 'DEAN_ESCALATION', f'Work cycle {cy.number}: no repair start before 48-hour deadline')
        recipients = scoped_users(db,'DEAN',complaint.hostel_id)+scoped_users(db,'RECTOR',complaint.hostel_id)
        alert(db, recipients, complaint, '48-hour Dean escalation', f'{complaint.number}: repair work was not started within 48 hours.')
        if not scoped_users(db,'DEAN',complaint.hostel_id):
            admin_users = db.scalars(select(User).where(User.role=='SYSTEM_ADMIN', User.active.is_(True))).all()
            alert(db,admin_users,complaint,'Dean not configured',f'{complaint.number} is overdue but no Dean has access to this hostel. Configure Dean immediately.')
        stats['escalated'] += 1
    waiting = db.scalars(select(Complaint).where(Complaint.status == 'AWAITING_CONFIRMATION', Complaint.work_completed_at.is_not(None)).with_for_update(skip_locked=True)).all()
    for c in waiting:
        elapsed = now - as_utc(c.work_completed_at)
        if elapsed >= timedelta(hours=48):
            has_esc = db.scalar(select(Escalation.id).where(Escalation.complaint_id==c.id).limit(1)) is not None
            if c.effective_priority == 'EMERGENCY' or has_esc:
                if not c.confirmation_reminded_at:
                    alert(db, scoped_users(db,'RECTOR',c.hostel_id), c, 'Repair needs Rector verification', f'{c.number}: high-risk/escalated repair awaiting verification')
                    c.confirmation_reminded_at=now
                continue
            c.status = 'AUTO_CLOSED'
            c.closed_at = now
            c.closure_reason = 'NO_STUDENT_RESPONSE'
            event(db, c, None, 'AUTO_CLOSED', 'No student response 48 hours after reported repair')
            alert(db, [db.get(User,c.student_id)], c, 'Complaint auto-closed', f'{c.number} was auto-closed after no reply; you can reopen within 7 days.')
            stats['auto_closed'] += 1
        elif elapsed >= timedelta(hours=24) and not c.confirmation_reminded_at:
            c.confirmation_reminded_at = now
            event(db,c,None,'CONFIRMATION_REMINDER','24-hour reminder')
            alert(db, [db.get(User,c.student_id)], c,'Please verify repair',f'Confirm whether {c.number} has been resolved.')
            stats['reminded'] += 1
    # Keep brute-force prevention tables bounded without losing operational complaint audit.
    db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < now - timedelta(days=30)))
    db.commit()
    return stats


def deliver_email_batch(db, limit=30):
    host = os.getenv('SMTP_HOST','')
    if not host: return 0
    sent = 0
    unsent = db.scalars(select(Notification).where(Notification.email_state == 'PENDING', Notification.email_attempts < 4).order_by(Notification.created_at).limit(limit)).all()
    for note in unsent:
        user = db.get(User, note.recipient_id)
        if not user or not user.email:
            note.email_state='SKIPPED'; continue
        msg = EmailMessage(); msg['Subject']=note.title
        msg['From']=os.getenv('SMTP_FROM','hcms@example.invalid')
        msg['To']=user.email; msg.set_content(note.body)
        try:
            port=int(os.getenv('SMTP_PORT','587'))
            with smtplib.SMTP(host,port, timeout=10) as smtp:
                smtp.starttls()
                if os.getenv('SMTP_USER'):
                    smtp.login(os.getenv('SMTP_USER'),os.getenv('SMTP_PASSWORD',''))
                smtp.send_message(msg)
            note.email_state='SENT'; sent += 1
        except Exception:
            note.email_attempts += 1
            if note.email_attempts>=4: note.email_state='FAILED'
    db.commit()
    return sent


def save_image(data:bytes, filename:str):
    if len(data)>5*1024*1024:
        raise ValueError('Each image must be 5 MB or smaller.')
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))
        if img.format not in ('JPEG','PNG','WEBP'):
            raise ValueError('Only JPEG, PNG and WebP images are supported.')
        if img.width*img.height > 16000000:
            raise ValueError('Image dimensions are too large.')
        img.thumbnail((2200,2200))
        out = io.BytesIO()
        if img.mode not in ('RGB','RGBA'):
            img = img.convert('RGB')
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        img.save(out,format='JPEG',quality=82,optimize=True)
        key = secrets.token_hex(22)+'.jpg'
        (UPLOAD_DIR / key).write_bytes(out.getvalue())
        return key, 'image/jpeg'
    except (UnidentifiedImageError, OSError):
        raise ValueError('The uploaded file is not a valid image.')
