from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, cast
from zoneinfo import ZoneInfo

from .date_rules import (
    collection_suggestion,
    format_deadline,
    is_expired,
    reminder_schedule,
    serialize_deadline,
)
from .documents import extract_document
from .monitor import MonitorRunResult, MonitorService
from .material_reader import MaterialReader, extract_urls, read_message_materials
from .models import (
    AppSettings,
    AttachmentRecord,
    DeliveryStatus,
    MessageRecord,
    MessageRelation,
    NoticeRecord,
    NoticeStatus,
)
from .notice_package import NoticePackage, write_notice_package
from .storage import NoticeStore


_UNSET = object()


@dataclass(frozen=True)
class AttachmentInput:
    attachment_id: str
    source_group: str
    source_message_id: str | None
    original_name: str
    source_path: str | Path | None = None
    mime_type: str | None = None


class NoticeService:
    """Business operations shared by the Skill, CLI and MCP boundary."""

    def __init__(self, store: NoticeStore, settings: AppSettings | None = None) -> None:
        self.store = store
        self.settings = settings or store.load_settings()
        self.settings.validate()
        self.store.save_settings(self.settings)

    def update_settings(self, settings: AppSettings) -> None:
        previous = self.settings
        settings.validate()
        self.settings = settings
        self.store.save_settings(settings)
        if previous.to_dict() != settings.to_dict():
            # Approved notices have frozen effective parameters. Drafts remain
            # configurable; suggestion changes leave the source deadline intact and
            # force a fresh review context when a global setting changes.
            for notice in self.store.list_notices():
                if notice.status != NoticeStatus.DRAFT:
                    continue
                notice.revision += 1
                self.store.save_notice(notice)
        self.reconcile_reminders()

    def ingest_batch(
        self,
        *,
        source_group: str,
        messages: Iterable[MessageRecord],
        attachments: Iterable[AttachmentInput] = (),
        relations: Iterable[MessageRelation] = (),
        batch_id: str | None = None,
        read_complete: bool = False,
        read_stop_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        batch = batch_id or f"batch-{uuid.uuid4().hex}"
        message_list = list(messages)
        self.store.save_batch(
            batch,
            source_group,
            message_list,
            read_complete=read_complete,
            read_stop_reason=read_stop_reason,
            metadata=metadata,
        )
        self.store.save_message_relations(batch, relations)
        for item in attachments:
            initial = AttachmentRecord(
                attachment_id=item.attachment_id,
                source_group=item.source_group,
                source_message_id=item.source_message_id,
                original_name=item.original_name,
                mime_type=item.mime_type,
                extraction_status="missing" if item.source_path is None else "pending",
                error="未提供原件路径" if item.source_path is None else None,
            )
            if item.source_path is None:
                self.store.save_attachment(batch, initial)
                continue

            try:
                stored = self.store.save_attachment(batch, initial, item.source_path)
            except OSError as exc:
                self.store.save_attachment(
                    batch,
                    AttachmentRecord(
                        attachment_id=initial.attachment_id,
                        source_group=initial.source_group,
                        source_message_id=initial.source_message_id,
                        original_name=initial.original_name,
                        mime_type=initial.mime_type,
                        extraction_status="failed",
                        error=f"原件复制失败: {exc}",
                    ),
                )
                continue
            if stored.stored_path is None:
                continue
            extraction = extract_document(stored.stored_path)
            self.store.save_attachment(
                batch,
                AttachmentRecord(
                    attachment_id=stored.attachment_id,
                    source_group=stored.source_group,
                    source_message_id=stored.source_message_id,
                    original_name=stored.original_name,
                    stored_path=stored.stored_path,
                    mime_type=stored.mime_type,
                    extraction_status=extraction.status,
                    extracted_text=extraction.text,
                    locations=tuple(block.location for block in extraction.blocks),
                    error=extraction.error,
                ),
            )
        return batch

    def create_notice(
        self,
        *,
        batch_id: str,
        title: str,
        source_message_ids: list[str],
        attachment_ids: list[str],
        collection_required: bool,
        original_deadline: str | date | datetime | None,
        submission_method: str = "提交",
        advance_days: int | None = None,
        show_original_deadline: bool | None = None,
        reminder_offsets: list[int] | None = None,
        reminder_template: str | None = None,
        target_group: str | None = None,
        reminders_enabled: bool = True,
        notice_id: str | None = None,
        facts: dict[str, Any] | None = None,
    ) -> NoticeRecord:
        effective_advance = self.settings.collection_advance_days if advance_days is None else advance_days
        if effective_advance < 0:
            raise ValueError("advance_days must be non-negative")
        effective_offsets = self.settings.reminder_offsets if reminder_offsets is None else reminder_offsets
        if any(offset < 0 for offset in effective_offsets):
            raise ValueError("reminder_offsets must be non-negative")
        class_deadline = (facts or {}).get("class_deadline") or original_deadline
        notice = NoticeRecord(
            notice_id=notice_id or f"notice-{uuid.uuid4().hex}",
            batch_id=batch_id,
            title=title,
            source_message_ids=list(source_message_ids),
            attachment_ids=list(attachment_ids),
            collection_required=collection_required,
            original_deadline=serialize_deadline(original_deadline),
            class_deadline=serialize_deadline(class_deadline),
            advance_days=advance_days,
            show_original_deadline=show_original_deadline,
            reminder_offsets=reminder_offsets,
            reminder_template=reminder_template
            or "提醒：{title}请于{class_deadline}前完成{submission_method}。",
            submission_method=submission_method,
            target_group=target_group,
            reminders_enabled=reminders_enabled,
            facts=dict(facts or {}),
        )
        self.store.save_notice(notice)
        self.reconcile_reminders()
        return notice

    def update_notice_parameters(
        self,
        notice_id: str,
        *,
        source_message_ids: list[str] | None | object = _UNSET,
        attachment_ids: list[str] | None | object = _UNSET,
        collection_required: bool | object = _UNSET,
        original_deadline: str | date | datetime | None | object = _UNSET,
        advance_days: int | None | object = _UNSET,
        show_original_deadline: bool | None | object = _UNSET,
        reminder_offsets: list[int] | None | object = _UNSET,
        submission_method: str | None = None,
        reminder_template: str | None = None,
        target_group: str | None | object = _UNSET,
        reminders_enabled: bool | object = _UNSET,
        facts: dict[str, Any] | object = _UNSET,
    ) -> NoticeRecord:
        """Change a draft's timing rules and invalidate its prior approval."""
        notice = self.store.get_notice(notice_id)
        if notice is None:
            raise KeyError(f"通知不存在: {notice_id}")
        if notice.status == NoticeStatus.CANCELLED:
            raise ValueError("已取消的通知不能直接重新进入审核，请创建新的通知事项")
        if source_message_ids is not _UNSET:
            notice.source_message_ids = (
                []
                if source_message_ids is None
                else [str(item) for item in cast(list[str], source_message_ids)]
            )
        if attachment_ids is not _UNSET:
            notice.attachment_ids = (
                []
                if attachment_ids is None
                else [str(item) for item in cast(list[str], attachment_ids)]
            )
        if collection_required is not _UNSET:
            notice.collection_required = bool(collection_required)
        if original_deadline is not _UNSET:
            notice.original_deadline = serialize_deadline(cast(Any, original_deadline))
        if advance_days is not _UNSET:
            notice.advance_days = None if advance_days is None else int(cast(int, advance_days))
            if notice.advance_days is not None and notice.advance_days < 0:
                raise ValueError("advance_days must be non-negative")
        if show_original_deadline is not _UNSET:
            notice.show_original_deadline = None if show_original_deadline is None else bool(show_original_deadline)
        if reminder_offsets is not _UNSET:
            notice.reminder_offsets = None if reminder_offsets is None else list(cast(list[int], reminder_offsets))
            if notice.reminder_offsets is not None and any(offset < 0 for offset in notice.reminder_offsets):
                raise ValueError("reminder_offsets must be non-negative")
        if submission_method is not None:
            notice.submission_method = submission_method
        if reminder_template is not None:
            notice.reminder_template = reminder_template
        if target_group is not _UNSET:
            notice.target_group = None if target_group is None else str(target_group)
        if reminders_enabled is not _UNSET:
            notice.reminders_enabled = bool(reminders_enabled)
        if facts is not _UNSET:
            notice.facts = {} if facts is None else dict(cast(dict[str, Any], facts))

        notice.class_deadline = serialize_deadline(notice.facts.get("class_deadline") or notice.original_deadline)
        notice.status = NoticeStatus.DRAFT
        notice.revision += 1
        self.store.save_notice(notice)
        self.reconcile_reminders()
        return notice

    def monitor_once(
        self,
        source_group: str,
        messages: Iterable[MessageRecord],
        *,
        read_complete: bool = True,
        stop_reason: str | None = None,
        cursor: dict[str, Any] | None = None,
    ) -> MonitorRunResult:
        """Process one adapter polling window and retain only stable new keys."""
        return MonitorService(self.store).scan(
            source_group,
            messages,
            read_complete=read_complete,
            stop_reason=stop_reason,
            cursor=cursor,
        )

    def read_batch_materials(
        self,
        batch_id: str,
        *,
        reader: MaterialReader | None = None,
    ) -> list[dict[str, Any]]:
        """Read and persist web/article material linked from a saved batch."""
        if self.store.get_batch_info(batch_id) is None:
            raise KeyError(f"批次不存在: {batch_id}")
        results = read_message_materials(
            self.store.get_batch_messages(batch_id), reader=reader
        )
        for result in results:
            self.store.save_material(batch_id, result.to_dict())
        return [result.to_dict() for result in results]

    def generate_notice_package(
        self,
        notice_id: str,
        *,
        facts: dict[str, Any] | None = None,
        output_root: str | Path = "data/artifacts",
        mmdc: str | None = None,
    ) -> NoticePackage:
        """Generate version-bound text, Mermaid and image artifacts for review."""
        notice = self.store.get_notice(notice_id)
        if notice is None:
            raise KeyError(f"通知不存在: {notice_id}")
        payload = dict(notice.facts)
        if facts:
            payload.update(facts)
        payload.update(
            {
                "notice_id": notice.notice_id,
                "title": notice.title,
                "collection_required": notice.collection_required,
                "original_deadline": notice.original_deadline,
                "class_deadline": notice.facts.get("class_deadline"),
                "reminders_enabled": notice.reminders_enabled,
                "reminder_offsets": notice.effective_reminder_offsets(self.settings),
                "submission_method": notice.submission_method,
                "target_group": notice.target_group,
                "source_message_ids": notice.source_message_ids,
                "show_original_deadline": notice.effective_show_original_deadline(self.settings),
                "advance_days": notice.effective_advance_days(self.settings),
            }
        )
        if "attachment_names" not in payload:
            attachment_records = [
                self.store.get_attachment(attachment_id)
                for attachment_id in notice.attachment_ids
            ]
            payload["attachment_names"] = [
                item.original_name for item in attachment_records if item is not None
            ]
            payload["attachment_paths"] = [
                item.stored_path or "原件缺失"
                for item in attachment_records
                if item is not None
            ]
        package = write_notice_package(
            payload,
            output_root,
            settings=self.settings,
            mmdc=mmdc,
        )
        for artifact_type, path in package.artifact_paths.items():
            if artifact_type == "package_json":
                continue
            self.store.save_artifact(
                notice_id=notice.notice_id,
                notice_revision=notice.revision,
                artifact_type=artifact_type,
                path=path,
            )
        overview_id = (
            package.flowchart_chapters[0].chapter_id
            if package.flowchart_chapters
            else None
        )
        for chapter_id, chapter_paths in package.chapter_artifact_paths.items():
            if chapter_id == overview_id:
                continue
            for artifact_type, path in chapter_paths.items():
                self.store.save_artifact(
                    notice_id=notice.notice_id,
                    notice_revision=notice.revision,
                    artifact_type=f"{artifact_type}:{chapter_id}",
                    path=path,
                )
        return package

    def save_review(
        self,
        notice_id: str,
        *,
        polished_text: str,
        concise_text: str,
        review_notes: str = "",
        approved: bool = False,
    ) -> NoticeRecord:
        existing = self.store.get_notice(notice_id)
        if existing is None:
            raise KeyError(f"通知不存在: {notice_id}")
        if existing.status == NoticeStatus.CANCELLED:
            raise ValueError("已取消的通知不能重新审核")
        if approved and (not polished_text.strip() or not concise_text.strip()):
            raise ValueError("审核通过前必须同时提供通知润色版和省流版")
        if approved and (not existing.target_group or not existing.target_group.strip()):
            raise ValueError("审核通过前必须明确目标群")
        notice = self.store.save_review(
            notice_id,
            polished_text=polished_text,
            concise_text=concise_text,
            review_notes=review_notes,
            approved=approved,
        )
        if approved:
            # Freeze the effective global values on approval. Later global
            # changes affect drafts only and never rewrite an approved notice.
            notice.advance_days = notice.effective_advance_days(self.settings)
            notice.show_original_deadline = notice.effective_show_original_deadline(self.settings)
            notice.reminder_offsets = notice.effective_reminder_offsets(self.settings)
            self.store.save_notice(notice)
        self.reconcile_reminders()
        return notice

    def cancel_notice(self, notice_id: str) -> NoticeRecord:
        notice = self.store.cancel_notice(notice_id)
        self.reconcile_reminders()
        return notice

    def set_delivery_status(self, notice_id: str, status: str | DeliveryStatus) -> NoticeRecord:
        notice = self.store.get_notice(notice_id)
        if notice is None:
            raise KeyError(f"通知不存在: {notice_id}")
        parsed = status if isinstance(status, DeliveryStatus) else DeliveryStatus(status)
        self.store.set_delivery_status(notice_id, parsed)
        notice.delivery_status = parsed
        return notice

    def render_review_packet(self, notice_id: str) -> str:
        notice = self.store.get_notice(notice_id)
        if notice is None:
            raise KeyError(f"通知不存在: {notice_id}")
        show_original = notice.effective_show_original_deadline(self.settings)
        lines = [f"# 通知草稿：{notice.title}", "", "## 通知润色版", notice.polished_text or "（待 Codex 生成）", ""]
        lines.extend(["## 省流版", notice.concise_text or "（待 Codex 生成）", "", "## 截止日期核对"])
        lines.append(f"班级采用截止时间：{format_deadline(notice.class_deadline)}")
        if show_original or notice.class_deadline == notice.original_deadline:
            lines.append(f"上级原截止时间：{format_deadline(notice.original_deadline)}")
        else:
            lines.append("上级原截止时间：按设置隐藏")
        if notice.collection_required and notice.original_deadline and not notice.facts.get("class_deadline"):
            lines.append(f"**收交建议：建议于{format_deadline(collection_suggestion(notice.original_deadline, notice.effective_advance_days(self.settings)))}收齐。**（仅给用户看，未确认前不改变正文时间。）")
        source_lines = [f"- {message_id}" for message_id in notice.source_message_ids]
        if not source_lines:
            source_lines = ["- 未登记来源消息"]
        artifact_lines = [
            f"- {row['artifact_type']}：{row['path']}"
            for row in self.store.list_artifacts(
                notice.notice_id, notice_revision=notice.revision
            )
        ] or ["- 尚未生成 Mermaid 或图片产出"]
        lines.extend(
            [
                "",
                "## 来源消息",
                *source_lines,
                "",
                "## 原件",
                *self._attachment_lines(notice),
                "",
                "## Mermaid 与图片产出",
                *artifact_lines,
                "",
                "## 审核说明",
                notice.review_notes or "（暂无）",
            ]
        )
        return "\n".join(lines)

    def _attachment_lines(self, notice: NoticeRecord) -> list[str]:
        lines: list[str] = []
        for attachment_id in notice.attachment_ids:
            attachment = self.store.get_attachment(attachment_id)
            if attachment is None:
                lines.append(f"- {attachment_id}：登记信息不存在")
            elif attachment.stored_path:
                lines.append(
                    f"- {attachment.original_name}：{attachment.stored_path}"
                    f"（{attachment.extraction_status}，来源 {attachment.source_message_id or '未知'}）"
                )
            else:
                lines.append(
                    f"- {attachment.original_name}：原件缺失"
                    f"（{attachment.error or '未取得'}，来源 {attachment.source_message_id or '未知'}）"
                )
        return lines or ["- 无附件"]

    def context_for_codex(self, batch_id: str) -> dict[str, Any]:
        batch = self.store.get_batch_info(batch_id)
        messages = self.store.get_batch_messages(batch_id)
        attachments = []
        for attachment in self.store.list_batch_attachments(batch_id):
            attachments.append(
                {
                    "attachment_id": attachment.attachment_id,
                    "source_message_id": attachment.source_message_id,
                    "name": attachment.original_name,
                    "path": attachment.stored_path,
                    "status": attachment.extraction_status,
                    "text": attachment.extracted_text,
                    "locations": list(attachment.locations),
                    "error": attachment.error,
                }
            )
        return {
            "batch_id": batch_id,
            "batch": batch,
            "messages": [message.to_dict() for message in messages],
            "material_urls": list(
                dict.fromkeys(
                    url
                    for message in messages
                    for url in extract_urls(message.text)
                )
            ),
            "materials": self.store.list_materials(batch_id),
            "message_relations": [
                relation.to_dict()
                for relation in self.store.list_message_relations(batch_id)
            ],
            "attachments": attachments,
        }

    def reconcile_reminders(self) -> None:
        desired: list[tuple[str, int, str, str, int]] = []
        for notice in self.store.list_notices():
            if (
                notice.status != NoticeStatus.APPROVED
                or not notice.reminders_enabled
                or notice.class_deadline is None
            ):
                continue
            # A notice freezes its reminder nodes at approval time. This keeps
            # later global changes (clock, calendar mode, or template display)
            # from rewriting an already approved notice. A changed notice gets
            # a new revision and therefore a new schedule below.
            current_rows = [
                row
                for row in self.store.list_reminders(notice.notice_id)
                if int(row["notice_revision"]) == notice.revision
            ]
            if current_rows:
                desired.extend(
                    (
                        notice.notice_id,
                        int(row["offset_days"]),
                        str(row["scheduled_for"]),
                        str(row["rendered_text"]),
                        notice.revision,
                    )
                    for row in current_rows
                    if str(row["status"]) in {"pending", "generated", "approved"}
                )
                continue
            points = reminder_schedule(
                notice.class_deadline,
                notice.effective_reminder_offsets(self.settings),
                reminder_time=self.settings.reminder_time,
                timezone=self.settings.timezone,
                working_days=self.settings.use_working_days,
            )
            for offset, point in zip(
                sorted(set(notice.effective_reminder_offsets(self.settings)), reverse=True),
                points,
            ):
                text = self._render_reminder(notice)
                desired.append((notice.notice_id, offset, point.isoformat(), text, notice.revision))
        self.store.sync_reminders(desired)

    def _render_reminder(self, notice: NoticeRecord) -> str:
        show_original = notice.effective_show_original_deadline(self.settings)
        original_deadline = format_deadline(notice.original_deadline) if notice.original_deadline else ""
        values = {
            "title": notice.title,
            "class_deadline": format_deadline(notice.class_deadline),
            "submission_method": notice.submission_method,
            "original_deadline": original_deadline if show_original else "",
        }
        try:
            text = notice.reminder_template.format(**values)
        except (KeyError, ValueError):
            text = f"提醒：{notice.title}请于{format_deadline(notice.class_deadline)}前完成{notice.submission_method}。"
        if show_original and original_deadline and "{original_deadline}" not in notice.reminder_template:
            text = f"{text}（上级截止：{original_deadline}）"
        if not show_original and original_deadline:
            text = text.replace(f"（上级截止：{original_deadline}）", "")
        return text

    def prepare_due_reminders(self, now: datetime | None = None) -> list[dict[str, Any]]:
        self.reconcile_reminders()
        instant = now or datetime.now().astimezone()
        zone = ZoneInfo(self.settings.timezone)
        instant = instant.replace(tzinfo=zone) if instant.tzinfo is None else instant.astimezone(zone)
        now_iso = instant.isoformat()
        result: list[dict[str, Any]] = []
        for notice in self.store.list_notices():
            if notice.status != NoticeStatus.APPROVED or notice.class_deadline is None:
                continue
            if is_expired(notice.class_deadline, instant, timezone=self.settings.timezone):
                if self.store.claim_overdue_report(notice.notice_id, notice.revision, now_iso):
                    result.append(
                        {
                            "notice_id": notice.notice_id,
                            "title": notice.title,
                            "status": "overdue",
                            "class_deadline": notice.class_deadline,
                            "message": f"事项“{notice.title}”已超过班级截止时间 {format_deadline(notice.class_deadline)}。",
                        }
                    )
        due = self.store.prepare_due_reminders(now_iso)
        by_notice: dict[str, list[dict[str, Any]]] = {}
        for item in due:
            by_notice.setdefault(str(item["notice_id"]), []).append(item)
        for items in by_notice.values():
            if len(items) == 1:
                result.append(items[0])
                continue
            items.sort(key=lambda item: str(item["scheduled_for"]))
            keep = items[-1]
            missed_offsets = [item["offset_days"] for item in items]
            self.store.cancel_reminders(item["reminder_id"] for item in items[:-1])
            keep["coalesced"] = True
            keep["missed_offsets"] = missed_offsets
            keep["rendered_text"] = (
                f"{keep['rendered_text']}（此前提醒节点 {', '.join(str(x) for x in missed_offsets)} 天前未处理，已合并提醒。）"
            )
            result.append(keep)
        return result
