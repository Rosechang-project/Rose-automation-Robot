# scheduler.py
import datetime as dt_module
import logging
import os
from datetime import datetime
from threading import Lock
from uuid import NAMESPACE_URL, uuid5

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from linebot.v3.messaging import ApiClient, Configuration, MessagingApi, PushMessageRequest, TextMessage
from linebot.v3.messaging.exceptions import ApiException

from services.calendar_service import event_time_text, event_title, list_events
from services.sheet_service import authorized_calendar, get_users, read_bot_state, store_bot_state

load_dotenv()

LINE_CONF = Configuration(access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
TZ = pytz.timezone("Asia/Taipei")
LOGGER = logging.getLogger(__name__)
_reminder_lock = Lock()


def smart_reminder_job():
    with _reminder_lock:
        return send_reminders(datetime.now(TZ))


def send_reminders(now):
    summary = {"users": 0, "events": 0, "sent": 0, "skipped": 0, "errors": 0}
    if now.hour == 8:
        start_dt = now.replace(hour=12, minute=0, second=0, microsecond=0)
        end_dt = start_dt + dt_module.timedelta(hours=12)
        title = "☀️ 早安報報！今日下午行程："
    elif now.hour == 21:
        tomorrow = now + dt_module.timedelta(days=1)
        start_dt = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt + dt_module.timedelta(hours=12)
        title = "🌙 晚安報報！明日上午行程預告："
    else:
        return {**summary, "reason": "outside_reminder_window"}

    try:
        users = get_users()
        state = read_bot_state()
    except Exception:
        LOGGER.exception("Could not load reminder state")
        return {**summary, "errors": 1, "reason": "reminder_state_unavailable"}

    summary["users"] = len(users)
    for index, user in enumerate(users, start=1):
        u_id = user.get("userId")
        calendar_id = authorized_calendar(user)
        if not calendar_id or not u_id:
            summary["skipped"] += 1
            continue

        key = f"reminder:{now:%Y-%m-%d:%H}:{u_id}"
        stored = state.get(key, {})
        if stored.get("sent") or (stored and stored["calendar"] != calendar_id):
            summary["skipped"] += 1
            continue
        try:
            if not stored:
                entries = [
                    f"• {event_time_text(event)} {event_title(event)}"
                    for event in list_events(calendar_id, start_dt, end=end_dt)
                ]
                summary["events"] += len(entries)
                if not entries:
                    summary["skipped"] += 1
                    continue
                stored = {"calendar": calendar_id, "text": "\n".join([title, *entries])}
                store_bot_state(key, stored, claim=True)
                state[key] = stored

            push_reminder(u_id, key, stored["text"])
            store_bot_state(key, {"sent": True})
            state[key] = {"sent": True}
            summary["sent"] += 1
        except Exception:
            summary["errors"] += 1
            LOGGER.exception("Reminder failed for mapping row %s", index + 1)

    return summary


def push_reminder(user_id, key, text):
    try:
        with ApiClient(LINE_CONF) as api_client:
            MessagingApi(api_client).push_message(
                PushMessageRequest(to=user_id, messages=[TextMessage(text=text)]),
                x_line_retry_key=str(uuid5(NAMESPACE_URL, key)),
            )
    except ApiException as exc:
        headers = exc.headers or {}
        if exc.status != 409 or not headers.get("x-line-accepted-request-id"):
            raise


def setup_scheduler():
    scheduler = BackgroundScheduler(timezone="Asia/Taipei")
    scheduler.add_job(
        smart_reminder_job,
        "cron",
        hour="8,21",
        minute="0",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    print("[Scheduler] registered reminder job at Asia/Taipei 08:00 and 21:00")
    return scheduler
