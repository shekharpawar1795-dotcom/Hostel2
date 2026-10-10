"""Run as separate continuous process; also supports --once for external cron."""
import time,sys,logging,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app.core import SessionLocal, init_db, process_due, deliver_email_batch
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')

def tick():
    with SessionLocal() as db:
        stats=process_due(db)
        sent=deliver_email_batch(db)
        logging.info('Reconciliation: %s; emails sent: %d',stats,sent)

if __name__=='__main__':
    init_db()
    if '--once' in sys.argv:
        tick();sys.exit(0)
    while True:
        try:tick()
        except Exception:logging.exception('Worker tick failed (will retry)')
        time.sleep(int(os.getenv('WORKER_INTERVAL_SECONDS','300')))
