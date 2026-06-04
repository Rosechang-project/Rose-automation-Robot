# Rose 行程管理機器人

`Two-Way Scheduler Bot` 是一個整合 LINE、Google Sheets 與 Google Calendar 的行程/待辦管理 bot。

使用者可以透過 LINE 註冊、建立待辦、建立行程、查詢清單，也可以完成或刪除待辦、取消 Calendar 上的未來行程。系統會在每天 08:00 和 21:00 自動推播行程提醒。

## 功能

- LINE Webhook：使用 FastAPI 接收 LINE callback。
- 使用者註冊：註冊後會在 Google Sheets 建立個人工作表。
- 待辦管理：待辦寫入 Google Sheets，可查詢、完成、刪除。
- 行程管理：行程寫入 Google Calendar，可用關鍵字取消。
- 定時提醒：APScheduler 每天固定檢查 Calendar 並用 LINE push message 提醒。
- 時區：預設使用 `Asia/Taipei`。

## 專案結構

```text
main.py                     # FastAPI 入口與 LINE webhook
scheduler.py                # 每天 08:00 / 21:00 的行程提醒任務
requirements.txt            # Python 套件依賴
README.md                   # 專案說明
services/
  __init__.py
  line_service.py           # LINE 事件處理與指令解析
  sheet_service.py          # Google Sheets 使用者/待辦資料操作
  calendar_service.py       # Google Calendar 行程操作
```

## 環境變數

請建立 `.env`：

```ini
LINE_CHANNEL_ACCESS_TOKEN=your_access_token
LINE_CHANNEL_SECRET=your_channel_secret
GOOGLE_SHEET_ID=your_spreadsheet_id
GOOGLE_APPLICATION_CREDENTIALS=google_key.json
```

`google_key.json` 是 Google Service Account 金鑰檔，請不要提交到 Git。

## 安裝

```bash
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

## 啟動

```bash
python main.py
```

服務會啟動在：

```text
http://localhost:8000
```

LINE webhook callback URL 請設定為：

```text
https://你的公開網址/callback
```

本機開發時可搭配 ngrok 或其他 tunnel 服務。

## LINE 指令

```text
註冊 Rose
```

建立使用者，並在 Google Sheets 建立個人待辦工作表。

```text
user@example.com
```

綁定 Google Calendar ID 或 Gmail。

```text
待辦 買牛奶、整理簡報
```

新增一筆或多筆待辦到 Google Sheets。

```text
行程 6/25 09:00 開會
```

新增一筆 Google Calendar 行程，預設長度 1 小時。

```text
查詢
```

查詢未完成待辦與接下來 5 筆行程。

```text
完成 1
刪除 1
```

完成或刪除第 1 筆未完成待辦。

```text
取消 開會
```

取消未來行程中第一筆標題包含「開會」的 Google Calendar 事件。

## 資料表

系統會使用 `User_Mapping` 工作表紀錄使用者：

```text
Name | userId | Calendar_ID | Status
```

每位使用者會另外建立一張以使用者名稱命名的工作表：

```text
時間 | 任務 | 狀態
```
