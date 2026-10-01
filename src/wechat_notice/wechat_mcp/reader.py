from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models import MessageRecord
from .ax import AccessibilityUnavailable, WeChatAccessibility


@dataclass(frozen=True)
class FetchResult:
    chat_name: str
    messages: tuple[MessageRecord, ...] = ()
    complete: bool = False
    stop_reason: str | None = None
    missing_fields: tuple[str, ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chat_name": self.chat_name,
            "messages": [message.to_dict() for message in self.messages],
            "complete": self.complete,
            "stop_reason": self.stop_reason,
            "missing_fields": list(self.missing_fields),
            "error": self.error,
        }


class WeChatReader:
    """只读微信适配器；首版限制为当前会话、当前 AX 视图。"""

    def __init__(self, accessibility: WeChatAccessibility | None = None) -> None:
        self.accessibility = accessibility or WeChatAccessibility()

    def capabilities(self) -> dict[str, Any]:
        return self.accessibility.capability_report()

    def fetch_messages_by_chat(self, chat_name: str, *, last_n: int = 50) -> FetchResult:
        if not chat_name.strip():
            return FetchResult(chat_name=chat_name, error="chat_name 不能为空")
        try:
            current = self.accessibility.current_chat_name(activate=False)
            if current != chat_name:
                return FetchResult(
                    chat_name=chat_name,
                    complete=False,
                    stop_reason="target_chat_is_not_current",
                    missing_fields=("messages_outside_current_chat",),
                    error="当前版本只读取已经打开的会话；切换会话需要前台交互和单独授权",
                )
            raw_messages = self.accessibility.current_messages(last_n=last_n)
            messages = tuple(
                MessageRecord(
                    local_id=str(item["local_id"]),
                    source_group=chat_name,
                    sequence=int(item["sequence"]),
                    text=str(item.get("text", "")),
                    message_type=str(item.get("message_type", "unknown")),
                    sender=item.get("sender"),
                    timestamp=item.get("timestamp"),
                    quote_id=item.get("quote_id"),
                    attachment_ids=tuple(item.get("attachment_ids", [])),
                    metadata=dict(item.get("metadata", {})),
                )
                for item in raw_messages
            )
            return FetchResult(
                chat_name=chat_name,
                messages=messages,
                complete=False,
                stop_reason="current_ax_view_only",
                missing_fields=("sender", "timestamp", "wechat_message_id", "attachment_path", "history_beyond_view"),
            )
        except (AccessibilityUnavailable, ValueError) as exc:
            return FetchResult(chat_name=chat_name, error=str(exc))
