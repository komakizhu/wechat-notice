import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wechat_notice.service import NoticeService
from wechat_notice.storage import NoticeStore
from wechat_notice.wechat_mcp import server


class FakeSender:
    def send_reviewed_text(self, chat_name, text, *, approved, allow_foreground):
        return {
            "sent": True,
            "status": "send_called",
            "chat_name": chat_name,
        }


class ServerTests(unittest.TestCase):
    def test_text_send_requires_approved_version_and_blocks_repeat(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory) / "data"
            store = NoticeStore(data_root)
            store.save_batch("batch-1", "大群", [])
            service = NoticeService(store)
            notice = service.create_notice(
                batch_id="batch-1",
                title="发送测试",
                source_message_ids=[],
                attachment_ids=[],
                collection_required=False,
                original_deadline=None,
                target_group="班级群",
                notice_id="notice-send",
            )
            notice = service.save_review(
                notice.notice_id,
                polished_text="审核通过的正文",
                concise_text="省流正文",
                approved=True,
            )

            with patch.dict(os.environ, {"WECHAT_NOTICE_DATA_ROOT": str(data_root)}), patch.object(
                server, "WeChatSender", FakeSender
            ):
                result = server.send_reviewed_text(
                    "班级群",
                    "审核通过的正文",
                    notice_id=notice.notice_id,
                    notice_revision=notice.revision,
                    approved=True,
                    allow_foreground=True,
                )
                repeated = server.send_reviewed_text(
                    "班级群",
                    "审核通过的正文",
                    notice_id=notice.notice_id,
                    notice_revision=notice.revision,
                    approved=True,
                    allow_foreground=True,
                )

            self.assertTrue(result["sent"])
            self.assertEqual(store.list_deliveries(notice.notice_id)[0]["status"], "result_uncertain")
            self.assertEqual(repeated["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
