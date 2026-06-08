# services/line_service.py
import datetime as dt_module
import os
import re
from datetime import datetime

import pytz
from dotenv import load_dotenv
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import ApiClient, Configuration, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import FollowEvent, MessageEvent, TextMessageContent

from services.calendar_service import delete_calendar_event, insert_calendar_event
from services.sheet_service import (
    add_user_todo,
    create_user_worksheet,
    get_user_mapping_sheet,
    get_user_todo_values,
    update_or_delete_todo,
    update_user_calendar,
)

load_dotenv()

LINE_CONF = Configuration(access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
HANDLER = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
TZ = pytz.timezone("Asia/Taipei")


def get_line_handler():
    return HANDLER


def reply(reply_token, text):
    with ApiClient(LINE_CONF) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=text)])
        )


@HANDLER.add(FollowEvent)
def handle_follow(event):
    welcome_msg = """歡迎使用 Rose 行程管理機器人。

你可以先輸入：
我是 Rose

註冊完成後，再傳你的 Google Calendar ID 或 Gmail，系統會幫你綁定日曆。

常用指令：
新增 買牛奶、整理簡報
預約 6/25 09:00 開會
查詢
完成 1
刪除 1
取消 開會"""
    reply(event.reply_token, welcome_msg)


@HANDLER.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    reply_token = event.reply_token
    user_msg = event.message.text.strip()
    u_id = event.source.user_id

    user_list = get_user_mapping_sheet().get_all_records()
    current_user = next((u for u in user_list if u["userId"] == u_id), None)

    register_command = first_matching_prefix(user_msg, ["我是", "註冊"])

    if register_command:
        name = user_msg.replace(register_command, "", 1).strip()
        if not name:
            reply_text = "請輸入你的名字，例如：我是 Rose"
        elif current_user:
            reply_text = f"你已經註冊過了，目前名稱是：{current_user['Name']}"
        elif any(u["Name"] == name for u in user_list):
            reply_text = f"名稱「{name}」已經有人使用，請換一個名字。"
        else:
            try:
                create_user_worksheet(name, u_id)
                reply_text = (
                    f"{name}，註冊完成。\n\n"
                    "接著請傳你的 Google Calendar ID 或 Gmail，"
                    "我會幫你綁定日曆。"
                )
            except Exception as e:
                reply_text = f"註冊失敗：{e}"

    elif "@" in user_msg and "." in user_msg:
        if not current_user:
            reply_text = "請先註冊，例如：我是 Rose"
        else:
            update_user_calendar(u_id, user_msg)
            reply_text = (
                f"日曆已綁定：{user_msg}\n"
                "之後每天 08:00 和 21:00 會主動提醒你的行程。"
            )

    elif current_user:
        user_name = current_user["Name"]
        user_calendar = current_user["Calendar_ID"]

        if first_matching_prefix(user_msg, ["預約", "行程"]):
            reply_text = handle_calendar_command(user_msg, user_name, user_calendar)

        elif first_matching_prefix(user_msg, ["新增", "待辦"]):
            reply_text = handle_todo_command(user_msg, user_name)

        elif user_msg == "查詢":
            reply_text = handle_query_command(user_name, user_calendar)

        elif any(user_msg.startswith(action) for action in ["完成", "刪除"]):
            action = "完成" if user_msg.startswith("完成") else "刪除"
            try:
                num = int(re.search(r"\d+", user_msg).group())
                success, task_title = update_or_delete_todo(user_name, num, action)
                if success:
                    reply_text = f"已{action}：{task_title}"
                else:
                    reply_text = f"找不到第 {num} 筆未完成待辦。"
            except Exception:
                reply_text = f"請輸入待辦編號，例如：{action} 1"

        elif user_msg.startswith("取消"):
            keyword = user_msg.replace("取消", "", 1).strip()
            if not keyword:
                reply_text = "請輸入要取消的行程關鍵字，例如：取消 開會"
            elif not user_calendar:
                reply_text = "你尚未綁定 Google Calendar ID。"
            else:
                try:
                    success, canceled_title = delete_calendar_event(user_calendar, keyword)
                    if success:
                        reply_text = f"已取消行程：{canceled_title}"
                    else:
                        reply_text = f"找不到包含「{keyword}」的未來行程。"
                except Exception as e:
                    reply_text = f"取消行程失敗：{e}"

        else:
            reply_text = (
                f"{user_name}，我看不懂這個指令。\n\n"
                "可以試試：\n"
                "新增 買牛奶\n"
                "預約 6/25 09:00 開會\n"
                "查詢"
            )

    else:
        reply_text = "請先註冊，例如：我是 Rose"

    reply(reply_token, reply_text)


def first_matching_prefix(text, prefixes):
    return next((prefix for prefix in prefixes if text.startswith(prefix)), None)


def handle_calendar_command(user_msg, user_name, user_calendar):
    try:
        command = first_matching_prefix(user_msg, ["預約", "行程"])
        pure_content = user_msg.replace(command, "", 1).strip()
        date_match = re.search(r"(\d{4}[/\-]\d{1,2}[/\-]\d{1,2})|(\d{1,2}[/\-]\d{1,2})|(\d{4})", pure_content)
        time_match = re.search(r"\d{1,2}:\d{2}", pure_content)

        if not date_match or not time_match:
            return "格式不完整，請輸入：預約 6/25 09:00 開會"

        date_raw = date_match.group()
        time_raw = time_match.group()
        task_name = pure_content.replace(date_raw, "", 1).replace(time_raw, "", 1).strip()
        if not task_name:
            task_name = "未命名行程"

        parsed_date = parse_date(date_raw)
        if not parsed_date:
            return "日期格式不正確，請使用 6/25、6-25、0625 或 2026/6/25。"
        if not user_calendar:
            return "你尚未綁定 Google Calendar ID，請先傳你的 Gmail 或 Calendar ID。"

        current_year = datetime.now(TZ).year
        hour_val, min_val = map(int, time_raw.split(":"))
        year = parsed_date.year if parsed_date.year != 1900 else current_year
        start_dt = TZ.localize(
            datetime(year=year, month=parsed_date.month, day=parsed_date.day, hour=hour_val, minute=min_val)
        )
        end_dt = start_dt + dt_module.timedelta(hours=1)

        if start_dt.hour < 12:
            reminder_base = (start_dt - dt_module.timedelta(days=1)).replace(hour=21, minute=0)
        else:
            reminder_base = start_dt.replace(hour=8, minute=0)
        remind_min = int((start_dt - reminder_base).total_seconds() / 60)

        current_time_str = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
        insert_calendar_event(user_calendar, task_name, start_dt, end_dt, remind_min, current_time_str)
        return f"{user_name}，已新增行程：{task_name}"
    except Exception as e:
        return f"新增行程失敗：{e}"


def parse_date(date_raw):
    for fmt in ["%m/%d", "%m-%d", "%m%d", "%Y/%m/%d", "%Y-%m-%d"]:
        try:
            return datetime.strptime(date_raw, fmt)
        except ValueError:
            continue
    return None


def handle_todo_command(user_msg, user_name):
    command = first_matching_prefix(user_msg, ["新增", "待辦"])
    content = user_msg.replace(command, "", 1).strip()
    if not content:
        return "請輸入待辦內容，例如：新增 買牛奶"
    if re.search(r"\d{1,2}[/\-]\d{1,2}|\d{4}", content) or re.search(r"\d{1,2}:\d{2}", content):
        return (
            "這看起來像有日期或時間的行程。\n"
            "如果要加入 Google Calendar，請改用：預約 6/20 16:00 開會"
        )

    tasks = re.split(r"[、,，]+", content)
    timestamp_str = datetime.now(TZ).strftime("%m/%d %H:%M")
    added = []
    for task in tasks:
        task = task.strip()
        if task:
            add_user_todo(user_name, timestamp_str, task)
            added.append(task)

    return f"已新增 {len(added)} 筆待辦。"


def handle_query_command(user_name, user_calendar):
    try:
        combined_reply = f"{user_name} 的清單\n"
        rows = get_user_todo_values(user_name)
        sheet_tasks = []
        display_count = 0
        for i, row in enumerate(rows):
            if i == 0:
                continue
            if len(row) > 2 and row[1] and row[2] != "已完成":
                display_count += 1
                sheet_tasks.append(f"{display_count}. {row[1]}")

        combined_reply += "\n未完成待辦：\n" + ("\n".join(sheet_tasks) if sheet_tasks else "目前沒有待辦。")

        if user_calendar:
            now_iso = datetime.now(dt_module.timezone.utc).isoformat().replace("+00:00", "Z")

            from services.calendar_service import get_calendar_service

            svc = get_calendar_service()
            events = (
                svc.events()
                .list(
                    calendarId=user_calendar,
                    timeMin=now_iso,
                    maxResults=5,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
                .get("items", [])
            )

            combined_reply += "\n\n接下來的行程：\n"
            if not events:
                combined_reply += "目前沒有未來行程。"
            else:
                for event in events:
                    start = event["start"].get("dateTime", event["start"].get("date"))
                    if "T" in start:
                        combined_reply += f"{start[5:10]} {start[11:16]} {event['summary']}\n"
                    else:
                        combined_reply += f"{start} 全天 {event['summary']}\n"
        else:
            combined_reply += "\n\n日曆狀態：尚未綁定 Google Calendar ID。"

        combined_reply += "\n\n可用指令：完成 1、刪除 1、取消 行程關鍵字"
        return combined_reply
    except Exception as e:
        return f"查詢失敗：{e}"
