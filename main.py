# main.py
import os
import datetime as dt_module  # 標準模組重新命名，防止污染
import re
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
from datetime import datetime  # 全域統一使用類別

# 🔑 完美召喚 Google Sheets 部門的所有核心功能
from services.sheet_service import (
    get_user_mapping_sheet, 
    create_user_worksheet, 
    update_user_calendar, 
    add_user_todo, 
    get_user_todo_values, 
    update_or_delete_todo
)

load_dotenv()
app = FastAPI()

# --- 基礎設定 ---
LINE_CONF = Configuration(access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
HANDLER = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
SCOPE = ["https://www.googleapis.com/auth/calendar"]

GOOGLE_KEY_PATH = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', 'google_key.json')
CREDS = Credentials.from_service_account_file(GOOGLE_KEY_PATH, scopes=SCOPE)

TZ = pytz.timezone('Asia/Taipei')

# --- Google 日曆服務初始化 (試算表初始化已全部搬走) ---
CALENDAR_SERVICE = build('calendar', 'v3', credentials=CREDS)


# --- 1. Cron-job 友善接口 ---
@app.get("/")
async def home():
    return {"status": "小精靈二號機運作中", "uptime": str(datetime.now(TZ))}

@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get('X-Line-Signature')
    body = await request.body()
    try:
        HANDLER.handle(body.decode('utf-8'), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return 'OK'


# --- 2. 定時提醒任務 (08:00 & 21:00) ---
def smart_reminder_job():
    now = datetime.now(TZ)
    users = get_user_mapping_sheet().get_all_records()
    
    if now.hour == 8:
        start_dt = now.replace(hour=12, minute=0, second=0, microsecond=0)
        end_dt = now.replace(hour=23, minute=59, second=59, microsecond=0)
        title = "☀️ 早安報報！今日下午行程："
    elif now.hour == 21:
        tomorrow = now + dt_module.timedelta(days=1)
        start_dt = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = tomorrow.replace(hour=11, minute=59, second=59, microsecond=0)
        title = "🌙 晚安報報！明日上午行程預告："
    else: return

    for user in users:
        u_id, c_id = user['userId'], user['Calendar_ID']
        if not c_id or not u_id: continue
        try:
            events_res = CALENDAR_SERVICE.events().list(
                calendarId=c_id, timeMin=start_dt.isoformat(), timeMax=end_dt.isoformat(),
                singleEvents=True, orderBy='startTime'
            ).execute()
            events = events_res.get('items', [])
            if events:
                report = f"{title}\n"
                for e in events:
                    start = e['start'].get('dateTime', e['start'].get('date'))
                    report += f"• {start[11:16] if 'T' in start else '全天'} {e['summary']}\n"
                with ApiClient(LINE_CONF) as api_client:
                    MessagingApi(api_client).push_message(PushMessageRequest(to=u_id, messages=[TextMessage(text=report.strip())]))
        except: pass

scheduler = BackgroundScheduler(timezone="Asia/Taipei")
scheduler.add_job(smart_reminder_job, 'cron', hour='8,21', minute='0')
scheduler.start()


# --- 3. 新友加入引導 ---
@HANDLER.add(FollowEvent)
def handle_follow(event):
    welcome_msg = """歡迎來到 Rose 的待辦事項專區！✨

我是你的小精靈，能幫你管理多人的雜事與日曆。

🔑 【開通第一步】
請先輸入：我是 [您的姓名]
(例如：我是 Rose)

開通後，我會幫您建立專屬的分頁，並指引您如何連動 Google 日曆喔！"""
    with ApiClient(LINE_CONF) as api_client:
        MessagingApi(api_client).reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=welcome_msg)]))


# --- 4. 訊息處理邏輯 ---
@HANDLER.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    reply_token = event.reply_token 
    user_msg = event.message.text.strip()
    u_id = event.source.user_id
    
    # 透過封裝好的服務取得用戶清單
    user_list = get_user_mapping_sheet().get_all_records()
    current_user = next((u for u in user_list if u['userId'] == u_id), None)

    # A. 註冊邏輯
    if user_msg.startswith("我是"):
        name = user_msg.replace("我是", "").strip()
        if not name: return
        if current_user: 
            reply_text = f"🧐 妳已經註冊過了喔！妳的名字是：{current_user['Name']}"
        elif any(u['Name'] == name for u in user_list): 
            reply_text = f"❌ 抱歉，名字「{name}」已被使用，請換個稱呼吧！"
        else:
            try:
                # 🗃️ 呼叫搬家後的註冊分頁建立服務
                create_user_worksheet(name, u_id)
                reply_text = f"🎉 {name}，歡迎加入！已為您開通分頁。\n\n最後一步：請回傳您的 Google 日曆 ID (通常是您的 Gmail) 給我，並記得把日曆「共用」給我的金鑰 Email 喔！"
            except Exception as e: 
                reply_text = f"創表失敗：{e}"
        
    # B. 設定日曆 ID
    elif "@" in user_msg and "." in user_msg:
        if not current_user: 
            reply_text = "請先輸入「我是 [姓名]」完成註冊喔！"
        else:
            # 🗃️ 呼叫搬家後的日曆欄位更新服務
            update_user_calendar(u_id, user_msg)
            reply_text = f"✅ 日曆設定成功！目前的日曆 ID：{user_msg}\n我會在每日 08:00 與 21:00 為您巡邏行程。"

    # C. 功能邏輯 (已註冊使用者)
    elif current_user:
        user_name, user_calendar = current_user['Name'], current_user['Calendar_ID']

        # 1. 智慧預約
        if user_msg.startswith("預約"):
            try:
                pure_content = user_msg.replace("預約", "").strip()
                date_match = re.search(r'(\d{1,4}[/\-]\d{1,2})|(\d{4})', pure_content)
                time_match = re.search(r'\d{1,2}:\d{2}', pure_content)
                
                if not date_match or not time_match:
                    reply_text = "❌ 格式理解失敗！請確保包含日期與時間。範例：預約 6/25 05:00 起床泡奶"
                else:
                    date_raw = date_match.group()
                    time_raw = time_match.group()
                    task_name = pure_content.replace(date_raw, "").replace(time_raw, "").strip()
                    if not task_name: task_name = "未命名行程"
                    
                    parsed_date = None
                    date_formats = ["%m/%d", "%m-%d", "%m%d", "%Y/%m/%d", "%Y-%m-%d"]
                    for fmt in date_formats:
                        try:
                            parsed_date = datetime.strptime(date_raw, fmt)
                            break
                        except ValueError: continue
                    
                    if not parsed_date: reply_text = "❌ 日期格式無法識別，請輸入如：6/25、06-25 或 0625"
                    elif not user_calendar: reply_text = "❌ 尚未設定日曆 ID，請先回傳 Gmail 帳號。"
                    else:
                        current_year = datetime.now(TZ).year
                        hour_val, min_val = map(int, time_raw.split(':'))
                        start_dt = TZ.localize(datetime(year=current_year, month=parsed_date.month, day=parsed_date.day, hour=hour_val, minute=min_val))
                        end_dt = start_dt + dt_module.timedelta(hours=1)
                        
                        if start_dt.hour < 12: 
                            remind_min = int((start_dt - (start_dt - dt_module.timedelta(days=1)).replace(hour=21, minute=0)).total_seconds() / 60)
                        else: 
                            remind_min = int((start_dt - start_dt.replace(hour=8, minute=0)).total_seconds() / 60)
                        
                        current_time_str = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
                        body = {
                            'summary': task_name,
                            'description': f"=======================\n📅 建立時間：{current_time_str} (台北時間)\n📝 備註事項：透過 LINE 小精靈自動同步\n=======================",
                            'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'Asia/Taipei'},
                            'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'Asia/Taipei'},
                            'reminders': {'useDefault': False, 'overrides': [{'method': 'popup', 'minutes': max(1, remind_min)}]}
                        }
                        CALENDAR_SERVICE.events().insert(calendarId=user_calendar, body=body).execute()
                        reply_text = f"📅 {user_name} 預約成功：{task_name}"
            except Exception as e: 
                reply_text = f"❌ 系統錯誤：{e}"

        # 2. 新增雜事
        elif user_msg.startswith("新增"):
            content = user_msg.replace("新增", "").strip()
            if re.search(r'\d{1,2}[/\-]\d{1,2}|\d{4}', content) or re.search(r'\d{1,2}:\d{2}', content):
                reply_text = "💡 溫馨提示：偵測到您輸入了時間資訊！\n\n這裡的「新增」僅供記錄單純的【待辦雜事】（不會有定時提醒功能喔）。\n\n如果您希望小精靈巡邏並定時提醒您，請改用【預約】功能！\n👉 格式範例：預約 6/20 16:00 看牙醫"
            else:
                tasks = re.split(r'[，,]+', content)
                timestamp_str = datetime.now(TZ).strftime("%m/%d %H:%M")
                for t in tasks:
                    if t.strip(): 
                        # 🗃️ 呼叫搬家後的單純雜事寫入服務
                        add_user_todo(user_name, timestamp_str, t.strip())
                reply_text = f"✅ 已為 {user_name} 記錄雜事。"

        # 3. 查詢行程
        elif user_msg == "查詢":
            try:
                combined_reply = f"🌹 {user_name} 的最新情報：\n"
                # 🗃️ 呼叫搬家後的資料讀取服務
                rows = get_user_todo_values(user_name)
                sheet_tasks = []
                display_count = 0
                for i, row in enumerate(rows):
                    if i == 0: continue
                    if len(row) > 2 and row[2] == "未完成":
                        display_count += 1
                        sheet_tasks.append(f"{display_count}. ⏳ {row[1]}")
                
                combined_reply += "\n📝 【待辦雜事】\n" + ("\n".join(sheet_tasks) if sheet_tasks else "目前沒有雜事喔！")
                
                if user_calendar:
                    now_iso = datetime.now(dt_module.timezone.utc).isoformat().replace('+00:00', 'Z')
                    events = CALENDAR_SERVICE.events().list(calendarId=user_calendar, timeMin=now_iso, maxResults=5, singleEvents=True, orderBy='startTime').execute().get('items', [])
                    combined_reply += "\n\n📅 【近期行程】\n"
                    if not events: combined_reply += "近期沒有排定行程。"
                    else:
                        for e in events:
                            s = e['start'].get('dateTime', e['start'].get('date'))
                            combined_reply += f"• {s[5:10]} {s[11:16]} {e['summary']}\n"
                else: combined_reply += "\n\n📅 【日曆狀態】\n尚未設定日曆 ID。"
                
                combined_reply += f"\n{'-'*15}\n💡 指令小幫手：\n🗑️ 刪除雜事：刪除 [編號]\n❌ 取消行程：取消 [關鍵字]"
                reply_text = combined_reply
            except Exception as e: reply_text = f"查詢失敗：{e}"

        # 4. 完成 / 刪除
        elif any(user_msg.startswith(act) for act in ["完成", "刪除"]):
            action = "完成" if "完成" in user_msg else "刪除"
            try:
                num = int(re.search(r'\d+', user_msg).group())
                # 🗃️ 呼叫搬家後的狀態更新與刪除服務
                success, task_title = update_or_delete_todo(user_name, num, action)
                if success: reply_text = f"✅ 已{action}：{task_title}"
                else: reply_text = f"🧐 找不到編號 {num}"
            except: reply_text = f"❌ 請輸入數字，例如：{action} 1"

        # 5. 取消行程
        elif user_msg.startswith("取消"):
            keyword = user_msg.replace("取消", "").strip()
            if not keyword: reply_text = "❌ 請輸入關鍵字，例如：取消 去機場"
            else:
                try:
                    now_iso = datetime.now(dt_module.timezone.utc).isoformat().replace('+00:00', 'Z')
                    events = CALENDAR_SERVICE.events().list(calendarId=user_calendar, q=keyword, timeMin=now_iso).execute().get('items', [])
                    if events:
                        CALENDAR_SERVICE.events().delete(calendarId=user_calendar, eventId=events[0]['id']).execute()
                        reply_text = f"🗑️ 已從日曆取消：{events[0]['summary']}"
                    else: reply_text = f"🧐 找不到「{keyword}」行程。"
                except Exception as e: reply_text = f"取消失敗：{e}"

        # 6. 預設說明
        else:
            reply_text = f"{user_name} Hi！我是你的待辦事項小精靈。輸入「查詢」看清單，或是「新增 [事項]」來記錄雜事。"
            
    else:
        reply_text = "歡迎初次見面！請先輸入「我是 [您的姓名]」來開始使用喔！"

    with ApiClient(LINE_CONF) as api_client:
        MessagingApi(api_client).reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=reply_text)]))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)