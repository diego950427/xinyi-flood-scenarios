"""Only draw actual computed arrays. No invented flood footprint or flow arrows."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from backend import DATA, BG, INK, ACCENT, load_grid, json_read

COLORS = ["#102744", "#255f88", "#2998bb", "#73cae1", "#efb94d", "#e5654b"]
EDGES_CM = [0, 1, 5, 10, 30, 50, 10000]


def coordinates(geometry):
    kind, coords = geometry["type"], geometry["coordinates"]
    if kind == "Polygon":
        return coords
    if kind == "MultiPolygon":
        return [ring for poly in coords for ring in poly]
    if kind == "LineString":
        return [coords]
    if kind == "MultiLineString":
        return coords
    return []


def map_figure(grid, field="max_depth_m", show_units=False):
    _, active, report, _, tf = load_grid()
    x = tf.c + (np.arange(grid.shape[1]) + .5) * tf.a
    y = tf.f + (np.arange(grid.shape[0]) + .5) * tf.e
    is_depth = "depth" in field
    a = np.where(active & (grid >= 0), grid * (100 if is_depth else 1 / 3600), np.nan)
    if is_depth:
        scale = []
        for i in range(6):
            lo, hi = EDGES_CM[i] / 100, min(EDGES_CM[i + 1], 100) / 100
            scale += [[lo, COLORS[i]], [hi, COLORS[i]]]
        zmax, label = 100, "水深 cm"
        titles = {"max_depth_m": "模擬期間各格最大水深", "final_depth_m": "模擬結束時水深"}
        title = titles.get(field, field)
    else:
        scale = [[0, "#102744"], [.5, "#2998bb"], [1, "#efb94d"]]
        zmax, label = max(float(np.nanmax(a)), 1), "小時"
        title = "超過 10 公分的累積時間"
    fig = go.Figure(go.Heatmap(
        x=x, y=y, z=a, zmin=0, zmax=zmax, colorscale=scale,
        colorbar=dict(title=dict(text=label, side="top"), orientation="h", x=.5, xanchor="center",
                      y=-.25, len=.9, thickness=14,
                      tickvals=[1, 10, 30, 50, 100] if is_depth else None,
                      ticktext=["1", "10", "30", "50", "≥100"] if is_depth else None),
        hovertemplate="東向 %{x:.0f} m<br>北向 %{y:.0f} m<br>" + label + "：%{z:.2f}<extra></extra>",
        name=title,
    ))
    boundary = json_read(DATA / "xinyi_boundary.geojson")
    for feature in boundary["features"]:
        for ring in coordinates(feature["geometry"]):
            xy = np.asarray(ring)
            fig.add_trace(go.Scatter(x=xy[:, 0], y=xy[:, 1], mode="lines",
                                    line=dict(color="#edeff1", width=2), name="信義區界",
                                    showlegend=False, hoverinfo="skip"))
    if show_units:
        units = json_read(DATA / "virtual_units.json")
        fig.add_trace(go.Scatter(
            x=[u["x"] for u in units], y=[u["y"] for u in units], mode="markers",
            marker=dict(size=5, color="#f1b745", line=dict(width=.5, color="#081f5c")),
            name="假設交換單元", text=[f"假設單元 {u['id']}（非實測雨水口）" for u in units],
            hovertemplate="%{text}<extra></extra>"))
    fig.update_layout(title=title, height=420, paper_bgcolor=BG, plot_bgcolor=BG,
                      font=dict(color=INK, family="Microsoft JhengHei, sans-serif", size=15),
                      margin=dict(l=5, r=5, t=45, b=65), dragmode="pan", showlegend=show_units,
                      legend=dict(orientation="h", y=1.08),
                      xaxis=dict(title=None, showgrid=False, constrain="domain",
                                 range=[float(x.min()), float(x.max())], nticks=5),
                      yaxis=dict(title="北向（公尺）", scaleanchor="x", showgrid=False, constrain="domain",
                                 range=[float(y.min()), float(y.max())], nticks=5))
    return fig


def rainfall_figure(req):
    from backend import forcing
    _, active, report, _, _ = load_grid()
    edges, rates, station, meta = forcing(req, active)
    counts = np.bincount(station[report], minlength=rates.shape[1])
    means = rates.dot(counts / counts.sum()) * 1000 * 3600
    center = (edges[1:] + edges[:-1]) / 7200
    fig = go.Figure(go.Bar(x=center, y=means, width=np.diff(edges) / 3600,
                          marker_color=ACCENT, name="區內平均雨強",
                          hovertemplate="開始後 %{x:.2f} 小時<br>%{y:.1f} mm/h<extra></extra>"))
    fig.update_layout(title="這次輸入的降雨", xaxis_title="開始後（小時）", yaxis_title="雨強 mm/h",
                      height=240, paper_bgcolor=BG, plot_bgcolor=BG, font=dict(color=INK, size=14),
                      margin=dict(l=5, r=5, t=40, b=5), bargap=0)
    total = float(np.dot(means, np.diff(edges) / 3600))
    return fig, total, meta


def history_figure(folder):
    frame = pd.read_csv(Path(folder) / "native/history.csv")
    fig = go.Figure()
    for col, label, color in [
        ("xinyi_area_gt10_km2", "當時超過 10 公分的面積", "#9ebfe9"),
    ]:
        fig.add_trace(go.Scatter(x=frame.time_s / 3600, y=frame[col], name=label,
                                mode="lines", line=dict(color=color, width=3)))
    fig.update_layout(title="當時超過 10 公分的面積", xaxis_title="開始後（小時）",
                      yaxis_title="平方公里", height=300, paper_bgcolor=BG, plot_bgcolor=BG,
                      font=dict(color=INK), margin=dict(l=5, r=5, t=45, b=5))
    return fig


def export_png(folder, grid, summary):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.colors import ListedColormap, BoundaryNorm
    from matplotlib import font_manager
    available = {f.name for f in font_manager.fontManager.ttflist}
    plt.rcParams["font.family"] = [f for f in ["Microsoft JhengHei", "Noto Sans CJK TC", "Noto Sans CJK JP", "DejaVu Sans"] if f in available]
    _, active, _, _, tf = load_grid()
    fig, ax = plt.subplots(figsize=(11, 9), facecolor=BG)
    ax.set_facecolor(BG)
    arr = np.ma.masked_where(~active | (grid < 0), grid * 100)
    extent = [tf.c, tf.c + grid.shape[1] * tf.a, tf.f + grid.shape[0] * tf.e, tf.f]
    ax.imshow(arr, extent=extent, cmap=ListedColormap(COLORS),
              norm=BoundaryNorm(EDGES_CM, len(COLORS)), interpolation="nearest")
    for feature in json_read(DATA / "xinyi_boundary.geojson")["features"]:
        for ring in coordinates(feature["geometry"]):
            xy = np.asarray(ring)
            ax.plot(xy[:, 0], xy[:, 1], color=INK, linewidth=1)
    from matplotlib.patches import Patch
    labels = ["≤1 cm", "1–5 cm", "5–10 cm", "10–30 cm", "30–50 cm", ">50 cm"]
    legend = ax.legend(handles=[Patch(color=c, label=l) for c, l in zip(COLORS, labels)],
                       loc="upper left", facecolor=BG, labelcolor=INK, framealpha=.95)
    ax.set_title("信義區｜SWMM 等效排水＋地表情境\n各格最大水深；非同時積水範圍、非真實預報",
                 color=INK, fontsize=17, pad=18)
    ax.tick_params(colors=INK)
    ax.set_xlabel("TWD97 東向（公尺）", color=INK)
    ax.set_ylabel("北向（公尺）", color=INK)
    fig.text(.08, .02, "20 m 地形｜等效單元非實測管網｜" + summary["rainfall"]["label"],
             color=INK, fontsize=10)
    fig.tight_layout(rect=(0, .04, 1, 1))
    fig.savefig(Path(folder) / "max_depth.png", dpi=160, facecolor=BG)
    plt.close(fig)
