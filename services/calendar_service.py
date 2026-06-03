# services/calendar_service.py
import os
from datetime import datetime
import datetime as dt_module
import pytz
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

TZ = pytz.timezone('Asia/Taipei')

# --- 1. 總開關：建立與 Google Calendar 的連線 (從 main.py 搬過來) ---
SCOPE = ["https://www.googleapis.com/auth/calendar"]
GOOGLE_KEY_PATH = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', 'google_key.json')

CREDS = Credentials.from_service_account_file(GOOGLE_KEY_PATH, scopes=SCOPE)
CALENDAR_SERVICE = build('calendar', 'v3', credentials=CREDS)

# --- 2. 獲取連線實例的接口 (供外部或排程呼叫使用) ---
def get_calendar_service():
    return CALENDAR_SERVICE

# --- 3. 功能積木：純粹負責「塞行程進日曆」的工人 ---
def insert_calendar_event(user_calendar, task_name, start_dt, end_dt, remind_min, current_time_str):
    body = {
        'summary': task_name,
        'description': f"=======================\n📅 建立時間：{current_time_str} (台北時間)\n📝 備註事項：透過 LINE 小精靈自動同步\n=======================",
        'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'Asia/Taipei'},
        'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'Asia/Taipei'},
        'reminders': {
            'useDefault': False, 
            'overrides': [{'method': 'popup', 'minutes': max(1, remind_min)}]
        }
    }
    return CALENDAR_SERVICE.events().insert(calendarId=user_calendar, body=body).execute()

# --- 4. 功能積木：純粹負責「從日曆取消行程」的工人 ---
def delete_calendar_event(user_calendar, keyword):
    now_iso = datetime.now(dt_module.timezone.utc).isoformat().replace('+00:00', 'Z')
    events = CALENDAR_SERVICE.events().list(
        calendarId=user_calendar, q=keyword, timeMin=now_iso
    ).execute().get('items', [])
    
    if events:
        CALENDAR_SERVICE.events().delete(calendarId=user_calendar, eventId=events[0]['id']).execute()
        return True, events[0]['summary']
    return False, None