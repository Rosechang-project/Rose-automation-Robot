import json
import os
from secrets import randbelow
from threading import Lock, local
from uuid import NAMESPACE_URL, uuid5

import gspread
from dotenv import load_dotenv

load_dotenv()

GOOGLE_KEY_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "google_key.json")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")

TODO_STATUS_PENDING = "未完成"
TODO_STATUS_DONE = "已完成"
TODO_STATUS_DELETED = "已刪除"
USER_STATUS_PENDING = "尚未綁定日曆"
USER_STATUS_READY = "已綁定"
USER_MAPPING_TITLE = "User_Mapping"
BOT_STATE_TITLE = "_Bot_State"
RESERVED_WORKSHEET_NAMES = {USER_MAPPING_TITLE.casefold(), BOT_STATE_TITLE.casefold()}

_connection = local()
_create_sheet_lock = Lock()


def get_spreadsheet():
    if not hasattr(_connection, "spreadsheet"):
        client = gspread.service_account(filename=GOOGLE_KEY_PATH)
        _connection.spreadsheet = client.open_by_key(SHEET_ID)
    return _connection.spreadsheet


def _get_or_create_sheet(title, headers, *, hidden=False):
    spreadsheet = get_spreadsheet()
    with _create_sheet_lock:
        try:
            return spreadsheet.worksheet(title)
        except gspread.exceptions.WorksheetNotFound:
            sheet_id = randbelow(2**31 - 1) + 1
            requests = [
                {"addSheet": {"properties": {
                    "sheetId": sheet_id,
                    "title": title,
                    "hidden": hidden,
                    "gridProperties": {"rowCount": 100, "columnCount": len(headers)},
                }}},
                _append_rows(sheet_id, [headers]),
            ]
            try:
                spreadsheet.batch_update({"requests": requests})
            except gspread.exceptions.APIError as exc:
                # A second process may have created the sheet after our lookup.
                try:
                    return spreadsheet.worksheet(title)
                except gspread.exceptions.WorksheetNotFound:
                    raise exc
            return spreadsheet.worksheet(title)


def get_user_mapping_sheet():
    return _get_or_create_sheet(
        USER_MAPPING_TITLE, ["Name", "userId", "Calendar_ID", "Status", "Approved_Calendar_ID"]
    )


def get_users():
    return get_user_mapping_sheet().get_all_records(numericise_ignore=["all"])


def authorized_calendar(user):
    calendar = user.get("Calendar_ID", "")
    return calendar if calendar and calendar == user.get("Approved_Calendar_ID") else ""


def _bot_state_sheet():
    return _get_or_create_sheet(BOT_STATE_TITLE, ["Key", "Value"], hidden=True)


def read_bot_state():
    return {
        row[0]: json.loads(row[1])
        for row in _bot_state_sheet().get_all_values()[1:]
        if len(row) >= 2 and row[0] and row[1]
    }


def store_bot_state(key, value, requests=(), *, claim=False):
    state_sheet = _bot_state_sheet()
    encoded = json.dumps(value, ensure_ascii=False)
    if not claim and not requests:
        row_number = state_sheet.col_values(1).index(key) + 1
        state_sheet.update_cell(row_number, 2, encoded)
        return

    # Sheets rejects the entire batch if another process already claimed this key.
    get_spreadsheet().batch_update({"requests": [
        _claim_request(state_sheet.id, key),
        *requests,
        _append_rows(state_sheet.id, [[key, encoded]]),
    ]})


def _claim_request(sheet_id, key):
    claim_id = uuid5(NAMESPACE_URL, key).hex
    return {"addNamedRange": {"namedRange": {
        "namedRangeId": claim_id,
        "name": f"Bot_claim_{claim_id}",
        "range": {
            "sheetId": sheet_id,
            "startRowIndex": 0,
            "endRowIndex": 1,
            "startColumnIndex": 0,
            "endColumnIndex": 1,
        },
    }}}


def _row_data(row):
    return {"values": [{"userEnteredValue": {"stringValue": value}} for value in row]}


def _append_rows(sheet_id, rows):
    return {"appendCells": {
        "sheetId": sheet_id,
        "rows": [_row_data(row) for row in rows],
        "fields": "userEnteredValue",
    }}


def _update_row(sheet_id, row_index, column_index, row):
    return {"updateCells": {
        "start": {"sheetId": sheet_id, "rowIndex": row_index, "columnIndex": column_index},
        "rows": [_row_data(row)],
        "fields": "userEnteredValue",
    }}


def create_user_worksheet(name, user_id, event_key):
    mapping = get_user_mapping_sheet()
    sheet_id = randbelow(2**31 - 1) + 1
    store_bot_state(event_key, {"done": True}, [
        _claim_request(mapping.id, f"registration:{user_id}"),
        {"addSheet": {"properties": {
            "sheetId": sheet_id,
            "title": name,
            "gridProperties": {"rowCount": 100, "columnCount": 5},
        }}},
        _append_rows(sheet_id, [["時間", "任務", "狀態"]]),
        _append_rows(mapping.id, [[name, user_id, "", USER_STATUS_PENDING]]),
    ])


def update_user_calendar(user_id, calendar_id, event_key):
    mapping = get_user_mapping_sheet()
    row_index = mapping.col_values(2).index(user_id)
    store_bot_state(event_key, {"done": True}, [
        _update_row(mapping.id, row_index, 2, [calendar_id, USER_STATUS_READY]),
    ])


def add_user_todos(user_name, timestamp, tasks, event_key):
    worksheet = get_spreadsheet().worksheet(user_name)
    rows = [[timestamp, task, TODO_STATUS_PENDING] for task in tasks]
    store_bot_state(event_key, {"done": True}, [_append_rows(worksheet.id, rows)])


def _is_open_todo(row):
    return len(row) > 2 and row[1] and row[2] not in {TODO_STATUS_DONE, TODO_STATUS_DELETED}


def get_open_todos(user_name):
    worksheet = get_spreadsheet().worksheet(user_name)
    return [
        (todo_id, row[1])
        for todo_id, row in enumerate(worksheet.get_all_values()[1:], start=1)
        if _is_open_todo(row)
    ]


def update_or_delete_todo(user_name, todo_id, action, event_key):
    worksheet = get_spreadsheet().worksheet(user_name)
    rows = worksheet.get_all_values()
    if not 0 < todo_id < len(rows) or not _is_open_todo(rows[todo_id]):
        return False, None

    # Keep row positions stable for both older and newly added tasks.
    status = TODO_STATUS_DONE if action == "完成" else TODO_STATUS_DELETED
    store_bot_state(event_key, {"done": True}, [
        _claim_request(worksheet.id, f"todo:{worksheet.id}:{todo_id}"),
        _update_row(worksheet.id, todo_id, 2, [status]),
    ])
    return True, rows[todo_id][1]
