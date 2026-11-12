"""Chart semantics and script-safety tests; does not claim browser visual QA."""
from pathlib import Path
import importlib.util
import json
import math
import re
import shutil
import subprocess
import sys
import unittest
from html.parser import HTMLParser
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import charts


class ChartTests(unittest.TestCase):
    def test_real_forcing_integral_and_endpoints(self):
        req = {"mode": "historical", "event_id": "H20240710", "recession_min": 60}
        data, total, meta = charts.rainfall_data(req)
        self.assertEqual(len(data["values"]) + 1, len(data["edges_s"]))
        self.assertEqual(data["edges_s"][-1], 25200)
        self.assertEqual(data["values"][-1], 0)
        self.assertEqual(meta["rain_end_s"], 21600)
        self.assertGreater(total, 0)
        import numpy as np
        from backend import load_grid, DATA
        _, _, report, _, _ = load_grid()
        a = np.load(DATA / "rain_20240710.npz")
        weights = np.bincount(a["station_index"][report], minlength=a["depths_mm"].shape[1])
        independently_weighted_mm = float(a["depths_mm"].sum(axis=0).dot(weights / weights.sum()))
        self.assertAlmostEqual(total, independently_weighted_mm, places=9)

    def test_custom_integral_and_zero(self):
        for rain in [0, 60]:
            data, total, _ = charts.rainfall_data({"mode":"custom", "total_mm":rain,
                "duration_min":60, "rain_shape":"middle_peak", "recession_min":30})
            self.assertAlmostEqual(total, rain, places=9)
            self.assertEqual(data["edges_s"][-1], 5400)

    def test_html_safely_escapes_source_labels(self):
        attack = '</script><img src=x onerror="alert(1)">'
        out = charts._document('rain', attack, attack, attack, attack,
                               {'label':attack,'values':[1],'edges_s':[0,60]})
        self.assertNotIn('<img src=x', out)
        self.assertIn('\\u003c/script\\u003e', out)
        class Resources(HTMLParser):
            external=[]
            scripts=0
            def handle_starttag(self, tag, attrs):
                attrs=dict(attrs)
                if tag=='script': self.scripts+=1
                if (tag=='script' and 'src' in attrs) or tag=='link':
                    self.external.append((tag,attrs))
        parsed=Resources();parsed.feed(out)
        self.assertEqual(parsed.external,[])
        self.assertEqual(parsed.scripts,3)

    def test_missing_or_nonfinite_rejected(self):
        for values in [[], [float('nan')], [float('inf')], [-1]]:
            with self.assertRaises(ValueError):
                charts._finite(values, 'test')

    def test_history_keeps_instantaneous_not_ever(self):
        # Synthetic fixture expressly tests a falling series, not a research result.
        with TemporaryDirectory(dir=ROOT / 'qa') as name:
            folder = Path(name); (folder / 'native').mkdir()
            (folder / 'native/history.csv').write_text(
                'time_s,xinyi_area_gt10_km2\n0,0\n60,2\n120,1\n', encoding='utf-8')
            self.assertEqual(charts.history_data(folder)['values'], [0,2,1])
            out=charts.history_html(folder)
            self.assertIn('當時超過',out)
            self.assertIn('這條線可以下降',out)

    def test_budget_does_not_hide_residual_or_initial_storage(self):
        b=dict(initial_surface_m3=10,initial_native_m3=20,rain_m3=100,
               infiltration_m3=5,boundary_out_m3=40,drain_m3=30,
               surface_stored_m3=45,native_stored_m3=8,native_flood_m3=1)
        data=charts.budget_data({'balance':b})
        self.assertEqual(data['rows'][0]['value'],130)
        self.assertEqual(data['rows'][-1]['value'],53)
        self.assertEqual(data['residual_m3'],1)
        self.assertTrue(any(d['name']=='未回到地表' for d in data['rows']))

    def test_renderer_syntax(self):
        node=shutil.which('node')
        if not node:
            self.skipTest('Node is not installed; syntax check not run')
        for name in ['mono-tokens.js','renderers.js']:
            subprocess.run([node,'--check',str(ROOT/'charts_assets'/name)], check=True,
                           capture_output=True, text=True)

    def test_color_contrast(self):
        def lum(h):
            a=[int(h[i:i+2],16)/255 for i in [1,3,5]]
            a=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in a]
            return sum(v*w for v,w in zip(a,[.2126,.7152,.0722]))
        bg=lum('#142f60')
        for h in ['#edeff1','#bdcde5']:
            self.assertGreaterEqual((lum(h)+.05)/(bg+.05),4.5)
        self.assertGreaterEqual((lum('#9ebfe9')+.05)/(bg+.05),3)
        self.assertGreaterEqual((lum('#647ea9')+.05)/(bg+.05),3)


if __name__ == '__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ChartTests))
    (ROOT/'qa/charts_tests.json').write_text(json.dumps({'passed':result.wasSuccessful(),
        'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'skipped':len(result.skipped),'scope':'chart semantics, security, JS syntax and contrast; no solver run'},indent=2),encoding='utf-8')
    sys.exit(not result.wasSuccessful())
