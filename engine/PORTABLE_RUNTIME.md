# 跨平台運算環境

`cloud_runtime.ensure_runtime()` 回傳 `command`、`binary`、`library`、版本、SHA-256 與來源指紋。
執行時使用：`command + [input.bin, output_folder, model.inp, units.csv]`。
API 回傳值必須是 `52004`；其他 SWMM 版本不接受。

## Linux / Streamlit Community Cloud

由 `packages.txt` 安裝 CMake、編譯器與 Mono。第一次運算編譯 `engine/vendor/` 的 EPA 原始碼與既有 C# 地表求解器，快取在專案 `.runtime/`。
之後使用相同來源指紋快取，不重複編譯。建置有跨程序鎖，數值計算以每次獨立程序執行。
Mono 的 `dllmap` 將原本 `swmm5.dll` 呼叫映射至 `libswmm5.so`，Unix 呼叫慣例明確使用 Cdecl。
Linux 入口先把原生檔名轉成絕對路徑，並檢查每條路徑不超過官方 `MAXFNAME=259` 的 UTF-8 位元組上限。
這避開 5.2.4 的 POSIX `realpath` 對小緩衝區不相容分支；保留上游原始碼及作業系統邊界保護，沒有改水理計算。

## Windows 本機

Windows 可設定 `XINYI_SWMM_LIBRARY` 指向已安裝的官方 5.2.4 `swmm5.dll`；或以 `XINYI_CC` 指定現有 GCC，編譯同份原始碼。
這兩種方式都不會修改原始 DLL，不會安裝或改動 Windows 系統。
C# 由 Windows 既有 .NET Framework 64 位元編譯器建置。

## 驗收

`python qa/test_portable_engine.py` 實際執行乾地、降雨、積水、反流、零出口、時間步與高程平移九組小型原生測試。
每組核對完成標記、地表與 SWMM 最後時間、雨量積分、非負水深、水量收支與原生警告。
小型測試是程式與數值守恆檢查，不能代替信義區完整事件、實測校正或淹水預報。
七小時時鐘測試保留 INP 結束時間多兩秒的排程緩衝，交換驅動仍在指定的 25,200 秒停止，沒有多加雨量或放寬驗收。
