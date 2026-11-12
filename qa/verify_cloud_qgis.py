"""Append real headless PyQGIS verification to --report from verify_cloud_download.py.

Use an interpreter with qgis.core available; no platform-specific install path is embedded.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import xml.etree.ElementTree as ET

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from qgis.core import QgsApplication, QgsProject

ROOT = Path(__file__).resolve().parents[1]


def inside(value):
    path = Path(value)
    path = (path if path.is_absolute() else ROOT / path).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError('Report and extracted project must remain inside this project')
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--report', required=True)
args = parser.parse_args()
report_path = inside(args.report)
report = json.loads(report_path.read_text(encoding='utf-8'))
folder = inside(report['extracted_to'])
project_path = folder / 'result.qgs'
files = [project_path, folder/'max_depth_m.tif', folder/'xinyi_boundary.geojson']
before = {p.name: digest(p) for p in files}
sources = [e.text for e in ET.parse(project_path).findall('.//projectlayers/maplayer/datasource')]
if set(sources) != {'./max_depth_m.tif', './xinyi_boundary.geojson'}:
    raise ValueError('Unexpected QGIS source references; refused to load')
app = QgsApplication([], False)
app.initQgis()
project = QgsProject()
loaded = project.read(str(project_path))
layers = list(project.mapLayers().values())
checks = {
    'loaded_actual_cloud_download': bool(loaded),
    'exactly_two_valid_layers': len(layers) == 2 and all(layer.isValid() for layer in layers),
    'one_gdal_one_ogr': sorted(layer.providerType() for layer in layers) == ['gdal', 'ogr'],
    'project_and_layers_epsg3826': project.crs().authid() == 'EPSG:3826' and all(layer.crs().authid() == 'EPSG:3826' for layer in layers),
    'relative_sources_and_files_exist': all((folder/source).is_file() for source in sources),
    'nonempty_default_extent': not project.viewSettings().defaultViewExtent().isEmpty(),
    'source_files_unchanged': all(digest(folder/name) == value for name,value in before.items()),
}
report['headless_qgis'] = {'project': project_path.relative_to(ROOT).as_posix(),
                         'checks': checks, 'passed': all(checks.values()), 'stored_sources': sources,
                         'scope': 'Actual extracted cloud download loaded in installed PyQGIS offscreen; no GUI or project save.'}
report['passed'] = report['passed_before_qgis'] and report['headless_qgis']['passed']
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'passed': report['passed'], 'qgis_checks': checks}), flush=True)
project.clear()
os._exit(0 if report['passed'] else 1)
