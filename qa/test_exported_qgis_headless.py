"""Read actual exported projects using installed PyQGIS; never launch desktop QGIS."""
from pathlib import Path
import hashlib
import json
import os
import xml.etree.ElementTree as ET

from qgis.core import QgsApplication, QgsProject

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


app = QgsApplication([], False)
app.initQgis()
projects = sorted((ROOT / 'examples').glob('*/result.qgs'))
projects += sorted((ROOT / '.runtime/full_domain').glob('runs/*/result.qgs'))
rows = []
for path in projects:
    files = [path, path.parent / 'max_depth_m.tif', path.parent / 'xinyi_boundary.geojson']
    before = {p.name: digest(p) for p in files}
    xml = ET.parse(path)
    stored_sources = [e.text for e in xml.findall('.//projectlayers/maplayer/datasource')]
    project = QgsProject()
    loaded = project.read(str(path))
    layers = list(project.mapLayers().values())
    checks = {
        'project_loaded_by_pyqgis': bool(loaded),
        'exactly_two_layers': len(layers) == 2,
        'all_layers_valid': bool(layers) and all(layer.isValid() for layer in layers),
        'one_raster_one_vector': sorted(layer.providerType() for layer in layers) == ['gdal', 'ogr'],
        'project_epsg3826': project.crs().authid() == 'EPSG:3826',
        'both_layers_epsg3826': bool(layers) and all(layer.crs().authid() == 'EPSG:3826' for layer in layers),
        'stored_sources_relative_and_expected': set(stored_sources) == {'./max_depth_m.tif', './xinyi_boundary.geojson'},
        'relative_sources_exist': all((path.parent / source).is_file() for source in stored_sources),
        'default_extent_not_empty': not project.viewSettings().defaultViewExtent().isEmpty(),
        'inputs_unchanged_by_read': all(digest(p) == before[p.name] for p in files),
    }
    request = json.loads((path.parent / 'request.json').read_text(encoding='utf-8'))
    rows.append({
        'project': str(path.relative_to(ROOT)).replace('\\', '/'),
        'request': {key: request.get(key) for key in ('mode', 'event_id', 'total_mm', 'duration_min')},
        'stored_sources': stored_sources,
        'layers': [{'name': layer.name(), 'provider': layer.providerType(),
                    'valid': layer.isValid(), 'crs': layer.crs().authid()} for layer in layers],
        'checks': checks, 'passed': all(checks.values()),
    })
    project.clear()

report = {
    'passed': len(rows) == 3 and all(row['passed'] for row in rows),
    'expected_project_count': 3,
    'scope': 'Real local PyQGIS headless loading of two public V2 examples and one new V3 full-domain result. No GUI, solver rerun, source changes or new numerical acceptance claim.',
    'projects': rows,
}
(ROOT / 'qa/exported_qgis_headless.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report, ensure_ascii=False), flush=True)
# Avoid existing Qt/GDAL shutdown interaction after explicitly clearing projects.
os._exit(0 if report['passed'] else 1)
