"""Export chart views from a preserved, completed example; never runs the model."""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import charts

folder=ROOT/'examples/20261020_194910_441553a8'
if not folder.is_dir():
    raise SystemExit('The independently completed historical example is missing.')
summary=json.loads((folder/'summary.json').read_text(encoding='utf-8-sig'))
if not summary['passed']:
    raise SystemExit('Preview requires a completed numerical-QA-passed example.')
out=ROOT/'qa/chart_previews'
out.mkdir(exist_ok=True)
rain,total,meta=charts.rainfall_html(summary['request'])
for name,html in [('rain',rain),('history',charts.history_html(folder)),('budget',charts.budget_html(summary))]:
    (out/(name+'.html')).write_text(html,encoding='utf-8')
print(json.dumps({'output':'qa/chart_previews','example':folder.name,'district_rain_mm':total}))
