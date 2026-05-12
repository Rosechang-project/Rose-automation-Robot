import os
import datetime
import re
import gspread
from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from apscheduler.schedulers.background import BackgroundScheduler
from linebot.v3.messaging import PushMessageRequest
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent

load_dotenv()
app = FastAPI()

# --- 基礎設定 ---
LINE_CONF = Configuration(access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
HANDLER = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
SCOPE = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/calendar"]
CREDS = Credentials.from_service_account_file("google_key.json", scopes=SCOPE)

# --- 服務初始化 ---
SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
GS_CLIENT = gspread.authorize(CREDS)
worksheet = GS_CLIENT.open_by_key(SHEET_ID).get_worksheet(0)

MY_CALENDAR_ID = os.getenv('GOOGLE_CALENDAR_ID')
CALENDAR_SERVICE = build('calendar', 'v3', credentials=CREDS)

@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get('X-Line-Signature')
    body = await request.body()
    try:
        HANDLER.handle(body.decode('utf-8'), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return 'OK'


# --- 1. 定義早安報報任務 ---
def send_morning_report():
    try:
        my_id = os.getenv('LINE_MY_USER_ID')
        report_text = "☀️ Rose 早安！今日行程彙整：\n"

        # 抓取試算表未完成雜事
        all_rows = worksheet.get_all_values()
        sheet_tasks = [f"• {row[1]}" for row in all_rows[1:] if len(row) > 2 and row[2] == "未完成"]
        report_text += "\n📝 【待辦雜事】\n" + ("\n".join(sheet_tasks) if sheet_tasks else "目前沒有雜事喔！")

        # 抓取今日日曆行程
        now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
        events_result = CALENDAR_SERVICE.events().list(
            calendarId=MY_CALENDAR_ID, timeMin=now,
            maxResults=10, singleEvents=True, orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])

        report_text += "\n\n📅 【今日行程】\n"
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        today_events = []
        for e in events:
            start = e['start'].get('dateTime', e['start'].get('date'))
            if today_str in start: # 只挑今天的
                dt = datetime.datetime.strptime(start[:16], "%Y-%m-%dT%H:%M")
                today_events.append(f"• {dt.strftime('%H:%M')} {e['summary']}")
        
        report_text += "\n".join(today_events) if today_events else "今天目前沒有排定行程。"

        # 主動推播訊息 (Push Message)
        with ApiClient(LINE_CONF) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.push_message(
                PushMessageRequest(
                    to=my_id,
                    messages=[TextMessage(text=report_text)]
                )
            )
    except Exception as e:
        print(f"定時任務失敗: {e}")

# --- 2. 設定排程器 ---
scheduler = BackgroundScheduler(timezone="Asia/Taipei")
# 設定每天早上 08:00 執行 (妳可以先改成 1 分鐘後的時間來測試)
scheduler.add_job(send_morning_report, 'cron', hour=15, minute=51)
scheduler.start()


@HANDLER.add(FollowEvent)
def handle_follow(event):
    welcome_msg = """我是 Rose 的待辦事項小精靈🌹

我能幫妳管理雜事與日曆行程：
📝 新增事項 (多筆請用逗號分開)
🔍 查詢清單與近期行程
🎉 完成/刪除任務
📅 預約日曆行程 (自動提醒)

💡 指令小幫手：
• 新增：新增 買咖啡, 繳電費
• 預約：預約 0520 14:00 搭飛機
• 刪除：刪除 [編號]
• 取消：取消 [關鍵字]
• 查詢：直接輸入 查詢"""
    
    with ApiClient(LINE_CONF) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=welcome_msg)]
            )
        )

@HANDLER.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    # 第一步：把 LINE 給妳的回信通行證（reply_token）先存起來
    reply_token = event.reply_token 
    
    # 接下來才是抓取文字和印出資訊
    user_msg = event.message.text
    
    # 2. 修改這裡！讓它印出 ID 同時印出文字
    print(f"📢 收到訊息！")
    print(f"ID: {event.source.user_id}")
    print(f"內容: {user_msg}")
    print("-" * 20) # 畫條線比較好讀

    # --- 邏輯 A：智慧預約 (自動計算提醒時間) ---
    if user_msg.startswith("預約"):
        try:
            match = re.match(r"預約\s+(\d{4})\s+(\d{1,2}:\d{2})\s+(.+)", user_msg)
            if match:
                date_str, time_str, task_name = match.groups()
                current_year = datetime.datetime.now().year
                start_dt = datetime.datetime.strptime(f"{current_year}-{date_str[:2]}-{date_str[2:]} {time_str}", "%Y-%m-%d %H:%M")
                
                # --- 智慧提醒計算 ---
                # 1. 判斷是上午還是下午 (以 12:00 為界)
                if start_dt.hour < 12:
                    # 前一天晚上 9 點 (21:00)
                    remind_time = (start_dt - datetime.timedelta(days=1)).replace(hour=21, minute=0)
                    remind_msg = "前一天晚上 21:00"
                else:
                    # 當天早上 8 點
                    remind_time = start_dt.replace(hour=8, minute=0)
                    remind_msg = "今天早上 08:00"
                
                # 計算距離開始時間「多少分鐘前」
                delta_minutes = int((start_dt - remind_time).total_seconds() / 60)
                
                # 如果計算出來是負數（例如現在已經超過提醒時間），就設為預設 30 分鐘
                if delta_minutes <= 0:
                    delta_minutes = 30
                    remind_msg = "30 分鐘前"

                event_body = {
                    'summary': task_name,
                    'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'Asia/Taipei'},
                    'end': {'dateTime': (start_dt + datetime.timedelta(hours=1)).isoformat(), 'timeZone': 'Asia/Taipei'},
                    'reminders': {
                        'useDefault': False,
                        'overrides': [{'method': 'popup', 'minutes': delta_minutes}]
                    }
                }
                CALENDAR_SERVICE.events().insert(calendarId=MY_CALENDAR_ID, body=event_body).execute()
                reply_text = f"📅 預約成功！\n事項：{task_name}\n提醒時間：已設定於 {remind_msg}"
        except Exception as e:  # <--- 妳可能漏掉了這兩行
            reply_text = f"日曆同步失敗：{str(e)}"

    # --- 邏輯 B：綜合查詢 (含貼心指令教學) ---
    elif user_msg == "查詢":
        try:
            combined_reply = "🌹 Rose 的最新情報：\n"
            
            # 1. 處理試算表雜事
            all_rows = worksheet.get_all_values()
            sheet_tasks = []
            count = 0
            for idx, row in enumerate(all_rows):
                if idx == 0: continue 
                if len(row) > 2 and row[2] == "未完成":
                    count += 1
                    sheet_tasks.append(f"{count}. ⏳ {row[1]}")
            
            combined_reply += "\n📝 【待辦雜事】\n" + ("\n".join(sheet_tasks) if sheet_tasks else "目前沒有雜事喔！")

            # 2. 處理日曆行程
            now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
            events_result = CALENDAR_SERVICE.events().list(
                calendarId=MY_CALENDAR_ID, timeMin=now,
                maxResults=5, singleEvents=True, orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])

            combined_reply += "\n\n📅 【近期行程】\n"
            if not events:
                combined_reply += "近期沒有排定行程。"
            else:
                for event in events:
                    start = event['start'].get('dateTime', event['start'].get('date'))
                    dt = datetime.datetime.strptime(start[:16], "%Y-%m-%dT%H:%M")
                    combined_reply += f"• {dt.strftime('%m/%d %H:%M')} {event['summary']}\n"

            # --- 💡 加上妳要的貼心註解 ---
            combined_reply += "\n" + "-"*15 + "\n" # 加上分隔線
            combined_reply += "💡 指令小幫手：\n"
            combined_reply += "🗑️ 刪除雜事請輸入：刪除 [編號]\n"
            combined_reply += "❌ 取消行程請輸入：取消 [關鍵字]"

            reply_text = combined_reply
        except Exception as e:
            reply_text = f"查詢失敗：{str(e)}"

    # --- 邏輯 C：智慧多重新增 ---
    elif user_msg.startswith("新增"):
        try:
            content = user_msg.replace("新增", "").strip()
            if content:
                # 使用正則表達式，同時支援中英文逗號分隔
                # 如果妳想用空格分開，可以改成 r'[，,\s]+'
                tasks = re.split(r'[，,]+', content)
                
                added_list = []
                now_str = datetime.datetime.now().strftime("%m/%d %H:%M")
                
                for t in tasks:
                    clean_task = t.strip()
                    if clean_task: # 確保不是空字串
                        worksheet.append_row([now_str, clean_task, "未完成"])
                        added_list.append(clean_task)
                
                if len(added_list) > 1:
                    reply_text = f"✅ 已成功拆分並記錄 {len(added_list)} 項雜事：\n• " + "\n• ".join(added_list)
                else:
                    reply_text = f"✅ 已記錄雜事：{added_list[0]}"
            else:
                reply_text = "❌ 妳要新增什麼呢？格式：新增 買豆腐, 買蛋糕"
        except Exception as e:
            reply_text = f"新增失敗：{str(e)}"

    # --- 邏輯 D/E：完成與刪除 (統一邏輯) ---
    elif user_msg.startswith("完成") or user_msg.startswith("刪除"):
        action = "完成" if "完成" in user_msg else "刪除"
        try:
            num_str = user_msg.replace(action, "").strip()
            if num_str.isdigit():
                target_count = int(num_str)
                current_count = 0
                target_row_index = -1
                
                # 遍歷試算表，找出「第 n 個」未完成的事項在哪一列
                all_rows = worksheet.get_all_values()
                for idx, row in enumerate(all_rows):
                    if idx == 0: continue
                    if len(row) > 2 and row[2] == "未完成":
                        current_count += 1
                        if current_count == target_count:
                            target_row_index = idx + 1 # 找到對應的試算表行數
                            break
                
                if target_row_index != -1:
                    task_name = worksheet.cell(target_row_index, 2).value
                    if action == "完成":
                        worksheet.update_cell(target_row_index, 3, "已完成")
                        reply_text = f"🎉 已完成：{task_name}"
                    else:
                        worksheet.delete_rows(target_row_index)
                        reply_text = f"🗑️ 已刪除：{task_name}"
                else:
                    reply_text = f"🧐 找不到編號 {num_str} 的事項喔。"
            else:
                reply_text = f"❌ 請輸入數字，例如：{action} 1"
        except Exception as e:
            reply_text = f"操作失敗：{str(e)}"

    # --- 邏輯 F：取消行程 (日曆) ---
    elif user_msg.startswith("取消"):
        try:
            keyword = user_msg.replace("取消", "").strip()
            if not keyword:
                reply_text = "❌ 請輸入要取消的關鍵字，例如：取消 泡奶"
            else:
                now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
                events_result = CALENDAR_SERVICE.events().list(
                    calendarId=MY_CALENDAR_ID, q=keyword, timeMin=now,
                    singleEvents=True, orderBy='startTime'
                ).execute()
                events = events_result.get('items', [])

                if events:
                    event_id = events[0]['id']
                    event_title = events[0]['summary']
                    CALENDAR_SERVICE.events().delete(calendarId=MY_CALENDAR_ID, eventId=event_id).execute()
                    reply_text = f"🗑️ 已從日曆取消：{event_title}"
                else:
                    reply_text = f"🧐 找不到包含「{keyword}」的未來行程。"
        except Exception as e:
            reply_text = f"取消行程失敗：{str(e)}"

    # --- 最後的預設幫助訊息 (必須放在最後面！) ---
    else:
        reply_text = "Rose 妳好！我是妳的雙刀流秘書：\n\n🔍 查詢 (看清單)\n📝 新增 [事項] (記雜事)\n📅 預約 [日期] [時間] [事項]\n🎉 完成 [編號]\n🗑️ 刪除 [編號]\n❌ 取消 [行程關鍵字]"

    # --- 回覆 LINE (確保回覆功能正常) ---
    with ApiClient(LINE_CONF) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)