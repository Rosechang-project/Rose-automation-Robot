# services/sheet_service.py
import os

import gspread
from dotenv import load_dotenv

load_dotenv()

GOOGLE_KEY_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "google_key.json")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")

TODO_STATUS_PENDING = "未完成"
TODO_STATUS_DONE = "已完成"
USER_STATUS_PENDING = "尚未綁定日曆"
USER_STATUS_READY = "已綁定"

client = gspread.service_account(filename=GOOGLE_KEY_PATH)
SPREADSHEET = client.open_by_key(SHEET_ID)


def get_user_mapping_sheet():
    try:
        return SPREADSHEET.worksheet("User_Mapping")
    except gspread.exceptions.WorksheetNotFound:
        sheet = SPREADSHEET.add_worksheet(title="User_Mapping", rows="100", cols="5")
        sheet.append_row(["Name", "userId", "Calendar_ID", "Status"])
        return sheet


def create_user_worksheet(name, u_id):
    mapping_sheet = get_user_mapping_sheet()
    new_ws = SPREADSHEET.add_worksheet(title=name, rows="100", cols="5")
    new_ws.append_row(["時間", "任務", "狀態"])
    mapping_sheet.append_row([name, u_id, "", USER_STATUS_PENDING])
    return new_ws


def update_user_calendar(u_id, calendar_id):
    mapping_sheet = get_user_mapping_sheet()
    row_idx = mapping_sheet.col_values(2).index(u_id) + 1
    mapping_sheet.update_cell(row_idx, 3, calendar_id)
    mapping_sheet.update_cell(row_idx, 4, USER_STATUS_READY)


def add_user_todo(user_name, timestamp, task):
    u_worksheet = SPREADSHEET.worksheet(user_name)
    u_worksheet.append_row([timestamp, task, TODO_STATUS_PENDING])


def get_user_todo_values(user_name):
    u_worksheet = SPREADSHEET.worksheet(user_name)
    return u_worksheet.get_all_values()


def update_or_delete_todo(user_name, num, action):
    u_worksheet = SPREADSHEET.worksheet(user_name)
    rows = u_worksheet.get_all_values()
    target_idx, count = -1, 0

    for i, row in enumerate(rows):
        is_open_task = i > 0 and len(row) > 2 and row[1] and row[2] != TODO_STATUS_DONE
        if is_open_task:
            count += 1
            if count == num:
                target_idx = i + 1
                break

    if target_idx != -1:
        task = u_worksheet.cell(target_idx, 2).value
        if action == "完成":
            u_worksheet.update_cell(target_idx, 3, TODO_STATUS_DONE)
        else:
            u_worksheet.delete_rows(target_idx)
        return True, task
    return False, None
