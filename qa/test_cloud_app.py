"""App inputs and cross-session isolation; native computation is tested separately."""
from pathlib import Path
import json
import os
import sys
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
os.environ['XINYI_STATE_DIR'] = str(ROOT / '.runtime' / ('ui_' + uuid.uuid4().hex[:8]))
sys.path.insert(0, str(ROOT))
import backend as b
from streamlit.testing.v1 import AppTest

checks = {}
own, stranger = 'a' * 40, 'b' * 40
rid = 'test_owned'
folder = b.run_folder(rid)
folder.mkdir(parents=True)
b.json_save(folder / 'owner.json', {'owner': b.owner_key(own)})
b.json_save(folder / 'status.json', {'state':'cancelled','message':'synthetic fixture'})
checks['stranger_cannot_list_results'] = b.visible_runs(stranger) == []
checks['owner_can_list_result'] = folder in b.visible_runs(own)
try:
    b.cancel_job(rid, stranger)
    checks['stranger_cannot_cancel'] = False
except ValueError:
    checks['stranger_cannot_cancel'] = True
checks['path_traversal_rejected'] = True
for invalid in ['../x', 'a/b', '..', 'C:\\x', '']:
    try:
        b.run_folder(invalid)
        checks['path_traversal_rejected'] = False
    except ValueError:
        pass

at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=60).run()
checks['initial_renders'] = len(at.exception) == 0
checks['history_default'] = at.radio(key='mode').value == '歷史大雨事件'
checks['local_nine_station_default'] = at.selectbox(key='event_id').value == 'H20240710'
checks['four_events'] = len(at.selectbox(key='event_id').options) == 4
checks['accepted_examples_visible'] = len(at.selectbox(key='result_picker').options) >= 2
checks['simple_navigation_and_no_subheadings'] = ([t.label for t in at.tabs] == ['開始試算', '使用說明']
                                                and len(at.subheader) == 0)
checks['guide_available'] = any('60 mm' in m.value and 'result.qgs' in m.value for m in at.markdown)
original_result = at.selectbox(key='result_picker').value
at.radio(key='mode').set_value('自己輸入雨量').run()
at.number_input(key='rain_total').set_value(300.0)
at.number_input(key='rain_duration').set_value(10).run()
checks['excessive_intensity_disables_submit'] = at.button(key='start_run').disabled
at.number_input(key='rain_total').set_value(10.0).run()
checks['valid_custom_enables_submit'] = not at.button(key='start_run').disabled
checks['custom_renders'] = len(at.exception) == 0
checks['new_inputs_do_not_relabel_old_example'] = (at.selectbox(key='result_picker').value == original_result
    and any('目前顯示：先前本機範例' in e.value for e in at.success)
    and any('降雨 **360 分鐘**' in m.value and '雨後觀察 **60 分鐘**' in m.value for m in at.markdown))
# Unit tests never pretend a mocked submission is native solver evidence.
with patch('backend.start_job', side_effect=RuntimeError('TEST_BUSY')):
    at.button(key='start_run').click().run()
    checks['busy_error_visible'] = any('TEST_BUSY' in e.value for e in at.error)
checks['no_uncaught_ui_errors'] = len(at.exception) == 0
out = {'passed': all(checks.values()), 'checks': checks,
       'scope':'UI/input/isolation only; no solver completion claim.'}
b.json_save(ROOT / 'qa' / 'cloud_app_tests.json', out)
print(json.dumps(out, ensure_ascii=False, indent=2))
assert out['passed']
