# services/sheet_service.py
import gspread
import os
from dotenv import load_dotenv

load_dotenv()

# --- 總開關：建立與 Google Sheets 的連線 ---
GOOGLE_KEY_PATH = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', 'google_key.json')
SHEET_ID = os.getenv('GOOGLE_SHEET_ID')

# 防禦型建立連線
client = gspread.service_account(filename=GOOGLE_KEY_PATH)
SPREADSHEET = client.open_by_key(SHEET_ID)

# --- 1. 取得主對照表分頁 ---
def get_user_mapping_sheet():
    try:
        return SPREADSHEET.worksheet("User_Mapping")
    except gspread.exceptions.WorksheetNotFound:
        sheet = SPREADSHEET.add_worksheet(title="User_Mapping", rows="100", cols="5")
        sheet.append_row(["Name", "userId", "Calendar_ID", "Status"])
        return sheet

# --- 2. 註冊：建立新用戶的專屬工作表，並寫入對照表 ---
def create_user_worksheet(name, u_id):
    mapping_sheet = get_user_mapping_sheet()
    new_ws = SPREADSHEET.add_worksheet(title=name, rows="100", cols="5")
    new_ws.append_row(["時間", "事項", "狀態"])
    mapping_sheet.append_row([name, u_id, "", "待設定日曆"])
    return new_ws

# --- 3. 更新：填入使用者的 Google 日曆 ID ---
def update_user_calendar(u_id, calendar_id):
    mapping_sheet = get_user_mapping_sheet()
    row_idx = mapping_sheet.col_values(2).index(u_id) + 1
    mapping_sheet.update_cell(row_idx, 3, calendar_id)
    mapping_sheet.update_cell(row_idx, 4, "已開通")

# --- 4. 雜事：幫使用者新增一筆待辦雜事 ---
def add_user_todo(user_name, timestamp, task):
    u_worksheet = SPREADSHEET.worksheet(user_name)
    u_worksheet.append_row([timestamp, task, "未完成"])

# --- 5. 查詢：撈取使用者工作表內的所有數值 ---
def get_user_todo_values(user_name):
    u_worksheet = SPREADSHEET.worksheet(user_name)
    return u_worksheet.get_all_values()

# --- 6. 完成或刪除：修改指定編號的雜事狀態或刪除那一列 ---
def update_or_delete_todo(user_name, num, action):
    u_worksheet = SPREADSHEET.worksheet(user_name)
    rows = u_worksheet.get_all_values()
    target_idx, count = -1, 0
    
    for i, r in enumerate(rows):
        if i > 0 and len(r) > 2 and r[2] == "未完成":
            count += 1
            if count == num:
                target_idx = i + 1
                break
                
    if target_idx != -1:
        task = u_worksheet.cell(target_idx, 2).value
        if action == "完成":
            u_worksheet.update_cell(target_idx, 3, "已完成")
        else:
            u_worksheet.delete_rows(target_idx)
        return True, task
    return False, None