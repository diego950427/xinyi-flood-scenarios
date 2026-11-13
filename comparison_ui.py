"""An explicit compare action keeps the existing simulator light on first load."""
from pathlib import Path
import json
import pandas as pd
import streamlit as st

from backend import json_read
from comparison_data import build_comparison
from comparison_view import comparison_html
from comparison_import import import_comparison_zip

FIELDS = {
    "最大水深": "max_depth_m", "結束水深": "final_depth_m",
    "超過 10 cm 多久": "duration_gt10_s", "首次超過 10 cm": "first_gt10_s",
    "最大水深發生時間": "time_of_max_s",
}


def comparison_table(scenarios):
    summaries = [s["metrics"] for s in scenarios]
    rows = []
    for label, getter, digits in [
        ("曾超過 5 cm（km²）", lambda s: s["area_ever_gt5_km2"], 4),
        ("曾超過 10 cm（km²）", lambda s: s["area_ever_gt10_km2"], 4),
        ("曾超過 30 cm（km²）", lambda s: s["area_ever_gt30_km2"], 4),
        ("99% 網格最大水深不超過（cm）", lambda s: s["p99_depth_m"] * 100, 2),
        ("單格最大水深（cm；未校準）", lambda s: s["max_depth_m"] * 100, 2),
        ("全域降雨輸入（m³）", lambda s: s["budget"]["rain_m3"], 1),
        ("全域 SWMM 排出（m³）", lambda s: s["budget"]["drain_m3"], 1),
        ("全域最後地表留水（m³）", lambda s: s["budget"]["surface_stored_m3"], 1),
        ("收支差（%）", lambda s: s["combined_error_pct"], 5),
    ]:
        a, b = [float(getter(s)) for s in summaries]
        rows.append({"項目": label, "A": round(a, digits), "B": round(b, digits),
                     "B − A": round(b - a, digits)})
    return pd.DataFrame(rows)


def render_comparison(folders, example_folders, labels, token):
    available = {p.name: p for p in folders
                 if (p / "status.json").exists() and json_read(p / "status.json").get("state") == "completed"}
    names = {k: labels.get(k, k) for k in available}
    with st.expander("載入以前下載的結果 ZIP"):
        uploaded = st.file_uploader("信義區結果包", type=["zip"], key="compare_upload")
        if st.button("加入比較清單", disabled=uploaded is None, key="import_comparison"):
            try:
                path = import_comparison_zip(uploaded.getvalue(), token)
                old = st.session_state.get("comparison_imports", [])
                if str(path) not in old:
                    st.session_state["comparison_imports"] = old + [str(path)]
                st.success("結果已載入，可在 A、B 選單選取。")
            except (ValueError, OSError) as exc:
                st.error(str(exc))
    for path in st.session_state.get("comparison_imports", []):
        p = Path(path)
        if not (p / "import_source.json").exists():
            continue
        s = json_read(p / "summary.json")
        r = json_read(p / "request.json")
        available[p.name] = p
        names[p.name] = f"載入結果｜{s['rainfall']['label']}｜排出 {r['drain_mm_h']:g}｜{p.name[:8]}"
    ids = list(available)
    if len(ids) < 2:
        st.info("需要兩筆已完成結果。可以先跑一筆，或載入之前下載的結果 ZIP。")
        return
    chosen = st.session_state.get("result_picker")
    if st.session_state.get("compare_a") not in ids:
        st.session_state["compare_a"] = chosen if chosen in ids else ids[0]
    if st.session_state.get("compare_b") not in ids:
        st.session_state["compare_b"] = next(x for x in ids if x != st.session_state["compare_a"])
    ca, cb = st.columns(2)
    with ca:
        ida = st.selectbox("A · 作為基準", ids, format_func=names.get, key="compare_a")
    with cb:
        idb = st.selectbox("B · 拿來比較", ids, format_func=names.get, key="compare_b")
    field_label = st.radio("比較數值", list(FIELDS), horizontal=True, key="compare_field")
    if st.button("顯示比較", type="primary", key="open_comparison"):
        st.session_state["comparison_open"] = True
    if not st.session_state.get("comparison_open"):
        return
    a, b = available[ida], available[idb]
    field = FIELDS[field_label]
    signature = (ida, idb, field, (a / "summary.json").stat().st_mtime_ns,
                 (b / "summary.json").stat().st_mtime_ns)
    try:
        saved = st.session_state.get("comparison_render")
        if not saved or saved["signature"] != signature:
            with st.spinner("讀取兩筆實際結果…"):
                # Names contain only public identifiers; no local file paths enter the HTML.
                payload = build_comparison(a, b, names[ida], names[idb], field)
                saved = {"signature": signature, "html": comparison_html(payload),
                         "warnings": payload["warnings"] + payload["notes"], "scenarios": payload["scenarios"]}
                st.session_state["comparison_render"] = saved
        if ida == idb:
            st.info("A、B 是同一筆結果；有效格的差值應為 0。")
        sa, sb = [json_read(p / "summary.json") for p in (a, b)]
        if sa["rainfall"]["label"] != sb["rainfall"]["label"]:
            st.warning("兩組降雨不同；差值包含雨量差異，不能當成排水改善效果。")
        elif sa["balance"]["time_s"] != sb["balance"]["time_s"]:
            st.warning("兩組模擬時長不同；結束水深與持續時間的觀察長度也不同。")
        st.iframe(saved["html"], height=830,
                  alt="A 與 B 同尺度地形比較，可同步旋轉、查值及切換差值。")
        table = comparison_table(saved["scenarios"])
        st.dataframe(table, hide_index=True, width="stretch")
        left, right = st.columns(2)
        with left:
            st.download_button("保存互動比較（離線 HTML）", saved["html"].encode("utf-8"),
                               "信義區_情境比較.html", "text/html", key="save_comparison")
        with right:
            metadata = []
            for label, getter in [
                ("結果識別", lambda i: [ida, idb][i]),
                ("名稱", lambda i: names[[ida, idb][i]]),
                ("降雨時間（秒）", lambda i: saved["scenarios"][i]["metrics"]["rain_duration_s"]),
                ("計算時間（秒）", lambda i: saved["scenarios"][i]["metrics"]["simulation_duration_s"]),
                ("假設排出能力（mm/h）", lambda i: saved["scenarios"][i]["request"]["drain_mm_h"]),
                ("暫存（mm）", lambda i: saved["scenarios"][i]["request"]["storage_mm"]),
                ("入滲（mm/h）", lambda i: saved["scenarios"][i]["request"]["infiltration_mm_h"]),
                ("開口面積（m²）", lambda i: saved["scenarios"][i]["request"]["inlet_area_m2"]),
            ]:
                metadata.append({"項目": label, "A": getter(0), "B": getter(1), "B − A": ""})
            metadata.append({"項目": "用途", "A": "假設排水情境比較，非實際淹水預報", "B": "", "B − A": "B 減 A"})
            export = pd.concat([pd.DataFrame(metadata), table], ignore_index=True)
            st.download_button("保存比較表（CSV）", export.to_csv(index=False).encode("utf-8-sig"),
                               "信義區_比較表.csv", "text/csv", key="save_comparison_table")
        with st.expander("兩筆設定與資料核對"):
            for side, folder in [("A", a), ("B", b)]:
                summary = json_read(folder / "summary.json")
                r = json_read(folder / "request.json")
                st.write(f"**{side}** · {summary['rainfall']['label']} · "
                         f"降雨 {summary['rainfall']['rain_end_s'] / 60:g} 分鐘 · "
                         f"退水 {r['recession_min']:g} 分鐘 · 排出 {r['drain_mm_h']:g} mm/h · "
                         f"暫存 {r['storage_mm']:g} mm · 入滲 {r['infiltration_mm_h']:g} mm/h")
            for note in saved["warnings"]:
                st.write(note)
    except (ValueError, OSError, KeyError) as exc:
        st.error(f"無法比較這兩筆結果：{exc}")
