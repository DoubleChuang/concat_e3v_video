# 設計：靜音局部重編（檔案前綴）

日期：2026-10-22
狀態：設計已由使用者核准（方案：檔案前綴重編；前置並行、合併依序）。
2026-10-22 修正：有剩餘檔案時前綴改輸出 `.ts`，final concat 加 `aac_adtstoasc`；
`convert_filename_to_datetime` 改用設定的時區解讀檔名。

## 動機

目前勾選「靜音前 N 秒」時，`VideoProcessor._build_concat_cmd` 會對整個合併後的長影片加上
`volume=0.0:enable='lt(t,N)'` 並以 AAC 重編**整條音軌**。影片雖是 stream copy，但音訊解碼與
重編仍耗費大量 CPU 與時間。

目標：只處理受靜音影響的部分，其餘音訊完全不重編；多個輸出群組的前置處理可並行，最後再
以 stream copy 合併。輸出檔名、靜音長度、影音同步與既有行為不變。

## 現況摘要

- `e3vvid/video_processor.py`
  - `find_continous_video()` 依檔名時間戳將來源 `.TS` 分組；每組輸出一個 MP4。
  - `_build_concat_cmd()`：`mute_seconds > 0` 時使用
    `-c:v copy -af volume=0.0:enable='lt(t,N)' -c:a aac`；否則 `-c copy`。
  - `concat()`：逐組建立 videolist、Popen ffmpeg、支援 `cancel_event`，任一失敗回傳 `[]`。
- 打包版（`build/app.spec`）只內建 `ffmpeg`，**沒有** `ffprobe`。
- 來源為 E3V 連續錄影，檔名 `YYYYMMDDHHMMSS_*.TS`，通常約 1 分鐘一段。
- 既有測試 98 passed。

## 設計

### 1. 流程（每個輸出群組）

`mute_seconds == 0`：完全維持現有 `-c copy` 路徑，不做任何探測。

`mute_seconds > 0`：

1. **探測**：使用 `self._ffmpeg_bin` 對群組內檔案執行 `ffmpeg -hide_banner -i <file>`，
   從 stderr 解析 `Duration:` 與第一條 `Audio:` 串流（codec、profile、sample rate、channels）。
   依序探測到累積長度足夠為止；音訊參數取前綴第一個檔案。
2. **選前綴**：依序累加每個檔案的長度，直到累積長度 `>= N + 0.5s`（安全邊界），
   得到「覆蓋前 N 秒所需的最短前綴」。前綴至少包含第一個檔案；若 N 超過整組總長，
   前綴等於全部檔案，且整組音訊都會被靜音。
3. **前綴重編**：只對前綴執行
   `-c:v copy -af volume=0.0:enable='lt(t,N)' -c:a aac -ar <sr> -ac <ch> -profile:a aac_low`
   輸出暫存 MP4。影片不重編；音訊只重編前綴（約 N 再加不到一個檔的時間）。
4. **最後合併**：
   - 有剩餘檔案：建立 final list（前綴暫存 MP4 + 其餘原始 TS），
     執行 `ffmpeg -f concat -safe 0 -i final_list -c copy <輸出>.mp4`。
   - 沒有剩餘檔案：前綴直接輸出成最終檔，不再多一次 concat。
5. **並行**：所有群組的前綴重編用 `ThreadPoolExecutor(max_workers=max(1, min(4, os.cpu_count() or 1)))`
   同時執行；最終 concat 依序執行，避免磁碟讀寫亂序。
6. **取消**：`cancel_event` 設置時，殺掉所有執行中的子程序、等待 `communicate()` 收尾、
   回傳 `[]`。

### 2. 音訊參數與相容性

- 只接受 `aac` + profile `LC`（或未標示 profile）的來源走快速路徑。
- 以前綴第一個檔案的參數產生 `-ar`、`-ac`、`-profile:a aac_low`，讓重編後的前綴與其餘
  原始 AAC 串流參數一致。
- 若剩餘檔案非空，額外探測剩餘第一個檔案；codec／profile／sample rate／channels
  任一不一致則不走快速路徑。
- 前綴在**沒有剩餘檔案**時直接輸出最終 `.mp4`；**有剩餘檔案**時輸出暫存 `.ts`，
  讓前綴與原始 TS 的 time base 一致，final concat 才能安全 `-c copy`。
- final concat 加 `-bsf:a aac_adtstoasc`，把 TS 的 ADTS AAC 轉成 MP4 需要的 raw AAC。

### 3. Fallback（正確性優先）

下列任一情況，該群組改用現有「整條音軌重編」指令（`_build_concat_cmd`）：

- `Duration` 無法解析（`N/A`）或檔案探測失敗。
- 音訊不是 AAC LC。
- 前綴與剩餘檔案的音訊參數不一致。
- 前綴重編失敗。
- 最後 concat 失敗。

Fallback 仍使用既有的 `-c:v copy -af volume=0.0:enable='lt(t,N)' -c:a aac`，輸出檔名不變。
Fallback 在合併階段依序執行，避免與其他群組搶 CPU/IO。

### 4. 資料流

```
find_continous_video() ──▶ groups（每組 list of "file '...'"）
                              │
                    probe 每個群組的前幾個檔案
                              │
                     ┌────────┴────────┐
                快速路徑可行       不可行/失敗
                     │                 │
        前綴音訊重編（並行）      整條音軌重編（依序）
                     │                 │
        前綴暫存 + 其餘 TS ──▶ concat -c copy ──▶ 最終 _muted.mp4
```

### 5. 指令形狀

前綴（範例）：

```
ffmpeg -y -f concat -safe 0 -i prefix_list.txt \
  -c:v copy \
  -af "volume=0.0:enable='lt(t,10)'" \
  -c:a aac -ar 48000 -ac 2 -profile:a aac_low \
  /tmp/.../prefix0.ts
```

最後合併（範例）：

```
ffmpeg -y -f concat -safe 0 -i final_list.txt -c copy \
  -bsf:a aac_adtstoasc <dst>/<name>_muted.mp4
```

Fallback：與現有 `_build_concat_cmd` 相同（整組 list、`-c:v copy`、volume filter、`-c:a aac`）。

### 6. 錯誤處理

- 探測失敗、非 AAC LC、參數不一致：記錄 log，該群組走 fallback。
- 前綴失敗：記錄 log，該群組走 fallback。
- final concat 失敗：記錄 log，該群組走 fallback。
- fallback 也失敗：維持現行行為，整體回傳 `[]`。
- 取消：不執行 fallback；殺掉子程序後回傳 `[]`。
- 暫存檔一律放在 `tempfile.TemporaryDirectory()` 內，結束或例外時自動清除。

### 7. 邊界情況

- `N = 0`：走既有 `-c copy` 路徑，不探測、不建立前綴。
- 單檔群組：前綴即該檔、無剩餘檔案；影片 copy、該檔音訊重編（約 1 分鐘），直接輸出 MP4。
- `N >= 群組總長`：前綴等於全部檔案、整組音訊靜音，直接輸出最終檔。
- `merge_all=True` 且有時間 gap：以實際探測的累積長度選前綴，不依牆鐘時間推估。
- 來源檔案為空或損壞：探測失敗 → fallback；fallback 仍失敗 → 回傳 `[]`。

### 8. 測試

- `_parse_ffmpeg_info`（純函式）：
  - 解析 `Duration: 00:01:00.00`、`Audio: aac (LC), 48000 Hz, stereo, ...`。
  - `Duration: N/A`、非 AAC、HE-AAC、未知聲道 → 回傳不可用。
- 前綴規劃（monkeypatch `_probe_media`）：
  - N 在首檔內、跨多檔、N ≥ 總長、`merge_all` 有 gap。
  - 探測失敗、非 AAC、前後參數不一致 → fallback。
- 指令建構：
  - 前綴含 `-c:v copy`、精確的 `volume=0.0:enable='lt(t,N)'`、`-c:a aac`、`-ar`、`-ac`。
  - final concat 使用 `-c copy`。
  - fallback 與現有 `_build_concat_cmd` 行為一致。
- `concat()` 流程（fake `Popen` / fake `_probe_media`）：
  - 快速路徑：先跑前綴、再跑 final concat，回傳 `_muted.mp4`。
  - 無剩餘檔案：前綴直接輸出最終檔。
  - 前綴失敗 → fallback；final concat 失敗 → fallback。
  - 取消：殺掉執行中的程序、回傳 `[]`。
  - 多群組：前綴都先執行，final concat 依序執行。
- 整合測試（偵測不到 ffmpeg 時 skip）：
  - 產生 3 個短 TS（各 2 秒、帶音調），靜音 1 秒。
  - 驗證輸出存在、0.5s 無聲、1.5s／2.5s／5.5s 有聲、影音 duration 差距 ≤ 0.25 秒。
  - 完整解碼輸出（`ffmpeg -v warning -i out -f null -`），不得出現 `aac bitstream error`。
- 既有 98 個測試全部維持通過。

## 不變更

- UI（`app/ui/main_window.py`）、`app/pipeline.py`、`app/worker.py` 介面與行為。
- `VideoProcessor.concat(cancel_event=None) -> list[str]` 簽章與回傳語意。
- 輸出檔名規則（`%Y_%m_%dT%H:%M:%S_muted.mp4`）、上傳流程、YouTube 相關功能。
- 不新增第三方依賴；不打包 `ffprobe`。
- `mute_seconds == 0` 的既有快速路徑。

## 風險與取捨

- 前綴以「檔案邊界」為單位，重編量是 N 向上取到檔案邊界（約 N + 不到 1 個檔），
  不是精確的 N 秒；但**輸出靜音長度仍精確為 N 秒**。
- 前綴與其餘檔案之間會有 AAC 接縫；整合測試驗證影音同步、接縫後音量與完整解碼。
  前綴有剩餘檔案時必須輸出 `.ts`（與原始 TS 同 time base），final concat 再加
  `aac_adtstoasc`；混合 MP4 前綴與 TS 會造成 audio time base 膨脹與 ADTS 錯誤。
- 此修正同時讓 `convert_filename_to_datetime` 以設定的時區（`pytz.localize`）
  解讀檔名，避免主機時區造成測試與實際檔名偏移。
- TS 的 `Duration` 可能不精確；以 0.5 秒安全邊界與 fallback 控制風險。
- 並行只用在 CPU 較重的前綴重編；最終合併維持依序，避免 HDD/SD 卡亂序。
