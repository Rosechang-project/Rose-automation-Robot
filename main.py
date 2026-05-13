import os
import datetime
import re
import gspread
import pytz
from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage, PushMessageRequest
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from apscheduler.schedulers.background import BackgroundScheduler

load_dotenv()
app = FastAPI()

# --- 基礎設定 ---
LINE_CONF = Configuration(access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
HANDLER = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
SCOPE = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/calendar"]
CREDS = Credentials.from_service_account_file("google_key.json", scopes=SCOPE)
TZ = pytz.timezone('Asia/Taipei')

# --- 服務初始化 ---
SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
GS_CLIENT = gspread.authorize(CREDS)
SPREADSHET = GS_CLIENT.open_by_key(SHEET_ID)
CALENDAR_SERVICE = build('calendar', 'v3', credentials=CREDS)

# --- 輔助函式：取得 User_Mapping 分頁 ---
def get_user_mapping_sheet():
    try:
        return SPREADSHET.worksheet("User_Mapping")
    except gspread.exceptions.WorksheetNotFound:
        sheet = SPREADSHET.add_worksheet(title="User_Mapping", rows="100", cols="5")
        sheet.append_row(["Name", "userId", "Calendar_ID", "Status"])
        return sheet

# --- 1. Cron-job 友善接口 (首頁) ---
@app.get("/")
async def home():
    return {"status": "小精靈二號機運作中", "uptime": str(datetime.datetime.now(TZ))}

@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get('X-Line-Signature')
    body = await request.body()
    try:
        HANDLER.handle(body.decode('utf-8'), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return 'OK'

# --- 2. 定時提醒任務 (早上 8 點 & 晚上 9 點) ---
def smart_reminder_job():
    now = datetime.datetime.now(TZ)
    mapping_sheet = get_user_mapping_sheet()
    users = mapping_sheet.get_all_records()
    
    # 決定提醒邏輯
    if now.hour == 8:
        # 早上提醒當天下午 (12:00-23:59)
        start_dt = now.replace(hour=12, minute=0, second=0, microsecond=0)
        end_dt = now.replace(hour=23, minute=59, second=59, microsecond=0)
        title = "☀️ 早安報報！今日下午行程："
    elif now.hour == 21:
        # 晚上提醒隔天上午 (00:00-11:59)
        tomorrow = now + datetime.timedelta(days=1)
        start_dt = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = tomorrow.replace(hour=11, minute=59, second=59, microsecond=0)
        title = "🌙 晚安報報！明日上午行程預告："
    else:
        return

    for user in users:
        u_id = user['userId']
        c_id = user['Calendar_ID']
        if not c_id or not u_id: continue
        
        try:
            events_result = CALENDAR_SERVICE.events().list(
                calendarId=c_id, timeMin=start_dt.isoformat(), timeMax=end_dt.isoformat(),
                singleEvents=True, orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])
            
            if events:
                report = f"{title}\n"
                for e in events:
                    start = e['start'].get('dateTime', e['start'].get('date'))
                    time_str = start[11:16] if 'T' in start else "全天"
                    report += f"• {time_str} {e['summary']}\n"
                
                with ApiClient(LINE_CONF) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    line_bot_api.push_message(PushMessageRequest(to=u_id, messages=[TextMessage(text=report.strip())]))
        except Exception as e:
            print(f"提醒失敗 ({user['Name']}): {e}")

# 設定排程
scheduler = BackgroundScheduler(timezone="Asia/Taipei")
scheduler.add_job(smart_reminder_job, 'cron', hour='8,21', minute='0')
scheduler.start()

# --- 3. 新友加入引導 ---
@HANDLER.add(FollowEvent)
def handle_follow(event):
    welcome_msg = """歡迎來到 Rose 的自動化小天地！✨

我是妳的專屬秘書，能幫妳管理多人的雜事與日曆。

🔑 【開通第一步】
請先輸入：我是 [您的姓名]
(例如：我是 Ace)

開通後，我會幫您建立專屬的分頁，並指引您如何連動 Google 日曆喔！"""
    
    with ApiClient(LINE_CONF) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=welcome_msg)]))

# --- 4. 訊息處理邏輯 ---
@HANDLER.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    reply_token = event.reply_token 
    user_msg = event.message.text.strip()
    u_id = event.source.user_id
    mapping_sheet = get_user_mapping_sheet()
    user_list = mapping_sheet.get_all_records()
    
    # 找尋目前使用者
    current_user = next((u for u in user_list if u['userId'] == u_id), None)

    # --- 邏輯 A：註冊流程 ---
    if user_msg.startswith("我是"):
        name = user_msg.replace("我是", "").strip()
        if not name: return

        if current_user:
            reply_text = f"🧐 妳已經註冊過了喔！妳的名字是：{current_user['Name']}"
        elif any(u['Name'] == name for u in user_list):
            reply_text = f"❌ 抱歉，名字「{name}」已被佔用，請換個稱呼吧！"
        else:
            try:
                # 自動創表
                new_ws = SPREADSHET.add_worksheet(title=name, rows="100", cols="5")
                new_ws.append_row(["時間", "事項", "狀態"])
                mapping_sheet.append_row([name, u_id, "", "待設定日曆"])
                reply_text = f"🎉 {name}，歡迎加入！已為您開通分頁。\n\n最後一步：請回傳您的 Google 日曆 ID (通常是您的 Gmail) 給我，並記得把日曆「共用」給我的金鑰 Email 喔！"
            except Exception as e:
                reply_text = f"創表失敗：{e}"
        
    # --- 邏輯 B：設定日曆 ID ---
    elif "@" in user_msg and "." in user_msg:
        if not current_user:
            reply_text = "請先輸入「我是 [姓名]」完成註冊喔！"
        else:
            # 找到該使用者在那一行 (row)
            all_uids = mapping_sheet.col_values(2)
            row_idx = all_uids.index(u_id) + 1
            mapping_sheet.update_cell(row_idx, 3, user_msg)
            mapping_sheet.update_cell(row_idx, 4, "已開通")
            reply_text = f"✅ 日曆設定成功！目前的日曆 ID：{user_msg}\n我會在每日 08:00 與 21:00 為您巡邏行程。"

    # --- 邏輯 C：雜事與日曆功能 (需先註冊) ---
    elif current_user:
        user_name = current_user['Name']
        user_calendar = current_user['Calendar_ID']
        u_worksheet = SPREADSHET.worksheet(user_name)

        # 這裡放入妳原本的新增、查詢、刪除、預約邏輯...
        # 記得把原本程式碼中的 `worksheet` 改成 `u_worksheet`
        # `MY_CALENDAR_ID` 改成 `user_calendar`
        
        # --- (以下簡化示範「新增」邏輯，其餘依此類推) ---
        if user_msg.startswith("新增"):
            content = user_msg.replace("新增", "").strip()
            tasks = re.split(r'[，,]+', content)
            now_str = datetime.datetime.now(TZ).strftime("%m/%d %H:%M")
            for t in tasks:
                if t.strip(): u_worksheet.append_row([now_str, t.strip(), "未完成"])
            reply_text = f"✅ 已為 {user_name} 記錄雜事。"
        
        elif user_msg == "查詢":
            # 妳原本強大的查詢邏輯... (記得切換 user_calendar)
            reply_text = f"這是 {user_name} 的查詢結果..." # 實作細節略，同妳原本代碼
        
        else:
            reply_text = f"{user_name} 妳好！我是妳的雙刀流秘書。輸入「查詢」看清單，或是「新增 [事項]」來記錄雜事。"
            
    else:
        reply_text = "歡迎初次見面！請先輸入「我是 [您的姓名]」來開始使用喔！"

    # 回覆訊息
    with ApiClient(LINE_CONF) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=reply_text)]))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)