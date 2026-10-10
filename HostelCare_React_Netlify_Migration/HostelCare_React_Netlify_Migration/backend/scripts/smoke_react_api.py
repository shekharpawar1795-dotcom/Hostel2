"""Self-contained smoke test of React JSON adapter and legacy workflow delegation."""
import tempfile, os
from pathlib import Path
sandbox=Path(tempfile.mkdtemp(prefix='hostelcare_react_smoke_'))
os.environ['DATABASE_URL']='sqlite:///'+str(sandbox/'test.sqlite3')
os.environ['UPLOAD_DIR']=str(sandbox/'uploads')
os.environ['SESSION_SECRET']='this_is_a_test_secret_not_for_real_use_1234567890'
from fastapi.testclient import TestClient
from app.main import app
from app.core import init_db, SessionLocal, ph
from app.models import User, Hostel
from sqlalchemy import select

init_db()
with SessionLocal() as db:
    db.add(User(login_id='TESTADMIN',name='React API Admin',role='SYSTEM_ADMIN',
                password_hash=ph.hash('TestPassSecure123'),force_password_change=False))
    db.commit()

with TestClient(app) as client:
    sess=client.get('/api/session')
    assert sess.status_code==200,sess.text
    assert sess.json()['user'] is None
    csrf=sess.json()['csrf']
    invalid=client.post('/api/action/login',data={'csrf_token':csrf,'login_id':'TESTADMIN','password':'wrong'})
    assert invalid.status_code==422,invalid.text
    csrf=client.get('/api/session').json()['csrf']
    logged=client.post('/api/action/login',data={'csrf_token':csrf,'login_id':'TESTADMIN','password':'TestPassSecure123'})
    assert logged.status_code==200,logged.text
    assert logged.json()['next']=='/dashboard'
    sess=client.get('/api/session').json()
    assert sess['user']['role']=='SYSTEM_ADMIN',sess
    assert 'password_hash' not in sess['user']
    csrf=sess['csrf']
    dashboard=client.get('/api/data?view=dashboard')
    assert dashboard.status_code==200,dashboard.text
    assert dashboard.json()['hostels']==[]
    added=client.post('/api/action/admin/hostels',data={'csrf_token':csrf,'code':'HAA','name':'Hostel A'})
    assert added.status_code==200,added.text
    dbstate=client.get('/api/data?view=dashboard')
    assert dbstate.json()['hostels'][0]['name']=='Hostel A',dbstate.text
    assert 'password_hash' not in dbstate.text
    new_student=client.post('/api/action/admin/users',data={'csrf_token':csrf,'role':'STUDENT','login_id':'TESTURN0001','name':'Test Student'})
    assert new_student.status_code==200,new_student.text
    assert len(new_student.json()['credentials'])==1
    student_password=new_student.json()['credentials'][0][2]
    other=TestClient(app)
    session2=other.get('/api/session').json()
    s_login=other.post('/api/action/login',data={'csrf_token':session2['csrf'],'login_id':'TESTURN0001','password':student_password})
    assert s_login.status_code==200,s_login.text
    assert s_login.json()['next']=='/profile/password'
    assert other.get('/api/data?view=dashboard').status_code==428
    assert other.get('/api/data?view=password').status_code==200
    print('PASS: React API login, secure session, admin state, delegated forms, credentials, forced password change')
