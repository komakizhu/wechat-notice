import unittest
from typing import Any

from wechat_notice.wechat_mcp.reader import WeChatReader


class FakeAccessibility:
    def __init__(self) -> None:
        self.activate_values: list[bool] = []

    def capabilities(self) -> dict[str, Any]:
        return {"background_ax_read": "unverified"}

    def current_chat_name(self, *, activate: bool = False) -> str:
        self.activate_values.append(activate)
        return "大群"

    def current_messages(self, *, last_n: int = 50) -> list[dict[str, Any]]:
        return [
            {
                "local_id": "ax-visible-000000",
                "sequence": 0,
                "text": "通知内容",
                "message_type": "text",
                "sender": None,
                "timestamp": None,
                "quote_id": None,
                "attachment_ids": [],
                "metadata": {"identity": "synthetic_visible_index"},
            }
        ][:last_n]


class ReaderTests(unittest.TestCase):
    def test_reader_does_not_activate_for_current_chat_reads(self) -> None:
        fake = FakeAccessibility()
        result = WeChatReader(fake).fetch_messages_by_chat("大群", last_n=10)

        self.assertEqual(result.messages[0].text, "通知内容")
        self.assertFalse(result.complete)
        self.assertIn("sender", result.missing_fields)
        self.assertEqual(fake.activate_values, [False])

    def test_reader_does_not_switch_to_another_chat(self) -> None:
        fake = FakeAccessibility()
        result = WeChatReader(fake).fetch_messages_by_chat("班级群")

        self.assertEqual(result.messages, ())
        self.assertEqual(result.stop_reason, "target_chat_is_not_current")
        self.assertEqual(fake.activate_values, [False])


if __name__ == "__main__":
    unittest.main()
