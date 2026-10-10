"""Create an initial System Admin. Prints a unique first-login password once."""
import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from sqlalchemy import select
from app.core import SessionLocal,init_db,ph,temp_password
from app.models import User

if __name__=='__main__':
    init_db()
    login=os.getenv('BOOTSTRAP_ADMIN_LOGIN','HCMSADMIN').strip().upper()
    name=os.getenv('BOOTSTRAP_ADMIN_NAME','System Administrator').strip()
    if not os.getenv('SESSION_SECRET'):
        print('WARNING: SESSION_SECRET should be set to a long random value before production.')
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.login_id==login)):
            print('Admin already exists; no new password issued.');sys.exit(0)
        if db.scalar(select(User).where(User.role=='SYSTEM_ADMIN')):
            print('An administrator already exists. Use that account for provisioning.');sys.exit(1)
        pwd=temp_password()
        db.add(User(login_id=login,name=name,role='SYSTEM_ADMIN',password_hash=ph.hash(pwd),force_password_change=True))
        db.commit()
    print('\nINITIAL ADMIN LOGIN:',login)
    print('ONE-TIME PASSWORD:  ',pwd)
    print('Store it privately. It will not be displayed again. Change it at first login.\n')
