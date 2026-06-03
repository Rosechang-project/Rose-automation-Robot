Markdown
# 🌹 LINE 智慧雜事日曆小精靈
### `Two-Way Scheduler Bot v2.5`

一款專為多人團隊、多用戶設計的 **LINE 智慧待辦與 Google 日曆雙向同步系統**。  
專案採用現代化微服務（Microservices）架構設計，將網路櫃檯、字串分析邏輯、試算表資料庫與日曆 API 徹底解耦，具備高度的永續擴充性與極致的 Clean Code 表現。

---

## 🚀 專案亮點與核心功能

- **👤 多用戶專屬隔離空間**：新用戶加入後輸入「我是 [姓名]」，系統會自動在後台 Google Sheets 為該用戶建立「個人獨立分頁」，確保資料完全隱私與隔離。
- **📅 雙向日曆同步 (智慧雷達版)**：支援自然語言輸入（例如 `預約 6/18 09:00 吃米粉湯`），系統內建正則表達式雷達，自動解析時間、時區（Asia/Taipei）並寫入 Google Calendar，同時提供智慧防呆彈性提醒。
- **📝 純雜事備忘錄**：輸入 `新增 買牛奶`，可記錄非定時的待辦事項，並支援 `查詢`、`完成 1`、`刪除 1` 等互動管理。
- **⏰ 背景巡邏鬧鐘**：採用 `APScheduler` 定時引擎，每日固定於 **08:00 (早安報報)** 與 **21:00 (晚安報報)** 主動推播巡邏用戶的 Google 日曆行程。

---

## 🏗️ 系統模組化架構 (Software Architecture)

本專案歷經重大架構重構 (Refactoring)，全面落實「職責分離 (Separation of Concerns)」心法，專案結構如下：

```text
├── main.py                 # FastAPI 網路櫃檯，全心負責 Webhook 監聽與生命週期管理
├── scheduler.py            # 獨立背景排程引擎，負責定時巡邏廣播任務
├── google_key.json         # Google Service Account 安全憑證 (已加入 .gitignore)
├── .env                    # 環境變數保險箱
└── services/
    ├── __init__.py         # 模組合法營業執照 (保持空白)
    ├── sheet_service.py    # Google Sheets 服務專家 (封裝所有 Excel 讀寫邏輯)
    ├── calendar_service.py # Google Calendar 服務專家 (封裝日曆插入/刪除與時區計算)
    └── line_service.py     # LINE 指揮官 (封裝所有字串分析與商業 If-Else 邏輯)
💎 重構特點
✨ 極致瘦身主控台：將 main.py 精簡至約 40 行，使其轉職為純粹的 Router 櫃檯。

✨ 現代化生命週期管理：全面升級為 FastAPI 官方推薦的 @asynccontextmanager (lifespan) 機制，取代過時的舊寫法，確保背景排程器優雅啟停。

✨ 無死代碼環境：嚴格落實 Clean Imports 規範，全面清除未使用的工具包，避免全域污染。

🛠️ 開發套件與技術棧

Backend Framework: FastAPI (Uvicorn)

Database / Storage: Google Sheets API (gspread)

Integration: Google Calendar API, LINE Messaging API SDK v3

Task Scheduling: APScheduler

Timezone Defense: pytz (Asia/Taipei)

💻 本地啟動與部署 (Quick Start)
想要在本地環境測試或運行本專案，請遵循以下步驟：

1. 複製專案並進入目錄
Bash
git clone <妳的GitHub專案網址>
cd <專案資料夾名稱>
2. 建立並啟用虛擬環境 (venv)
Bash
python -m venv venv

# Windows 啟用命令：
.\venv\Scripts\activate

# macOS/Linux 啟用命令：
source venv/bin/activate
3. 安裝依賴套件
Bash
pip install fastapi uvicorn gspread google-api-python-client apscheduler pytz line-bot-sdk python-dotenv
4. 配置環境變數 (.env)
在根目錄建立 .env 檔案並填入您的金鑰：

Ini, TOML
LINE_CHANNEL_ACCESS_TOKEN=your_access_token
LINE_CHANNEL_SECRET=your_secret
GOOGLE_SHEET_ID=your_spreadsheet_id
GOOGLE_APPLICATION_CREDENTIALS=google_key.json
5. 啟動伺服器
Bash
python main.py
🤝 如何與小精靈互動 (Commands)
本系統內建強大的自然語言分析與智慧防呆，可接受以下指令：

💡 初次開通：我是 [您的姓名] (例如：我是 Rose) ➔ 自動建立專屬 Sheets 分頁

🔑 綁定日曆：[您的Gmail/日曆ID] (例如：rose@gmail.com) ➔ 設定同步目標

📝 新增雜事：新增 買牛奶, 繳電費 ➔ 支援逗號多筆同時寫入備忘錄

📅 智慧預約：預約 6/18 09:00 吃米粉湯 ➔ 自動解析日期時間並同步 Google 日曆，且內建巡邏防呆提醒

🔍 綜合查詢：查詢 ➔ 一鍵撈取 Sheets 未完成雜事與近期前 5 筆日曆行程

🗑️ 管理雜事：完成 [編號] 或 刪除 [編號] (例如：完成 1)

❌ 取消行程：取消 [日曆關鍵字] (例如：取消 吃米粉湯) ➔ 直接從 Google 日曆無損拔除行程