from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import (String, Integer, Boolean, DateTime, Text, ForeignKey,
    UniqueConstraint, CheckConstraint, Index, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    login_id: Mapped[str] = mapped_column(String(60), nullable=False, unique=True, index=True)
    urn: Mapped[str | None] = mapped_column(String(60), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    preferred_name: Mapped[str | None] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(30))
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    force_password_change: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Session(Base):
    __tablename__ = 'sessions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Hostel(Base):
    __tablename__ = 'hostels'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    emergency_phone: Mapped[str | None] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Room(Base):
    __tablename__ = 'rooms'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    hostel_id: Mapped[str] = mapped_column(ForeignKey('hostels.id'), index=True)
    building: Mapped[str] = mapped_column(String(80), default='Main', nullable=False)
    floor: Mapped[str] = mapped_column(String(30), default='0', nullable=False)
    number: Mapped[str] = mapped_column(String(30), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    __table_args__ = (UniqueConstraint('hostel_id', 'building', 'number', name='uq_room_identity'),)


class Allocation(Base):
    __tablename__ = 'allocations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    student_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False, index=True)
    room_id: Mapped[str] = mapped_column(ForeignKey('rooms.id'), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index('uq_active_allocation_student', 'student_id', unique=True,
        sqlite_where=text('active = 1'), postgresql_where=text('active = true')),)


class Scope(Base):
    __tablename__ = 'scopes'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False, index=True)
    hostel_id: Mapped[str] = mapped_column(ForeignKey('hostels.id'), nullable=False, index=True)
    __table_args__ = (UniqueConstraint('user_id', 'hostel_id', name='uq_user_hostel'),)


class Complaint(Base):
    __tablename__ = 'complaints'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    student_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False, index=True)
    hostel_id: Mapped[str] = mapped_column(ForeignKey('hostels.id'), nullable=False, index=True)
    room_id: Mapped[str] = mapped_column(ForeignKey('rooms.id'), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    effective_category: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(12), nullable=False, default='NORMAL')
    effective_priority: Mapped[str] = mapped_column(String(12), nullable=False, default='NORMAL')
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='SUBMITTED', index=True)
    cycle_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    current_staff_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    work_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    work_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmation_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closure_reason: Mapped[str | None] = mapped_column(String(90))
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint('student_id', 'idempotency_key', name='uq_student_submission'),
        Index('ix_complaint_hostel_status_created', 'hostel_id', 'status', 'created_at'))


class WorkCycle(Base):
    __tablename__ = 'work_cycles'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    complaint_id: Mapped[str] = mapped_column(ForeignKey('complaints.id'), nullable=False, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    work_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint('complaint_id', 'number', name='uq_work_cycle'),)


class Assignment(Base):
    __tablename__ = 'assignments'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    complaint_id: Mapped[str] = mapped_column(ForeignKey('complaints.id'), nullable=False, index=True)
    cycle_number: Mapped[int] = mapped_column(Integer, nullable=False)
    staff_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False, index=True)
    assigned_by: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Event(Base):
    __tablename__ = 'events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    complaint_id: Mapped[str] = mapped_column(ForeignKey('complaints.id'), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default='', nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Escalation(Base):
    __tablename__ = 'escalations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    complaint_id: Mapped[str] = mapped_column(ForeignKey('complaints.id'), nullable=False, index=True)
    cycle_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(60), default='NO_WORK_STARTED_48H')
    escalated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint('complaint_id', 'cycle_number', 'reason', name='uq_escalation_cycle'),)


class Attachment(Base):
    __tablename__ = 'attachments'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    complaint_id: Mapped[str] = mapped_column(ForeignKey('complaints.id'), nullable=False, index=True)
    uploader_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(200), nullable=False)
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = 'notifications'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    recipient_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False, index=True)
    complaint_id: Mapped[str | None] = mapped_column(ForeignKey('complaints.id'))
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    body: Mapped[str] = mapped_column(Text, default='', nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    email_state: Mapped[str] = mapped_column(String(18), default='PENDING', nullable=False)
    email_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Feedback(Base):
    __tablename__ = 'feedback'
    complaint_id: Mapped[str] = mapped_column(ForeignKey('complaints.id'), primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    rating: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoginAttempt(Base):
    __tablename__ = 'login_attempts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    login_id: Mapped[str] = mapped_column(String(60), index=True)
    ip: Mapped[str] = mapped_column(String(100), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class AdminAudit(Base):
    __tablename__ = 'admin_audit'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(60), nullable=False)
    target_id: Mapped[str] = mapped_column(String(100), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default='')
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
