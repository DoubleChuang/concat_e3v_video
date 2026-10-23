# 自動更新（檢查更新）設計

日期：2026-10-23
狀態：已實作

## 問題

GUI 使用者拿到的是 PyInstaller 產物，沒有套件管理器可以更新。每次改版都要回 GitHub Release
手動找對應平台檔案、解壓、覆蓋。要有「說明 → 檢查更新」：

1. 知道目前版本，向 GitHub Releases 找最新正式版
2. 有新版就顯示更新說明，一鍵下載
3. 下載完自動替換執行檔並重新啟動（至少 Windows / Linux / macOS 都要能）

## 平台限制（重點）

| 平台 | 能不能全自動 | 做法 |
|---|---|---|
| Windows | 可以 | 執行中的 `.exe` 被鎖住，寫 `.bat` 等行程結束 → `move /y` → `start` |
| Linux | 可以 | 單檔執行檔可直接 atomic replace（`os.replace`），舊 inode 由執行中行程持有 |
| macOS | 可以，但要整包換 | 換 `Contents/MacOS/...` 會讓 ad-hoc 簽章失效，必須整個 `.app` 換掉；由 shell script 等行程結束 → `mv` → `xattr -dr` → `open` |

以原始碼執行（`sys.frozen == False`）不提供自動替換：直接改使用者 checkout 的原始碼風險太高，
只顯示版本資訊與下載頁面。

未來若要 Apple 公證 / Developer ID 簽章，macOS 更新器的規則會更嚴（更新檔本身要被信任），
那時應改用 Sparkle（EdDSA 簽章）而不是自己寫 shell script。

## 架構

沿用專案的分層慣例，更新功能自成一包 `app/updater/`，domain 不 import PySide6、不做 I/O：

```
app/updater/
  version.py    Version（semver 解析 / 比較）
  models.py     Target / Asset / Release / UpdatePlan / InstallOutcome
  targets.py    平台正規化 + release 檔名對照
  errors.py     UpdateError 家族
  ports.py      ReleaseSource / Downloader / Installer（Protocol）
  service.py    UpdateService：check() → download() → apply()
  github.py     GitHub Releases 轉接器（urllib，含 JSON→domain 純函式）
  download.py   HttpDownloader（串流、進度、sha256 / size 驗證、重試）
  installers.py Linux / macOS / Windows 安裝器（腳本產生為純函式）
  factory.py    依目前平台組裝 service
```

簡報層（Qt）：

```
app/ui/update_worker.py     UpdateCheckWorker / UpdateApplyWorker（QThread + signals）
app/ui/update_dialog.py     UpdateAvailableDialog / DownloadProgressDialog
app/ui/update_presenter.py  流程控制：檢查 → 對話框 → 下載 → 套用 → 重啟
app/ui/update_menu.py       說明選單（HomeWindow 是 QWidget、MainWindow 是 QMainWindow）
```

## 流程

1. `UpdatePresenter.check()` 開執行緒呼叫 `UpdateService.check()`
2. `GitHubReleaseSource` 讀 `https://api.github.com/repos/.../releases/latest`
3. `Version` 比較目前版本；沒有新版 → 手動檢查顯示「已是最新版本」，自動檢查靜默
4. 有新版 → `Release.asset_for(Target)` 找對應檔名；找不到 → 顯示「這個平台沒有檔案」並開 release 頁
5. 使用者按「下載並更新」→ 另一條執行緒 `download()` → `apply()`
6. 下載時以 GitHub asset 的 `digest: sha256:...` 驗證，大小或雜湊不符就失敗且不留半個檔
7. `apply()` 依平台替換；`InstallOutcome.restart_required` 為真 → 顯示訊息後重啟

## 設定

| key | 預設 | 說明 |
|---|---|---|
| `update_auto_check` | true | 啟動 3 秒後自動檢查（`app/main.py` 的 `QTimer.singleShot`） |

## 測試

新增 `tests/test_updater_*.py` 與 `tests/test_update_*.py`：

- Version 比較（10 > 9、prerelease < release、rc.10 > rc.2）
- 平台正規化與 asset 對照（含不支援平台）
- GitHub JSON 解析、404 / 離線錯誤映射
- 下載器：進度、雜湊不符、大小不符、重試
- Service：up-to-date / 有新版 / 平台不支援 / 下載路徑
- 安裝器：Linux 替換與 rollback、Windows / macOS 腳本內容與跳脫、權限不足退回手動
- 選單與 presenter：手動/自動檢查、下載流程、失敗處理、忙碌時停用選單

全部使用假物件，不碰網路、不需要 GUI 顯示。
