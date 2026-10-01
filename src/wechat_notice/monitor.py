from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable

from .models import MessageRecord
from .storage import NoticeStore


@dataclass(frozen=True)
class MonitorRunResult:
    source_group: str
    new_messages: tuple[MessageRecord, ...] = ()
    duplicate_ids: tuple[str, ...] = ()
    unkeyed_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    read_complete: bool = False
    stop_reason: str | None = None
    cursor: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_group": self.source_group,
            "new_messages": [item.to_dict() for item in self.new_messages],
            "duplicate_ids": list(self.duplicate_ids),
            "unkeyed_ids": list(self.unkeyed_ids),
            "warnings": list(self.warnings),
            "read_complete": self.read_complete,
            "stop_reason": self.stop_reason,
            "cursor": self.cursor,
        }


def _stable_key(message: MessageRecord) -> str | None:
    for key in ("wechat_message_id", "stable_id", "message_id"):
        value = message.metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _text_hash(message: MessageRecord) -> str:
    return hashlib.sha256(message.text.encode("utf-8")).hexdigest()


class MonitorService:
    """One polling pass over an adapter result; never invents message IDs."""

    def __init__(self, store: NoticeStore) -> None:
        self.store = store

    def scan(
        self,
        source_group: str,
        messages: Iterable[MessageRecord],
        *,
        read_complete: bool = True,
        stop_reason: str | None = None,
        cursor: dict[str, Any] | None = None,
    ) -> MonitorRunResult:
        if not source_group.strip():
            raise ValueError("source_group 不能为空")
        new_messages: list[MessageRecord] = []
        duplicate_ids: list[str] = []
        unkeyed_ids: list[str] = []
        warnings: list[str] = []
        maximum_sequence: int | None = None
        for message in messages:
            if message.source_group != source_group:
                warnings.append(f"已忽略不属于源群“{source_group}”的消息 {message.local_id}")
                continue
            maximum_sequence = (
                message.sequence
                if maximum_sequence is None
                else max(maximum_sequence, message.sequence)
            )
            key = _stable_key(message)
            if key is None:
                unkeyed_ids.append(message.local_id)
                continue
            if self.store.mark_message_seen(
                source_group=source_group,
                stable_key=key,
                local_id=message.local_id,
                text_hash=_text_hash(message),
            ):
                new_messages.append(message)
            else:
                duplicate_ids.append(message.local_id)
        if unkeyed_ids:
            warnings.append(
                "部分消息缺少稳定消息标识，未做自动去重；相同正文也不能据此删除："
                + "、".join(unkeyed_ids)
            )
        previous_cursor = self.store.get_monitor_cursor(source_group) or {}
        next_cursor = dict(previous_cursor)
        if cursor:
            next_cursor.update(cursor)
        if maximum_sequence is not None:
            next_cursor["last_visible_sequence"] = maximum_sequence
        if read_complete:
            self.store.save_monitor_cursor(source_group, next_cursor)
        else:
            warnings.append("本次读取不完整，游标未推进；下一次应保留重叠窗口并复核漏读风险")
        return MonitorRunResult(
            source_group=source_group,
            new_messages=tuple(new_messages),
            duplicate_ids=tuple(duplicate_ids),
            unkeyed_ids=tuple(unkeyed_ids),
            warnings=tuple(warnings),
            read_complete=read_complete,
            stop_reason=stop_reason,
            cursor=next_cursor or None,
        )
