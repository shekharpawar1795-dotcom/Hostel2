"""Same-origin JSON adapter for the independent React frontend.
The original FastAPI handlers remain the source of truth for ALL mutations.
Never expose password_hash, session tokens, or unsanitized private records.
"""
from __future__ import annotations
import secrets
from urllib.parse import urlsplit, parse_qs
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session as DBSession
from .models import (User, Room, Hostel, Complaint, Assignment, WorkCycle, Event,
                     Escalation, Attachment, Notification, Feedback, Scope, AdminAudit)
from .core import (db_session, get_current_user, csrf_token, initial_csrf, SECURE_COOKIES,
                   user_hostel_ids, can_view, student_room, CATEGORIES, PRIORITIES, ROLES,
                   complaint_cycle)
from . import main as legacy

router = APIRouter(prefix='/api')


def obj(value):
    if value is None: return None
    # Serializes only SQLAlchemy model columns. Sensitive User fields are excluded.
    if isinstance(value, User):
        return {field:obj(getattr(value,field)) for field in (
            'id','login_id','urn','name','preferred_name','email','phone','role',
            'force_password_change','active','created_at')}
    from datetime import date, datetime
    if isinstance(value,(datetime,date)): return value.isoformat()
    if isinstance(value,(list,tuple)): return [obj(x) for x in value]
    if isinstance(value,dict): return {k:obj(v) for k,v in value.items()}
    if hasattr(value,'__table__'):
        return {c.name:obj(getattr(value,c.name)) for c in value.__table__.columns
                if c.name not in ('password_hash','token_hash','storage_key')}
    return value


def allocation_json(db,user):
    if not user or user.role!='STUDENT':return None
    a=student_room(db,user)
    return {'allocation':obj(a[0]),'room':obj(a[1]),'hostel':obj(a[2])} if a else None


def current(request,db):
    user=get_current_user(request,db)
    if not user: raise HTTPException(401,'Please log in.')
    return user


def gate(user):
    if user.force_password_change: raise HTTPException(428,'Change your temporary password first.')


def err_response(exc):
    return JSONResponse({'ok':False,'error':str(exc.detail)},status_code=exc.status_code)


@router.get('/session')
def session_info(request:Request,db:DBSession=Depends(db_session)):
    user=get_current_user(request,db)
    raw=request.cookies.get('hcms_session')
    csrf=csrf_token(raw) if user and raw else request.cookies.get('hcms_login_csrf') or initial_csrf()
    unread=db.scalar(select(func.count(Notification.id)).where(Notification.recipient_id==user.id,Notification.read_at.is_(None))) if user else 0
    response=JSONResponse({'user':obj(user),'csrf':csrf,'unread':unread or 0})
    if not user:
        response.set_cookie('hcms_login_csrf',csrf,secure=SECURE_COOKIES,
                            httponly=True,samesite='lax',max_age=600,path='/')
    return response


@router.get('/data')
def data(request:Request,view:str='dashboard',id:str='',q:str='',status:str='',page:int=1,
         user_search:str='',db:DBSession=Depends(db_session)):
    try:
        user=current(request,db)
        if view!='password':gate(user)
        base={'user':obj(user),'categories':CATEGORIES,'priorities':PRIORITIES,'roles':ROLES}
        if view=='password':return base
        if view=='profile':return {**base,'allocation':allocation_json(db,user)}
        if view=='notifications':
            return {**base,'notifications':obj(db.scalars(select(Notification).where(
                Notification.recipient_id==user.id).order_by(Notification.created_at.desc()).limit(100)).all())}
        if view=='new':
            if user.role!='STUDENT':raise HTTPException(403,'Students only')
            return {**base,'allocation':allocation_json(db,user),'idempotency_key':secrets.token_urlsafe(22)}
        if view=='complaint':
            c=db.get(Complaint,id)
            if not can_view(db,user,c):raise HTTPException(404,'Complaint not found')
            events=db.scalars(select(Event).where(Event.complaint_id==id).order_by(Event.at.desc())).all()
            pics=db.scalars(select(Attachment).where(Attachment.complaint_id==id)).all()
            escalations=db.scalars(select(Escalation).where(Escalation.complaint_id==id)).all()
            assignments=db.scalars(select(Assignment).where(Assignment.complaint_id==id).order_by(Assignment.assigned_at.desc())).all()
            ids={c.student_id,*[a.staff_id for a in assignments],*[e.actor_id for e in events if e.actor_id]}
            if c.current_staff_id:ids.add(c.current_staff_id)
            people=db.scalars(select(User).where(User.id.in_(ids))).all()
            staff=[]
            if user.role=='RECTOR':
                staff=db.scalars(select(User).join(Scope,Scope.user_id==User.id).where(
                    User.role=='MAINTENANCE_STAFF',User.active.is_(True),Scope.hostel_id==c.hostel_id)).all()
            return {**base,'complaint':obj(c),'events':obj(events),'photos':obj(pics),
                'escalations':obj(escalations),'assignments':obj(assignments),
                'people':{p.id:obj(p) for p in people},'room':obj(db.get(Room,c.room_id)),
                'hostel':obj(db.get(Hostel,c.hostel_id)),'staff_list':obj(staff),
                'current_cycle':obj(complaint_cycle(db,c)),'feedback':obj(db.get(Feedback,c.id))}
        if view!='dashboard':raise HTTPException(404,'Page not found')
        if user.role=='STUDENT':
            cs=db.scalars(select(Complaint).where(Complaint.student_id==user.id).order_by(
                Complaint.created_at.desc()).limit(12)).all()
            return {**base,'complaints':obj(cs),'allocation':allocation_json(db,user)}
        if user.role=='RECTOR':
            ids=user_hostel_ids(db,user)
            filters=[Complaint.hostel_id.in_(ids)]
            if q.strip():
                term='%'+q.strip()[:80]+'%'
                filters.append(or_(Complaint.description.ilike(term),Complaint.number.ilike(term)))
            if status:filters.append(Complaint.status==status)
            total=db.scalar(select(func.count()).select_from(Complaint).where(*filters)) or 0
            complaints=db.scalars(select(Complaint).where(*filters).order_by(
                Complaint.created_at.desc()).offset((max(1,page)-1)*25).limit(25)).all()
            counts=db.execute(select(Complaint.status,func.count()).where(Complaint.hostel_id.in_(ids))
                              .group_by(Complaint.status)).all()
            return {**base,'complaints':obj(complaints),'total':total,'counts':dict(counts),
                    'page':max(1,page),'search':q,'status_filter':status,
                    'hostels':obj(db.scalars(select(Hostel).where(Hostel.id.in_(ids))).all())}
        if user.role=='MAINTENANCE_STAFF':
            cs=db.scalars(select(Complaint).where(Complaint.current_staff_id==user.id).order_by(
                Complaint.created_at.desc()).limit(80)).all()
            return {**base,'complaints':obj(cs)}
        if user.role=='DEAN':
            ids=user_hostel_ids(db,user)
            es=db.scalars(select(Escalation).join(Complaint,Complaint.id==Escalation.complaint_id)
                .where(Complaint.hostel_id.in_(ids)).order_by(Escalation.escalated_at.desc()).limit(100)).all()
            cs={e.complaint_id:db.get(Complaint,e.complaint_id) for e in es}
            unresolved=sum(c.status not in ('CLOSED','AUTO_CLOSED','REJECTED','DUPLICATE') for c in cs.values())
            return {**base,'escalations':obj(es),'complaints_by_id':obj(cs),'unresolved':unresolved}
        # ADMIN: bounded lists, with only safe User fields
        hostels=db.scalars(select(Hostel).order_by(Hostel.name)).all()
        stmt=select(User)
        if user_search.strip():
            term='%'+user_search.strip()[:80]+'%'
            stmt=stmt.where(or_(User.login_id.ilike(term),User.name.ilike(term)))
        return {**base,'hostels':obj(hostels),
            'users':obj(db.scalars(stmt.order_by(User.created_at.desc()).limit(100)).all()),
            'staff_users':obj(db.scalars(select(User).where(User.role.in_([
                'RECTOR','DEAN','MAINTENANCE_STAFF']),User.active.is_(True)).order_by(User.name).limit(1000)).all()),
            'rooms':obj(db.scalars(select(Room).order_by(Room.building,Room.number).limit(1500)).all()),
            'audit':obj(db.scalars(select(AdminAudit).order_by(AdminAudit.at.desc()).limit(20)).all())}
    except HTTPException as exc:return err_response(exc)


@router.get('/photos/{photo_id}')
def photo(photo_id:str,request:Request,db:DBSession=Depends(db_session)):
    try:return legacy.photo(request,photo_id,db)
    except HTTPException as exc:return err_response(exc)


@router.post('/action/{action:path}')
async def act(action:str,request:Request,db:DBSession=Depends(db_session)):
    # Strict allow-list prevents arbitrary route execution.
    pieces=[p for p in action.strip('/').split('/') if p]
    try:
        if pieces==['login']: result=await legacy.login(request,db)
        elif pieces==['logout']:result=await legacy.logout(request,db)
        elif pieces==['profile']:result=await legacy.profile_update(request,db)
        elif pieces==['profile','password']:result=await legacy.password_change(request,db)
        elif pieces==['notifications','read']:result=await legacy.notifications_read(request,db)
        elif pieces==['student','new']:result=await legacy.student_create(request,db)
        elif len(pieces)==4 and pieces[0]=='student' and pieces[1]=='complaints' and pieces[3]=='verify':
            result=await legacy.student_verify(request,pieces[2],db)
        elif len(pieces)==4 and pieces[0]=='rector' and pieces[1]=='complaints' and pieces[3]=='action':
            result=await legacy.rector_action(request,pieces[2],db)
        elif len(pieces)==4 and pieces[0]=='staff' and pieces[1]=='complaints' and pieces[3]=='action':
            result=await legacy.maintenance_action(request,pieces[2],db)
        elif len(pieces)==4 and pieces[0]=='dean' and pieces[1]=='complaints' and pieces[3]=='directive':
            result=await legacy.dean_directive(request,pieces[2],db)
        elif pieces==['admin','hostels']:result=await legacy.add_hostel(request,db)
        elif pieces==['admin','rooms']:result=await legacy.add_room(request,db)
        elif pieces==['admin','users']:result=await legacy.add_user(request,db)
        elif pieces==['admin','users','import']:result=await legacy.import_students(request,db)
        elif pieces==['admin','scopes']:result=await legacy.add_scope(request,db)
        elif pieces==['admin','allocations']:result=await legacy.add_allocation(request,db)
        elif len(pieces)==4 and pieces[:2]==['admin','hostels'] and pieces[3]=='toggle':
            result=await legacy.toggle_hostel(request,pieces[2],db)
        elif len(pieces)==4 and pieces[:2]==['admin','hostels'] and pieces[3]=='delete':
            result=await legacy.delete_hostel(request,pieces[2],db)
        elif len(pieces)==4 and pieces[:2]==['admin','hostels'] and pieces[3]=='emergency-contact':
            result=await legacy.change_emergency_contact(request,pieces[2],db)
        elif len(pieces)==4 and pieces[:2]==['admin','users'] and pieces[3]=='toggle':
            result=await legacy.toggle_user(request,pieces[2],db)
        elif len(pieces)==4 and pieces[:2]==['admin','users'] and pieces[3]=='reset':
            result=await legacy.reset_user(request,pieces[2],db)
        else:raise HTTPException(404,'Unknown action')
        loc=result.headers.get('location','/dashboard')
        params=parse_qs(urlsplit(loc).query)
        credentials=result.context.get('new_credentials') if hasattr(result,'context') else None
        duplicates=result.context.get('duplicates') if hasattr(result,'context') else None
        payload={'ok':params.get('kind',['success'])[0]!='error',
                 'message':params.get('msg',['Action completed'])[0],
                 'next':urlsplit(loc).path or '/dashboard'}
        if credentials is not None:payload['credentials']=credentials
        if duplicates is not None:payload['duplicates']=duplicates
        response=JSONResponse(payload,status_code=200 if payload['ok'] else 422)
        # Preserve login/logout Set-Cookie headers from the original handlers.
        for key,value in result.raw_headers:
            if key.lower()==b'set-cookie':response.raw_headers.append((key,value))
        return response
    except HTTPException as exc:return err_response(exc)
