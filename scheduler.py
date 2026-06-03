# scheduler.py
import os
import pytz
import datetime as dt_module
from datetime import datetime
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, PushMessageRequest, TextMessage

# 🔑 跨部門呼叫：需要試算表來抓 user，需要日曆來抓行程
from services.sheet_service import get_user_mapping_sheet
from services.calendar_service import get_calendar_service

load_dotenv()

# --- 基礎通訊配置 ---
LINE_CONF = Configuration(access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
TZ = pytz.timezone('Asia/Taipei')
CALENDAR_SERVICE = get_calendar_service()

def smart_reminder_job():
    now = datetime.now(TZ)
    # 🗃️ 透過轉接頭向試算表部門要最新的人員名單
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
    else: 
        return

    for user in users:
        u_id, c_id = user['userId'], user['Calendar_ID']
        if not c_id or not u_id: 
            continue
        try:
            # 📅 透過轉接頭向日曆部門撈取該時段的事件清單
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
                
                # 💬 發送 LINE 推播通知
                with ApiClient(LINE_CONF) as api_client:
                    MessagingApi(api_client).push_message(
                        PushMessageRequest(to=u_id, messages=[TextMessage(text=report.strip())])
                    )
        except Exception as e:
            print(f"[Scheduler Error] 發送失敗: {e}")
            pass

# ⚙️ 初始化排程引擎並提供給 main.py 啟動
def setup_scheduler():
    scheduler = BackgroundScheduler(timezone="Asia/Taipei")
    scheduler.add_job(smart_reminder_job, 'cron', hour='8,21', minute='0')
    return scheduler