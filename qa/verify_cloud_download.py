"""Recompute acceptance from a downloaded cloud ZIP; never execute a model.

Example (run with the application's Python dependencies):
  python qa/verify_cloud_download.py --zip result.zip \
    --output qa/artifacts/cloud_history/extracted --report qa/cloud_history_acceptance.json
Then run verify_cloud_qgis.py with a PyQGIS interpreter and the same --report.
Use a new or empty extraction directory for every verification.
"""
from pathlib import Path, PurePosixPath
import argparse
import csv
import hashlib
import json
import math
import re
import stat
import sys
import zipfile

import numpy as np
import rasterio

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend as b

FIELDS = ['final_depth_m', 'qx_m2_s', 'qrow_m2_s', 'max_depth_m',
          'time_of_max_s', 'first_gt10_s', 'duration_gt10_s']
METRICS = ['combined_error_pct', 'expected_rain_m3', 'reporting_area_km2',
           'area_ever_gt5_km2', 'area_ever_gt10_km2', 'area_ever_gt30_km2',
           'max_depth_m', 'p99_depth_m', 'native_binary_storage_m3']
TEXT_SUFFIXES = {'.json', '.qgs', '.geojson', '.txt', '.csv', '.inp', '.rpt', '.log', '.xml'}
PRIVATE_MARKERS = re.compile(r'[A-Za-z]:[\\/](?:Users|CU)[\\/]|USER_HOME|/Users/|/home/[^/\s]+/|github_pat_|ghp_[A-Za-z0-9]{20}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY')


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def inside_project(value):
    candidate = Path(value)
    candidate = (candidate if candidate.is_absolute() else ROOT / candidate).resolve()
    if not candidate.is_relative_to(ROOT.resolve()):
        raise ValueError('Output and report must be inside the project')
    return candidate


def relative(path):
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def extract_checked(archive, destination):
    """Reject traversal, links, duplicates, device names and oversized payloads first."""
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError('Extraction directory must be new or empty; old files cannot be used as ZIP evidence')
    with zipfile.ZipFile(archive) as source:
        infos = source.infolist()
        names = [i.filename for i in infos]
        if len(names) > 512 or len(names) != len(set(n.casefold() for n in names)):
            raise ValueError('Too many or duplicate archive members')
        if sum(i.file_size for i in infos) > 1_000_000_000 or any(i.file_size > 512_000_000 for i in infos):
            raise ValueError('Unexpected archive expansion size')
        for info in infos:
            name = info.filename
            parts = PurePosixPath(name).parts
            target = (destination / name).resolve()
            device_name = any(re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', p) for p in parts)
            if (not name or info.orig_filename != name or '\\' in name or ':' in name or PurePosixPath(name).is_absolute()
                    or '..' in parts or any(p.endswith((' ', '.')) for p in parts) or device_name
                    or stat.S_ISLNK(info.external_attr >> 16)
                    or not target.is_relative_to(destination.resolve())):
                raise ValueError('Unsafe archive member')
        if source.testzip() is not None:
            raise ValueError('Archive CRC failure')
        destination.mkdir(parents=True, exist_ok=True)
        entries = []
        for info in infos:
            target = destination / info.filename
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            blob = source.read(info)
            digest = hashlib.sha256(blob).hexdigest()
            if target.exists() and sha(target) != digest:
                raise ValueError('Existing extraction contains different data')
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(blob)
            entries.append({'path': info.filename, 'bytes': len(blob), 'sha256': digest})
    return entries


def verify(archive, destination):
    entries = extract_checked(archive, destination)
    summary = b.json_read(destination / 'summary.json')
    request = b.json_read(destination / 'request.json')
    normalized = b.validate_request(request)
    provenance = b.json_read(destination / 'provenance.json')
    _, active, reporting, _, transform = b.load_grid()
    with np.load(destination / 'rain_input.npz', allow_pickle=False) as saved:
        edges, rates, station = [saved[n].copy() for n in ('edges_s', 'rates_m_s', 'station_index')]
    expected_edges, expected_rates, expected_station, _ = b.forcing(normalized, active)
    recomputed = b.validate_outputs(destination / 'native', active, reporting, edges, rates, station)
    expected_engine = {p.name: sha(p) for p in (ROOT / 'engine').glob('*.cs')}
    public_manifest = b.json_read(ROOT / 'data/public_manifest.json')
    checks = {
        'safe_member_paths': True, 'crc_all_members': True,
        'reported_all_15_checks_pass': len(summary['checks']) == 15 and all(summary['checks'].values()) and summary['passed'],
        'recomputed_all_15_checks_pass': len(recomputed['checks']) == 15 and all(recomputed['checks'].values()) and recomputed['passed'],
        'reported_checks_match_recomputation': summary['checks'] == recomputed['checks'],
        'reported_numeric_summary_matches': all(math.isclose(summary[k], recomputed[k], rel_tol=1e-10, abs_tol=1e-9) for k in METRICS),
        'linux_provenance': provenance['platform'] == 'linux' and provenance['native_work'] == 'native/',
        'source_manifest_hash_matches_release': provenance['source_manifest_sha256'] == sha(ROOT / 'data/source_manifest.json'),
        'local_release_inputs_match_manifest': all(sha(ROOT / 'data' / f['file']) == f['release_sha256'] for f in public_manifest['files']),
        'coupling_source_hashes_match_release': provenance['engine_sources'] == expected_engine,
        'valid_historical_or_custom_request': normalized['mode'] in {'historical', 'custom'},
        'request_matches_summary_and_provenance': request == summary['request'] == provenance['request'],
        'saved_rain_matches_request': np.array_equal(edges, expected_edges) and np.array_equal(rates, expected_rates) and np.array_equal(station, expected_station),
    }
    state = np.fromfile(destination / 'native/state.bin', dtype='<f8').reshape(7, -1)
    arrays_valid = []
    with np.load(destination / 'grids.npz', allow_pickle=False) as grids:
        for i, name in enumerate(FIELDS):
            expected = np.full(active.shape, -9999, np.float32)
            expected[active] = state[i]
            with rasterio.open(destination / (name + '.tif')) as ds:
                valid = (ds.crs.to_epsg() == 3826 and ds.res == (20.0, 20.0)
                         and ds.transform == transform and ds.nodata == -9999
                         and np.array_equal(ds.read(1), expected) and np.array_equal(grids[name], expected))
            arrays_valid.append({'field': name, 'matches_native_and_npz': bool(valid)})
    checks['seven_rasters_and_npz_match_native_state'] = all(r['matches_native_and_npz'] for r in arrays_valid)
    with (destination / 'native/history.csv').open(encoding='utf-8-sig') as stream:
        history = list(csv.DictReader(stream))
    native = b.read_output(destination / 'native/model.out')
    progress = b.json_read(destination / 'native/progress.json')
    console = (destination / 'native/console.log').read_text(encoding='utf-8')
    clocks = {'history_s': float(history[-1]['time_s']), 'progress_s': progress['time_s'],
              'progress_end_s': progress['end_s'], 'balance_s': recomputed['balance']['time_s'],
              'native_binary_s': float(native['times_s'][-1]), 'expected_s': float(expected_edges[-1])}
    checks['all_end_clocks_match_requested_forcing'] = all(abs(v - clocks['expected_s']) < .01 for v in clocks.values())
    checks['exact_native_completion_line'] = bool(re.search(r'^COMPLETED_COUPLED\s+\.$', console, re.MULTILINE))
    privacy_findings, text_decodings = [], {}
    for row in entries:
        path = destination / row['path']
        if path.suffix.lower() in TEXT_SUFFIXES:
            try:
                text = path.read_text(encoding='utf-8-sig')
                text_decodings[row['path']] = 'utf-8-sig'
            except UnicodeDecodeError:
                # Preserve every byte; native reports contain single-byte unit symbols.
                text = path.read_text(encoding='latin-1')
                text_decodings[row['path']] = 'latin-1 byte-preserving scan'
            if PRIVATE_MARKERS.search(text):
                privacy_findings.append(row['path'])
    checks['no_personal_paths_or_obvious_credentials_in_text'] = not privacy_findings
    checks['no_executables_or_secret_files'] = not any(Path(r['path']).suffix.lower() in {'.exe', '.dll', '.key', '.pem'} for r in entries)
    archive_label = relative(archive) if archive.is_relative_to(ROOT.resolve()) else archive.name
    return {
        'schema_version': 1, 'passed_before_qgis': all(checks.values()),
        'scope': 'Actual cloud-download ZIP; numerical checks independently recomputed from native outputs, not a solver rerun. QGIS loading is a separate follow-up check.',
        'archive': archive_label, 'archive_sha256': sha(archive), 'archive_bytes': archive.stat().st_size,
        'extracted_to': relative(destination), 'member_count': len(entries),
        'uncompressed_bytes': sum(r['bytes'] for r in entries), 'checks': checks,
        'native_checks_recomputed': recomputed['checks'],
        'request': {k: normalized.get(k) for k in ['mode', 'event_id', 'total_mm', 'duration_min', 'rain_shape', 'recession_min', 'drain_mm_h', 'storage_mm', 'inlet_area_m2', 'infiltration_mm_h', 'exchange_cap_s', 'model']},
        'native_version': native['version'], 'clocks': clocks,
        'exchange_steps': recomputed['balance']['exchange_steps'], 'surface_steps': recomputed['balance']['surface_steps'],
        'native_wall_s': recomputed['balance']['wall_s'], 'result_metrics': {k: recomputed[k] for k in METRICS},
        'native_flow_error_pct': recomputed['balance']['native_flow_error_pct'],
        'provenance_platform': 'linux' if provenance['platform'] == 'linux' else 'unexpected',
        'declared_cloud_binary_hashes': {k: provenance[k] for k in ('engine_sha256', 'swmm_library_sha256')},
        'binary_hash_limitation': 'Executable/library bytes are absent from the ZIP. Their hashes are recorded declarations; native output version and numerical integrity were actually checked.',
        'rasters': arrays_valid, 'privacy_findings': privacy_findings, 'text_scan_decodings': text_decodings,
        'files': entries, 'headless_qgis': {'status': 'not_run'},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', required=True, type=Path, dest='archive')
    parser.add_argument('--output', required=True, help='Extraction directory inside this project')
    parser.add_argument('--report', default='qa/cloud_download_acceptance.json', help='JSON report inside this project')
    args = parser.parse_args()
    destination, report_path = inside_project(args.output), inside_project(args.report)
    artifacts = (ROOT / 'qa/artifacts').resolve()
    if destination == artifacts or not destination.is_relative_to(artifacts):
        parser.error('--output must be a dedicated subdirectory under qa/artifacts')
    archive = args.archive.resolve(strict=True)
    try:
        report = verify(archive, destination)
    except Exception as exc:
        # Error messages may contain private local paths; do not publish them.
        report = {'schema_version': 1, 'passed_before_qgis': False, 'passed': False,
                  'error_type': type(exc).__name__, 'error': 'Verification could not finish; inspect the local input and rerun.',
                  'archive': archive.name, 'archive_sha256': sha(archive), 'extracted_to': relative(destination),
                  'headless_qgis': {'status': 'not_run'}}
    b.json_save(report_path, report)
    print(json.dumps({'report': relative(report_path), 'passed_before_qgis': report['passed_before_qgis'],
                      'checks': report.get('checks', {}), 'error_type': report.get('error_type')}))
    return 0 if report['passed_before_qgis'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
