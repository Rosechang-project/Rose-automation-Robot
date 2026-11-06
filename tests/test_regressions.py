import asyncio
import base64
import hmac
import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

with patch.dict("os.environ", {
    "LINE_CHANNEL_SECRET": "test-secret",
    "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
}):
    import main
    import scheduler
    from services import calendar_service, line_service, sheet_service


def user(user_id, calendar):
    return {"Name": user_id, "userId": user_id, "Calendar_ID": calendar, "Approved_Calendar_ID": calendar}


def message(text, event_id="event", source="user"):
    return SimpleNamespace(
        source=SimpleNamespace(user_id="rose", type=source),
        message=SimpleNamespace(text=text),
        webhook_event_id=event_id,
        reply_token="test-reply",
    )


def event(event_id, title, start="2030-06-20T04:00:00Z"):
    return {"id": event_id, "etag": f'"{event_id}"', "summary": title, "start": {"dateTime": start}}


class LineCommandsTest(unittest.TestCase):
    def setUp(self):
        self.state = {}
        self.users = [user("rose", "rose@example.com"), user("other", "other@example.com")]
        users_patch = patch.object(line_service, "get_users", return_value=self.users)
        state_patch = patch.object(line_service, "read_bot_state", return_value=self.state)
        save_patch = patch.object(line_service, "store_bot_state", side_effect=self.save_state)
        for patcher in (users_patch, state_patch, save_patch):
            patcher.start()
            self.addCleanup(patcher.stop)

    def save_state(self, key, value, **kwargs):
        self.state[key] = value

    def test_email_inside_todo_does_not_change_binding(self):
        with (
            patch.object(line_service, "add_user_todos") as add,
            patch.object(line_service, "update_user_calendar") as bind,
        ):
            response = line_service.message_reply(message("新增 寄帳單到 other@example.com 12,000 元"))
            self.assertIn("記錄雜事", response)
            self.assertEqual(add.call_args.args[2], ["寄帳單到 other@example.com 12,000 元"])
            self.assertIn("尚未核准", line_service.message_reply(message("other@example.com")))
            bind.assert_not_called()
            line_service.message_reply(message("rose@example.com"))
            bind.assert_called_once_with("rose", "rose@example.com", "webhook:event")

    def test_unapproved_existing_calendar_and_group_query(self):
        self.users[0]["Approved_Calendar_ID"] = ""
        with (
            patch.object(line_service, "handle_query_command") as query,
            patch.object(line_service, "reply") as reply,
        ):
            line_service.message_reply(message("查詢"))
            query.assert_called_once_with("rose", "")
            query.reset_mock()
            line_service.handle_message(message("查詢", source="group"))
            query.assert_not_called()
            reply.assert_not_called()

    def test_invalid_inputs_and_replayed_deletion(self):
        def update_todo(user_name, todo_id, action, key):
            self.save_state(key, {"done": True})
            return True, "Task"

        with (
            patch.object(line_service, "update_or_delete_todo", side_effect=update_todo) as update,
            patch.object(line_service, "add_user_todos") as add,
        ):
            self.assertIn("重新輸入「查詢」", line_service.message_reply(message("刪除 -1")))
            update.assert_not_called()
            self.assertIn("請輸入待辦內容", line_service.message_reply(message("新增 、，")))
            add.assert_not_called()
            self.assertIn("已刪除", line_service.message_reply(message("刪除 T1")))
            self.assertIsNone(line_service.message_reply(message("刪除 T1")))
            update.assert_called_once_with("rose", 1, "刪除", "webhook:event")

    def test_legacy_todo_numbers_cannot_modify_a_different_task(self):
        self.users[0]["Approved_Calendar_ID"] = ""
        with (
            patch.object(line_service, "get_open_todos", return_value=[(1, "A"), (3, "C"), (4, "D")]),
            patch.object(line_service, "update_or_delete_todo", return_value=(True, "D")) as update,
        ):
            listing = line_service.message_reply(message("查詢"))
            self.assertIn("T3. ⏳ C", listing)
            self.assertIn("T4. ⏳ D", listing)
            for command in ("刪除 3", "完成 3"):
                with self.subTest(command=command):
                    self.assertIn("重新輸入「查詢」", line_service.message_reply(message(command)))
            update.assert_not_called()
            self.assertIn("已刪除：D", line_service.message_reply(message("刪除 T4")))
            update.assert_called_once_with("rose", 4, "刪除", "webhook:event")

    def test_booking_uses_only_leading_date_and_time(self):
        with (
            patch.object(line_service, "datetime", wraps=datetime) as clock,
            patch.object(line_service, "insert_calendar_event") as insert,
        ):
            clock.now.return_value = line_service.TZ.localize(datetime(2026, 11, 6, 14))
            for date in ("1208", "12/8", "12-08", "2026/12/08", "2026-12-08"):
                with self.subTest(date=date):
                    title = "檢查 12/01  10:30 帳單"
                    command = message(f"預約 {date} 09:00 {title}", event_id=date)
                    self.assertIn("預約成功", line_service.message_reply(command))
                    self.assertEqual(insert.call_args.args[2:4], (title, "2026-12-08T09:00:00+08:00"))

            insert.reset_mock()
            command = message("預約 檢查 12/01 10:30 帳單", event_id="missing-prefix")
            self.assertIn("請輸入日期與時間", line_service.message_reply(command))
            insert.assert_not_called()

    def test_booking_reuses_plan_and_id_after_timeout(self):
        with (
            patch.object(line_service, "datetime", wraps=datetime) as clock,
            patch.object(line_service, "insert_calendar_event", side_effect=[TimeoutError, None]) as insert,
        ):
            clock.now.return_value = line_service.TZ.localize(datetime(2028, 2, 28))
            command = message("預約 02/29 12:00 買東西 12000 元")
            with self.assertRaises(TimeoutError):
                line_service.message_reply(command)
            self.assertIn("預約成功", line_service.message_reply(command))
            self.assertEqual(insert.call_args_list[0], insert.call_args_list[1])
            self.assertEqual(insert.call_args.args[3], "2028-02-29T12:00:00+08:00")
            self.assertIsNone(line_service.parse_date("02/29", 2027))

    def test_cancellation_reuses_same_event_after_timeout(self):
        with (
            patch.object(line_service, "find_cancellation_candidates", return_value=[event("one", "看牙醫")]) as find,
            patch.object(line_service, "delete_calendar_event", side_effect=[TimeoutError, True]) as delete,
        ):
            command = message("取消 看牙醫")
            with self.assertRaises(TimeoutError):
                line_service.message_reply(command)
            self.assertIn("已從日曆取消", line_service.message_reply(command))
            find.assert_called_once()
            self.assertEqual(delete.call_args_list[0], delete.call_args_list[1])
            self.assertEqual(delete.call_args.args, ("rose@example.com", "one", '"one"'))

    def test_multiple_cancellation_matches_require_event_selection(self):
        with (
            patch.object(line_service, "find_cancellation_candidates", return_value=[
                event("one", "看牙醫"), event("two", "看牙醫"),
            ]),
            patch.object(line_service, "delete_calendar_event") as delete,
        ):
            response = line_service.message_reply(message("取消 看牙醫"))
            self.assertIn("取消 ID one", response)
            self.assertIn("取消 ID two", response)
            delete.assert_not_called()


class SheetTest(unittest.TestCase):
    def test_deletion_keeps_older_row_ids_and_records_replay_atomically(self):
        spreadsheet = Mock()
        worksheet = spreadsheet.worksheet.return_value
        worksheet.id = 12
        worksheet.get_all_values.return_value = [
            ["時間", "任務", "狀態"],
            ["08:00", "已完成的舊待辦", "已完成"],
            ["08:00", "另一筆", "未完成"],
        ]
        state_sheet = Mock(id=13)
        with (
            patch.object(sheet_service, "get_spreadsheet", return_value=spreadsheet),
            patch.object(sheet_service, "_bot_state_sheet", return_value=state_sheet),
        ):
            self.assertEqual(sheet_service.get_open_todos("rose"), [(2, "另一筆")])
            result = sheet_service.update_or_delete_todo("rose", 2, "刪除", "webhook:event")

        self.assertEqual(result, (True, "另一筆"))
        requests = spreadsheet.batch_update.call_args.args[0]["requests"]
        self.assertEqual([next(iter(item)) for item in requests],
                         ["addNamedRange", "addNamedRange", "updateCells", "appendCells"])
        self.assertEqual(requests[2]["updateCells"]["start"]["rowIndex"], 2)
        state_row = requests[3]["appendCells"]["rows"][0]["values"]
        self.assertEqual(state_row[0]["userEnteredValue"]["stringValue"], "webhook:event")
        self.assertEqual(json.loads(state_row[1]["userEnteredValue"]["stringValue"]), {"done": True})


class CalendarAndRemindersTest(unittest.TestCase):
    def test_cancellation_excludes_description_match_and_ongoing_events(self):
        now = calendar_service.TZ.localize(datetime(2030, 6, 20, 10))
        with patch.object(calendar_service, "list_events", return_value=[
            {**event("unrelated", "會議"), "description": "看牙醫"},
            event("ongoing", "看牙醫", "2030-06-20T01:00:00Z"),
            event("upcoming", "看牙醫"),
        ]):
            matches = list(calendar_service.find_cancellation_candidates("calendar", "看牙醫", now))
        self.assertEqual([item["id"] for item in matches], ["upcoming"])
        self.assertEqual(calendar_service.event_time_text(matches[0]), "12:00")

    def test_cancel_by_id_refuses_recurring_series_master(self):
        now = calendar_service.TZ.localize(datetime(2030, 6, 20, 10))
        calendar = Mock()
        calendar.events.return_value.get.return_value.execute.return_value = {
            **event("series", "看牙醫"),
            "recurrence": ["RRULE:FREQ=WEEKLY"],
        }
        with patch.object(calendar_service, "get_calendar_service", return_value=calendar):
            self.assertIsNone(calendar_service.get_cancellation_candidate("calendar", "series", now))

    def test_reminder_retry_only_sends_to_failed_user(self):
        state = {}
        now = scheduler.TZ.localize(datetime(2030, 6, 20, 8, 5))

        def save_state(key, value, **kwargs):
            state[key] = value

        with (
            patch.object(scheduler, "get_users", return_value=[
                user("rose", "rose@example.com"),
                user("other", "other@example.com"),
                {**user("unapproved", "other@example.com"), "Approved_Calendar_ID": ""},
            ]),
            patch.object(scheduler, "read_bot_state", return_value=state),
            patch.object(scheduler, "store_bot_state", side_effect=save_state),
            patch.object(scheduler, "list_events", return_value=[event("one", "Lunch")]) as list_events,
            patch.object(scheduler, "push_reminder", side_effect=[None, TimeoutError, None]) as push,
            self.assertLogs(scheduler.LOGGER, "ERROR"),
        ):
            first = scheduler.send_reminders(now)
            second = scheduler.send_reminders(now)

        self.assertEqual((first["sent"], first["errors"]), (1, 1))
        self.assertEqual((second["sent"], second["errors"]), (1, 0))
        self.assertEqual([call.args[0] for call in push.call_args_list], ["rose", "other", "other"])
        self.assertEqual(push.call_args_list[1], push.call_args_list[2])
        self.assertIn("12:00 Lunch", push.call_args.args[2])
        self.assertEqual(list_events.call_count, 2)

    def test_line_conflict_with_accepted_request_is_a_successful_replay(self):
        error = scheduler.ApiException(status=409)
        error.headers = {"x-line-accepted-request-id": "accepted-request"}
        with patch.object(scheduler, "MessagingApi") as api:
            push = api.return_value.push_message
            push.side_effect = error
            scheduler.push_reminder("rose", "window", "Reminder")
            scheduler.push_reminder("rose", "window", "Reminder")
        self.assertEqual(push.call_args_list[0], push.call_args_list[1])


class EndpointsTest(unittest.IsolatedAsyncioTestCase):
    async def test_missing_and_invalid_line_signature(self):
        for headers in ({}, {"X-Line-Signature": "invalid"}):
            request = SimpleNamespace(headers=headers, body=AsyncMock(return_value=b"{}"))
            with self.assertRaises(HTTPException) as result:
                await main.callback(request)
            self.assertEqual(result.exception.status_code, 400)

    async def test_callback_runs_sync_handler_off_event_loop(self):
        def blocking_handler(body, signature):
            with self.assertRaises(RuntimeError):
                asyncio.get_running_loop()

        request = SimpleNamespace(headers={"X-Line-Signature": "fake"}, body=AsyncMock(return_value=b"{}"))
        with patch.object(main.HANDLER, "handle", side_effect=blocking_handler):
            self.assertEqual(await main.callback(request), "OK")

    async def test_signed_line_event_reaches_sdk_and_routes_a_todo(self):
        payload = json.dumps({
            "destination": "bot",
            "events": [{
                "type": "message",
                "source": {"type": "user", "userId": "rose"},
                "message": {
                    "type": "text", "id": "message-id", "text": "新增 繳費 12,000 元", "quoteToken": "quote",
                },
                "timestamp": 1700000000000,
                "mode": "active",
                "replyToken": "token",
                "webhookEventId": "01H810YECXQQZ37VAXPF6H9E6T",
                "deliveryContext": {"isRedelivery": False},
            }],
        }).encode()
        signature = base64.b64encode(hmac.digest(b"test-secret", payload, "sha256")).decode()
        request = SimpleNamespace(headers={"X-Line-Signature": signature}, body=AsyncMock(return_value=payload))
        with (
            patch.object(line_service, "get_users", return_value=[user("rose", "")]),
            patch.object(line_service, "read_bot_state", return_value={}),
            patch.object(line_service, "add_user_todos") as add,
            patch.object(line_service, "reply") as reply,
        ):
            self.assertEqual(await main.callback(request), "OK")
        self.assertEqual(add.call_args.args[2], ["繳費 12,000 元"])
        self.assertIn("記錄雜事", reply.call_args.args[1])

    async def test_reminder_partial_failure_returns_503(self):
        with (
            patch.dict("os.environ", {"CRON_SECRET": "test"}),
            patch.object(main, "smart_reminder_job", return_value={"errors": 1, "sent": 1}),
        ):
            response = await main.run_reminder("test")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.body)["status"], "partial_failure")
