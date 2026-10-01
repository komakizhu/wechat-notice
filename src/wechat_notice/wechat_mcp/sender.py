from __future__ import annotations

from typing import Any

from .ax import AccessibilityUnavailable, WeChatAccessibility, ax_get, dfs


class WeChatSender:
    """显式授权后发送文字的最小适配器。

    首版不自动导航到目标群，也不实现文件选择对话框。调用者需先打开目标
    会话并同时传入 ``approved`` 与 ``allow_foreground``。
    """

    def __init__(self, accessibility: WeChatAccessibility | None = None) -> None:
        self.accessibility = accessibility or WeChatAccessibility()

    def send_reviewed_text(
        self,
        chat_name: str,
        text: str,
        *,
        approved: bool = False,
        allow_foreground: bool = False,
    ) -> dict[str, Any]:
        if not approved:
            return {
                "sent": False,
                "status": "blocked",
                "reason": "需要用户明确审核通过",
            }
        if not allow_foreground:
            return {
                "sent": False,
                "status": "requires_foreground_authorization",
                "reason": "微信文字发送依赖前台输入；请明确允许前台操作",
            }
        if not text.strip():
            return {"sent": False, "status": "invalid", "reason": "发送内容不能为空"}

        try:
            current = self.accessibility.current_chat_name(activate=False)
            if current != chat_name:
                return {
                    "sent": False,
                    "status": "target_chat_not_current",
                    "reason": "首版发送器不自动切换会话，请先打开目标群",
                    "current_chat": current,
                    "target_chat": chat_name,
                }
            ax_app = self.accessibility.application(activate=True)
            input_field = self._find_input_field(ax_app)
            accessibility = self.accessibility.imports.accessibility
            accessibility.AXUIElementPerformAction(
                input_field, accessibility.kAXRaiseAction
            )
            error = accessibility.AXUIElementSetAttributeValue(
                input_field, accessibility.kAXValueAttribute, text
            )
            if error != 0:
                raise AccessibilityUnavailable(f"无法写入微信输入框，AX 错误 {error}")
            self._press_return()
            return {
                "sent": True,
                "status": "send_called",
                "delivery": "unverified",
                "chat_name": chat_name,
            }
        except AccessibilityUnavailable as exc:
            return {"sent": False, "status": "unavailable", "reason": str(exc)}

    def send_reviewed_file(
        self,
        chat_name: str,
        path: str,
        *,
        approved: bool = False,
        allow_foreground: bool = False,
    ) -> dict[str, Any]:
        """文件发送保留接口，但首版不伪装成已支持。"""
        return {
            "sent": False,
            "status": "unverified",
            "reason": "当前未验证微信文件选择与发送能力，请使用微信原生转发",
            "chat_name": chat_name,
            "path": path,
            "approved": approved,
            "allow_foreground": allow_foreground,
        }

    def _find_input_field(self, ax_app: Any) -> Any:
        accessibility = self.accessibility.imports.accessibility

        def is_input(_element, role, _title, identifier) -> bool:
            return role == accessibility.kAXTextAreaRole and identifier == "chat_input_field"

        result = dfs(ax_app, is_input, self.accessibility.imports)
        if result is None:
            raise AccessibilityUnavailable("AX 树中找不到微信聊天输入框")
        return result

    def _press_return(self) -> None:
        try:
            from Quartz import (
                CGEventCreateKeyboardEvent,
                CGEventPost,
                CGEventSetFlags,
                kCGEventFlagMaskNonCoalesced,
                kCGHIDEventTap,
            )
        except ImportError as exc:
            raise AccessibilityUnavailable("需要 Quartz 才能发送回车") from exc
        keycode_return = 36
        down = CGEventCreateKeyboardEvent(None, keycode_return, True)
        up = CGEventCreateKeyboardEvent(None, keycode_return, False)
        CGEventSetFlags(down, kCGEventFlagMaskNonCoalesced)
        CGEventSetFlags(up, kCGEventFlagMaskNonCoalesced)
        CGEventPost(kCGHIDEventTap, down)
        CGEventPost(kCGHIDEventTap, up)
