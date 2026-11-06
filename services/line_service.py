# services/line_service.py
import datetime as dt_module
import logging
import os
import re
from datetime import datetime
from itertools import islice
from threading import Lock
from uuid import NAMESPACE_URL, uuid5

import pytz
from dotenv import load_dotenv
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import ApiClient, Configuration, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import FollowEvent, MessageEvent, TextMessageContent

from services.calendar_service import (
    delete_calendar_event,
    event_time_text,
    event_title,
    find_cancellation_candidates,
    get_cancellation_candidate,
    insert_calendar_event,
    list_events,
)
from services.sheet_service import (
    RESERVED_WORKSHEET_NAMES,
    add_user_todos,
    authorized_calendar,
    create_user_worksheet,
    get_open_todos,
    get_users,
    read_bot_state,
    store_bot_state,
    update_or_delete_todo,
    update_user_calendar,
)

load_dotenv()

LINE_CONF = Configuration(access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
HANDLER = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
TZ = pytz.timezone("Asia/Taipei")
LOGGER = logging.getLogger(__name__)
_webhook_lock = Lock()
CALENDAR_ID_PATTERN = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")


def get_line_handler():
    return HANDLER


def reply(reply_token, text):
    with ApiClient(LINE_CONF) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=text)])
        )


@HANDLER.add(FollowEvent)
def handle_follow(event):
    welcome_msg = """歡迎來到 Rose 的待辦事項專區！✨

我是你的小精靈，能幫你管理多人的雜事與日曆。

🔑 【開通第一步】
請先輸入：我是 [您的姓名]
(例如：我是 Rose)

開通後，我會幫您建立專屬的分頁，並指引您如何連動 Google 日曆喔！

常用指令：
新增 買牛奶、整理簡報
預約 6/25 09:00 開會
查詢
完成 T1
刪除 T1
取消 開會"""
    reply(event.reply_token, welcome_msg)


@HANDLER.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    if event.source.type != "user":
        return

    # Serialize spreadsheet read/modify/write sequences within this process.
    with _webhook_lock:
        try:
            reply_text = message_reply(event)
        except Exception:
            LOGGER.exception("LINE command failed")
            raise
    if reply_text:
        reply(event.reply_token, reply_text)


def message_reply(event):
    user_msg = event.message.text.strip()
    u_id = event.source.user_id

    user_list = get_users()
    current_user = next((u for u in user_list if u["userId"] == u_id), None)
    register_command = first_matching_prefix(user_msg, ["我是", "註冊"])
    if current_user and user_msg == "查詢":
        return handle_query_command(current_user["Name"], authorized_calendar(current_user))

    event_key = f"webhook:{event.webhook_event_id}"
    stored = read_bot_state().get(event_key, {})
    if stored.get("done"):
        return None

    if register_command:
        name = user_msg[len(register_command):].strip()
        if not name:
            return "請輸入你的名字，例如：我是 Rose"
        if current_user:
            return f"🧐 妳已經註冊過了喔！妳的名字是：{current_user['Name']}"
        if name.casefold() in RESERVED_WORKSHEET_NAMES or any(
            u["Name"].casefold() == name.casefold() for u in user_list
        ):
            return f"❌ 名字「{name}」已被使用，請換個稱呼吧！"
        if len(name) > 100 or re.search(r"[:/\\?*\[\]]|[\r\n]", name):
            return "❌ 這個名字無法用來建立工作表，請換個稱呼。"
        create_user_worksheet(name, u_id, event_key)
        return (
            f"🎉 {name}，歡迎加入！已為您開通分頁。\n\n"
            "請由管理者核准您的 Google 日曆 ID，並將日曆共用給 Bot 的 Google 服務帳號。"
            "核准後，請在這裡單獨傳送日曆 ID。"
        )

    if not current_user:
        return "歡迎初次見面！請先輸入「我是 [您的姓名]」來開始使用喔！"

    user_name = current_user["Name"]
    user_calendar = authorized_calendar(current_user)
    if first_matching_prefix(user_msg, ["預約", "行程"]):
        return handle_calendar_command(user_msg, user_name, user_calendar, event_key, stored)
    if first_matching_prefix(user_msg, ["新增", "待辦"]):
        return handle_todo_command(user_msg, user_name, event_key)
    if user_msg.startswith(("完成", "刪除")):
        action = user_msg[:2]
        id_match = re.fullmatch(r"[Tt]([1-9][0-9]{0,9})", user_msg[2:].strip())
        if not id_match:
            return f"❌ 請重新輸入「查詢」，再使用清單上的編號，例如：{action} T1"
        todo_id = int(id_match[1])
        success, task_title = update_or_delete_todo(user_name, todo_id, action, event_key)
        return f"✅ 已{action}：{task_title}" if success else f"🧐 找不到編號 T{todo_id}"
    if user_msg.startswith("取消"):
        return handle_cancel_command(user_msg[2:].strip(), user_calendar, event_key, stored)

    approved_calendar = current_user.get("Approved_Calendar_ID")
    if user_msg and user_msg == approved_calendar:
        update_user_calendar(u_id, user_msg, event_key)
        return f"✅ 日曆設定成功！目前的日曆 ID：{user_msg}"
    if CALENDAR_ID_PATTERN.fullmatch(user_msg):
        return "❌ 這個日曆 ID 尚未核准，請聯絡管理者。"
    return f"{user_name} Hi！我是你的待辦事項小精靈。輸入「查詢」看清單，或是「新增 [事項]」來記錄雜事。"


def first_matching_prefix(text, prefixes):
    return next((prefix for prefix in prefixes if text.startswith(prefix)), None)


def handle_calendar_command(user_msg, user_name, user_calendar, event_key, stored):
    if not user_calendar:
        return "❌ 請先綁定管理者核准的日曆。"
    if stored and stored["calendar"] != user_calendar:
        return "❌ 日曆綁定已變更，請重新輸入預約指令。"

    if not stored:
        content = user_msg[2:].strip()
        schedule = re.match(
            r"(?P<date>(?:\d{4}[/\-])?\d{1,2}[/\-]\d{1,2}|\d{4})\s+"
            r"(?P<time>\d{1,2}:\d{2})(?!\d)",
            content,
        )
        if not schedule:
            return "❌ 請輸入日期與時間，例如：預約 6/25 05:00 起床泡奶"

        now = datetime.now(TZ)
        date = parse_date(schedule["date"], now.year)
        if date is None:
            return "❌ 日期無效，請輸入如：6/25、06-25、0625 或 2026/6/25"
        hour, minute = map(int, schedule["time"].split(":"))
        if hour > 23 or minute > 59:
            return "❌ 時間無效，請輸入 00:00 到 23:59。"

        start = TZ.localize(date.replace(hour=hour, minute=minute))
        if start <= now:
            return "❌ 這個時間已經過去了，請預約未來時間的行程。"

        if start.hour < 12:
            reminder_base = (start - dt_module.timedelta(days=1)).replace(hour=21, minute=0)
        else:
            reminder_base = start.replace(hour=8, minute=0)
        stored = {
            "calendar": user_calendar,
            "title": content[schedule.end():].strip() or "未命名行程",
            "start": start.isoformat(),
            "end": (start + dt_module.timedelta(hours=1)).isoformat(),
            "reminder": int((start - max(reminder_base, now)).total_seconds() / 60),
            "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        }
        store_bot_state(event_key, stored, claim=True)

    event_id = uuid5(NAMESPACE_URL, event_key).hex
    insert_calendar_event(
        user_calendar, event_id, stored["title"], stored["start"], stored["end"],
        stored["reminder"], stored["created_at"],
    )
    store_bot_state(event_key, {"done": True})
    return f"📅 {user_name} 預約成功：{stored['title']}"


def parse_date(date_raw, year):
    for value, fmt in [
        (date_raw, "%Y/%m/%d"),
        (date_raw, "%Y-%m-%d"),
        (f"{year}/{date_raw}", "%Y/%m/%d"),
        (f"{year}-{date_raw}", "%Y-%m-%d"),
        (f"{year}/{date_raw}", "%Y/%m%d"),
    ]:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def handle_cancel_command(keyword, user_calendar, event_key, stored):
    if not keyword:
        return "❌ 請輸入關鍵字，例如：取消 去機場"
    if not user_calendar:
        return "❌ 請先綁定管理者核准的日曆。"
    if stored and stored["calendar"] != user_calendar:
        return "❌ 日曆綁定已變更，請重新搜尋要取消的行程。"
    if not stored:
        now = datetime.now(TZ)
        if keyword.startswith("ID "):
            event = get_cancellation_candidate(user_calendar, keyword[3:].strip(), now)
        else:
            matches = list(islice(find_cancellation_candidates(user_calendar, keyword, now), 6))
            if len(matches) > 1:
                choices = "\n".join(
                    f"• {event_time_text(item, include_date=True)} {event_title(item)}\n取消 ID {item['id']}"
                    for item in matches[:5]
                )
                return f"找到多筆行程，請複製要取消的指令。\n{choices}"
            event = matches[0] if matches else None
        if event is None:
            return f"🧐 找不到符合「{keyword}」的未來行程。"
        stored = {
            "calendar": user_calendar,
            "id": event["id"],
            "title": event_title(event),
            "etag": event.get("etag"),
        }
        store_bot_state(event_key, stored, claim=True)

    deleted = delete_calendar_event(user_calendar, stored["id"], stored["etag"])
    store_bot_state(event_key, {"done": True})
    if deleted:
        return f"🗑️ 已從日曆取消：{stored['title']}"
    return "❌ 行程內容已變更，請重新搜尋後再取消。"


def handle_todo_command(user_msg, user_name, event_key):
    command = first_matching_prefix(user_msg, ["新增", "待辦"])
    content = user_msg.replace(command, "", 1).strip()
    if not content:
        return "❌ 請輸入待辦內容，例如：新增 買牛奶"
    if re.search(r"\d{1,2}[/\-]\d{1,2}|\d{1,2}:\d{2}", content):
        return (
            "💡 溫馨提示：偵測到您輸入了時間資訊！\n\n"
            "這裡的「新增」僅供記錄單純的【待辦雜事】（不會有定時提醒功能喔）。\n\n"
            "如果您希望小精靈巡邏並定時提醒您，請改用【預約】功能！\n"
            "👉 格式範例：預約 6/20 16:00 看牙醫"
        )

    # Keep commas between a digit and a three-digit group inside the task.
    parts = re.split(r"、|(?<!\d)[,，]|[,，](?!\d{3}(?!\d))", content)
    tasks = [part.strip() for part in parts if part.strip()]
    if not tasks:
        return "❌ 請輸入待辦內容，例如：新增 買牛奶"
    timestamp_str = datetime.now(TZ).strftime("%m/%d %H:%M")
    add_user_todos(user_name, timestamp_str, tasks, event_key)
    return f"✅ 已為 {user_name} 記錄雜事。"


def handle_query_command(user_name, user_calendar):
    combined_reply = f"🌹 {user_name} 的最新情報：\n"
    sheet_tasks = [f"T{todo_id}. ⏳ {title}" for todo_id, title in get_open_todos(user_name)]
    combined_reply += "\n📝 【待辦雜事】\n" + ("\n".join(sheet_tasks) or "目前沒有雜事喔！")

    if user_calendar:
        combined_reply += "\n\n📅 【近期行程】\n"
        try:
            events = islice(list_events(user_calendar, datetime.now(TZ)), 5)
            entries = [f"• {event_time_text(event, include_date=True)} {event_title(event)}" for event in events]
            combined_reply += "\n".join(entries) or "近期沒有排定行程。"
        except Exception:
            LOGGER.exception("Calendar query failed")
            combined_reply += "暫時無法查詢日曆，請稍後再試。"
    else:
        combined_reply += "\n\n📅 【日曆狀態】\n尚未綁定核准的日曆。"

    return (
        f"{combined_reply}\n{'-' * 15}\n💡 指令小幫手：\n"
        "🗑️ 刪除雜事：刪除 T1\n❌ 取消行程：取消 [關鍵字]"
    )
