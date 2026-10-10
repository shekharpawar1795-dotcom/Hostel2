from __future__ import annotations
import csv, io, os, re, secrets, hashlib
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote
from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, HTTPException
from contextlib import asynccontextmanager
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession
from argon2.exceptions import VerifyMismatchError, VerificationError
from .models import *
from .core import *

@asynccontextmanager
async def lifespan(app):
    if os.getenv('AUTO_CREATE_TABLES','true') == 'true':
        init_db()
    yield

app = FastAPI(title='HCMS | Hostel Complaint Management', docs_url=None, redoc_url=None, lifespan=lifespan)
templates = Jinja2Templates(directory=str(Path(__file__).parent / 'templates'))
app.mount('/static', StaticFiles(directory=str(Path(__file__).parent / 'static')), name='static')


@app.middleware('http')
async def secure_headers(req, call_next):
    response = await call_next(req)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    if SECURE_COOKIES:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
    response.headers['Cache-Control'] = 'no-store' if req.url.path.startswith(('/api','/dashboard','/complaint','/admin','/rector','/dean','/staff','/student','/profile','/notifications')) else 'private, max-age=0'
    return response


def redirect(url):
    return RedirectResponse(url, status_code=303)


def go(url, message, kind='success'):
    sep = '&' if '?' in url else '?'
    return redirect(url+sep+'msg='+quote(message)+'&kind='+kind)


def page(request, db, template, **ctx):
    user=get_current_user(request,db)
    raw=request.cookies.get('hcms_session')
    token=csrf_token(raw) if raw else request.cookies.get('hcms_login_csrf','')
    notifications = db.scalar(select(func.count(Notification.id)).where(Notification.recipient_id==user.id,Notification.read_at.is_(None))) if user else 0
    return templates.TemplateResponse(request,template,{
        'user':user, 'csrf':token, 'unread_count':notifications, 'categories':CATEGORIES, 'priorities':PRIORITIES,
        'roles':ROLES,'msg':request.query_params.get('msg'), 'kind':request.query_params.get('kind','success'), **ctx})


def who(request, db, *roles):
    user=get_current_user(request,db)
    if not user: raise HTTPException(401,'Please log in.')
    if user.force_password_change and request.url.path != '/profile/password':
        raise HTTPException(428,'Change your temporary password before using the website.')
    if roles: require_role(user,*roles)
    return user


def get_scoped_complaint(db,user,complaint_id):
    c=db.get(Complaint,complaint_id)
    if not can_view(db,user,c): raise HTTPException(404,'Complaint not found')
    return c


def find_allocation(db,student):
    return student_room(db,student)


def staff_task(db,user,c):
    if c.current_staff_id != user.id or c.status not in ('ASSIGNED','ACCEPTED','IN_PROGRESS','ON_HOLD'):
        raise HTTPException(403,'This active task is not assigned to you.')
    return db.scalar(select(Assignment).where(Assignment.complaint_id == c.id, Assignment.cycle_number==c.cycle_number, Assignment.staff_id==user.id, Assignment.ended_at.is_(None)))


def notify_change(db,c,title,body):
    alert(db,[db.get(User,c.student_id)]+scoped_users(db,'RECTOR',c.hostel_id),c,title,body)


@app.exception_handler(HTTPException)
async def errors(request, exc):
    if exc.status_code == 401:
        return redirect('/login?msg=Please+log+in&kind=error')
    if exc.status_code == 428:
        return redirect('/profile/password?msg=Change+your+temporary+password+first&kind=error')
    with SessionLocal() as db:
        response = page(request,db,'message.html',title='Request could not be completed',error=str(exc.detail),status=exc.status_code)
        response.status_code = exc.status_code
        return response


@app.get('/healthz')
def health():
    with SessionLocal() as db:
        db.scalar(select(func.count(User.id)))
    return {'status':'ok'}


@app.get('/')
def home(request:Request,db:DBSession=Depends(db_session)):
    return redirect('/dashboard' if get_current_user(request,db) else '/login')


@app.get('/login')
def login_page(request:Request,db:DBSession=Depends(db_session)):
    if get_current_user(request,db): return redirect('/dashboard')
    raw=initial_csrf()
    response=templates.TemplateResponse(request,'login.html',{
        'user':None,'csrf':raw,'msg':request.query_params.get('msg'),'kind':request.query_params.get('kind','success')})
    response.set_cookie('hcms_login_csrf',raw,secure=SECURE_COOKIES,httponly=True,samesite='lax',max_age=600)
    return response


@app.post('/login')
async def login(request:Request,db:DBSession=Depends(db_session)):
    form=await request.form();require_csrf(request,form)
    login_id=normalize_login(str(form.get('login_id','')))
    password=str(form.get('password',''))
    ip=request.client.host if request.client else 'unknown'
    since=utcnow()-timedelta(minutes=15)
    recent=db.scalar(select(func.count(LoginAttempt.id)).where(LoginAttempt.login_id==login_id, LoginAttempt.ip==ip,
        LoginAttempt.success.is_(False),LoginAttempt.created_at>since)) or 0
    if recent>=10:
        return go('/login','Too many failed attempts. Try again in 15 minutes.','error')
    user=db.scalar(select(User).where(User.login_id==login_id, User.active.is_(True)))
    valid=False
    if user:
        try:valid=ph.verify(user.password_hash,password)
        except (VerifyMismatchError,VerificationError):pass
    db.add(LoginAttempt(login_id=login_id,ip=ip,success=valid));db.commit()
    if not valid:
        return go('/login','Invalid login ID or password.','error')
    token=create_session(db,user)
    response=redirect('/profile/password' if user.force_password_change else '/dashboard')
    response.set_cookie('hcms_session',token,max_age=12*3600,httponly=True,secure=SECURE_COOKIES,samesite='lax',path='/')
    response.delete_cookie('hcms_login_csrf')
    return response


@app.post('/logout')
async def logout(request:Request,db:DBSession=Depends(db_session)):
    form=await request.form();require_csrf(request,form)
    raw=request.cookies.get('hcms_session')
    if raw:
        s=db.scalar(select(Session).where(Session.token_hash==hash_token(raw)))
        if s:s.revoked_at=utcnow();db.commit()
    r=redirect('/login?msg=You+are+signed+out')
    r.delete_cookie('hcms_session');return r


@app.get('/profile/password')
def password_page(request:Request,db:DBSession=Depends(db_session)):
    user=get_current_user(request,db)
    if not user:return redirect('/login')
    return page(request,db,'password.html')


@app.post('/profile/password')
async def password_change(request:Request,db:DBSession=Depends(db_session)):
    user=get_current_user(request,db)
    if not user:return redirect('/login')
    form=await request.form();require_csrf(request,form)
    old=str(form.get('old_password',''));new=str(form.get('new_password',''));confirm=str(form.get('confirm_password',''))
    try: verified=ph.verify(user.password_hash,old)
    except (VerifyMismatchError,VerificationError):verified=False
    if not verified:return go('/profile/password','Current password is incorrect.','error')
    if new!=confirm or not strong_password(new):return go('/profile/password','New password must match and contain 12–128 characters with letters and digits.','error')
    if old==new:return go('/profile/password','Choose a different password.','error')
    user.password_hash=ph.hash(new);user.force_password_change=False
    for s in db.scalars(select(Session).where(Session.user_id==user.id)):
        if s.token_hash != hash_token(request.cookies.get('hcms_session','')):s.revoked_at=utcnow()
    db.commit()
    return go('/dashboard','Password updated successfully.')


@app.get('/profile')
def profile_page(request:Request,db:DBSession=Depends(db_session)):
    user=who(request,db)
    allocation=find_allocation(db,user) if user.role=='STUDENT' else None
    return page(request,db,'profile.html',allocation=allocation)


@app.post('/profile')
async def profile_update(request:Request,db:DBSession=Depends(db_session)):
    user=who(request,db)
    form=await request.form(); require_csrf(request,form)
    display_name=str(form.get('preferred_name','')).strip()
    phone=str(form.get('phone','')).strip()
    if len(display_name)>100 or len(phone)>25 or (phone and not re.fullmatch(r'[+()\d .\-]{7,25}',phone)):
        return go('/profile','Enter a valid preferred name and phone number.','error')
    user.preferred_name=display_name or None;user.phone=phone or None
    db.commit();return go('/profile','Profile updated. URN, role and room remain administration-controlled.')


@app.get('/dashboard')
def dashboard(request:Request,db:DBSession=Depends(db_session)):
    user=who(request,db)
    if user.role=='STUDENT':
        allc=db.scalars(select(Complaint).where(Complaint.student_id==user.id).order_by(Complaint.created_at.desc()).limit(12)).all()
        return page(request,db,'student.html',complaints=allc,allocation=find_allocation(db,user), title='My Hostel Dashboard')
    if user.role=='RECTOR':return rector_dashboard(request,db)
    if user.role=='MAINTENANCE_STAFF':return staff_dashboard(request,db)
    if user.role=='DEAN':return dean_dashboard(request,db)
    return admin_dashboard(request,db)


@app.get('/notifications')
def notifications_page(request:Request,db:DBSession=Depends(db_session)):
    user=who(request,db)
    notes=db.scalars(select(Notification).where(Notification.recipient_id==user.id).order_by(Notification.created_at.desc()).limit(100)).all()
    return page(request,db,'notifications.html',notes=notes)


@app.post('/notifications/read')
async def notifications_read(request:Request,db:DBSession=Depends(db_session)):
    user=who(request,db);form=await request.form();require_csrf(request,form)
    for note in db.scalars(select(Notification).where(Notification.recipient_id==user.id,Notification.read_at.is_(None))):note.read_at=utcnow()
    db.commit();return redirect('/notifications')


@app.get('/student/new')
def student_new(request:Request,db:DBSession=Depends(db_session)):
    user=who(request,db,'STUDENT')
    return page(request,db,'complaint_new.html',allocation=find_allocation(db,user),idempotency_key=secrets.token_urlsafe(22))


@app.post('/student/new')
async def student_create(request:Request,db:DBSession=Depends(db_session)):
    user=who(request,db,'STUDENT');form=await request.form();require_csrf(request,form)
    allocation=find_allocation(db,user)
    if not allocation:return go('/student/new','No active room assignment. Contact System Admin.','error')
    _,room,hostel=allocation
    cat=str(form.get('category','')).upper();p=str(form.get('priority','')).upper()
    desc=str(form.get('description','')).strip(); key=str(form.get('idempotency_key',''))
    if cat not in CATEGORIES or p not in PRIORITIES or not 10<=len(desc)<=1000 or not 16<=len(key)<=80:
        return go('/student/new','Please provide a category, priority and description of 10–1000 characters.','error')
    existing=db.scalar(select(Complaint).where(Complaint.student_id==user.id,Complaint.idempotency_key==key))
    if existing:return redirect('/complaints/'+existing.id)
    images=form.getlist('photos')
    images=[x for x in images if hasattr(x,'filename') and x.filename]
    if len(images)>3:return go('/student/new','Maximum three images allowed.','error')
    saved=[]
    try:
        for f in images:
            content=await f.read(5*1024*1024+1)
            saved.append((f.filename,*save_image(content,f.filename)))
    except ValueError as ex:
        for _,k,_ in saved:(UPLOAD_DIR/k).unlink(missing_ok=True)
        return go('/student/new',str(ex),'error')
    now=utcnow();c=Complaint(number='PENDING-'+secrets.token_hex(10),student_id=user.id,hostel_id=hostel.id,room_id=room.id,
        category=cat,effective_category=cat,description=desc,priority=p,effective_priority=p,status='SUBMITTED',
        idempotency_key=key,created_at=now)
    try:
        db.add(c);db.flush()
        c.number=f'HC-{now.year}-{c.id[:8].upper()}'
        new_cycle(db,c,now)
        event(db,c,user,'SUBMITTED',f'{cat}; {p}; {room.number}')
        for filename,key_saved,mime in saved:
            db.add(Attachment(complaint_id=c.id,uploader_id=user.id,filename=filename[:200],storage_key=key_saved,mime_type=mime))
        alert(db,scoped_users(db,'RECTOR',hostel.id),c,'New hostel complaint',f'{c.number}: {room.number} — {desc[:160]}')
        if p=='EMERGENCY':
            alert(db,scoped_users(db,'RECTOR',hostel.id),c,'EMERGENCY: immediate attention',f'{c.number}: immediate human response is required. The website is not an emergency hotline.')
        db.commit()
    except IntegrityError:
        db.rollback()
        existing=db.scalar(select(Complaint).where(Complaint.student_id==user.id,Complaint.idempotency_key==key))
        if existing:return redirect('/complaints/'+existing.id)
        raise
    return go('/complaints/'+c.id,'Complaint registered successfully. Reference '+c.number)


@app.get('/complaints/{cid}')
def complaint_detail(request:Request,cid:str,db:DBSession=Depends(db_session)):
    user=who(request,db)
    c=get_scoped_complaint(db,user,cid)
    events=db.scalars(select(Event).where(Event.complaint_id==c.id).order_by(Event.at.desc())).all()
    pics=db.scalars(select(Attachment).where(Attachment.complaint_id==c.id)).all()
    escalations=db.scalars(select(Escalation).where(Escalation.complaint_id==c.id)).all()
    assignments=db.scalars(select(Assignment).where(Assignment.complaint_id==c.id).order_by(Assignment.assigned_at.desc())).all()
    people={u.id:u for u in db.scalars(select(User).where(User.id.in_({c.student_id,*[a.staff_id for a in assignments],*[e.actor_id for e in events if e.actor_id]}))).all()}
    staff_list=[]
    if user.role=='RECTOR':
        staff_list=db.scalars(select(User).join(Scope,Scope.user_id==User.id).where(User.role=='MAINTENANCE_STAFF',User.active.is_(True),Scope.hostel_id==c.hostel_id)).all()
    return page(request,db,'complaint_detail.html',c=c,events=events,pics=pics,escalations=escalations,assignments=assignments,people=people,
        owner=db.get(User,c.student_id),room=db.get(Room,c.room_id),hostel=db.get(Hostel,c.hostel_id),staff_list=staff_list,
        current_cycle=complaint_cycle(db,c),feedback=db.get(Feedback,c.id))


@app.get('/photos/{aid}')
def photo(request:Request,aid:str,db:DBSession=Depends(db_session)):
    user=who(request,db);pic=db.get(Attachment,aid)
    if not pic or not can_view(db,user,db.get(Complaint,pic.complaint_id)):
        raise HTTPException(404,'Image not found')
    path=UPLOAD_DIR / pic.storage_key
    if not path.is_file():raise HTTPException(404,'Image unavailable')
    return FileResponse(path,media_type=pic.mime_type,headers={'Cache-Control':'private, no-store'})


def rector_dashboard(request,db):
    user=who(request,db,'RECTOR');ids=user_hostel_ids(db,user)
    search=request.query_params.get('q','').strip()[:80]
    status=request.query_params.get('status','').strip()
    try:page_num=max(1,int(request.query_params.get('page','1')))
    except ValueError:page_num=1
    all_filter=[Complaint.hostel_id.in_(ids)]
    filtered=all_filter.copy()
    if search:
        term=f'%{search}%'
        from sqlalchemy import or_
        filtered.append(or_(Complaint.description.ilike(term),Complaint.number.ilike(term)))
    if status in OPEN_STATES+('CLOSED','AUTO_CLOSED','REJECTED','DUPLICATE'):
        filtered.append(Complaint.status==status)
    total=db.scalar(select(func.count()).select_from(Complaint).where(*filtered)) or 0
    complaints=db.scalars(select(Complaint).where(*filtered).order_by(Complaint.created_at.desc())
        .offset((page_num-1)*25).limit(25)).all() if ids else []
    rows=db.execute(select(Complaint.status,func.count()).where(*all_filter).group_by(Complaint.status)).all() if ids else []
    counts={r[0]:r[1] for r in rows}
    return page(request,db,'rector.html',complaints=complaints,counts=counts,
        total=total,page_num=page_num,search=search,status_filter=status,
        hostels=db.scalars(select(Hostel).where(Hostel.id.in_(ids))).all())


@app.post('/rector/complaints/{cid}/action')
async def rector_action(request:Request,cid:str,db:DBSession=Depends(db_session)):
    user=who(request,db,'RECTOR');form=await request.form();require_csrf(request,form)
    c=db.scalar(select(Complaint).where(Complaint.id==cid).with_for_update())
    if not c or c.hostel_id not in user_hostel_ids(db,user):raise HTTPException(404,'Complaint not found')
    action=str(form.get('action',''));reason=str(form.get('reason','')).strip()
    if action=='review' and c.status in ('SUBMITTED','REOPENED'):
        c.status='UNDER_REVIEW';event(db,c,user,'UNDER_REVIEW')
    elif action=='assign' and c.status in ('SUBMITTED','UNDER_REVIEW','ASSIGNED','ACCEPTED','REOPENED','ON_HOLD'):
        staff=db.get(User,str(form.get('staff_id','')))
        if not staff or staff.role!='MAINTENANCE_STAFF' or not staff.active or c.hostel_id not in user_hostel_ids(db,staff):
            return go('/complaints/'+cid,'Choose a maintenance staff member authorized for this hostel.','error')
        if c.current_staff_id == staff.id:return go('/complaints/'+cid,'This worker is already assigned.','error')
        for a in db.scalars(select(Assignment).where(Assignment.complaint_id==c.id,Assignment.ended_at.is_(None))):a.ended_at=utcnow()
        c.current_staff_id=staff.id;c.status='ASSIGNED'
        db.add(Assignment(complaint_id=c.id,cycle_number=c.cycle_number,staff_id=staff.id,assigned_by=user.id))
        event(db,c,user,'ASSIGNED',f'Assigned to {staff.name}; {reason}')
        alert(db,[staff],c,'Maintenance task assigned',f'{c.number} in room {db.get(Room,c.room_id).number}: {c.description[:140]}')
    elif action=='classify' and c.status in OPEN_STATES:
        cat=str(form.get('category',''));p=str(form.get('priority',''))
        if cat not in CATEGORIES or p not in PRIORITIES:raise HTTPException(422,'Invalid category or priority')
        c.effective_category=cat;c.effective_priority=p
        event(db,c,user,'CLASSIFIED',f'Effective category {cat}, priority {p}; {reason}')
    elif action=='reject' and c.status in ('SUBMITTED','UNDER_REVIEW'):
        if len(reason)<8:return go('/complaints/'+cid,'A clear rejection reason is required (8+ characters).','error')
        c.status='REJECTED';event(db,c,user,'REJECTED',reason)
        alert(db,[db.get(User,c.student_id)],c,'Complaint rejected',f'{c.number}: {reason}')
    elif action=='reopen' and c.status in ('CLOSED','AUTO_CLOSED'):
        try:reopen(db,c,user,reason)
        except ValueError as ex:return go('/complaints/'+cid,str(ex),'error')
    elif action=='verify' and c.status=='AWAITING_CONFIRMATION':
        has_esc=db.scalar(select(Escalation.id).where(Escalation.complaint_id==c.id).limit(1)) is not None
        if not (c.effective_priority=='EMERGENCY' or has_esc):
            return go('/complaints/'+cid,'Student confirmation is required for ordinary complaints.','error')
        if len(reason)<8:return go('/complaints/'+cid,'Record verification details (8+ characters).','error')
        c.status='CLOSED';c.closed_at=utcnow();c.closure_reason='RECTOR_VERIFIED'
        event(db,c,user,'RECTOR_VERIFIED',reason)
        alert(db,[db.get(User,c.student_id)],c,'Repair verified',f'{c.number}: Rector verified the repair.')
    else:
        raise HTTPException(409,'Action is not allowed in the current status.')
    db.commit();return go('/complaints/'+cid,'Action saved successfully.')


def staff_dashboard(request,db):
    user=who(request,db,'MAINTENANCE_STAFF')
    assigned=db.scalars(select(Complaint).where(Complaint.current_staff_id==user.id).order_by(Complaint.created_at.desc()).limit(80)).all()
    return page(request,db,'staff.html',complaints=assigned)


@app.post('/staff/complaints/{cid}/action')
async def maintenance_action(request:Request,cid:str,db:DBSession=Depends(db_session)):
    user=who(request,db,'MAINTENANCE_STAFF');form=await request.form();require_csrf(request,form)
    c=db.scalar(select(Complaint).where(Complaint.id==cid).with_for_update())
    if not c:raise HTTPException(404,'Not found')
    a=staff_task(db,user,c)
    if not a:raise HTTPException(403,'Task assignment is inactive')
    action=str(form.get('action',''));note=str(form.get('note','')).strip()
    if action=='accept' and c.status=='ASSIGNED':
        c.status='ACCEPTED';a.accepted_at=utcnow();event(db,c,user,'ACCEPTED')
    elif action=='start' and c.status=='ACCEPTED':
        if len(note)<5:return go('/complaints/'+cid,'Start work requires a brief repair note (5+ characters).','error')
        now=utcnow();c.status='IN_PROGRESS';c.work_started_at=now
        cy=complaint_cycle(db,c);cy.work_started_at=now
        event(db,c,user,'WORK_STARTED',note)
        alert(db,[db.get(User,c.student_id)],c,'Maintenance started',f'{c.number}: technician started work.')
    elif action=='hold' and c.status in ('ACCEPTED','IN_PROGRESS'):
        if len(note)<8:return go('/complaints/'+cid,'Provide a clear reason for hold (8+ characters).','error')
        c.status='ON_HOLD';event(db,c,user,'ON_HOLD',note)
        alert(db,scoped_users(db,'RECTOR',c.hostel_id),c,'Repair on hold',f'{c.number}: {note}')
    elif action=='resume' and c.status=='ON_HOLD':
        c.status='IN_PROGRESS' if c.work_started_at else 'ACCEPTED'
        event(db,c,user,'RESUMED',note)
    elif action=='progress' and c.status=='IN_PROGRESS':
        if len(note)<3:return go('/complaints/'+cid,'Write a progress note.','error')
        event(db,c,user,'PROGRESS',note)
    elif action=='complete' and c.status=='IN_PROGRESS':
        if len(note)<8:return go('/complaints/'+cid,'A repair summary of at least 8 characters is required.','error')
        c.status='AWAITING_CONFIRMATION';c.work_completed_at=utcnow()
        c.confirmation_reminded_at=None
        event(db,c,user,'WORK_COMPLETED',note)
        alert(db,[db.get(User,c.student_id)],c,'Please confirm the repair',f'{c.number} has been marked repaired. Please confirm or dispute.')
    else:raise HTTPException(409,'Action not allowed from current status')
    # Attach repair evidence only to accepted progress/completion updates.
    if action in ('progress','complete'):
        images=[f for f in form.getlist('photos') if hasattr(f,'filename') and f.filename]
        if len(images)>3:
            db.rollback();return go('/complaints/'+cid,'Select no more than 3 repair photos.','error')
        saved=[]
        try:
            for f in images:
                data=await f.read(5*1024*1024+1)
                key,mime=save_image(data,f.filename)
                saved.append((f.filename,key,mime))
            for filename,key,mime in saved:
                db.add(Attachment(complaint_id=c.id,uploader_id=user.id,storage_key=key,filename=filename[:200],mime_type=mime))
        except ValueError as ex:
            db.rollback()
            for _,key,_ in saved:(UPLOAD_DIR/key).unlink(missing_ok=True)
            return go('/complaints/'+cid,str(ex),'error')
    db.commit();return go('/complaints/'+cid,'Maintenance update saved.')


@app.post('/student/complaints/{cid}/verify')
async def student_verify(request:Request,cid:str,db:DBSession=Depends(db_session)):
    user=who(request,db,'STUDENT');form=await request.form();require_csrf(request,form)
    c=db.scalar(select(Complaint).where(Complaint.id==cid).with_for_update())
    if not c or c.student_id!=user.id:raise HTTPException(404,'Not found')
    action=str(form.get('action',''));reason=str(form.get('reason','')).strip()
    if action=='confirm' and c.status=='AWAITING_CONFIRMATION':
        has_esc=db.scalar(select(Escalation.id).where(Escalation.complaint_id==c.id).limit(1)) is not None
        if c.effective_priority=='EMERGENCY' or has_esc:
            event(db,c,user,'STUDENT_CONFIRMED_PENDING_RECTOR','Student confirmed; Rector must verify safety/escalated repair')
            alert(db,scoped_users(db,'RECTOR',c.hostel_id),c,'Student confirmed; verification required',f'{c.number}: please verify before closure.')
        else:
            c.status='CLOSED';c.closed_at=utcnow();c.closure_reason='STUDENT_CONFIRMED'
            event(db,c,user,'STUDENT_CONFIRMED')
        rating=str(form.get('rating','')).strip();comment=str(form.get('comment',''))[:1000]
        if rating and rating in ('1','2','3','4','5') and not db.get(Feedback,c.id):
            db.add(Feedback(complaint_id=c.id,student_id=user.id,rating=int(rating),comment=comment))
    elif action=='reopen' and (c.status=='AWAITING_CONFIRMATION' or
        (c.status=='AUTO_CLOSED' and c.closed_at and utcnow()-as_utc(c.closed_at)<=timedelta(days=7))):
        try:reopen(db,c,user,reason)
        except ValueError as ex:return go('/complaints/'+cid,str(ex),'error')
    else:raise HTTPException(409,'The complaint cannot be confirmed or reopened now.')
    db.commit();return go('/complaints/'+cid,'Your response was saved.')


def dean_dashboard(request,db):
    user=who(request,db,'DEAN');ids=user_hostel_ids(db,user)
    escalations=db.scalars(select(Escalation).join(Complaint,Complaint.id==Escalation.complaint_id)
        .where(Complaint.hostel_id.in_(ids)).order_by(Escalation.escalated_at.desc()).limit(100)).all() if ids else []
    c_by_id={e.complaint_id:db.get(Complaint,e.complaint_id) for e in escalations}
    unresolved=sum(c_by_id[e.complaint_id].status not in ('CLOSED','AUTO_CLOSED','REJECTED','DUPLICATE') for e in escalations)
    return page(request,db,'dean.html',escalations=escalations,c_by_id=c_by_id,unresolved=unresolved)


@app.post('/dean/complaints/{cid}/directive')
async def dean_directive(request:Request,cid:str,db:DBSession=Depends(db_session)):
    user=who(request,db,'DEAN');form=await request.form();require_csrf(request,form)
    c=get_scoped_complaint(db,user,cid)
    detail=str(form.get('directive','')).strip()
    if len(detail)<10 or len(detail)>1500:return go('/complaints/'+cid,'Directive must contain 10–1500 characters.','error')
    event(db,c,user,'DEAN_DIRECTIVE',detail)
    alert(db,scoped_users(db,'RECTOR',c.hostel_id),c,'Dean issued a directive',f'{c.number}: {detail}')
    db.commit();return go('/complaints/'+cid,'Directive recorded and Rector notified.')


def admin_audit(db, actor, action, target_type, target_id, detail=''):
    db.add(AdminAudit(actor_id=actor.id, action=action, target_type=target_type,
        target_id=str(target_id), detail=str(detail)[:1200]))


def admin_dashboard(request,db):
    who(request,db,'SYSTEM_ADMIN')
    hostels=db.scalars(select(Hostel).order_by(Hostel.name)).all()
    user_search=request.query_params.get('user_search','').strip()[:80]
    user_stmt=select(User)
    if user_search:
        from sqlalchemy import or_
        term=f'%{user_search}%'
        user_stmt=user_stmt.where(or_(User.login_id.ilike(term),User.name.ilike(term)))
    users=db.scalars(user_stmt.order_by(User.created_at.desc()).limit(100)).all()
    staff_users=db.scalars(select(User).where(User.role.in_(['RECTOR','DEAN','MAINTENANCE_STAFF']),User.active.is_(True)).order_by(User.name).limit(1000)).all()
    rooms=db.scalars(select(Room).order_by(Room.building,Room.number).limit(1500)).all()
    return page(request,db,'admin.html',hostels=hostels,users=users,staff_users=staff_users,
        rooms=rooms,user_search=user_search, hostel_by_id={h.id:h for h in hostels},
        admin_audit=db.scalars(select(AdminAudit).order_by(AdminAudit.at.desc()).limit(20)).all())


@app.post('/admin/hostels')
async def add_hostel(request:Request,db:DBSession=Depends(db_session)):
    actor=who(request,db,'SYSTEM_ADMIN');form=await request.form();require_csrf(request,form)
    code=str(form.get('code','')).strip().upper();name=str(form.get('name','')).strip()
    emergency_phone=str(form.get('emergency_phone','')).strip() or None
    if not re.fullmatch(r'[A-Z0-9_-]{2,24}',code) or len(name)<3 or len(name)>150 or (emergency_phone and not re.fullmatch(r'[+()\d .\-]{7,30}',emergency_phone)):
        return go('/dashboard','Hostel code must be 2–24 letters/numbers; name 3–150 characters.','error')
    if db.scalar(select(Hostel).where(Hostel.code==code)):
        return go('/dashboard','Hostel code already exists.','error')
    new_hostel=Hostel(code=code,name=name,emergency_phone=emergency_phone);db.add(new_hostel);db.flush()
    admin_audit(db,actor,'CREATE_HOSTEL','Hostel',new_hostel.id,f'{code}: {name}')
    db.commit()
    return go('/dashboard','Hostel '+name+' created.')


@app.post('/admin/hostels/{hid}/toggle')
async def toggle_hostel(request:Request,hid:str,db:DBSession=Depends(db_session)):
    actor=who(request,db,'SYSTEM_ADMIN');form=await request.form();require_csrf(request,form)
    h=db.get(Hostel,hid)
    if not h:raise HTTPException(404,'Hostel not found')
    if h.active:
        open_count=db.scalar(select(func.count(Complaint.id)).where(Complaint.hostel_id==hid,Complaint.status.in_(OPEN_STATES))) or 0
        if open_count:return go('/dashboard',f'Cannot archive: {open_count} open complaints. Resolve/transfer them first.','error')
        occupants=db.scalar(select(func.count(Allocation.id)).join(Room,Room.id==Allocation.room_id).where(Room.hostel_id==hid,Allocation.active.is_(True))) or 0
        if occupants:return go('/dashboard',f'Cannot archive: {occupants} students still have active room allocations. Transfer them first.','error')
        h.active=False;message='Hostel archived. Historical data retained.'
    else:
        h.active=True;message='Hostel reactivated.'
    admin_audit(db,actor,'RESTORE_HOSTEL' if h.active else 'ARCHIVE_HOSTEL','Hostel',h.id,h.name)
    db.commit();return go('/dashboard',message)


@app.post('/admin/hostels/{hid}/delete')
async def delete_hostel(request:Request,hid:str,db:DBSession=Depends(db_session)):
    actor=who(request,db,'SYSTEM_ADMIN');form=await request.form();require_csrf(request,form)
    h=db.get(Hostel,hid)
    if not h:raise HTTPException(404,'Hostel not found')
    for table,col in ((Room,Room.hostel_id),(Complaint,Complaint.hostel_id),(Scope,Scope.hostel_id)):
        if db.scalar(select(func.count()).select_from(table).where(col==hid)):
            return go('/dashboard','Hostel has related data. Archive it instead; deleting would destroy relationships.','error')
    admin_audit(db,actor,'DELETE_UNUSED_HOSTEL','Hostel',h.id,h.name)
    db.delete(h);db.commit();return go('/dashboard','Unused hostel permanently deleted.')



@app.post('/admin/hostels/{hid}/emergency-contact')
async def change_emergency_contact(request:Request,hid:str,db:DBSession=Depends(db_session)):
    actor=who(request,db,'SYSTEM_ADMIN');form=await request.form();require_csrf(request,form)
    h=db.get(Hostel,hid)
    if not h:raise HTTPException(404,'Hostel not found')
    phone=str(form.get('emergency_phone','')).strip() or None
    if phone and not re.fullmatch(r'[+()\d .\-]{7,30}',phone):
        return go('/dashboard','Enter a valid hostel emergency contact phone.','error')
    h.emergency_phone=phone
    admin_audit(db,actor,'UPDATE_EMERGENCY_CONTACT','Hostel',hid,'Number configured' if phone else 'Number cleared')
    db.commit()
    return go('/dashboard','Emergency contact updated.')

@app.post('/admin/rooms')
async def add_room(request:Request,db:DBSession=Depends(db_session)):
    actor=who(request,db,'SYSTEM_ADMIN');form=await request.form();require_csrf(request,form)
    hid=str(form.get('hostel_id',''));h=db.get(Hostel,hid)
    number=str(form.get('number','')).strip().upper();building=str(form.get('building','Main')).strip();floor=str(form.get('floor','0')).strip()
    try:capacity=int(form.get('capacity','2'))
    except:capacity=-1
    if not h or not h.active or not number or len(number)>30 or not building or len(building)>80 or not 1<=capacity<=20:
        return go('/dashboard','Provide an active hostel and valid room information.','error')
    if db.scalar(select(Room).where(Room.hostel_id==hid,Room.building==building,Room.number==number)):
        return go('/dashboard','Room already exists in this hostel/building.','error')
    new_room=Room(hostel_id=hid,building=building,floor=floor,number=number,capacity=capacity);db.add(new_room);db.flush()
    admin_audit(db,actor,'CREATE_ROOM','Room',new_room.id,f'Hostel {hid}, {building} {number}')
    db.commit()
    return go('/dashboard','Room added.')


@app.post('/admin/users')
async def add_user(request:Request,db:DBSession=Depends(db_session)):
    actor=who(request,db,'SYSTEM_ADMIN');form=await request.form();require_csrf(request,form)
    role=str(form.get('role',''));login=normalize_login(str(form.get('login_id','')));name=str(form.get('name','')).strip()
    email=str(form.get('email','')).strip().lower() or None
    if role not in ROLES or not re.fullmatch(r'[A-Z0-9_./-]{4,60}',login) or len(name)<2 or len(name)>150:
        return go('/dashboard','Provide a valid login ID (URN), name and role.','error')
    if db.scalar(select(User).where(User.login_id==login)):
        return go('/dashboard','This login ID / URN is already registered.','error')
    if email and (len(email)>200 or '@' not in email):return go('/dashboard','Invalid email address.','error')
    pwd=temp_password()
    user=User(login_id=login,urn=login if role=='STUDENT' else None,name=name,email=email,
        role=role,password_hash=ph.hash(pwd),force_password_change=True)
    db.add(user);db.flush()
    admin_audit(db,actor,'CREATE_USER','User',user.id,f'{login} ({role})')
    db.commit()
    return page(request,db,'credentials.html',new_credentials=[(login,name,pwd)],single=True)


@app.post('/admin/users/import')
async def import_students(request:Request,db:DBSession=Depends(db_session)):
    actor=who(request,db,'SYSTEM_ADMIN');form=await request.form();require_csrf(request,form)
    csv_text=str(form.get('csv_text',''))
    if len(csv_text)>180000:return go('/dashboard','CSV exceeds limit. Import in smaller batches.','error')
    rdr=csv.DictReader(io.StringIO(csv_text))
    if not rdr.fieldnames or not {'urn','name'}.issubset({f.strip().lower() for f in rdr.fieldnames}):
        return go('/dashboard','CSV headers must include urn,name and optional email.','error')
    new_credentials=[];duplicates=[]
    for index,row in enumerate(rdr):
        if index>=250:return go('/dashboard','Import at most 250 students per batch.','error')
        row={k.strip().lower():str(v or '').strip() for k,v in row.items() if k}
        login=normalize_login(row.get('urn',''));name=row.get('name','');email=row.get('email','').lower() or None
        if not re.fullmatch(r'[A-Z0-9_./-]{4,60}',login) or len(name)<2 or (email and '@' not in email):
            db.rollback();return go('/dashboard',f'Invalid student data on line {index+2}. Nothing imported.','error')
        if db.scalar(select(User.id).where(User.login_id==login)) or any(c[0]==login for c in new_credentials):
            duplicates.append(login);continue
        pwd=temp_password();db.add(User(login_id=login,urn=login,name=name,email=email,role='STUDENT',password_hash=ph.hash(pwd)))
        new_credentials.append((login,name,pwd))
    admin_audit(db,actor,'BULK_IMPORT_STUDENTS','User','BATCH',f'Created {len(new_credentials)}; skipped {len(duplicates)} duplicates')
    db.commit()
    return page(request,db,'credentials.html',new_credentials=new_credentials,duplicates=duplicates,single=False)


@app.post('/admin/users/{uid}/toggle')
async def toggle_user(request:Request,uid:str,db:DBSession=Depends(db_session)):
    admin=who(request,db,'SYSTEM_ADMIN');form=await request.form();require_csrf(request,form)
    u=db.get(User,uid)
    if not u:raise HTTPException(404,'Account not found')
    if u.id==admin.id:return go('/dashboard','You cannot deactivate your own admin account.','error')
    u.active=not u.active
    admin_audit(db,admin,'ENABLE_USER' if u.active else 'DISABLE_USER','User',u.id,u.login_id)
    if not u.active:
        for s in db.scalars(select(Session).where(Session.user_id==u.id,Session.revoked_at.is_(None))):s.revoked_at=utcnow()
    db.commit();return go('/dashboard','Account status updated.')


@app.post('/admin/users/{uid}/reset')
async def reset_user(request:Request,uid:str,db:DBSession=Depends(db_session)):
    admin=who(request,db,'SYSTEM_ADMIN');form=await request.form();require_csrf(request,form)
    u=db.get(User,uid)
    if not u:raise HTTPException(404,'Account not found')
    if u.id==admin.id:return go('/dashboard','Use Change Password to update your own account.','error')
    pwd=temp_password();u.password_hash=ph.hash(pwd);u.force_password_change=True
    admin_audit(db,admin,'RESET_TEMP_PASSWORD','User',u.id,u.login_id)
    for s in db.scalars(select(Session).where(Session.user_id==u.id,Session.revoked_at.is_(None))):s.revoked_at=utcnow()
    db.commit();return page(request,db,'credentials.html',new_credentials=[(u.login_id,u.name,pwd)],single=True)


@app.post('/admin/scopes')
async def add_scope(request:Request,db:DBSession=Depends(db_session)):
    actor=who(request,db,'SYSTEM_ADMIN');form=await request.form();require_csrf(request,form)
    user=db.get(User,str(form.get('user_id','')));h=db.get(Hostel,str(form.get('hostel_id','')))
    if not user or user.role not in ('RECTOR','DEAN','MAINTENANCE_STAFF') or not h or not h.active:
        return go('/dashboard','Choose a valid staff member and active hostel.','error')
    if not db.scalar(select(Scope).where(Scope.user_id==user.id,Scope.hostel_id==h.id)):
        db.add(Scope(user_id=user.id,hostel_id=h.id))
        admin_audit(db,actor,'GRANT_HOSTEL_SCOPE','User',user.id,f'{user.role}: {h.code}')
        db.commit()
    return go('/dashboard',f'{user.name} authorized for {h.name}.')


@app.post('/admin/allocations')
async def add_allocation(request:Request,db:DBSession=Depends(db_session)):
    actor=who(request,db,'SYSTEM_ADMIN');form=await request.form();require_csrf(request,form)
    login=normalize_login(str(form.get('student_urn','')))
    student=db.scalar(select(User).where(User.login_id==login));room=db.get(Room,str(form.get('room_id','')))
    if not student or student.role!='STUDENT' or not student.active or not room or not room.active or not db.get(Hostel,room.hostel_id).active:
        return go('/dashboard','Select an active student and room.','error')
    occupied=db.scalar(select(func.count(Allocation.id)).where(Allocation.room_id==room.id,Allocation.active.is_(True))) or 0
    old=db.scalar(select(Allocation).where(Allocation.student_id==student.id,Allocation.active.is_(True)))
    if occupied >= room.capacity and (not old or old.room_id!=room.id):
        return go('/dashboard','Room is at full capacity.','error')
    if old and old.room_id==room.id:return go('/dashboard','Student is already allocated to this room.','error')
    if old:old.active=False;old.ended_at=utcnow()
    db.add(Allocation(student_id=student.id,room_id=room.id))
    admin_audit(db,actor,'ALLOCATE_ROOM','Student',student.id,f'{student.login_id} -> {room.building}/{room.number}')
    db.commit()
    return go('/dashboard',f'{student.name} assigned to room {room.number}.')

# React SPA adapter: only JSON read endpoints and exact calls into existing workflow handlers.
# The original server-rendered routes continue to work unchanged.
from .react_api import router as react_router
app.include_router(react_router)
