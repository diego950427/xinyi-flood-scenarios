"""Extend the V1 research report with a local simulation workspace."""
from pathlib import Path
import json
import uuid
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from backend import (
    ROOT, DATA, RUNS, events, json_read, validate_request, start_job, active_job,
    status_of, cancel_job, run_folder, visible_runs, owner_key,
)
from visuals import map_figure
from charts import rainfall_html, history_html, budget_html

st.set_page_config(page_title="信義區｜自己選雨、自己試算", layout="wide")
st.html("""<!--
THESIS: Rain selection and actual run evidence lead; no decorative dashboard or fake forecast.
OWN-WORLD: Inherits V1 navy, pale-blue controls, high-contrast Chinese UI and real maps.
STORY: Choose a past storm or enter rain; start one job; see progress, depth and assumptions.
FIRST VIEWPORT: Title, two-mode input at left, rain preview at right, one explicit run button.
FORM: Narrow extension of established V1, prescribed input-run-results workflow; no concept seed.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, and DESIGN.md
-->""")
st.markdown("""<style>
.stApp{font-family:"Microsoft JhengHei",system-ui,sans-serif}
.stMainBlockContainer{max-width:1440px;padding-top:2.3rem}
h1{font-size:2rem!important}h2{font-size:1.45rem!important}
p,label,[data-testid="stCaptionContainer"]{line-height:1.65}
[data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] p{color:#c5d3e6!important}
[data-testid="stAlert"] p{color:#edeff1!important}
button:focus-visible,input:focus-visible{outline:3px solid #b9d6ff!important;outline-offset:2px}
@media(max-width:700px){.stMainBlockContainer{padding-left:1rem;padding-right:1rem}}
</style>""", unsafe_allow_html=True)
st.title("信義區｜自己選雨、自己試算")
st.write("先選一場大雨，或自己設定雨量與時間；計算完成後看哪裡容易留水。")
st.info("情境研究：真實 20 公尺地形＋降雨資料，搭配假設排水單元。不是完整真實管網，也不是淹水預報或發生機率。")
st.caption("第一次可以先看下方的已完成範例，再自行試算。完整歷史雨型需要較長時間；雲端休眠或重啟會清除暫存，成果請下載保存。")
run_action = st.empty()

if not (DATA / "events.json").exists():
    st.error("尚未準備資料。請先使用專案的安裝／檢查入口，不能以空白地圖代替計算。")
    st.stop()

current_job = active_job()
if "owner_token" not in st.session_state:
    st.session_state["owner_token"] = uuid.uuid4().hex + uuid.uuid4().hex
token = st.session_state["owner_token"]
own_job = current_job and current_job.get("owner") == owner_key(token)
if "pending_result_run" in st.session_state:
    finished_run = st.session_state.pop("pending_result_run")
    st.session_state["selected_run"] = finished_run
    st.session_state["result_picker"] = finished_run
if own_job:
    st.session_state["monitored_run"] = current_job["id"]
    st.session_state["job_seen_state"] = "running"
mode_label = st.radio("降雨來源", ["歷史大雨事件", "自己輸入雨量"], horizontal=True, key="mode")
mode = "historical" if mode_label == "歷史大雨事件" else "custom"
catalog = events()
left, right = st.columns([.42, .58], gap="large")
with left:
    st.subheader("設定這場雨")
    if mode == "historical":
        event_id = st.selectbox("選擇歷史事件", [e["id"] for e in catalog],
                               format_func=lambda v: next(e["label"] for e in catalog if e["id"] == v),
                               key="event_id")
        selected = next(e for e in catalog if e["id"] == event_id)
        st.caption(selected["note"])
        total_mm, duration_min, rain_shape = 100.0, 60, "uniform"
    else:
        event_id = catalog[0]["id"]
        total_mm = st.number_input("總雨量（mm）", min_value=0.0, max_value=300.0,
                                   value=100.0, step=10.0, key="rain_total")
        duration_min = st.number_input("降雨時間（分鐘）", min_value=10, max_value=360,
                                       value=60, step=10, key="rain_duration")
        shape_label = st.selectbox("雨怎麼下", ["平均下完", "中間最強"], key="rain_shape")
        rain_shape = "uniform" if shape_label == "平均下完" else "middle_peak"
        st.caption(f"平均雨強：{total_mm / (duration_min / 60):.1f} mm/h。總雨量不是每小時雨量。")
    recession = st.select_slider("雨停後繼續觀察（分鐘）", options=[0, 30, 60, 120, 180],
                                 value=60, key="recession")
    st.subheader("假設的排水能力")
    drain = st.select_slider("排出能力（等效 mm/h）", options=[0, 15, 30, 60, 100],
                              value=30, key="drain")
    st.caption("只換算到假設單元的服務面積；水要先流到交換點才能進去，不是直接從每格扣除。")
    with st.expander("進階假設（不知道就保留預設）"):
        storage = st.number_input("到達地表前的等效暫存量（mm）", 1.0, 100.0, 20.0, 5.0, key="storage")
        opening = st.number_input("每個假設開口面積（m²）", .01, 1.0, .2, .01, key="opening")
        infil = st.number_input("均勻入滲假設（mm/h）", 0.0, 30.0, 0.0, 1.0, key="infil")
        st.caption("入滲和排水分開計算，避免重複扣水。暫存量、開口面積與排出能力均非現地量測。")
    request = dict(mode=mode, event_id=event_id, total_mm=float(total_mm),
                   duration_min=float(duration_min), rain_shape=rain_shape,
                   recession_min=float(recession), drain_mm_h=float(drain),
                   storage_mm=float(storage), inlet_area_m2=float(opening),
                   infiltration_mm_h=float(infil), exchange_cap_s=1.0)
    valid = True
    try:
        request = validate_request(request)
    except ValueError as exc:
        valid = False
        st.error(str(exc))
    if run_action.button("開始這次模擬", type="primary", width="stretch", disabled=bool(current_job) or not valid,
                 key="start_run"):
        try:
            rid = start_job(request, token)
            st.session_state["selected_run"] = rid
            st.session_state["result_picker"] = rid
            st.session_state["monitored_run"] = rid
            st.session_state["job_seen_state"] = "queued"
            st.rerun()
        except (ValueError, RuntimeError) as exc:
            st.error(str(exc))
    st.caption("伺服器每次只跑一組。計算時保留此分頁；重新整理會建立新的工作階段。調整選項不會自動重跑。")
    if current_job and not own_job:
        st.warning("有人正在使用求解器，請等這組結束再開始。下方範例仍可查看。")
with right:
    if valid:
        rainchart, total, rainmeta = rainfall_html(request)
        components.html(rainchart, height=480, scrolling=False)
        st.write(f"信義區平均輸入 **{total:.1f} mm**；降雨資料時段 **{rainmeta['rain_end_s'] / 3600:g} 小時**。")
        if mode == "historical":
            st.caption("圖中是信義區網格按面積加權的雨強。九站事件保留空間差異；移植雨型全區使用同一站。")
    design = json_read(DATA / "unit_design.json")
    st.write(f"計算方式：**降雨落地 → 地表流動 → {design['unit_count']} 個假設交換點 → SWMM 暫存與排出**。")
    st.caption("水位過高可反流到地表。交換點按公開管線附近的位置分組選定，不能當實際雨水口；單元彼此沒有假造接管。")


@st.fragment(run_every="2s" if current_job else None)
def progress_panel():
    job = active_job()
    rid = job["id"] if job and job.get("owner") == owner_key(token) else st.session_state.get("monitored_run")
    if not rid:
        if current_job and not job:
            st.rerun()  # Refresh busy controls when another visitor's job ends.
        return
    status = status_of(rid)
    state = status["state"]
    if state in ("queued", "running", "finishing"):
        st.subheader("正在計算")
        fraction = min(.99, status.get("time_s", 0) / max(status.get("end_s", 1), 1))
        st.progress(fraction, text=status["message"])
        if "time_s" in status:
            st.caption(f"已模擬 {status['time_s'] / 3600:.2f}／{status['end_s'] / 3600:.2f} 小時；這不是電腦等待時間。")
        if st.button("停止這次計算", key="cancel_run"):
            cancel_job(rid, token)
            st.warning("已送出停止要求；保留紀錄，不會刪除先前成果。")
    elif st.session_state.get("job_seen_state") in ("queued", "running", "finishing"):
        st.session_state["job_seen_state"] = state
        # A fragment cannot mutate an already-instantiated selectbox in this run.
        st.session_state["pending_result_run"] = rid
        st.rerun()


progress_panel()
st.divider()
st.subheader("看已經跑過的結果")
personal_folders = visible_runs(token)
example_folders = sorted([p for p in (ROOT / "examples").glob("*") if (p / "summary.json").exists()], reverse=True)
folders = personal_folders + example_folders
if not folders:
    st.write("還沒有這個版本的計算。上方選好事件後，按「開始這次模擬」。")
    st.caption("不拿第一版的舊結果冒充 SWMM 聯動結果。")
else:
    labels = {}
    completed_ids = []
    for folder in folders:
        s = json_read(folder / "status.json")
        if s["state"] == "completed":
            completed_ids.append(folder.name)
        r = json_read(folder / "request.json")
        title = (next((e["label"] for e in catalog if e["id"] == r.get("event_id")), "歷史事件")
                 if r["mode"] == "historical" else f"{r['total_mm']:g} mm／{r['duration_min']:g} 分鐘")
        names = {"completed": "完成", "failed_qa": "數值未通過", "failed": "失敗",
                 "cancelled": "已停止", "queued": "準備", "running": "計算中", "finishing": "整理"}
        prefix = "已完成範例" if folder in example_folders else names.get(s['state'], s['state'])
        labels[folder.name] = f"{prefix}｜{title}｜排出 {r['drain_mm_h']:g}｜{folder.name}"
    ids = [f.name for f in folders]
    default_result = completed_ids[0] if completed_ids else ids[0]
    chosen = st.session_state.get("selected_run", default_result)
    if chosen not in ids:
        chosen = default_result
    if st.session_state.get("result_picker") not in ids:
        st.session_state["result_picker"] = chosen
    rid = st.selectbox("選擇計算紀錄", ids, index=None, format_func=labels.get, key="result_picker")
    if rid is None:
        st.info("請選擇一筆計算紀錄。")
        st.stop()
    folder = next(p for p in folders if p.name == rid)
    is_example = folder in example_folders
    s = json_read(folder / "status.json") if is_example else status_of(rid)
    if s["state"] == "completed":
        summary = json_read(folder / "summary.json")
        st.success("這筆已完成計算與數值檢查。下面是這筆紀錄，不是上方尚未執行的新設定。")
        if is_example:
            st.caption("預先完成範例：來自本機 V2 的原生求解結果。不是剛才在雲端新跑的，也不會假裝套用你上方改過的參數。")
        r = summary["request"]
        st.caption(f"這筆使用：{summary['rainfall']['label']}；排出 {r['drain_mm_h']:g} mm/h；暫存 {r['storage_mm']:g} mm；"
                   f"開口 {r['inlet_area_m2']:g} m²；入滲 {r['infiltration_mm_h']:g} mm/h。")
        stat = pd.DataFrame({
            "在這組假設下": ["曾超過 5 公分", "曾超過 10 公分", "曾超過 30 公分"],
            "信義區面積（平方公里）": [round(summary[f"area_ever_gt{x}_km2"], 4) for x in [5, 10, 30]],
        })
        st.dataframe(stat, hide_index=True, width="stretch")
        st.caption("「曾超過」會收集整段模擬中的位置，不代表這些地方同時積水，更不是淹水機率。")
        if summary["max_depth_m"] > 2:
            st.warning(f"少數格有較大極值：區內最大 {summary['max_depth_m']:.2f} m，"
                       f"但 99% 網格不超過 {summary['p99_depth_m']:.2f} m。"
                       "極值尚未驗證，仍須檢查地形與邊界條件，不能當成實際預測水深。")
        maplabel = st.radio("地圖顯示", ["最大水深", "結束時水深", "超過 10 公分多久"], horizontal=True, key="map_field")
        field = {"最大水深": "max_depth_m", "結束時水深": "final_depth_m",
                 "超過 10 公分多久": "duration_gt10_s"}[maplabel]
        show_units = st.checkbox("顯示假設交換點（不是實測雨水口）", key="show_units")
        grids = np.load(folder / "grids.npz")
        st.plotly_chart(map_figure(grids[field], field, show_units), width="stretch", height=420,
                        key="depth_chart", config={"displaylogo": False, "scrollZoom": False},
                        alt="信義區及周邊的情境水深網格；白線是信義區界。")
        st.caption("白線是信義區界；外圍仍參與計算。可縮放、移動和查值。每格 20 × 20 公尺；橫軸為 TWD97 東向公尺。")
        components.html(history_html(folder), height=470, scrolling=False)
        st.subheader("水去了哪裡")
        b = summary["balance"]
        budget = pd.DataFrame({
            "全計算域水量項目": ["降雨輸入", "入滲", "地表外框流出", "SWMM 排出", "最後留在地表", "最後留在 SWMM"],
            "立方公尺": [round(b[k], 1) for k in ["rain_m3", "infiltration_m3", "boundary_out_m3",
                                               "drain_m3", "surface_stored_m3", "native_stored_m3"]],
        })
        st.dataframe(budget, hide_index=True, width="stretch")
        components.html(budget_html(summary), height=490, scrolling=False)
        st.caption(f"聯動收支差 {summary['combined_error_pct']:.5f}%；SWMM 原生收支差 {b['native_flow_error_pct']:.5f}%。"
                   "收支通過代表數值帳算得一致，不代表現地水深已驗證。")
        download1, download2, download3 = st.columns(3)
        with download1:
            st.download_button("下載結果包（含 QGIS）", (folder / "results.zip").read_bytes(),
                               file_name=rid + "_results.zip", mime="application/zip")
        with download2:
            st.download_button("另存水深圖", (folder / "max_depth.png").read_bytes(),
                               file_name=rid + "_depth.png", mime="image/png")
        with download3:
            st.download_button("另存水量時間表", (folder / "native/history.csv").read_bytes(),
                               file_name=rid + "_history.csv", mime="text/csv")
        st.caption("雲端成果請下載保存；服務重啟後不保證保留。結果只會列在建立它的工作階段。")
        st.caption("用 QGIS 打開 result.qgs；整個結果資料夾要保留。SWMM 的 model.inp 需配合交換驅動，單獨開它不會重現地表聯動。")
    elif s["state"] in ("failed", "failed_qa", "cancelled"):
        st.error(s["message"])
        if (folder / "summary.json").exists():
            q = json_read(folder / "summary.json")
            st.write("未通過項目：", [k for k, v in q["checks"].items() if not v])
        st.caption("計算編號：" + rid)
    else:
        st.write("這筆尚未完成。請看上方進度，或選另一筆已完成紀錄。")

with st.expander("這個版本能回答什麼？資料來源在哪裡？"):
    st.write("可以比較同一地形下，不同雨量、雨型與假設排水能力造成的地表留水差異。不能確認某條真實水管超載、真實人孔冒水或某地址必然淹水。")
    st.write("地形：既有內政部 20 m DTM；雨量：既有民生公共物聯網／氣象資料整理。管線只用 XY 覆蓋，不使用未確認的管底高程或斷端補接。")
    st.write("每個 200 m 分組在公開管線 60 m 範圍內選低格作假設交換點。等效單元地底深 2 m，暫存面積依你設定的暫存量換算，入口係數 0.6；這些都是情境設計。")
    st.write("SWMM 5.2.4 計算等效單元水位與雙向開口流量，既有二維淺水求解器計算地表流動。降雨只加在地表一次，入滲與 SWMM 排出分開記帳。")
    st.markdown("[EPA SWMM 說明](https://www.epa.gov/water-research/storm-water-management-model-swmm) · "
                "[雨量來源入口](https://history.colife.org.tw/)")
    st.markdown("[程式、資料來源與測試紀錄](https://github.com/diego950427/xinyi-flood-scenarios)")
