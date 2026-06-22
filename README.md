# Rose 的代辦事項小精靈 ✨

`Two-Way Scheduler Bot` 是一個住在 LINE 裡的小精靈，幫大家記待辦、排日曆、查清單，還會在固定時間巡邏 Google Calendar，提醒接下來的行程。

使用者可以透過 LINE 完成註冊、記錄雜事、預約行程、查詢清單，也可以完成或刪除待辦、取消 Calendar 上的未來行程。

## 小精靈會做什麼

- 💬 LINE Webhook：用 FastAPI 接收 LINE callback。
- 🔑 使用者開通：輸入 `我是 Rose` 後，會在 Google Sheets 建立個人分頁。
- 📝 待辦雜事：用 `新增` 把雜事記到 Google Sheets。
- 📅 智慧預約：用 `預約` 把行程寫進 Google Calendar。
- 🌹 查詢清單：一次看未完成待辦和近期行程。
- ☀️ / 🌙 行程提醒：每天 08:00 和 21:00 用 LINE push message 提醒。
- 🕘 時區：全部使用 `Asia/Taipei`。

## 專案結構

```text
main.py                     # FastAPI 入口、LINE webhook、cron trigger endpoint
scheduler.py                # 每天 08:00 / 21:00 的行程提醒任務
requirements.txt            # Python 套件依賴
README.md                   # 小精靈使用說明
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
CRON_SECRET=your_private_cron_secret
```

`google_key.json` 是 Google Service Account 金鑰檔，請不要提交到 Git。

`CRON_SECRET` 是保護 `/cron/reminder` 用的密碼。Render 和觸發提醒的外部服務要設定同一組值。

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

開通小精靈：

```text
我是 Rose
```

綁定 Google Calendar ID 或 Gmail：

```text
user@example.com
```

新增待辦雜事：

```text
新增 買牛奶、整理簡報
```

新增 Google Calendar 行程：

```text
預約 6/25 09:00 開會
```

查詢未完成待辦與接下來 5 筆行程：

```text
查詢
```

完成或刪除第 1 筆未完成待辦：

```text
完成 1
刪除 1
```

取消未來行程中第一筆標題包含關鍵字的事件：

```text
取消 開會
```

## Render 不要睡著

Render 免費方案閒置時會睡著，所以需要外部 cron job 定期敲一下首頁。

建議使用 cron-job.org，每 10 分鐘打一次：

```text
https://rose-automation-robot.onrender.com/
```

這個 job 只是叫醒 Render，不會觸發提醒。

## 提醒推播

小精靈會在台北時間：

```text
08:00 檢查今天 12:00 到 23:59 的行程
21:00 檢查明天 00:00 到 11:59 的行程
```

如果 Render 當時醒著，APScheduler 會自動送提醒。

更保險的做法是另外設定一個外部 cron，在 `08:05` 和 `21:05` 主動呼叫提醒端點：

```text
POST https://rose-automation-robot.onrender.com/cron/reminder
Header: X-Cron-Secret: your_private_cron_secret
```

這個端點需要 `CRON_SECRET`，避免其他人亂觸發 LINE 推播。

## 資料表

系統會使用 `User_Mapping` 工作表紀錄使用者：

```text
Name | userId | Calendar_ID | Status
```

每位使用者會另外建立一張以使用者名稱命名的工作表：

```text
時間 | 任務 | 狀態
```
