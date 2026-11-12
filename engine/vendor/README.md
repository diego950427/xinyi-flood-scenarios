# EPA SWMM 5.2.4 原始碼

本資料夾保留美國 EPA 官方求解器原始碼，未修改其水理演算法。

- 上游：https://github.com/USEPA/Stormwater-Management-Model
- 版本：`v5.2.4`
- commit：`7952ca837988b1c32f791812eccc9fd64547e093`
- 官方版本壓縮檔：https://codeload.github.com/USEPA/Stormwater-Management-Model/zip/refs/tags/v5.2.4
- 壓縮檔 SHA-256：`148ab36f6dfda9d8871233dbcd33516d592d1eb4ff0977ce3ea284c2ea8dbea0`
- 取得日期：2026-11-12
- 原始碼逐檔 SHA-256：`source_manifest.json`

上游 README 明示 C 原始碼為 Public Domain；保留上游完整 README 與免責說明。
本研究與 EPA 沒有認證或背書關係。

Linux 由 `cloud_runtime.py` 使用 CMake 編譯這份固定來源，不在每次模擬下載遠端程式。
依官方 CMake 偵測編譯器的 OpenMP 支援；模型仍明訂 `THREADS 1`，與既有單執行緒設計一致。
Streamlit 的系統相依套件由專案根目錄 `packages.txt` 宣告。
