"""Date boundaries, pagination, MIME safety, and session-only storage."""

import base64
from datetime import datetime
import json
import os
import time
import unittest
from unittest.mock import Mock, patch

from ghost_box.mail import gmail
from ghost_box.mail import store as mail_store
from ghost_box.mail.text import decode_message


def raw_message(identifier, timestamp):
    raw = b"From: Alice <alice@example.com>\r\nSubject: Hello\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nA private message."
    return {"id": identifier, "threadId": "thread", "internalDate": str(timestamp),
            "raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")}


def response(data):
    result = Mock(status_code=200)
    result.json.return_value = data
    return result


class FetchTests(unittest.TestCase):
    def test_session_mail_is_not_restored_and_clear_removes_it(self):
        mailbox = mail_store.MailStore()
        mailbox.replace("me@example.com", [decode_message(raw_message("one", 1))])
        self.assertEqual(len(mail_store.messages(mailbox, "me@example.com")), 1)
        self.assertEqual(mail_store.messages(mail_store.MailStore(), "me@example.com"), [])
        mailbox.clear()
        self.assertIsNone(mail_store.message(mailbox, "me@example.com", "one"))

    @unittest.skipUnless(hasattr(time, "tzset"), "timezone override requires tzset")
    def test_local_days_and_dst(self):
        previous = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "Europe/Istanbul"
            time.tzset()
            lower, upper = gmail.time_bounds(datetime(2026, 10, 24, 0, 0), datetime(2026, 10, 24, 23, 59))
            self.assertEqual(time.localtime(lower).tm_hour, 0)
            self.assertEqual(upper - lower, 86400)
            os.environ["TZ"] = "America/New_York"
            time.tzset()
            lower, upper = gmail.time_bounds(datetime(2026, 3, 8, 0, 0), datetime(2026, 3, 8, 23, 59))
            self.assertEqual(upper - lower, 23 * 3600)
        finally:
            if previous is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous
            time.tzset()
        with self.assertRaises(gmail.AccountError):
            gmail.time_bounds(datetime(2026, 10, 25), datetime(2026, 10, 24))

    def test_pagination_boundaries_repeat_fetch_and_account_isolation(self):
        first, last = datetime(2026, 10, 24, 9, 30), datetime(2026, 10, 24, 10, 45)
        lower, upper = gmail.time_bounds(first, last)
        self.assertEqual(upper - lower, 76 * 60)
        replies = [
            response({"messages": [{"id": "start"}], "nextPageToken": "next"}),
            response(raw_message("start", lower * 1000)),
            response({"messages": [{"id": "end"}]}),
            response(raw_message("end", upper * 1000)),
        ]
        with (
            patch("ghost_box.mail.gmail.credential_store") as backend,
            patch("ghost_box.mail.gmail.Credentials.from_authorized_user_info") as credentials,
            patch("ghost_box.mail.gmail.AuthorizedSession") as factory,
            patch("builtins.open", side_effect=AssertionError("Email fetching must not open files")),
        ):
            mailbox = mail_store.MailStore()
            backend.return_value.get_password.return_value = json.dumps({
                "email": "me@example.com", "credentials": {"refresh_token": "fake"},
            })
            credentials.return_value.valid = True
            session = factory.return_value.__enter__.return_value
            mailbox.replace("me@example.com", [decode_message(raw_message("old", 1))])
            mailbox.replace("other@example.com", [decode_message(raw_message("other", 1))])
            for _ in range(2):
                session.get.reset_mock()
                session.get.side_effect = replies
                result = gmail.fetch(first, last, mailbox, "me@example.com", Mock(), lambda: False)
                self.assertEqual(result, {"count": 1, "cancelled": False})
                self.assertEqual(session.get.call_args_list[2].kwargs["params"]["pageToken"], "next")
                query = session.get.call_args_list[0].kwargs["params"]["q"]
                self.assertIn(f"after:{lower - 1} before:{upper}", query)
                self.assertIn("-category:promotions", query)
            self.assertEqual(len(mail_store.messages(mailbox, "me@example.com")), 1)
            self.assertEqual(len(mail_store.messages(mailbox, "other@example.com")), 1)
            self.assertIsNone(mail_store.message(mailbox, "me@example.com", "old"))
            self.assertEqual(mail_store.message(mailbox, "me@example.com", "start")["body"], "A private message.")
            coverage=mailbox.coverage['me@example.com'].copy()
            self.assertEqual(coverage['first'],first);self.assertEqual(coverage['last'],last)
            self.assertEqual(coverage['count'],1);self.assertTrue(coverage['exclude_promotions'])
            session.get.reset_mock()
            result = gmail.fetch(first, last, mailbox, "me@example.com", Mock(), lambda: True)
            self.assertTrue(result["cancelled"])
            session.get.assert_not_called()
            self.assertIsNotNone(mail_store.message(mailbox, "me@example.com", "start"))

            # Cancellation after downloading a message discards the pending replacement.
            session.get.side_effect = [
                response({"messages": [{"id": "replacement"}], "nextPageToken": "next"}),
                response(raw_message("replacement", lower * 1000)),
            ]
            stop = {"value": False}
            def cancel_after_progress(_):
                stop["value"] = True
            gmail.fetch(first, last, mailbox, "me@example.com", cancel_after_progress, lambda: stop["value"])
            self.assertIsNotNone(mail_store.message(mailbox, "me@example.com", "start"))
            self.assertIsNone(mail_store.message(mailbox, "me@example.com", "replacement"))

            # Network failure also preserves the previous mailbox.
            session.get.side_effect = RuntimeError("PRIVATE_RESPONSE")
            with self.assertRaises(gmail.AccountError):
                gmail.fetch(first, last, mailbox, "me@example.com", Mock(), lambda: False)
            self.assertIsNotNone(mail_store.message(mailbox, "me@example.com", "start"))

            self.assertEqual(mailbox.coverage['me@example.com'],coverage)

            # A complete empty result is a successful replacement with no messages.
            session.get.side_effect = [response({})]
            gmail.fetch(first, last, mailbox, "me@example.com", Mock(), lambda: False, exclude_promotions=False)
            self.assertFalse(mailbox.coverage["me@example.com"]["exclude_promotions"])
            self.assertEqual(mailbox.coverage["me@example.com"]["count"],0)
            self.assertNotIn("-category:promotions", session.get.call_args.kwargs["params"]["q"])
            self.assertEqual(len(mail_store.messages(mailbox, "me@example.com")), 0)
            self.assertEqual(len(mail_store.messages(mailbox, "other@example.com")), 1)

    def test_html_is_converted_to_text_without_active_content(self):
        raw = b"Content-Type: text/html; charset=utf-8\r\n\r\n<head><style>hide</style></head><p>Hello &amp; welcome</p><script>steal()</script><img src='https://example.com/pixel'>"
        data = raw_message("html", 1)
        data["raw"] = base64.urlsafe_b64encode(raw).decode()
        body = decode_message(data)["body"]
        self.assertIn("Hello & welcome", body)
        self.assertNotIn("steal", body)
        self.assertNotIn("pixel", body)
        self.assertNotIn("hide", body)
