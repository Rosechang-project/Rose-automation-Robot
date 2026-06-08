# scheduler.py
import datetime as dt_module
import os
from datetime import datetime

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from linebot.v3.messaging import ApiClient, Configuration, MessagingApi, PushMessageRequest, TextMessage

from services.calendar_service import get_calendar_service
from services.sheet_service import get_user_mapping_sheet

load_dotenv()

LINE_CONF = Configuration(access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
TZ = pytz.timezone("Asia/Taipei")
CALENDAR_SERVICE = get_calendar_service()


def smart_reminder_job():
    now = datetime.now(TZ)
    users = get_user_mapping_sheet().get_all_records()
    print(f"[Scheduler] reminder job started at {now.strftime('%Y-%m-%d %H:%M:%S %Z')}; users={len(users)}")

    if now.hour == 8:
        start_dt = now.replace(hour=12, minute=0, second=0, microsecond=0)
        end_dt = now.replace(hour=23, minute=59, second=59, microsecond=0)
        title = "午安提醒：今天下午到晚上的行程"
    elif now.hour == 21:
        tomorrow = now + dt_module.timedelta(days=1)
        start_dt = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = tomorrow.replace(hour=11, minute=59, second=59, microsecond=0)
        title = "晚安提醒：明天上午的行程"
    else:
        print(f"[Scheduler] skipped; current hour {now.hour} is not a reminder hour")
        return

    for index, user in enumerate(users, start=1):
        u_id = user.get("userId")
        calendar_id = user.get("Calendar_ID")
        if not calendar_id or not u_id:
            print(f"[Scheduler] user {index} skipped; missing userId or Calendar_ID")
            continue
        try:
            events_res = (
                CALENDAR_SERVICE.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=start_dt.isoformat(),
                    timeMax=end_dt.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            events = events_res.get("items", [])
            print(f"[Scheduler] user {index}; events={len(events)}; window={start_dt.isoformat()}~{end_dt.isoformat()}")

            if events:
                report = f"{title}\n"
                for event in events:
                    start = event["start"].get("dateTime", event["start"].get("date"))
                    time_text = start[11:16] if "T" in start else "全天"
                    report += f"{time_text} {event['summary']}\n"

                with ApiClient(LINE_CONF) as api_client:
                    MessagingApi(api_client).push_message(
                        PushMessageRequest(to=u_id, messages=[TextMessage(text=report.strip())])
                    )
                print(f"[Scheduler] user {index}; push sent")
        except Exception as e:
            print(f"[Scheduler Error] user {index}; 推播失敗：{e}")


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
