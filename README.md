# 信義區降雨與地表積水情境研究

[開啟公開模擬器](https://xinyi-flood-scenarios.streamlit.app/) · [程式與資料](https://github.com/diego950427/xinyi-flood-scenarios) · [Linux 原生驗證](https://github.com/diego950427/xinyi-flood-scenarios/actions)

選歷史大雨，或輸入總雨量與降雨時間，讓 **EPA SWMM 5.2.4** 和二維地表求解器實際計算。預設為 2024/7/10 信義周邊九站雨量；另外三場為臺北站移植雨型，介面逐項標明。

這是條件式情境研究。20 公尺地形、雨量與行政區界來自公開資料；322 個排水單元的開口、暫存、排出能力是假設。**沒有完整真實管網，也沒有校正成淹水預報或發生機率。**

## 使用

1. 選「歷史大雨事件」，或輸入總雨量、分鐘數與雨型。
2. 保留預設排水參數，或改一項來比較。
3. 按「開始這次模擬」，保留頁面等待。歷史雨型可能需要數十分鐘，依伺服器而異。
4. 完成後看水深圖、超過 10 公分的面積變化、水量收支；下載結果 ZIP，可直接用 QGIS 開 `result.qgs`。

範例是先前已完成的本機原生計算，明示其來源；修改輸入不會偷偷套用範例數值。新模擬必須真正完成求解並通過檢查才顯示成功。

## 方法與界線

- 89,394 格參與運算，每格 20 × 20 m；信義區 28,097 格用於統計。
- 降雨只加入地表一次；地表使用 HLL 通量與靜水重建。依水位差與 SWMM 交換，允許回流。
- 排水單元依公開管線附近的低格選點；單元彼此獨立，沒有補造真實管線連接。
- 水深圖是各格的「全時段最大值」，不代表同時積水。曲線則是當時超過 10 cm 的面積。
- 曾出現數公尺的少數極值，尚未經現地驗證；介面同時顯示 99 百分位並警示，不能用來判斷個別建物安全。
- 「收支通過」僅代表數值水量帳一致，不等同現地水深準確。

## 部署

Streamlit Community Cloud：儲存庫 `diego950427/xinyi-flood-scenarios`，分支 `main`，入口 `app.py`，**Python 3.12**。`requirements.txt` 與 `packages.txt` 宣告相依套件；沒有 API key，無須 secrets。

Linux 首次運算會由已附的 EPA 官方原始碼編譯 SWMM，Mono 執行同一套 C# 地表程式。編譯及每次求解各有獨立紀錄，沒有偷偷下載另一個求解器。跨平台驗證見 GitHub Actions；部署和正式跑完的狀態以實際紀錄為準。

免費主機一次只跑一組。不同工作階段隔離結果與停止權限；重整頁面會建立新工作階段。雲端硬碟是暫存，休眠／重啟後可能失去結果，請下載。運算上限 2 小時；未完成不會列成功。不是保證持久保存的運算平台。

本機 Linux：安裝 `packages.txt` 中的套件，再執行：

```sh
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address 127.0.0.1
```

Windows 可用既有官方 SWMM 5.2.4 DLL 的環境變數 `XINYI_SWMM_LIBRARY`，或提供 GCC `XINYI_CC`；不需要 THMC。

## 原始資料與授權

詳見 [DATA_SOURCES.md](DATA_SOURCES.md)、[資料清冊](data/source_manifest.json) 與 `third_party/`。原始數值、整理步驟和限制分開保存。圖表由 Lieflat Charts 範本改寫，相關部分遵守其非商業授權；不將整個第三方程式冒充本專案著作。

## 可重跑檢查

```sh
python qa/test_portable_engine.py
python qa/test_cloud_app.py
python qa/data_release_audit.py
```

驗證涵蓋原生版本、時鐘、水量守恆、雙向交換、輸入防呆、圖表真實數據及工作階段隔離。完整域實驗另外保存，沒有以小型測試冒充全區驗證。
