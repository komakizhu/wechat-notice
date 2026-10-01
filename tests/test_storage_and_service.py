import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from wechat_notice.models import (
    AppSettings,
    DeliveryStatus,
    MessageRecord,
    MessageRelation,
    NoticeStatus,
    ReminderStatus,
)
from wechat_notice.material_reader import FetchedContent, MaterialReader
from wechat_notice.service import AttachmentInput, NoticeService
from wechat_notice.storage import NoticeStore


class StorageAndServiceTests(unittest.TestCase):
    def _service(self, directory: str) -> tuple[NoticeStore, NoticeService]:
        store = NoticeStore(Path(directory) / "data")
        store.save_batch("batch-1", "大群", [])
        return store, NoticeService(store)

    def test_ingest_preserves_an_original_and_builds_codex_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "上级通知.txt"
            source.write_text("请各班汇总名单。截止 2026-09-20。", encoding="utf-8")
            store, service = self._service(directory)
            messages = [
                MessageRecord("m1", "大群", 0, "请各班汇总名单", sender=None),
                MessageRecord("m2", "大群", 1, "附件见文件", attachment_ids=("a1",)),
            ]

            batch_id = service.ingest_batch(
                source_group="大群",
                messages=messages,
                attachments=[AttachmentInput("a1", "大群", "m2", source.name, source)],
                relations=[MessageRelation("m2", "m1", "supplement", confirmed=True)],
                batch_id="batch-1",
                read_complete=False,
                read_stop_reason="current_ax_view_only",
            )

            stored = store.get_attachment("a1")
            context = service.context_for_codex(batch_id)
            self.assertIsNotNone(stored)
            self.assertIsNotNone(stored.stored_path)
            self.assertEqual(
                Path(stored.stored_path).read_text(encoding="utf-8"),
                source.read_text(encoding="utf-8"),
            )
            self.assertEqual(stored.extraction_status, "extracted")
            self.assertIn("截止 2026-09-20", stored.extracted_text)
            self.assertEqual(context["messages"][1]["attachment_ids"], ["a1"])
            self.assertEqual(context["attachments"][0]["source_message_id"], "m2")
            self.assertEqual(context["message_relations"][0]["relation_type"], "supplement")

            service.store.save_batch(
                batch_id,
                "大群",
                [MessageRecord("m3", "大群", 2, "网页 https://example.org/notice。"), *messages],
            )
            self.assertEqual(service.context_for_codex(batch_id)["material_urls"], ["https://example.org/notice"])

            material_reader = MaterialReader(
                fetcher=lambda _url: FetchedContent(
                    "<title>网页通知</title><p>请在周五前提交。</p>".encode(),
                    "text/html",
                )
            )
            materials = service.read_batch_materials(batch_id, reader=material_reader)
            self.assertEqual(materials[0]["title"], "网页通知")
            self.assertEqual(service.context_for_codex(batch_id)["materials"][0]["status"], "extracted")

    def test_notice_dates_and_review_revision_follow_the_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service = self._service(directory)
            notice = service.create_notice(
                batch_id="batch-1",
                title="汇总名单",
                source_message_ids=["m1"],
                attachment_ids=[],
                collection_required=True,
                original_deadline="2026-09-20",
                submission_method="交给班长",
                target_group="班级群",
                notice_id="notice-1",
            )

            self.assertEqual(notice.class_deadline, "2026-09-20")
            self.assertEqual(notice.status, NoticeStatus.DRAFT)
            self.assertIn("2026年09月20日", service.render_review_packet("notice-1"))
            self.assertIn("收交建议：建议于2026年09月18日 12:00", service.render_review_packet("notice-1"))

            revised = service.save_review(
                "notice-1",
                polished_text="请各组于 9 月 18 日前交齐。",
                concise_text="谁：各组；做什么：交名单；何时：9 月 18 日前。",
                approved=True,
            )
            self.assertEqual(revised.status, NoticeStatus.APPROVED)
            self.assertEqual(revised.revision, notice.revision + 1)

    def test_approval_requires_a_target_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _store, service = self._service(directory)
            service.create_notice(
                batch_id="batch-1",
                title="缺少目标群",
                source_message_ids=["m1"],
                attachment_ids=[],
                collection_required=False,
                original_deadline=None,
                notice_id="notice-no-target",
            )

            with self.assertRaisesRegex(ValueError, "目标群"):
                service.save_review(
                    "notice-no-target",
                    polished_text="正文",
                    concise_text="省流",
                    approved=True,
                )

    def test_global_setting_change_does_not_rewrite_an_approved_notice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service = self._service(directory)
            service.create_notice(
                batch_id="batch-1",
                title="已审核事项",
                source_message_ids=[],
                attachment_ids=[],
                collection_required=True,
                original_deadline="2026-09-20",
                target_group="班级群",
                notice_id="notice-1",
            )
            approved = service.save_review("notice-1", polished_text="x", concise_text="x", approved=True)
            service.update_settings(AppSettings(collection_advance_days=5))

            current = store.get_notice("notice-1")
            self.assertEqual(approved.class_deadline, "2026-09-20")
            self.assertEqual(current.class_deadline, "2026-09-20")
            self.assertEqual(current.advance_days, 2)

    def test_global_setting_change_recalculates_a_draft(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service = self._service(directory)
            draft = service.create_notice(
                batch_id="batch-1",
                title="待审核事项",
                source_message_ids=[],
                attachment_ids=[],
                collection_required=True,
                original_deadline="2026-09-20",
                notice_id="notice-draft",
            )

            service.update_settings(AppSettings(collection_advance_days=5))

            current = store.get_notice("notice-draft")
            self.assertIsNotNone(current)
            self.assertEqual(current.class_deadline, "2026-09-20")
            self.assertEqual(current.revision, draft.revision + 1)

    def test_delivery_status_is_recorded_separately_from_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service = self._service(directory)
            service.create_notice(
                batch_id="batch-1",
                title="发送状态事项",
                source_message_ids=[],
                attachment_ids=[],
                collection_required=False,
                original_deadline=None,
                target_group="班级群",
                notice_id="notice-delivery",
            )

            service.save_review("notice-delivery", polished_text="x", concise_text="x", approved=True)
            current = service.set_delivery_status("notice-delivery", DeliveryStatus.RESULT_UNCERTAIN)

            self.assertEqual(current.status, NoticeStatus.APPROVED)
            self.assertEqual(current.delivery_status, DeliveryStatus.RESULT_UNCERTAIN)
            self.assertEqual(store.get_notice("notice-delivery").delivery_status, DeliveryStatus.RESULT_UNCERTAIN)

    def test_missing_attachment_is_recorded_without_losing_the_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service = self._service(directory)
            service.ingest_batch(
                source_group="大群",
                messages=[MessageRecord("m1", "大群", 0, "见附件")],
                attachments=[
                    AttachmentInput(
                        "missing-attachment",
                        "大群",
                        "m1",
                        "不存在.pdf",
                        Path(directory) / "does-not-exist.pdf",
                    )
                ],
                batch_id="batch-1",
            )

            attachment = store.get_attachment("missing-attachment")
            self.assertIsNotNone(attachment)
            self.assertEqual(attachment.extraction_status, "failed")
            self.assertIn("复制失败", attachment.error or "")

    def test_reminder_reconciliation_is_idempotent_and_reacts_to_date_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service = self._service(directory)
            service.create_notice(
                batch_id="batch-1",
                title="汇总名单",
                source_message_ids=[],
                attachment_ids=[],
                collection_required=True,
                original_deadline="2026-09-20",
                target_group="班级群",
                notice_id="notice-1",
            )
            service.save_review(
                "notice-1",
                polished_text="请提交名单。",
                concise_text="提交名单。",
                approved=True,
            )

            due = service.prepare_due_reminders(datetime.fromisoformat("2026-09-18T09:00:00+08:00"))
            self.assertEqual(len(due), 1)
            self.assertEqual(due[0]["status"], ReminderStatus.GENERATED.value)
            self.assertEqual(
                service.prepare_due_reminders(datetime.fromisoformat("2026-09-18T09:01:00+08:00")),
                [],
            )

            service.update_notice_parameters("notice-1", original_deadline="2026-09-25")
            rows = store.list_reminders("notice-1")
            self.assertTrue(any(row["status"] == ReminderStatus.CANCELLED.value for row in rows))
            self.assertFalse(any(row["scheduled_for"].startswith("2026-09-23") for row in rows))

            # Changing a timing field invalidates approval. Re-approval creates
            # the new reminder nodes for the updated deadline.
            service.save_review(
                "notice-1",
                polished_text="请提交名单。",
                concise_text="提交名单。",
                approved=True,
            )
            rows = store.list_reminders("notice-1")
            self.assertTrue(any(row["scheduled_for"].startswith("2026-09-23") for row in rows))

    def test_global_reminder_settings_do_not_rewrite_approved_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service = self._service(directory)
            service.create_notice(
                batch_id="batch-1",
                title="固定提醒事项",
                source_message_ids=[],
                attachment_ids=[],
                collection_required=True,
                original_deadline="2026-09-20",
                target_group="班级群",
                notice_id="notice-fixed-reminder",
            )
            service.save_review("notice-fixed-reminder", polished_text="x", concise_text="x", approved=True)
            before = store.list_reminders("notice-fixed-reminder")

            service.update_settings(AppSettings(reminder_offsets=[4], reminder_time="10:30"))

            after = store.list_reminders("notice-fixed-reminder")
            self.assertEqual(
                [(row["offset_days"], row["scheduled_for"], row["rendered_text"]) for row in after],
                [(row["offset_days"], row["scheduled_for"], row["rendered_text"]) for row in before],
            )

    def test_overdue_notice_is_reported_once_and_does_not_replay_old_reminders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _store, service = self._service(directory)
            service.create_notice(
                batch_id="batch-1",
                title="已截止事项",
                source_message_ids=[],
                attachment_ids=[],
                collection_required=True,
                original_deadline="2026-09-20",
                target_group="班级群",
                notice_id="notice-overdue",
            )
            service.save_review("notice-overdue", polished_text="x", concise_text="x", approved=True)

            first = service.prepare_due_reminders(datetime.fromisoformat("2026-09-21T09:00:00+08:00"))
            second = service.prepare_due_reminders(datetime.fromisoformat("2026-09-21T09:01:00+08:00"))
            self.assertEqual([item["status"] for item in first], ["overdue"])
            self.assertEqual(second, [])

    def test_multiple_missed_reminders_are_coalesced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _store, service = self._service(directory)
            service.create_notice(
                batch_id="batch-1",
                title="合并提醒事项",
                source_message_ids=[],
                attachment_ids=[],
                collection_required=True,
                original_deadline="2026-09-20",
                target_group="班级群",
                notice_id="notice-coalesced",
            )
            service.save_review("notice-coalesced", polished_text="x", concise_text="x", approved=True)

            result = service.prepare_due_reminders(datetime.fromisoformat("2026-09-19T12:00:00+08:00"))

            self.assertEqual(len(result), 1)
            self.assertTrue(result[0]["coalesced"])
            self.assertEqual(result[0]["missed_offsets"], [2, 1])

    def test_show_original_deadline_is_applied_to_reminder_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service = self._service(directory)
            service.update_settings(AppSettings(show_original_deadline=True, reminder_offsets=[1]))
            service.create_notice(
                batch_id="batch-1",
                title="展示原截止事项",
                source_message_ids=[],
                attachment_ids=[],
                collection_required=True,
                original_deadline="2026-09-20",
                target_group="班级群",
                notice_id="notice-original",
            )
            service.save_review("notice-original", polished_text="x", concise_text="x", approved=True)

            due = service.prepare_due_reminders(datetime.fromisoformat("2026-09-19T09:00:00+08:00"))

            self.assertEqual(len(due), 1)
            self.assertIn("上级截止：2026年09月20日", due[0]["rendered_text"])

    def test_disabled_notice_does_not_create_reminders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service = self._service(directory)
            service.create_notice(
                batch_id="batch-1",
                title="不提醒事项",
                source_message_ids=[],
                attachment_ids=[],
                collection_required=True,
                original_deadline="2026-09-20",
                target_group="班级群",
                reminders_enabled=False,
                notice_id="notice-no-reminder",
            )
            service.save_review("notice-no-reminder", polished_text="x", concise_text="x", approved=True)

            self.assertEqual(store.list_reminders("notice-no-reminder"), [])

    def test_structured_facts_and_generated_artifacts_are_persisted_by_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service = self._service(directory)
            notice = service.create_notice(
                batch_id="batch-1",
                title="结构化通知",
                source_message_ids=["m-facts"],
                attachment_ids=[],
                collection_required=True,
                original_deadline="2026-09-20",
                submission_method="交给班长",
                target_group="班级群",
                notice_id="notice-facts",
                facts={
                    "audience": "各组长",
                    "task": "提交名单",
                    "materials": ["名单.xlsx"],
                    "steps": ["填写表格"],
                },
            )

            saved = store.get_notice(notice.notice_id)
            self.assertEqual(saved.facts["task"], "提交名单")

            package = service.generate_notice_package(
                notice.notice_id,
                output_root=Path(directory) / "artifacts",
                mmdc="__not-installed__",
            )

            artifacts = store.list_artifacts(notice.notice_id, notice_revision=notice.revision)
            self.assertEqual({row["artifact_type"] for row in artifacts}, {"markdown", "mermaid", "flowchart", "summary"})
            self.assertEqual(package.class_deadline, "2026-09-20")

    def test_accepting_class_date_invalidates_review_and_reschedules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service = self._service(directory)
            notice = service.create_notice(batch_id="batch-1", title="收表", source_message_ids=[], attachment_ids=[], collection_required=True, original_deadline="2026-10-20", target_group="班级群")
            approved = service.save_review(notice.notice_id, polished_text="正文", concise_text="省流", approved=True)
            revised = service.update_notice_parameters(notice.notice_id, facts={"class_deadline": "2026-10-17T12:00:00+08:00"})
            self.assertEqual(revised.status, NoticeStatus.DRAFT)
            self.assertGreater(revised.revision, approved.revision)
            self.assertEqual(revised.class_deadline, "2026-10-17T12:00:00+08:00")
            self.assertTrue(all(row["status"] == "cancelled" for row in store.list_reminders(notice.notice_id)))
            service.save_review(notice.notice_id, polished_text="新版", concise_text="新版省流", approved=True)
            pending = [row for row in store.list_reminders(notice.notice_id) if row["status"] == "pending"]
            self.assertEqual({row["scheduled_for"] for row in pending}, {"2026-10-15T09:00:00+08:00", "2026-10-16T09:00:00+08:00"})



if __name__ == "__main__":
    unittest.main()
