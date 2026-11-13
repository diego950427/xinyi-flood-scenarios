"""Read-only result comparison tests; never invoke or imply a new solver run."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import comparison_data as c


def decode(item):
    dtype = "<f4" if item["dtype"] == "float32-le" else "u1"
    return np.frombuffer(base64.b64decode(item["data"]), dtype=dtype).reshape(item["shape"])


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")


class ExistingResultsTests(unittest.TestCase):
    def test_five_fields_are_full_resolution_native_values(self):
        a = ROOT / "examples/20261020_194910_441553a8"
        b = ROOT / "examples/20261020_194418_a791bf32"
        before = [c._sha(p / "grids.npz") for p in (a, b)]
        for field in c.FIELDS:
            with self.subTest(field=field):
                out = c.build_comparison(a, b, "歷史九站", "自訂降雨", field)
                self.assertEqual((out["grid"]["rows"], out["grid"]["cols"]), (455, 552))
                self.assertEqual(out["grid"]["cell_size_m"], 20)
                self.assertEqual(out["grid"]["active_cells"], 89394)
                self.assertEqual(out["grid"]["reporting_cells"], 28097)
                arrays = out["arrays"]
                aa, bb = decode(arrays["a"]), decode(arrays["b"])
                am, bm = decode(arrays["a_valid_mask"]).astype(bool), decode(arrays["b_valid_mask"]).astype(bool)
                for path, values, mask in ((a, aa, am), (b, bb, bm)):
                    with np.load(path / "grids.npz", allow_pickle=False) as source:
                        np.testing.assert_array_equal(values[mask], source[field][mask])
                    self.assertTrue(np.isnan(values[~mask]).all())
                common = am & bm
                np.testing.assert_array_equal(decode(arrays["difference_valid_mask"]), common)
                np.testing.assert_array_equal(decode(arrays["difference"])[common], (bb - aa)[common])
                self.assertTrue(np.isnan(decode(arrays["difference"])[~common]).all())
                active = decode(arrays["valid_mask"]).astype(bool)
                z = decode(arrays["terrain_m"])
                relative = decode(arrays["terrain_relative_m"])
                np.testing.assert_allclose(relative[active] + out["grid"]["origin"]["z"], z[active], atol=2e-5)
                self.assertGreaterEqual(out["scales"]["absolute"][1], float(max(aa[am].max(), bb[bm].max())))
                self.assertEqual(out["scales"]["difference"][0], -out["scales"]["difference"][1])
                self.assertGreater(len(out["boundary_rings"]), 0)
                self.assertEqual(len(out["warnings"]) >= 2, True)
                text = json.dumps(out, ensure_ascii=False, allow_nan=False)
                self.assertNotIn(str(ROOT), text)
                self.assertNotIn("native_work", text)
                self.assertFalse(out["scenarios"][0]["provenance"]["original_terrain_independently_verified"])
        self.assertEqual(before, [c._sha(p / "grids.npz") for p in (a, b)])

    def test_identical_results_have_zero_difference_and_no_input_warning(self):
        folder = ROOT / "examples/20261020_194418_a791bf32"
        out = c.build_comparison(folder, folder, "A", "B", "max_depth_m")
        mask = decode(out["arrays"]["difference_valid_mask"]).astype(bool)
        self.assertTrue(np.all(decode(out["arrays"]["difference"])[mask] == 0))
        self.assertEqual(out["warnings"], [])
        self.assertEqual(out["difference_summary"]["mean_difference"], 0)


class SentinelTests(unittest.TestCase):
    def test_never_crossed_is_not_time_zero_and_not_in_difference(self):
        active = np.array([[1, 1, 1, 1]], dtype=bool)
        a = np.array([[-1, 0, 4, -1]], dtype="<f4")
        b = np.array([[3, 2, -1, -1]], dtype="<f4")
        am, an = c._field_mask(a, active, "first_gt10_s", 10)
        bm, bn = c._field_mask(b, active, "first_gt10_s", 10)
        np.testing.assert_array_equal(an, [[1, 0, 0, 1]])
        np.testing.assert_array_equal(bn, [[0, 0, 1, 1]])
        difference, common, scale = c._compare_arrays(a, b, am, bm)
        np.testing.assert_array_equal(common, [[0, 1, 0, 0]])
        self.assertEqual(difference[0, 1], 2)
        self.assertTrue(np.isnan(difference[~common]).all())
        self.assertEqual(scale["absolute"], [0, 4])
        self.assertEqual(scale["difference"], [-2, 2])

    def test_all_never_has_no_fabricated_difference(self):
        active = np.ones((2, 2), dtype=bool)
        a = np.full((2, 2), -1, dtype="<f4")
        mask, _ = c._field_mask(a, active, "first_gt10_s", 10)
        diff, common, scales = c._compare_arrays(a, a, mask, mask)
        self.assertFalse(common.any())
        self.assertTrue(np.isnan(diff).all())
        self.assertFalse(scales["absolute_has_data"])
        self.assertFalse(scales["difference_has_data"])

    def test_unknown_negative_and_nonfinite_active_values_rejected(self):
        for value in (-2, -9999, float("nan"), float("inf"), 1e100):
            with self.subTest(value=value), self.assertRaises(ValueError):
                c._field_mask(np.array([[value]]), np.ones((1, 1), bool), "first_gt10_s", 10)
        with self.assertRaises(ValueError):
            c._field_mask(np.array([[-1.0]]), np.ones((1, 1), bool), "duration_gt10_s", 10)
        with self.assertRaises(ValueError):
            c._field_mask(np.array([[11.0]]), np.ones((1, 1), bool), "time_of_max_s", 10)

    def test_little_endian_float32_and_nodata_encoding(self):
        encoded = c._encode(np.array([[1.25, 9.0]], dtype=">f8"), np.array([[True, False]]))
        self.assertEqual(base64.b64decode(encoded["data"])[:4], b"\x00\x00\xa0\x3f")
        self.assertTrue(np.isnan(decode(encoded)[0, 1]))


class SmallFixtureTests(unittest.TestCase):
    """Tiny matrices test rejection paths, not hydrological research results."""
    def setUp(self):
        self.temp = TemporaryDirectory(dir=ROOT / "qa")
        self.base = Path(self.temp.name)
        self.data = self.base / "data"
        self.folder = self.base / "result"
        self.data.mkdir()
        (self.folder / "native").mkdir(parents=True)
        self.shape = (2, 3)
        self.transform = from_origin(303190, 2774030, 20, 20)
        self.active = np.array([[1, 1, 1], [1, 1, 0]], dtype="u1")
        self.report = np.array([[1, 1, 0], [1, 0, 0]], dtype="u1")
        self.raster(self.data / "terrain20m.tif", np.array([[2, 3, 4], [5, 6, -9999]], dtype="f4"))
        self.raster(self.data / "active.tif", self.active)
        self.raster(self.data / "xinyi.tif", self.report)
        write_json(self.data / "source_manifest.json", {name: {"sha256": c._sha(self.data / name)}
                   for name in ("terrain20m.tif", "active.tif", "xinyi.tif")})
        write_json(self.data / "xinyi_boundary.geojson", {"type": "FeatureCollection",
            "crs": {"properties": {"name": "urn:ogc:def:crs:EPSG::3826"}},
            "features": [{"geometry": {"type": "Polygon", "coordinates": [[[303190, 2774030],
                [303250, 2774030], [303250, 2773990], [303190, 2773990], [303190, 2774030]]]}}]})
        depth = np.array([[0, .2, .3], [.15, .1, -9999]], dtype="f4")
        self.arrays = {"max_depth_m": depth, "final_depth_m": np.where(self.active, depth / 2, -9999).astype("f4"),
            "first_gt10_s": np.array([[-1, 0, 5], [5, -1, -9999]], dtype="f4"),
            "duration_gt10_s": np.array([[0, 10, 5], [5, 0, -9999]], dtype="f4"),
            "time_of_max_s": np.array([[0, 5, 10], [10, 5, -9999]], dtype="f4"),
            "qx_m2_s": np.zeros(self.shape, dtype="f4"), "qrow_m2_s": np.zeros(self.shape, dtype="f4")}
        self.save_grids()
        self.request = dict(mode="custom", total_mm=1, duration_min=1/6, rain_shape="uniform",
            recession_min=0, drain_mm_h=30, storage_mm=20, inlet_area_m2=.2,
            infiltration_mm_h=0, exchange_cap_s=1, model=c.MODEL)
        self.summary = dict(passed=True, checks={key: True for key in c.CHECKS}, request=self.request,
            rainfall={"end_s": 10, "rain_end_s": 10}, combined_error_pct=0, expected_rain_m3=0,
            balance={**{key: 0 for key in c.BUDGET_KEYS}, "time_s": 10})
        self.provenance = {"request": self.request, "source_manifest_sha256": "a" * 64, "engine_sources": {}}
        write_json(self.folder / "request.json", self.request)
        write_json(self.folder / "summary.json", self.summary)
        write_json(self.folder / "provenance.json", self.provenance)
        write_json(self.folder / "status.json", {"state": "completed"})
        write_json(self.folder / "native/progress.json", {"time_s": 10, "end_s": 10})
        (self.folder / "native/history.csv").write_text("time_s\n0\n10\n", encoding="utf-8")
        names = list(self.summary["balance"])
        (self.folder / "native/balance.csv").write_text(",".join(names) + "\n" +
            ",".join(str(self.summary["balance"][key]) for key in names) + "\n", encoding="utf-8")
        np.savez_compressed(self.folder / "rain_input.npz", edges_s=np.array([0., 10.]),
                            rates_m_s=np.zeros((1, 1)), station_index=np.zeros(self.shape, dtype="i2"))
        self.patches = [patch.object(c, "DATA", self.data), patch.object(c, "_known_manifests", return_value={"a" * 64})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def raster(self, path, values, transform=None, crs="EPSG:3826"):
        with rasterio.open(path, "w", driver="GTiff", height=values.shape[0], width=values.shape[1],
                           count=1, dtype=values.dtype, transform=transform or self.transform,
                           crs=crs, nodata=-9999 if values.dtype.kind == "f" else 255) as ds:
            ds.write(values, 1)

    def save_grids(self):
        np.savez_compressed(self.folder / "grids.npz", **self.arrays)
        for name in c.FIELDS:
            self.raster(self.folder / (name + ".tif"), self.arrays[name])

    def build(self, field="max_depth_m"):
        return c.build_comparison(self.folder, self.folder, "A", "B", field)

    def test_report_mask_and_no_status_zip_supported(self):
        (self.folder / "status.json").unlink()
        result = self.build("first_gt10_s")
        self.assertEqual(result["grid"]["reporting_cells"], 3)
        self.assertEqual(result["difference_summary"]["common_reporting_cells"], 2)
        self.assertEqual(result["scenarios"][0]["metrics"]["field_never_reporting_cells"], 1)
        self.assertEqual(result["scenarios"][0]["metrics"]["area_ever_gt10_km2"], .0008)

    def test_failed_checks_and_incomplete_clock_rejected(self):
        self.summary["checks"]["full_native_clock"] = False
        write_json(self.folder / "summary.json", self.summary)
        with self.assertRaises(ValueError): self.build()
        self.summary["checks"]["full_native_clock"] = True
        write_json(self.folder / "summary.json", self.summary)
        write_json(self.folder / "native/progress.json", {"time_s": 9, "end_s": 10})
        with self.assertRaises(ValueError): self.build()

    def test_running_status_rejected(self):
        write_json(self.folder / "status.json", {"state": "running"})
        with self.assertRaises(ValueError): self.build()

    def test_shifted_transform_and_wrong_crs_rejected(self):
        path = self.folder / "max_depth_m.tif"
        self.raster(path, self.arrays["max_depth_m"], transform=from_origin(303210, 2774030, 20, 20))
        with self.assertRaises(ValueError): self.build()
        self.raster(path, self.arrays["max_depth_m"], crs="EPSG:3857")
        with self.assertRaises(ValueError): self.build()

    def test_raster_npz_disagreement_and_shape_rejected(self):
        changed = self.arrays["max_depth_m"].copy()
        changed[0, 1] += .1
        self.raster(self.folder / "max_depth_m.tif", changed)
        with self.assertRaises(ValueError): self.build()
        self.save_grids()
        self.arrays["final_depth_m"] = np.zeros((2, 2), dtype="f4")
        np.savez_compressed(self.folder / "grids.npz", **self.arrays)
        with self.assertRaises(ValueError): self.build()

    def test_unknown_manifest_and_request_disagreement_rejected(self):
        self.provenance["source_manifest_sha256"] = "b" * 64
        write_json(self.folder / "provenance.json", self.provenance)
        with self.assertRaises(ValueError): self.build()
        self.provenance["source_manifest_sha256"] = "a" * 64
        write_json(self.folder / "provenance.json", self.provenance)
        self.request["total_mm"] = 99
        write_json(self.folder / "request.json", self.request)
        with self.assertRaises(ValueError): self.build()

    def test_unsafe_npz_object_array_rejected(self):
        self.arrays["max_depth_m"] = np.full(self.shape, "test", dtype=object)
        np.savez_compressed(self.folder / "grids.npz", **self.arrays)
        with self.assertRaises(ValueError): self.build()

    def test_terrain_fingerprint_change_rejected(self):
        self.raster(self.data / "terrain20m.tif", np.ones(self.shape, dtype="f4"))
        with self.assertRaises(ValueError): self.build()

    def test_summary_balance_tampering_rejected(self):
        self.summary["balance"]["drain_m3"] = 900
        write_json(self.folder / "summary.json", self.summary)
        with self.assertRaisesRegex(ValueError, "balance.csv"):
            self.build()

    def test_summary_percentage_and_rain_tampering_rejected(self):
        self.summary["combined_error_pct"] = .0001
        write_json(self.folder / "summary.json", self.summary)
        with self.assertRaisesRegex(ValueError, "百分比"):
            self.build()
        self.summary["combined_error_pct"] = 0
        self.summary["expected_rain_m3"] = 3
        write_json(self.folder / "summary.json", self.summary)
        with self.assertRaisesRegex(ValueError, "積分"):
            self.build()

    def test_scalar_summary_metrics_are_recomputed_from_grids(self):
        self.summary.update(max_depth_m=999, p99_depth_m=999, reporting_area_km2=999,
                            area_ever_gt5_km2=999, area_ever_gt10_km2=999, area_ever_gt30_km2=999)
        write_json(self.folder / "summary.json", self.summary)
        metrics = self.build()["scenarios"][0]["metrics"]
        self.assertAlmostEqual(metrics["max_depth_m"], .2, places=6)
        self.assertLess(metrics["p99_depth_m"], .21)
        self.assertEqual(metrics["reporting_area_km2"], .0012)
        self.assertEqual(metrics["area_ever_gt10_km2"], .0008)
        self.assertEqual(metrics["area_ever_gt30_km2"], 0)
        self.assertEqual(metrics["budget"]["rain_m3"], 0)

    def test_actual_forcing_integral_overrides_summary_declaration(self):
        np.savez_compressed(self.folder / "rain_input.npz", edges_s=np.array([0., 10.]),
                            rates_m_s=np.full((1, 1), .001), station_index=np.zeros(self.shape, dtype="i2"))
        self.assertEqual(c._rain_integral(self.folder, self.active.astype(bool), 10), 20)
        with self.assertRaisesRegex(ValueError, "積分"):
            self.build()


if __name__ == "__main__":
    report_path = ROOT / "qa/comparison_data_tests.json"
    write_json(report_path, {"passed": False, "status": "RUNNING"})
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    report = {"passed": result.wasSuccessful(), "run": result.testsRun,
              "failures": len(result.failures), "errors": len(result.errors),
              "skipped": len(result.skipped),
              "scope": "Two real completed examples, full-resolution grid comparisons, sentinel handling, source/grid/clock validation and native-budget recomputation; no solver rerun"}
    write_json(report_path, report)
    raise SystemExit(0 if report["passed"] else 1)
