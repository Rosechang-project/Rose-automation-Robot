# services/calendar_service.py
import os
from datetime import datetime
from threading import local

import pytz
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

TZ = pytz.timezone("Asia/Taipei")
SCOPE = ["https://www.googleapis.com/auth/calendar"]
GOOGLE_KEY_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "google_key.json")

_connection = local()


def get_calendar_service():
    if not hasattr(_connection, "service"):
        creds = Credentials.from_service_account_file(GOOGLE_KEY_PATH, scopes=SCOPE)
        _connection.service = build("calendar", "v3", credentials=creds)
    return _connection.service


def insert_calendar_event(user_calendar, event_id, task_name, start_dt, end_dt, remind_min, current_time_str):
    body = {
        "id": event_id,
        "summary": task_name,
        "description": (
            "=======================\n"
            f"建立時間：{current_time_str}（由 LINE Bot 建立）\n"
            "提醒來源：Rose 行程管理機器人\n"
            "======================="
        ),
        "start": {"dateTime": start_dt, "timeZone": TZ.zone},
        "end": {"dateTime": end_dt, "timeZone": TZ.zone},
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": max(1, remind_min)}],
        },
    }
    try:
        get_calendar_service().events().insert(calendarId=user_calendar, body=body).execute()
    except HttpError as exc:
        if exc.resp.status != 409:
            raise


def event_start(event):
    start = event["start"]
    if "dateTime" in start:
        return datetime.fromisoformat(start["dateTime"]).astimezone(TZ)
    return TZ.localize(datetime.fromisoformat(start["date"]))


def event_title(event):
    return event.get("summary") or "未命名行程"


def event_time_text(event, *, include_date=False):
    start = event_start(event)
    if "dateTime" not in event["start"]:
        return f"{start:%m/%d} 全天" if include_date else "全天"
    return start.strftime("%m/%d %H:%M" if include_date else "%H:%M")


def list_events(user_calendar, start, *, end=None, keyword=None):
    events = get_calendar_service().events()
    params = {
        "calendarId": user_calendar,
        "timeMin": start.isoformat(),
        "singleEvents": True,
        "orderBy": "startTime",
        "timeZone": TZ.zone,
    }
    if end:
        params["timeMax"] = end.isoformat()
    if keyword:
        params["q"] = keyword
    request = events.list(**params)
    while request is not None:
        page = request.execute()
        yield from page.get("items", [])
        request = events.list_next(request, page)


def find_cancellation_candidates(user_calendar, keyword, now):
    keyword_folded = keyword.casefold()
    for event in list_events(user_calendar, now, keyword=keyword):
        title = event.get("summary") or ""
        if keyword_folded in title.casefold() and event_start(event) > now:
            yield event


def get_cancellation_candidate(user_calendar, event_id, now):
    try:
        event = get_calendar_service().events().get(calendarId=user_calendar, eventId=event_id).execute()
    except HttpError as exc:
        if exc.resp.status in {404, 410}:
            return None
        raise
    if (
        event.get("status") != "cancelled"
        and not event.get("recurrence")
        and "start" in event
        and event_start(event) > now
    ):
        return event
    return None


def delete_calendar_event(user_calendar, event_id, etag):
    request = get_calendar_service().events().delete(calendarId=user_calendar, eventId=event_id)
    if etag:
        request.headers["If-Match"] = etag
    try:
        request.execute()
    except HttpError as exc:
        if exc.resp.status == 412:
            return False
        if exc.resp.status not in {404, 410}:
            raise
    return True
