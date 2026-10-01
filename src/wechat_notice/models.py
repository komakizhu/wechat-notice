from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo


class NoticeStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    CANCELLED = "cancelled"


class ReminderStatus(StrEnum):
    PENDING = "pending"
    GENERATED = "generated"
    APPROVED = "approved"
    SENT = "sent"
    CANCELLED = "cancelled"


class DeliveryStatus(StrEnum):
    NOT_ATTEMPTED = "not_attempted"
    RESULT_UNCERTAIN = "result_uncertain"
    OBSERVED_SENT = "observed_sent"
    USER_CONFIRMED_SENT = "user_confirmed_sent"


@dataclass(frozen=True)
class MessageRelation:
    """在一批消息中记录补充、更正或引用关系。"""

    source_message_id: str
    related_message_id: str
    relation_type: str
    confirmed: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_message_id": self.source_message_id,
            "related_message_id": self.related_message_id,
            "relation_type": self.relation_type,
            "confirmed": self.confirmed,
            "note": self.note,
        }


@dataclass(frozen=True)
class MessageRecord:
    """从微信或手动输入得到的一条事实记录。

    微信 AX 界面通常无法提供稳定的消息 ID、发送者身份和时间，因此这些
    字段允许为空。``local_id`` 只由本项目生成，不能冒充微信消息 ID。
    """

    local_id: str
    source_group: str
    sequence: int
    text: str = ""
    message_type: str = "unknown"
    sender: str | None = None
    timestamp: str | None = None
    quote_id: str | None = None
    attachment_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["attachment_ids"] = list(self.attachment_ids)
        return result


@dataclass(frozen=True)
class AttachmentRecord:
    attachment_id: str
    source_group: str
    source_message_id: str | None
    original_name: str
    stored_path: str | None = None
    mime_type: str | None = None
    extraction_status: str = "pending"
    extracted_text: str = ""
    locations: tuple[str, ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["locations"] = list(self.locations)
        return result


@dataclass
class AppSettings:
    collection_advance_days: int = 2
    show_original_deadline: bool = False
    reminder_offsets: list[int] = field(default_factory=lambda: [2, 1])
    timezone: str = "Asia/Shanghai"
    reminder_time: str = "09:00"
    use_working_days: bool = False
    allow_item_overrides: bool = True

    def validate(self) -> None:
        if self.collection_advance_days < 0:
            raise ValueError("collection_advance_days must be non-negative")
        if any(offset < 0 for offset in self.reminder_offsets):
            raise ValueError("reminder offsets must be non-negative")
        if not self.timezone.strip():
            raise ValueError("timezone must not be empty")
        try:
            ZoneInfo(self.timezone)
        except Exception as exc:
            raise ValueError(f"unknown timezone: {self.timezone}") from exc
        hour, separator, minute = self.reminder_time.partition(":")
        if not separator or not hour.isdigit() or not minute.isdigit():
            raise ValueError("reminder_time must use HH:MM")
        if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
            raise ValueError("reminder_time must use a valid clock time")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AppSettings":
        settings = cls(
            collection_advance_days=int(value.get("collection_advance_days", 2)),
            show_original_deadline=bool(value.get("show_original_deadline", False)),
            reminder_offsets=[int(x) for x in value.get("reminder_offsets", [2, 1])],
            timezone=str(value.get("timezone", "Asia/Shanghai")),
            reminder_time=str(value.get("reminder_time", "09:00")),
            use_working_days=bool(value.get("use_working_days", False)),
            allow_item_overrides=bool(value.get("allow_item_overrides", True)),
        )
        settings.validate()
        return settings


@dataclass
class NoticeRecord:
    notice_id: str
    batch_id: str
    title: str
    source_message_ids: list[str] = field(default_factory=list)
    attachment_ids: list[str] = field(default_factory=list)
    collection_required: bool = False
    original_deadline: str | None = None
    class_deadline: str | None = None
    advance_days: int | None = None
    show_original_deadline: bool | None = None
    reminder_offsets: list[int] | None = None
    reminder_template: str = "提醒：{title}请于{class_deadline}前完成{submission_method}。"
    submission_method: str = "提交"
    polished_text: str = ""
    concise_text: str = ""
    review_notes: str = ""
    target_group: str | None = None
    reminders_enabled: bool = True
    status: NoticeStatus = NoticeStatus.DRAFT
    delivery_status: DeliveryStatus = DeliveryStatus.NOT_ATTEMPTED
    revision: int = 1
    # Structured facts used to regenerate Markdown/Mermaid artifacts. This is
    # source material, not an instruction to execute any tool operation.
    facts: dict[str, Any] = field(default_factory=dict)

    def effective_advance_days(self, settings: AppSettings) -> int:
        return settings.collection_advance_days if self.advance_days is None else self.advance_days

    def effective_show_original_deadline(self, settings: AppSettings) -> bool:
        return settings.show_original_deadline if self.show_original_deadline is None else self.show_original_deadline

    def effective_reminder_offsets(self, settings: AppSettings) -> list[int]:
        return list(settings.reminder_offsets if self.reminder_offsets is None else self.reminder_offsets)
