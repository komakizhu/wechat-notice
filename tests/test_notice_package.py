import tempfile
import unittest
from pathlib import Path

from PIL import Image

from wechat_notice.models import AppSettings, MessageRecord
from wechat_notice.notice_package import NoticeFacts, build_notice_package, write_notice_package
from wechat_notice.monitor import MonitorService
from wechat_notice.storage import NoticeStore


class NoticePackageTests(unittest.TestCase):
    def test_collection_keeps_source_deadline_and_suggests_separately(self) -> None:
        facts = NoticeFacts.from_dict(
            {
                "notice_id": "class-files",
                "title": "实验报告汇总",
                "item_type": "class_collection",
                "audience": "各小组",
                "task": "提交实验报告和汇总表",
                "materials": ["实验报告.pdf", "汇总表.xlsx"],
                "steps": ["填写汇总表", "交给学习委员"],
                "submission_method": "发给学习委员",
                "collection_required": True,
                "original_deadline": "2026-09-20",
                "source_message_ids": ["m-class"],
            }
        )

        package = build_notice_package(facts, AppSettings(collection_advance_days=2))

        self.assertEqual(package.class_deadline, "2026-09-20")
        self.assertIn("2026年09月20日", package.polished_text)
        self.assertIn("2026年09月20日", package.concise_text)
        self.assertIn("2026年09月20日", package.mermaid)
        self.assertIn("2026年09月20日", package.reminder_preview)
        self.assertIn("实验报告.pdf", package.mermaid)
        self.assertIn("发给学习委员", package.mermaid)
        self.assertIn("2026年09月18日 12:00", package.review_notes)
        self.assertNotIn("2026年09月18日", package.polished_text)
        self.assertIn("2026年09月20日", package.review_notes)

    def test_personal_notice_keeps_original_deadline_and_mermaid_escapes_labels(self) -> None:
        facts = NoticeFacts.from_dict(
            {
                "notice_id": "personal-event",
                "title": '英语考试报名 [补充] "重要"',
                "item_type": "personal_submission",
                "audience": "需要报名的同学",
                "task": "完成个人报名",
                "materials": ["身份证号"],
                "submission_method": "通过报名链接提交",
                "collection_required": False,
                "original_deadline": "2026-10-01",
            }
        )

        package = build_notice_package(facts)

        self.assertEqual(package.class_deadline, "2026-10-01")
        self.assertIn("2026年10月01日", package.polished_text)
        self.assertIn("2026年10月01日", package.concise_text)
        self.assertIn("&quot;重要&quot;", package.mermaid)
        self.assertNotIn('"重要"', package.mermaid)
        self.assertIn("未提前", package.review_notes)

    def test_write_package_creates_markdown_mermaid_and_two_images_without_mmdc(self) -> None:
        facts = NoticeFacts.from_dict(
            {
                "notice_id": "simulated",
                "title": "班级活动",
                "audience": "全班同学",
                "task": "填写报名信息",
                "materials": ["报名表"],
                "submission_method": "在线表单",
                "original_deadline": "2026-09-30",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            result = write_notice_package(facts, Path(directory), mmdc="__not-installed__")

            paths = {path.name for path in Path(directory, "simulated").iterdir()}
            self.assertTrue({"notice.md", "flowchart.mmd", "flowchart.png", "summary.png", "package.json"} <= paths)
            self.assertEqual(result.rendering["flowchart"], "fallback")
            self.assertGreater(Path(directory, "simulated", "flowchart.png").stat().st_size, 100)
            self.assertGreater(Path(directory, "simulated", "summary.png").stat().st_size, 100)

    def test_unparseable_deadline_is_kept_as_a_review_gap_instead_of_being_guessed(self) -> None:
        package = build_notice_package(
            NoticeFacts.from_dict(
                {
                    "notice_id": "unclear-date",
                    "title": "日期待核对",
                    "audience": "同学",
                    "task": "提交材料",
                    "original_deadline": "下周五",
                    "collection_required": True,
                }
            )
        )

        self.assertIsNone(package.class_deadline)
        self.assertIn("无法解析", package.review_notes)
        self.assertIn("待确认", package.review_notes)
        self.assertNotIn("截止时间：", package.polished_text)

    def test_show_original_deadline_is_consistent_across_outward_text_and_graph(self) -> None:
        package = build_notice_package(
            NoticeFacts.from_dict(
                {
                    "notice_id": "show-date",
                    "title": "展示原截止",
                    "audience": "各组",
                    "task": "统一交表",
                    "collection_required": True,
                    "original_deadline": "2026-09-20",
                    "show_original_deadline": True,
                }
            )
        )

        for outward in (package.polished_text, package.concise_text, package.reminder_preview, package.mermaid):
            self.assertIn("2026年09月20日", outward)

    def test_short_notice_uses_parallel_one_screen_overview(self) -> None:
        package = build_notice_package(
            NoticeFacts.from_dict(
                {
                    "notice_id": "compact-overview",
                    "title": "课堂作业提交",
                    "audience": "全班同学",
                    "task": "完成作业并提交",
                    "materials": ["作业文件", "提交截图"],
                    "steps": ["完成作业", "核对文件", "提交到群文件"],
                    "submission_method": "发到班级群文件",
                    "original_deadline": "2026-09-30",
                }
            )
        )

        self.assertEqual(len(package.flowchart_chapters), 1)
        self.assertIn("flowchart LR", package.mermaid)
        self.assertIn("start --> info", package.mermaid)
        self.assertIn("start --> materials", package.mermaid)
        self.assertIn("start --> deadline", package.mermaid)
        self.assertIn("start --> submit", package.mermaid)
        self.assertIn("完成作业", package.mermaid)
        self.assertIn("step1 --> step2", package.mermaid)
        self.assertIn("step2 --> step3", package.mermaid)

    def test_long_notice_splits_chapters_and_keeps_each_fallback_on_screen(self) -> None:
        facts = NoticeFacts.from_dict(
            {
                "notice_id": "chaptered-notice",
                "title": "调研与汇总提交",
                "audience": "各小组负责人",
                "task": "完成调研并提交汇总",
                "materials": [
                    "通知原文.pdf",
                    "数据表.xlsx",
                    "授权书.docx",
                    "公众号图片",
                    "补充说明.txt",
                ],
                "steps": [
                    "确认负责人和截止日期",
                    "领取并核对材料",
                    "完成调研",
                    "整理调研汇总",
                    "检查内容完整性",
                    "发给学习委员",
                ],
                "submission_method": "发给学习委员",
                "original_deadline": "2026-10-20",
                "decision_points": [
                    {
                        "question": "材料是否齐全？",
                        "yes": "继续办理",
                        "no": "补齐材料后再办理",
                    },
                    {
                        "question": "汇总内容是否完整？",
                        "yes": "提交",
                        "no": "补充或修改",
                    },
                ],
                "reminder_offsets": [5, 2, 1],
            }
        )

        with tempfile.TemporaryDirectory() as directory:
            package = write_notice_package(facts, directory, mmdc="__not-installed__")

            self.assertGreater(len(package.flowchart_chapters), 1)
            self.assertIn("按章节", Path(package.artifact_paths["markdown"]).read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(package.chapter_artifact_paths), 2)
            detail_sources = "\n".join(
                chapter.mermaid
                for chapter in package.flowchart_chapters
                if chapter.chapter_id.startswith("details")
            )
            self.assertIn("5、检查内容完整性", detail_sources)
            self.assertIn("6、发给学习委员", detail_sources)
            for paths in package.chapter_artifact_paths.values():
                with Image.open(paths["flowchart"]) as image:
                    self.assertLessEqual(image.height, 1100)

    def test_source_time_and_suggestion_do_not_mix(self) -> None:
        p = build_notice_package({"title": "收表", "collection_required": True, "original_deadline": "2026-10-20T01:00:00Z"})
        for text in (p.polished_text, p.concise_text, p.mermaid, p.reminder_preview):
            self.assertIn("2026年10月20日 09:00", text)
            self.assertNotIn("2026年10月18日", text)
        self.assertIn("2026年10月18日 12:00", p.review_notes)

    def test_explicit_class_date_is_preserved_without_subtraction(self) -> None:
        p = build_notice_package({"title": "收表", "collection_required": True, "original_deadline": "2026-10-20", "class_deadline": "2026-10-16T12:00:00+08:00"})
        self.assertEqual(p.class_deadline, "2026-10-16T12:00:00+08:00")
        for text in (p.polished_text, p.concise_text, p.mermaid, p.reminder_preview):
            self.assertIn("2026年10月16日 12:00", text)
            self.assertNotIn("2026年10月20日", text)

    def test_invitation_has_no_missing_action_fields_or_editor_workflow(self) -> None:
        p = build_notice_package({"title": "讲座", "task": "感兴趣的同学可自愿参加", "reminders_enabled": False})
        for text in (p.polished_text, p.concise_text, p.mermaid):
            for unwanted in ("未说明", "未提供", "截止", "提交", "材料", "用户审核", "转发"):
                self.assertNotIn(unwanted, text)
            self.assertIn("自愿", text)
        self.assertEqual(p.reminder_offsets, ())
        self.assertEqual(p.reminder_preview, "")

    def test_disabled_reminders_with_a_deadline_have_no_nodes(self) -> None:
        p = build_notice_package({"title": "截止", "original_deadline": "2026-10-20", "reminders_enabled": False})
        self.assertEqual(p.reminder_offsets, ())
        self.assertEqual(p.reminder_preview, "")
        self.assertNotIn("提醒", p.mermaid)

    def test_semantically_independent_actions_have_no_serial_edges(self) -> None:
        p = build_notice_package({"title": "准备", "steps": ["准备照片", "准备证件"], "steps_relation": "parallel"})
        self.assertNotIn("step1 --> step2", p.mermaid)
        self.assertIn("start --> step1", p.mermaid)
        self.assertIn("start --> step2", p.mermaid)



class MonitorTests(unittest.TestCase):
    def test_monitor_deduplicates_stable_ids_but_keeps_same_text_with_different_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = NoticeStore(Path(directory) / "data")
            monitor = MonitorService(store)
            first = MessageRecord(
                "visible-1",
                "大群",
                1,
                "收到",
                metadata={"stable_id": "wechat-1"},
            )
            same_text_new_id = MessageRecord(
                "visible-2",
                "大群",
                2,
                "收到",
                metadata={"stable_id": "wechat-2"},
            )

            first_run = monitor.scan("大群", [first, same_text_new_id])
            second_run = monitor.scan("大群", [first, same_text_new_id])

            self.assertEqual([item.local_id for item in first_run.new_messages], ["visible-1", "visible-2"])
            self.assertEqual(second_run.new_messages, ())
            self.assertEqual(set(second_run.duplicate_ids), {"visible-1", "visible-2"})

    def test_monitor_does_not_claim_to_deduplicate_without_a_stable_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            monitor = MonitorService(NoticeStore(Path(directory) / "data"))
            result = monitor.scan(
                "大群",
                [MessageRecord("view-1", "大群", 1, "重复内容")],
            )

            self.assertEqual(result.new_messages, ())
            self.assertEqual(result.unkeyed_ids, ("view-1",))
            self.assertIn("稳定消息标识", result.warnings[0])


if __name__ == "__main__":
    unittest.main()
