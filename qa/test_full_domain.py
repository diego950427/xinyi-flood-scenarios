"""Run the actual full 20m domain; no downsampling or saved-result substitution."""
from pathlib import Path
import json
import os
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
os.environ['XINYI_STATE_DIR'] = str(ROOT / '.runtime' / 'full_domain')
sys.path.insert(0, str(ROOT))
import backend as b

historical = '--historical' in sys.argv
req = dict(mode='historical' if historical else 'custom', event_id='H20240710',
           total_mm=10, duration_min=10, recession_min=60 if historical else 0,
           drain_mm_h=30, storage_mm=20, inlet_area_m2=.2, infiltration_mm_h=0,
           rain_shape='uniform', exchange_cap_s=1)
rid = 'qa_' + ('historical_' if historical else 'custom_') + uuid.uuid4().hex[:12]
folder = b.run_folder(rid)
folder.mkdir(parents=True)
b.json_save(folder/'request.json', b.validate_request(req))
b.json_save(folder/'status.json', {'state':'queued','message':'actual full-domain acceptance'})
started = time.time()
b.execute_job(rid)
status = b.status_of(rid)
summary = b.json_read(folder/'summary.json') if (folder/'summary.json').exists() else {}
report = {'passed':status['state']=='completed' and summary.get('passed',False),
          'status':status, 'summary':summary, 'wall_seconds':time.time()-started,
          'platform':sys.platform, 'run_id':rid,
          'grid':'89394 active 20m cells; 28097 Xinyi reporting cells',
          'source':'new computation by current code, not a precomputed example',
          'outputs':{p.name:b.sha(p) for p in folder.iterdir() if p.is_file() and p.name not in ['worker.log']}}
b.json_save(ROOT/'qa'/('full_domain_historical.json' if historical else 'full_domain_custom.json'),report)
print(json.dumps({'passed':report['passed'],'wall_seconds':report['wall_seconds'],'state':status['state']},ensure_ascii=False))
assert report['passed']
