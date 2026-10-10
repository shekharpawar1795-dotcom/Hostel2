"""End-to-end behavior tests on a real temporary SQLite database + FastAPI HTTP layer."""
import os, tempfile, re, io
from datetime import timedelta
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
TEST_ROOT=Path(tempfile.mkdtemp(prefix='hcms_test_'))
os.environ['DATABASE_URL']='sqlite:///'+str(TEST_ROOT/'test.sqlite3')
os.environ['UPLOAD_DIR']=str(TEST_ROOT/'uploads')
os.environ['SESSION_SECRET']='unique_test_secret_long_1234567890'
from fastapi.testclient import TestClient
from bs4 import BeautifulSoup
from sqlalchemy import select, func
from app.main import app
from app.models import User, Hostel, Room, Complaint, WorkCycle, Escalation, Notification, Attachment
from app.core import SessionLocal, init_db, ph, utcnow, process_due, as_utc


def csrf_of(html):
    soup=BeautifulSoup(html,'html.parser')
    input_el=soup.select_one('input[name="csrf_token"]')
    assert input_el,html[:1000]
    return input_el['value']


def post(client,path,values=None,**kwargs):
    values=values or {}
    response=client.get('/dashboard') if path not in ('/login','/profile/password') else client.get(path)
    token=csrf_of(response.text)
    data={'csrf_token':token,**values}
    return client.post(path,data=data,follow_redirects=True,**kwargs)


def login(client,login_id,password):
    r=client.get('/login')
    r=client.post('/login',data={'csrf_token':csrf_of(r.text),'login_id':login_id,'password':password},follow_redirects=False)
    assert r.status_code==303, r.text
    return r


def admin_user(client,role,login_id,name):
    r=post(client,'/admin/users',{'role':role,'login_id':login_id,'name':name})
    assert r.status_code==200
    pwd=BeautifulSoup(r.text,'html.parser').select_one('td code')
    assert pwd, r.text[:500]
    return pwd.text


def getid(cls,**where):
    with SessionLocal() as db:
        return db.scalar(select(cls).filter_by(**where)).id


def test_all_five_roles_multi_hostel_urn_security_and_deadlines():
    init_db()
    with SessionLocal() as db:
        db.add(User(login_id='BOOTADMIN',name='Admin',role='SYSTEM_ADMIN',password_hash=ph.hash('StartAdmin12345'),force_password_change=False))
        db.commit()
    admin=TestClient(app)
    assert login(admin,'BOOTADMIN','StartAdmin12345').headers['location']=='/dashboard'
    for code,name in [('HA','Hostel A'),('HB','Hostel B'),('HC','Unused Hostel')]:
        r=post(admin,'/admin/hostels',{'code':code,'name':name}); assert r.status_code==200,name
    h1=getid(Hostel,code='HA');h2=getid(Hostel,code='HB');h3=getid(Hostel,code='HC')
    for h,room in [(h1,'204'),(h2,'105')]:
        r=post(admin,'/admin/rooms',{'hostel_id':h,'building':'Main','floor':'2','number':room,'capacity':'2'})
        assert 'Room added' in r.text
    room1=getid(Room,hostel_id=h1);room2=getid(Room,hostel_id=h2)
    passwords={}
    for role,lid,name in [
        ('STUDENT','2026CS001','Student One'),('STUDENT','2026CS002','Student Two'),
        ('RECTOR','RECTORA','Rector A'),('RECTOR','RECTORB','Rector B'),
        ('MAINTENANCE_STAFF','ELEC001','Electrician'),('DEAN','DEAN001','Dean One')]:
        passwords[lid]=admin_user(admin,role,lid,name)
    assert passwords['2026CS001']!=passwords['2026CS002']
    for login_id,h in [('RECTORA',h1),('RECTORB',h2),('ELEC001',h1),('DEAN001',h1)]:
        assert 'authorized' in post(admin,'/admin/scopes',{'user_id':getid(User,login_id=login_id),'hostel_id':h}).text
    for u,room in [('2026CS001',room1),('2026CS002',room2)]:
        assert 'assigned to room' in post(admin,'/admin/allocations',{'student_urn':u,'room_id':room}).text

    # Only unused hostels may be hard-deleted; historic hostels must be archived instead.
    assert 'permanently deleted' in post(admin,f'/admin/hostels/{h3}/delete').text
    assert 'Archive it instead' in post(admin,f'/admin/hostels/{h1}/delete').text

    student=TestClient(app)
    assert login(student,'2026CS001',passwords['2026CS001']).headers['location']=='/profile/password'
    r=student.get('/dashboard',follow_redirects=False)
    assert r.status_code==303 and r.headers['location'].startswith('/profile/password')
    new_pwd='StudentSecureSecret123'
    r=post(student,'/profile/password',{'old_password':passwords['2026CS001'],'new_password':new_pwd,'confirm_password':new_pwd})
    assert 'Password updated successfully' in r.text, r.text[-2200:]
    r=post(student,'/profile',{'preferred_name':'Sam','phone':'+91 9876543210'})
    assert 'Profile updated' in r.text
    with SessionLocal() as db:
        u=db.scalar(select(User).where(User.login_id=='2026CS001'))
        assert u.preferred_name=='Sam' and u.login_id=='2026CS001' and not u.force_password_change

    r=student.get('/student/new')
    assert 'Hostel A' in r.text and '204' in r.text
    key=BeautifulSoup(r.text,'html.parser').select_one('input[name=idempotency_key]')['value']
    img=Image.new('RGB',(100,100),(30,150,150));data=io.BytesIO();img.save(data,format='JPEG')
    files={'photos':('ceiling.jpg',data.getvalue(),'image/jpeg')}
    r=student.post('/student/new', data={
        'csrf_token':csrf_of(r.text),'idempotency_key':key,'category':'OTHER',
        'priority':'NORMAL','description':'Ceiling fan is not working properly.'},files=files,follow_redirects=True)
    assert 'Complaint registered' in r.text
    with SessionLocal() as db:
        c=db.scalar(select(Complaint).where(Complaint.student_id==getid(User,login_id='2026CS001')))
        cid=c.id
        assert c.status=='SUBMITTED' and c.description.startswith('Ceiling fan')
    with SessionLocal() as db:
        pic=db.scalar(select(Attachment).where(Attachment.complaint_id==cid))
        assert pic is not None
        photo_id=pic.id
    assert student.get('/photos/'+photo_id).status_code==200
    # Student 2 cannot view another student's complaint or private photo.
    other=TestClient(app)
    login(other,'2026CS002',passwords['2026CS002'])
    assert other.get('/complaints/'+cid,follow_redirects=False).status_code==303  # forced password change
    post(other,'/profile/password',{'old_password':passwords['2026CS002'],'new_password':'AnotherStudent123','confirm_password':'AnotherStudent123'})
    assert other.get('/complaints/'+cid).status_code==404
    assert other.get('/photos/'+photo_id).status_code==404
    # Rector assigned to Hostel B also cannot view.
    rector_b=TestClient(app)
    login(rector_b,'RECTORB',passwords['RECTORB'])
    post(rector_b,'/profile/password',{'old_password':passwords['RECTORB'],'new_password':'RectorBsecure123','confirm_password':'RectorBsecure123'})
    assert rector_b.get('/complaints/'+cid).status_code==404

    rector=TestClient(app)
    login(rector,'RECTORA',passwords['RECTORA'])
    post(rector,'/profile/password',{'old_password':passwords['RECTORA'],'new_password':'RectorSecure123','confirm_password':'RectorSecure123'})
    r=post(rector,f'/rector/complaints/{cid}/action',{'action':'assign','staff_id':getid(User,login_id='ELEC001'),'reason':'Repair ceiling fan'})
    assert 'Action saved' in r.text
    with SessionLocal() as db:assert db.get(Complaint,cid).status=='ASSIGNED'
    staff=TestClient(app)
    login(staff,'ELEC001',passwords['ELEC001'])
    post(staff,'/profile/password',{'old_password':passwords['ELEC001'],'new_password':'WorkerSecure123','confirm_password':'WorkerSecure123'})
    assert 'Maintenance Staff' in staff.get('/dashboard').text or 'Maintenance tasks' in staff.get('/dashboard').text
    post(staff,f'/staff/complaints/{cid}/action',{'action':'accept','note':''})
    post(staff,f'/staff/complaints/{cid}/action',{'action':'start','note':'Checked fan wiring and switch'})
    with SessionLocal() as db:
        c=db.get(Complaint,cid)
        assert c.status=='IN_PROGRESS' and c.work_started_at is not None
    post(staff,f'/staff/complaints/{cid}/action',{'action':'complete','note':'Replaced faulty capacitor and tested fan'})
    assert 'Awaiting Confirmation' in student.get('/complaints/'+cid).text
    r=post(student,f'/student/complaints/{cid}/verify',{'action':'confirm','rating':'5','comment':'Fixed, thanks'})
    with SessionLocal() as db:assert db.get(Complaint,cid).status=='CLOSED'

    # Second complaint: Rector assigns but staff never starts; must escalate to Dean at 48h.
    create=student.get('/student/new')
    r=student.post('/student/new', data={'csrf_token':csrf_of(create.text),
        'idempotency_key':BeautifulSoup(create.text,'html.parser').select_one('input[name=idempotency_key]')['value'],
        'category':'PLUMBING','priority':'NORMAL','description':'Bathroom tap is continuously leaking'}, follow_redirects=True)
    with SessionLocal() as db:
        c=db.scalar(select(Complaint).where(Complaint.description.like('Bathroom tap%')))
        second=c.id
    post(rector,f'/rector/complaints/{second}/action',{'action':'assign','staff_id':getid(User,login_id='ELEC001'),'reason':'Check tap'})
    with SessionLocal() as db:
        cy=db.scalar(select(WorkCycle).where(WorkCycle.complaint_id==second))
        outcome=process_due(db,now=as_utc(cy.started_at)+timedelta(hours=48,minutes=5))
        assert outcome['escalated']==1, outcome
        assert db.scalar(select(func.count(Escalation.id)).where(Escalation.complaint_id==second))==1
        assert db.get(Complaint,second).status=='ASSIGNED' # escalation does not overwrite repair state
        again=process_due(db,now=as_utc(cy.started_at)+timedelta(hours=49))
        assert again['escalated']==0
    dean=TestClient(app)
    login(dean,'DEAN001',passwords['DEAN001'])
    post(dean,'/profile/password',{'old_password':passwords['DEAN001'],'new_password':'DeanSecure1234','confirm_password':'DeanSecure1234'})
    assert 'Bathroom tap' in dean.get('/dashboard').text
    assert 'directive' in dean.get('/complaints/'+second).text.lower()
    r=post(dean,f'/dean/complaints/{second}/directive',{'directive':'Please arrange urgent technician attendance and explain delay.'})
    assert 'Directive recorded' in r.text

    # Start work late after the deadline; historical Dean escalation must remain.
    post(staff,f'/staff/complaints/{second}/action',{'action':'accept'})
    post(staff,f'/staff/complaints/{second}/action',{'action':'start','note':'Started repairing the tap'})
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Escalation.id)).where(Escalation.complaint_id==second))==1

    # Third complaint: no student confirmation; auto-close after 48h and reopen in 7 days.
    create=student.get('/student/new')
    r=student.post('/student/new', data={'csrf_token':csrf_of(create.text),
        'idempotency_key':BeautifulSoup(create.text,'html.parser').select_one('input[name=idempotency_key]')['value'],
        'category':'FURNITURE','priority':'NORMAL','description':'Study desk hinge broken needs repair'},follow_redirects=True)
    with SessionLocal() as db:
        third=db.scalar(select(Complaint).where(Complaint.description.like('Study desk%'))).id
    post(rector,f'/rector/complaints/{third}/action',{'action':'assign','staff_id':getid(User,login_id='ELEC001')})
    post(staff,f'/staff/complaints/{third}/action',{'action':'accept'})
    post(staff,f'/staff/complaints/{third}/action',{'action':'start','note':'Started hinge repair'})
    post(staff,f'/staff/complaints/{third}/action',{'action':'complete','note':'Replaced hinge and checked desk'})
    with SessionLocal() as db:
        c=db.get(Complaint,third)
        now=as_utc(c.work_completed_at)+timedelta(hours=49)
        results=process_due(db,now=now)
        assert results['auto_closed']==1 and c.status=='AUTO_CLOSED'
    r=post(student,f'/student/complaints/{third}/verify',{'action':'reopen','reason':'Hinge became loose again'})
    with SessionLocal() as db:
        c=db.get(Complaint,third)
        assert c.status=='REOPENED' and c.cycle_number==2


def ensure_synthetic_context(db):
    init_db()
    student=db.scalar(select(User).where(User.login_id=='SYNTHSTU'))
    if student is None:
        student=User(login_id='SYNTHSTU',urn='SYNTHSTU',name='Synthetic Student',
                     role='STUDENT',password_hash=ph.hash('SyntheticSecure123'),force_password_change=False)
        db.add(student);db.flush()
    hostel=db.scalar(select(Hostel).where(Hostel.code=='SYNTHHOST'))
    if hostel is None:
        hostel=Hostel(code='SYNTHHOST',name='Synthetic Hostel')
        db.add(hostel);db.flush()
    room=db.scalar(select(Room).where(Room.hostel_id==hostel.id))
    if room is None:
        room=Room(hostel_id=hostel.id,building='Main',floor='1',number='S001')
        db.add(room);db.flush()
    return student,hostel,room


def test_worker_escalates_late_start_even_if_already_completed():
    """Repair starting at hour 49 still creates an escalation, even if later closed."""
    with SessionLocal() as db:
        s,h,room=ensure_synthetic_context(db)
        c=Complaint(number='HC-LATE-TEST',student_id=s.id,hostel_id=h.id,room_id=room.id,
            category='OTHER',effective_category='OTHER',description='A separate late-start test case',
            priority='NORMAL',effective_priority='NORMAL',status='CLOSED',idempotency_key='late-example-key')
        db.add(c);db.flush()
        start=utcnow()-timedelta(days=4)
        db.add(WorkCycle(complaint_id=c.id,number=1,started_at=start,work_started_at=start+timedelta(hours=49)))
        db.commit()
        outcome=process_due(db,now=utcnow())
        assert outcome['escalated']==1
        assert db.scalar(select(func.count(Escalation.id)).where(Escalation.complaint_id==c.id))==1
        assert db.get(Complaint,c.id).status=='CLOSED'
        again=process_due(db,now=utcnow());assert again['escalated']==0


def test_early_work_start_does_not_escalate():
    with SessionLocal() as db:
        s,h,room=ensure_synthetic_context(db)
        c=Complaint(number='HC-EARLY-TEST',student_id=s.id,hostel_id=h.id,room_id=room.id,
            category='OTHER',effective_category='OTHER',description='A separate early-start test case',
            priority='NORMAL',effective_priority='NORMAL',status='IN_PROGRESS',idempotency_key='early-example-key')
        db.add(c);db.flush()
        start=utcnow()-timedelta(days=3)
        db.add(WorkCycle(complaint_id=c.id,number=1,started_at=start,work_started_at=start+timedelta(hours=3)))
        db.commit()
        process_due(db,now=utcnow())
        assert db.scalar(select(func.count(Escalation.id)).where(Escalation.complaint_id==c.id))==0
