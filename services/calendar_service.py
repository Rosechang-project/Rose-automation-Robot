# services/calendar_service.py
import datetime as dt_module
import os
from datetime import datetime

import pytz
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

load_dotenv()

TZ = pytz.timezone("Asia/Taipei")
SCOPE = ["https://www.googleapis.com/auth/calendar"]
GOOGLE_KEY_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "google_key.json")

_calendar_service = None


def get_calendar_service():
    global _calendar_service
    if _calendar_service is None:
        creds = Credentials.from_service_account_file(GOOGLE_KEY_PATH, scopes=SCOPE)
        _calendar_service = build("calendar", "v3", credentials=creds)
    return _calendar_service


def insert_calendar_event(user_calendar, task_name, start_dt, end_dt, remind_min, current_time_str):
    body = {
        "summary": task_name,
        "description": (
            "=======================\n"
            f"建立時間：{current_time_str}（由 LINE Bot 建立）\n"
            "提醒來源：Rose 行程管理機器人\n"
            "======================="
        ),
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "Asia/Taipei"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": "Asia/Taipei"},
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": max(1, remind_min)}],
        },
    }
    return get_calendar_service().events().insert(calendarId=user_calendar, body=body).execute()


def delete_calendar_event(user_calendar, keyword):
    now_iso = datetime.now(dt_module.timezone.utc).isoformat().replace("+00:00", "Z")
    events = (
        get_calendar_service().events()
        .list(calendarId=user_calendar, q=keyword, timeMin=now_iso)
        .execute()
        .get("items", [])
    )

    if events:
        get_calendar_service().events().delete(calendarId=user_calendar, eventId=events[0]["id"]).execute()
        return True, events[0]["summary"]
    return False, None
