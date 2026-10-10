"""Exercises role workflow through React adapter, not the legacy HTML forms."""
import tempfile,os
from pathlib import Path
root=Path(tempfile.mkdtemp(prefix='hcms_workflow_'))
os.environ['DATABASE_URL']='sqlite:///'+str(root/'workflow.sqlite3')
os.environ['UPLOAD_DIR']=str(root/'upload')
os.environ['SESSION_SECRET']='long_secret_for_smoke_test_1234567890123456789'
from app.main import app
from app.core import SessionLocal,init_db,ph
from app.models import User,Hostel,Room,Complaint
from fastapi.testclient import TestClient
from sqlalchemy import select
init_db()
with SessionLocal() as db:
    db.add(User(login_id='WORKADMIN',name='Admin',role='SYSTEM_ADMIN',password_hash=ph.hash('AdminPassword123'),force_password_change=False))
    db.commit()

def client_login(uid,pwd):
    c=TestClient(app)
    csrf=c.get('/api/session').json()['csrf']
    r=c.post('/api/action/login',data={'csrf_token':csrf,'login_id':uid,'password':pwd})
    assert r.status_code==200,(uid,r.text)
    return c

def act(c,path,fields=None):
    csrf=c.get('/api/session').json()['csrf']
    r=c.post('/api/action/'+path,data={'csrf_token':csrf,**(fields or {})})
    assert r.status_code==200,(path,r.status_code,r.text)
    return r.json()

admin=client_login('WORKADMIN','AdminPassword123')
act(admin,'admin/hostels',{'code':'HAA','name':'Hostel A'})
with SessionLocal() as db:hid=db.scalar(select(Hostel.id))
act(admin,'admin/rooms',{'hostel_id':hid,'building':'Main','number':'101','floor':'1','capacity':'2'})
with SessionLocal() as db:rid=db.scalar(select(Room.id))
accounts={}
for lid,role in [('TESTSTUDENT','STUDENT'),('TESTRECTOR','RECTOR'),('TESTWORKER','MAINTENANCE_STAFF'),('TESTDEAN','DEAN')]:
    r=act(admin,'admin/users',{'login_id':lid,'name':'Test '+role.title().replace('_',' '),'role':role})
    accounts[lid]=r['credentials'][0][2]
with SessionLocal() as db:
    ids={u.login_id:u.id for u in db.scalars(select(User)).all()}
for lid in ('TESTRECTOR','TESTWORKER','TESTDEAN'):
    act(admin,'admin/scopes',{'user_id':ids[lid],'hostel_id':hid})
act(admin,'admin/allocations',{'student_urn':'TESTSTUDENT','room_id':rid})
clients={}
for lid,pwd in accounts.items():
    c=client_login(lid,pwd)
    act(c,'profile/password',{'old_password':pwd,'new_password':'NewPassword12345','confirm_password':'NewPassword12345'})
    clients[lid]=c
student=clients['TESTSTUDENT'];rector=clients['TESTRECTOR'];worker=clients['TESTWORKER'];dean=clients['TESTDEAN']
view=student.get('/api/data?view=new');assert view.status_code==200,view.text
r=act(student,'student/new',{'idempotency_key':view.json()['idempotency_key'], 'description':'Dormitory ceiling fan has stopped working','category':'ELECTRICAL','priority':'NORMAL'})
with SessionLocal() as db:cid=db.scalar(select(Complaint.id))
assert student.get('/api/data?view=complaint&id='+cid).status_code==200
assert dean.get('/api/data?view=complaint&id='+cid).status_code==404
assert rector.get('/api/data?view=complaint&id='+cid).status_code==200
act(rector,f'rector/complaints/{cid}/action',{'action':'assign','staff_id':ids['TESTWORKER']})
act(worker,f'staff/complaints/{cid}/action',{'action':'accept'})
act(worker,f'staff/complaints/{cid}/action',{'action':'start','note':'Investigated ceiling fan failure'})
act(worker,f'staff/complaints/{cid}/action',{'action':'complete','note':'Replaced capacitor and tested fan'})
act(student,f'student/complaints/{cid}/verify',{'action':'confirm','rating':'5','comment':'Working now'})
with SessionLocal() as db:assert db.get(Complaint,cid).status=='CLOSED'
print('PASS: Student create -> Rector assign -> Worker accept/start/complete -> Student confirm; Dean scope enforced')
