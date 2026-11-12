"""Check ZIP acceptance isolation using a real downloaded ZIP, without a solver.

Run with the application's dependencies:
  python qa/test_cloud_download_regression.py --zip path/to/downloaded_results.zip
Temporary copies stay under qa/artifacts and are removed after the checks.
"""
from pathlib import Path
import argparse
import shutil
import tempfile
import unittest
import zipfile

import verify_cloud_download as verifier

ARTIFACTS = (verifier.ROOT / 'qa/artifacts').resolve()


class DownloadIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        cls.temp = Path(tempfile.mkdtemp(prefix='cloud_download_regression_', dir=ARTIFACTS)).resolve()
        cls.original_hash = verifier.sha(cls.archive)
        cls.empty_zip = cls.temp / 'empty.zip'
        with zipfile.ZipFile(cls.empty_zip, 'w'):
            pass
        cls.incomplete_zip = cls.temp / 'missing_state.zip'
        with zipfile.ZipFile(cls.archive) as source, zipfile.ZipFile(cls.incomplete_zip, 'w') as target:
            if 'native/state.bin' not in source.namelist():
                raise ValueError('Regression fixture must contain native/state.bin')
            for info in source.infolist():
                if info.filename != 'native/state.bin':
                    target.writestr(info, source.read(info))

    @classmethod
    def tearDownClass(cls):
        unchanged = verifier.sha(cls.archive) == cls.original_hash
        if cls.temp == ARTIFACTS or not cls.temp.is_relative_to(ARTIFACTS):
            raise ValueError('Refused cleanup outside qa/artifacts')
        shutil.rmtree(cls.temp)
        if not unchanged:
            raise AssertionError('Original downloaded ZIP changed')

    def complete_result(self, name):
        destination = self.temp / name
        report = verifier.verify(self.archive, destination)
        self.assertTrue(report['passed_before_qgis'])
        self.assertGreater(report['member_count'], 0)
        return destination

    def test_complete_zip_in_new_directory_passes(self):
        self.complete_result('fresh_complete')

    def assert_rejected(self, archive, destination):
        try:
            report = verifier.verify(archive, destination)
        except ValueError:
            return
        self.fail(f"Reused old files: passed_before_qgis={report['passed_before_qgis']}, "
                  f"member_count={report['member_count']}")

    def test_empty_zip_cannot_reuse_old_result(self):
        destination = self.complete_result('empty_reuse')
        self.assert_rejected(self.empty_zip, destination)

    def test_missing_required_member_cannot_reuse_old_result(self):
        destination = self.complete_result('missing_state_reuse')
        self.assert_rejected(self.incomplete_zip, destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', required=True, type=Path, dest='archive')
    args = parser.parse_args()
    DownloadIsolationTests.archive = args.archive.resolve(strict=True)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(DownloadIsolationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
