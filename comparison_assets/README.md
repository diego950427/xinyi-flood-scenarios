# Offline comparison viewer

`comparison_view.comparison_html(payload)` embeds the stylesheet, renderer,
official Three.js distribution and base64 grids into one offline HTML document.
It does not call any network service or run a model. Use the comparison_data v1
payload. Streamlit can embed it with `st.iframe(html, height=830)`; the document
scrolls on narrow screens. No `scrolling` argument is needed.

The existing navy palette and system Chinese fonts are inherited. Desktop maps
are side by side, each 440 px tall. At widths of 650 px or less they stack, each
300 px tall. Difference view is one map, 420 px tall on narrow screens. Labels,
legend and picked values remain visible; optional controls contain the longer
interaction explanation. No new section subtitles are added.

Each actual active 20 m cell is a constant-height terrain square. There is no
interpolation, resampling, water-surface geometry, lighting that changes data
colors, or animation. World coordinates are shifted by the supplied origin to
protect GPU precision; pick values use the original projected coordinates.
Z is actual relative terrain height with a fixed 1:1 vertical scale.

Both maps use one camera state and one color scale. Depth defaults to 0–100 cm;
values beyond 100 cm retain the endpoint color and the legend explicitly says
≥100 cm. Select 完整範圍 to include all extremes. Difference defaults to ±100 cm
with a zero-centered scale; full-range is symmetric. Picking always returns the
unclipped actual value. Payload/diagnostic values remain in metres/seconds;
visible depth is centimetres and visible time is hours. Time fields use their
shared complete range. Never-crossed cells are not converted to zero or included
in time differences; picking identifies them as 未超過 10 cm.

The default view fits the actual reporting-mask bounds (Xinyi), with a shared
10% margin. 範圍 switches to 整個計算域 without discarding any cells. Reset fits
the selected extent again. The two-map shared view includes its extent choice.

兩筆條件 retains each result's actual rainfall label, rain/simulation/recession
duration and drainage/storage/infiltration assumptions. The supplied warnings
and notes stay readable there after an offline download, together with the full
Three.js MIT license. Different rainfall or simulation durations also trigger a
short visible warning. Historical mode never interprets unused custom defaults
as the actual rainfall. Maximum depth is explicitly labeled 各格最大，非同時.

Mouse: drag pans 2D; drag rotates 3D; Shift+drag pans 3D. Touch: one finger follows
the same behavior, two fingers pan/pinch. Buttons zoom. Focus a map and use arrow
keys to pan, Shift+arrow keys to rotate 3D, +/- to zoom and R to reset. Native
number fields provide keyboard access to every row/column. Wheel scroll is left
to the page. All rendering is requested on data/control/resize changes only.

If WebGL is unavailable or its context is lost, both maps switch to ordinary 2D
canvas. Picking, comparison, scales, pan, zoom and region boundaries remain.
There is also an explicit 相容模式 button under 操作.

## Browser diagnostic API

`window.__xinyiComparison` is available after initialization:

- `getState()` gives `ready`, renderer (`webgl`/`canvas2d`), revision, row/column
  counts, active cell count, render count, pending-frame status, both camera
  poses/frustums, shared view state, original and effective scales, errors and
  the latest pick. A failure returns `ready:false` and an error.
- `pickCell(row, col)` uses **zero-based** indices and returns original metre /
  second values, difference B−A, projected XY, terrain elevation, masks and unit.
- `projectCell('a'|'b', row, col)` returns client coordinates for a native-cell
  center. `pickAt('a'|'b', clientX, clientY)` uses the real raycast/canvas picker.
- `setView({mode:'2d'|'3d', display:'compare'|'difference', panX, panY, span,
  azimuth, tilt})` updates shared camera state. Wait one animation frame before
  querying projected coordinates/cameras. `reset()` resets the camera.
- `setScale('focus'|'full')` switches the shared range. `forceFallback()` invokes
  the real canvas fallback. These controls do not alter payload arrays.
- `setExtent('district'|'domain')` fits Xinyi or the entire computation domain;
  `getState().view.extent` reports the selection.

## Vendored dependency

Three.js **0.180.0**, MIT, unmodified standalone CommonJS build; the adapter
captures its exports in an inline closure. Full license: `LICENSE-THREE.txt`.

- Build: https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.cjs
- Official source tag: https://github.com/mrdoob/three.js/tree/r180
- License: https://raw.githubusercontent.com/mrdoob/three.js/r180/LICENSE
- `three-0.180.0.cjs`: 2,006,834 bytes, SHA-256
  `2980c5831824f46d79a39a93feb70dd851538ce5b5480a6463883b319022c51f`
- `LICENSE-THREE.txt`: 1,081 bytes, SHA-256
  `bfe119ea4fd413f5f7ca3fcd63adb0c4a073ed39daa2fe7d3e6b769e21272601`

No CDN is contacted when a delivered viewer is opened. The source URLs above
are attribution and reproducibility metadata, not runtime script imports.
