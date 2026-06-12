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
            reply_text = f"🧐 妳已經註冊過了喔！妳的名字是：{current_user['Name']}"
        elif any(u["Name"] == name for u in user_list):
            reply_text = f"❌ 抱歉，名字「{name}」已被使用，請換個稱呼吧！"
        else:
            try:
                create_user_worksheet(name, u_id)
                reply_text = (
                    f"🎉 {name}，歡迎加入！已為您開通分頁。\n\n"
                    "最後一步：請回傳您的 Google 日曆 ID（通常是您的 Gmail）給我，"
                    "並記得把日曆「共用」給我的金鑰 Email 喔！"
                )
            except Exception as e:
                reply_text = f"創表失敗：{e}"

    elif "@" in user_msg and "." in user_msg:
        if not current_user:
            reply_text = "請先輸入「我是 [姓名]」完成註冊喔！"
        else:
            update_user_calendar(u_id, user_msg)
            reply_text = (
                f"✅ 日曆設定成功！目前的日曆 ID：{user_msg}\n"
                "我會在每日 08:00 與 21:00 為您巡邏行程。"
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
                    reply_text = f"✅ 已{action}：{task_title}"
                else:
                    reply_text = f"🧐 找不到編號 {num}"
            except Exception:
                reply_text = f"❌ 請輸入數字，例如：{action} 1"

        elif user_msg.startswith("取消"):
            keyword = user_msg.replace("取消", "", 1).strip()
            if not keyword:
                reply_text = "❌ 請輸入關鍵字，例如：取消 去機場"
            elif not user_calendar:
                reply_text = "❌ 尚未設定日曆 ID，請先回傳 Gmail 帳號。"
            else:
                try:
                    success, canceled_title = delete_calendar_event(user_calendar, keyword)
                    if success:
                        reply_text = f"🗑️ 已從日曆取消：{canceled_title}"
                    else:
                        reply_text = f"🧐 找不到「{keyword}」行程。"
                except Exception as e:
                    reply_text = f"❌ 取消失敗：{e}"

        else:
            reply_text = f"{user_name} Hi！我是你的待辦事項小精靈。輸入「查詢」看清單，或是「新增 [事項]」來記錄雜事。"

    else:
        reply_text = "歡迎初次見面！請先輸入「我是 [您的姓名]」來開始使用喔！"

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
            return "❌ 格式理解失敗！請確保包含日期與時間。範例：預約 6/25 05:00 起床泡奶"

        date_raw = date_match.group()
        time_raw = time_match.group()
        task_name = pure_content.replace(date_raw, "", 1).replace(time_raw, "", 1).strip()
        if not task_name:
            task_name = "未命名行程"

        parsed_date = parse_date(date_raw)
        if not parsed_date:
            return "❌ 日期格式無法識別，請輸入如：6/25、06-25、0625 或 2026/6/25"
        if not user_calendar:
            return "❌ 尚未設定日曆 ID，請先回傳 Gmail 帳號。"

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
        return f"📅 {user_name} 預約成功：{task_name}"
    except Exception as e:
        return f"❌ 系統錯誤：{e}"


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
        return "❌ 請輸入待辦內容，例如：新增 買牛奶"
    if re.search(r"\d{1,2}[/\-]\d{1,2}|\d{4}", content) or re.search(r"\d{1,2}:\d{2}", content):
        return (
            "💡 溫馨提示：偵測到您輸入了時間資訊！\n\n"
            "這裡的「新增」僅供記錄單純的【待辦雜事】（不會有定時提醒功能喔）。\n\n"
            "如果您希望小精靈巡邏並定時提醒您，請改用【預約】功能！\n"
            "👉 格式範例：預約 6/20 16:00 看牙醫"
        )

    tasks = re.split(r"[、,，]+", content)
    timestamp_str = datetime.now(TZ).strftime("%m/%d %H:%M")
    added = []
    for task in tasks:
        task = task.strip()
        if task:
            add_user_todo(user_name, timestamp_str, task)
            added.append(task)

    return f"✅ 已為 {user_name} 記錄雜事。"


def handle_query_command(user_name, user_calendar):
    try:
        combined_reply = f"🌹 {user_name} 的最新情報：\n"
        rows = get_user_todo_values(user_name)
        sheet_tasks = []
        display_count = 0
        for i, row in enumerate(rows):
            if i == 0:
                continue
            if len(row) > 2 and row[1] and row[2] != "已完成":
                display_count += 1
                sheet_tasks.append(f"{display_count}. ⏳ {row[1]}")

        combined_reply += "\n📝 【待辦雜事】\n" + ("\n".join(sheet_tasks) if sheet_tasks else "目前沒有雜事喔！")

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

            combined_reply += "\n\n📅 【近期行程】\n"
            if not events:
                combined_reply += "近期沒有排定行程。"
            else:
                for event in events:
                    start = event["start"].get("dateTime", event["start"].get("date"))
                    if "T" in start:
                        combined_reply += f"• {start[5:10]} {start[11:16]} {event['summary']}\n"
                    else:
                        combined_reply += f"• {start} 全天 {event['summary']}\n"
        else:
            combined_reply += "\n\n📅 【日曆狀態】\n尚未設定日曆 ID。"

        combined_reply += f"\n{'-' * 15}\n💡 指令小幫手：\n🗑️ 刪除雜事：刪除 [編號]\n❌ 取消行程：取消 [關鍵字]"
        return combined_reply
    except Exception as e:
        return f"❌ 查詢失敗：{e}"
