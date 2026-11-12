"""Classify regenerated presentation separately; never accept changed model numbers."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for folder in (ROOT / 'examples').glob('*'):
        if not folder.is_dir():
            continue
        path = folder / 'example_source.json'
        source = json.loads(path.read_text(encoding='utf-8'))
        numerical, supporting, regenerated = [], [], []
        for record in source['included_numeric_files'] + source.get('included_supporting_files', []):
            name = record['path']
            if name == 'result.qgs':
                regenerated.append(record)
                continue
            if sha(folder / name) != record['sha256']:
                raise ValueError('Original evidence changed: ' + name)
            (supporting if name in ('max_depth.png', 'native/console.log') else numerical).append(record)
        previous = source.get('regenerated_presentation_files', [])
        previous_qgis = next((r for r in previous if r['path'] == 'result.qgs'), None)
        original_qgis = (regenerated[0]['original_sha256'] if regenerated else
                         previous_qgis['original_sha256'])
        if sha(folder / 'result.qgs') != sha(ROOT / 'templates/result.qgs'):
            raise ValueError('Presentation project differs from approved portable QGIS template')
        source['included_numeric_files'] = numerical
        source['included_supporting_files'] = supporting
        source['regenerated_presentation_files'] = [
            {'path': 'result.qgs', 'original_sha256': original_qgis,
             'sha256': sha(folder / 'result.qgs'),
             'reason': 'Replaced V2 presentation project with shared portable V3 template; numerical raster files unchanged.'},
            {'path': 'READ_ME.txt', 'sha256': sha(folder / 'READ_ME.txt'),
             'reason': 'Generated V3 opening instructions; not numerical evidence.'},
        ]
        path.write_text(json.dumps(source, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Classified both example manifests; original numerical hashes verified.')


if __name__ == '__main__':
    main()
