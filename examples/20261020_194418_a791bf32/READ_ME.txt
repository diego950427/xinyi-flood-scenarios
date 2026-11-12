信義區條件式 SWMM＋二維地表結果

QGIS：直接開 result.qgs；max_depth_m.tif 與 xinyi_boundary.geojson 必須保留在旁邊。
圖層值的單位為公尺，每格 20 × 20 公尺；最大值不是同時水深。
這不是校正後預報。排水單元、開口和出口能力是假設，不是真實管網。
是否通過數值檢查請看 summary.json 的 passed 與 checks，不以有圖判斷。

重現：在相同版本專案 使用 request.json 的同一組參數。
native/model.inp 單獨執行不會重現：聯動程式會逐步提供地表交換水位。
本包保存結果與原生證據，不是完整可攜的程式環境。
