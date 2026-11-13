"""Lieflat F3/F2/F9 chart adapters. Templates are attributed in charts_assets/.

All values come from input forcing or the completed run. Rendering does not run
the solver, interpolate missing rainfall, or convert exposure area to probability.
"""
from pathlib import Path
from html import escape
import csv
import json
import math

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "charts_assets"


def _json(value):
    # A JSON script payload must not let a source label terminate its script tag.
    return json.dumps(value, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _finite(values, name, nonnegative=True):
    result = [float(v) for v in values]
    if not result or not all(math.isfinite(v) and (v >= 0 or not nonnegative) for v in result):
        raise ValueError(f"{name} 缺資料、非有限值或含不允許的負值。")
    return result


def _document(kind, title, subtitle, note, source, data):
    # The upstream documentation comment includes a literal closing script tag.
    # HTML tokenization applies even inside a JavaScript comment when inlining.
    tokens = (ASSETS / "mono-tokens.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
    renderer = (ASSETS / "renderers.js").read_text(encoding="utf-8")
    payload = _json({"kind": kind, "data": data})
    # Dark cards deliberately follow the user's accepted dark navy reference;
    # this explicit preference takes precedence over the skill's paper default.
    return f'''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#081f5c;color:#edeff1;font-family:Inter,"Microsoft JhengHei","Noto Sans TC",sans-serif}}
.card{{background:#142f60;border-radius:24px;padding:20px 18px 14px;overflow:hidden}}
.chart-label{{margin:0 0 6px;font-size:16px;font-weight:600}}
.sub,.note{{font-size:13px;line-height:1.55;color:#bdcde5;margin:0 0 8px}}
.src{{font-size:11px;line-height:1.45;color:#bdcde5;margin-top:9px;letter-spacing:.015em}}
svg{{width:100%;height:240px;display:block}}svg text{{font-family:inherit}}
.readout{{font-size:13px;min-height:24px;line-height:1.5;margin:0 0 3px;color:#edeff1;font-variant-numeric:tabular-nums}}
.controls{{display:flex;gap:12px;align-items:center}}input[type=range]{{width:100%;min-width:0;accent-color:#9ebfe9}}
button{{background:#142f60;color:#edeff1;border:1px solid #9ebfe9;border-radius:8px;padding:5px 9px;font:inherit;white-space:nowrap;cursor:pointer}}
button:focus-visible,input:focus-visible{{outline:2px solid #edeff1;outline-offset:2px}}
@media(max-width:420px){{.card{{padding:16px 10px 12px}}}}
.fade{{animation:fade .9s ease both}}@keyframes fade{{from{{opacity:0}}}}
.draw{{stroke-dasharray:1;stroke-dashoffset:1;animation:draw 1.2s cubic-bezier(.4,0,.2,1) both}}@keyframes draw{{to{{stroke-dashoffset:0}}}}
.pop{{transform-box:fill-box;transform-origin:center;animation:pop .5s cubic-bezier(.2,.7,.3,1) both}}@keyframes pop{{from{{transform:scale(0)}}to{{transform:none}}}}
@media(prefers-reduced-motion:reduce){{.fade,.draw,.pop{{animation:none;stroke-dasharray:none;stroke-dashoffset:0}}}}
</style></head><body><section class="card">
<p class="chart-label">{escape(title)}</p><p class="sub">{escape(subtitle)}</p>
<svg id="chart" role="img" aria-label="{escape(title, quote=True)}"></svg>
<div id="readout" class="readout" aria-live="polite"></div>
<div class="controls"><input id="inspect" type="range" min="0" max="1" value="0" aria-label="移動以查看時間或水量項目"><button id="replay" type="button">重播</button></div>
<p class="note">{escape(note)}</p><div class="src">{escape(source)}</div></section>
<script>{tokens}</script><script id="chart-data" type="application/json">{payload}</script><script>{renderer}</script>
</body></html>'''


def rainfall_data(req):
    """Area-weighted *district* rain intensity in mm/h and exact interval edges."""
    import numpy as np
    from backend import load_grid, forcing
    _, active, report, _, _ = load_grid()
    edges, rates, station, meta = forcing(req, active)
    counts = np.bincount(station[report], minlength=rates.shape[1])
    if counts.sum() <= 0:
        raise ValueError("信義區沒有有效雨量分配網格。")
    values = _finite(rates.dot(counts / counts.sum()) * 1000 * 3600, "雨強")
    edges = _finite(edges, "時間")
    if len(edges) != len(values) + 1 or any(b <= a for a, b in zip(edges, edges[1:])):
        raise ValueError("降雨區間必須完整且按時間遞增。")
    total = sum(v * (b - a) / 3600 for v, a, b in zip(values, edges, edges[1:]))
    return {"edges_s": edges, "values": values, "rain_end_s": float(meta["rain_end_s"]),
            "total_mm": total, "label": str(meta["label"])}, total, meta


def rainfall_html(req):
    """Return (self-contained HTML, area-weighted total mm, source metadata)."""
    data, total, meta = rainfall_data(req)
    peak = max(data["values"])
    title = f"這場雨最強時為 {peak:.1f} mm/h" if peak else "這次設定沒有降雨"
    html = _document("rain", title,
        "時間往右，雨強往上。一條直線＝一個雨量區間。",
        "拖動滑桿查輸入。雨後延長段明示無雨；不把缺測填成 0。",
        "區內面積加權 · " + str(meta["label"]), data)
    return html, total, meta


def history_data(folder):
    with (Path(folder) / "native/history.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    times = _finite([r["time_s"] for r in rows], "時間")
    values = _finite([r["xinyi_area_gt10_km2"] for r in rows], "積水面積")
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("結果時間必須嚴格遞增。")
    return {"times_s": times, "values": values}


def history_html(folder):
    data = history_data(folder)
    peak = max(data["values"])
    return _document("history", f"同時積水 >10 cm：最多 {peak:.2f} km²",
        "一點＝一次求解器輸出。面積可隨退水下降。",
        "這條線可以下降。「曾超過」合併整段位置，與這裡的當時面積不同。",
        "各時刻計算結果 · 情境模擬，非淹水機率", data)


def budget_data(summary):
    b = summary["balance"]
    keys = ("initial_surface_m3", "initial_native_m3", "rain_m3", "infiltration_m3",
            "boundary_out_m3", "drain_m3", "surface_stored_m3", "native_stored_m3", "native_flood_m3")
    v = dict(zip(keys, _finite([b[k] for k in keys], "水量")))
    initial = v["initial_surface_m3"] + v["initial_native_m3"]
    stored = v["surface_stored_m3"] + v["native_stored_m3"]
    rows = [
        {"name": "總進水", "value": v["rain_m3"] + initial, "kind": "total"},
        {"name": "入滲", "value": -v["infiltration_m3"], "kind": "change"},
        {"name": "外框流出", "value": -v["boundary_out_m3"], "kind": "change"},
        {"name": "SWMM 排出", "value": -v["drain_m3"], "kind": "change"},
    ]
    if v["native_flood_m3"] > 0:
        rows.append({"name": "未回到地表", "value": -v["native_flood_m3"], "kind": "change"})
    rows.append({"name": "最後留水", "value": stored, "kind": "total"})
    residual = v["rain_m3"] + initial - v["infiltration_m3"] - v["boundary_out_m3"] - v["drain_m3"] - v["native_flood_m3"] - stored
    return {"rows": rows, "residual_m3": residual, "surface_m3": v["surface_stored_m3"],
            "native_m3": v["native_stored_m3"], "initial_m3": initial}


def budget_html(summary):
    data = budget_data(summary)
    return _document("budget", "水量帳：流走多少，還留下多少",
        "全計算域。實線梯＝總量；虛線梯＝扣除量。",
        f"留在地表 {data['surface_m3']:,.0f} m³；留在等效排水單元 {data['native_m3']:,.0f} m³。"
        f"帳面殘差 {data['residual_m3']:,.2f} m³，沒有為了湊齊而修改數值。",
        "求解器水量收支 · 1 m³＝1,000 公升", data)
