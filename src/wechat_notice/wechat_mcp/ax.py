from __future__ import annotations

import re
import platform
from dataclasses import dataclass
from typing import Any, Iterable


class AccessibilityUnavailable(RuntimeError):
    """PyObjC、权限或微信 AX 树不可用。"""


@dataclass(frozen=True)
class AXImports:
    appkit: Any
    accessibility: Any


def _load_imports() -> AXImports:
    try:
        import AppKit
        import ApplicationServices
    except ImportError as exc:
        raise AccessibilityUnavailable(
            "需要 macOS PyObjC 依赖；当前环境无法加载 AppKit/ApplicationServices"
        ) from exc
    return AXImports(AppKit, ApplicationServices)


def ax_get(element: Any, attribute: str, imports: AXImports) -> Any:
    error, value = imports.accessibility.AXUIElementCopyAttributeValue(element, attribute, None)
    return value if error == 0 else None


def dfs(element: Any, predicate, imports: AXImports) -> Any | None:
    if element is None:
        return None
    role = ax_get(element, imports.accessibility.kAXRoleAttribute, imports)
    title = ax_get(element, imports.accessibility.kAXTitleAttribute, imports)
    identifier = ax_get(element, imports.accessibility.kAXIdentifierAttribute, imports)
    if predicate(element, role, title, identifier):
        return element
    children = ax_get(element, imports.accessibility.kAXChildrenAttribute, imports) or []
    for child in children:
        result = dfs(child, predicate, imports)
        if result is not None:
            return result
    return None


def _normalize_chat_title(value: str) -> str:
    return re.sub(r"\(\d+\)$", "", value.strip()).strip()


class WeChatAccessibility:
    """小范围复用上游 AX 树访问能力。

    ``application`` 默认不激活微信。读取方法不会发送键盘、鼠标或剪贴板事件；
    需要前台交互的能力必须由调用者显式传入 ``allow_foreground=True``。
    """

    bundle_id = "com.tencent.xinWeChat"

    def __init__(self, *, imports: AXImports | None = None) -> None:
        self.imports = imports or _load_imports()

    def running_application(self) -> Any:
        apps = self.imports.appkit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(self.bundle_id)
        if not apps:
            raise AccessibilityUnavailable("微信没有运行")
        return apps[0]

    def application(self, *, activate: bool = False) -> Any:
        app = self.running_application()
        if activate:
            app.activateWithOptions_(self.imports.appkit.NSApplicationActivateIgnoringOtherApps)
        return self.imports.accessibility.AXUIElementCreateApplication(app.processIdentifier())

    def _require_ax_read_permission(self) -> None:
        trusted = getattr(self.imports.accessibility, "AXIsProcessTrusted", None)
        if callable(trusted) and not trusted():
            raise AccessibilityUnavailable(
                "macOS 辅助功能权限未授予，无法读取微信 AX 树"
            )

    def capability_report(self) -> dict[str, Any]:
        """只检查依赖和进程，不激活微信、不读取聊天内容。"""
        report: dict[str, Any] = {
            "platform": "macOS",
            "macos_version": platform.mac_ver()[0] or None,
            "bundle_id": self.bundle_id,
            "pyobjc": True,
            "wechat_running": False,
            "wechat_version": "unknown_until_verified",
            "accessibility_permission": "unknown_until_verified",
            "background_ax_read": "unverified",
            "message_read": "unverified",
            "history_paging": "unverified",
            "foreground_navigation": "requires_explicit_authorization",
            "screenshot_sender_detection": False,
            "message_sender_identity": "unknown_until_verified",
            "message_timestamp": "unknown_until_verified",
            "message_id": "local_synthetic_only",
            "attachment_download": "unverified",
            "text_send": "requires_explicit_authorization",
            "file_send": "unverified",
        }
        try:
            app = self.running_application()
            report["wechat_running"] = True
            bundle_url_attr = getattr(app, "bundleURL", None)
            bundle_url = bundle_url_attr() if callable(bundle_url_attr) else bundle_url_attr
            if bundle_url is not None:
                bundle = self.imports.appkit.NSBundle.bundleWithURL_(bundle_url)
                version = bundle.objectForInfoDictionaryKey_("CFBundleShortVersionString")
                if version:
                    report["wechat_version"] = str(version)
        except AccessibilityUnavailable as exc:
            report["error"] = str(exc)
        except Exception as exc:
            report["wechat_version_error"] = str(exc)
        trusted = getattr(self.imports.accessibility, "AXIsProcessTrusted", None)
        if callable(trusted):
            report["accessibility_permission"] = "granted" if trusted() else "denied"
            if report["accessibility_permission"] == "denied":
                report["background_ax_read"] = "unavailable"
                report["message_read"] = "unavailable"
            else:
                report["message_read"] = "unverified"
        return report

    def current_chat_name(self, *, activate: bool = False) -> str | None:
        self._require_ax_read_permission()
        ax_app = self.application(activate=activate)
        accessibility = self.imports.accessibility

        def is_chat_title(_element, role, _title, identifier) -> bool:
            return role == accessibility.kAXStaticTextRole and identifier == "big_title_line_h_view"

        element = dfs(ax_app, is_chat_title, self.imports)
        if element is None:
            return None
        value = ax_get(element, accessibility.kAXValueAttribute, self.imports)
        if isinstance(value, str) and value.strip():
            return _normalize_chat_title(value)
        title = ax_get(element, accessibility.kAXTitleAttribute, self.imports)
        return _normalize_chat_title(title) if isinstance(title, str) and title.strip() else None

    def _message_list(self, ax_app: Any) -> Any:
        accessibility = self.imports.accessibility

        def is_message_list(_element, role, title, _identifier) -> bool:
            if role != accessibility.kAXListRole:
                return False
            return str(title or "").strip().lower() in {"messages", "消息", "chat messages"}

        result = dfs(ax_app, is_message_list, self.imports)
        if result is None:
            raise AccessibilityUnavailable("AX 树中找不到微信消息列表")
        return result

    def current_messages(self, *, last_n: int = 50) -> list[dict[str, Any]]:
        """读取当前可见消息的 AX 文本，不截图、不猜发送方向、不翻页。"""
        if last_n <= 0:
            raise ValueError("last_n 必须为正整数")
        self._require_ax_read_permission()
        ax_app = self.application(activate=False)
        msg_list = self._message_list(ax_app)
        children = ax_get(msg_list, self.imports.accessibility.kAXChildrenAttribute, self.imports) or []
        records: list[dict[str, Any]] = []
        for index, child in enumerate(children):
            text = ax_get(child, self.imports.accessibility.kAXValueAttribute, self.imports)
            if text is None:
                text = ax_get(child, self.imports.accessibility.kAXTitleAttribute, self.imports)
            if text is None:
                continue
            value = str(text)
            records.append(
                {
                    "local_id": f"ax-visible-{index:06d}",
                    "sequence": index,
                    "text": value,
                    "message_type": self._message_type(value),
                    "sender": None,
                    "timestamp": None,
                    "quote_id": None,
                    "attachment_ids": [],
                    "metadata": {
                        "source": "macos_ax",
                        "identity": "synthetic_visible_index",
                        "sender_reason": "AX message node did not expose a stable sender",
                        "history_scope": "current_view_only",
                    },
                }
            )
        return records[-last_n:]

    @staticmethod
    def _message_type(text: str) -> str:
        markers = {
            "[图片]": "image",
            "[Image]": "image",
            "[视频]": "video",
            "[Video]": "video",
            "[文件]": "file",
            "[File]": "file",
            "[链接]": "link",
            "[Link]": "link",
        }
        for marker, message_type in markers.items():
            if marker in text:
                return message_type
        return "text"

    def click_element_center(self, element: Any, *, allow_foreground: bool = False) -> None:
        """前台交互的显式占位实现；读取流程不会调用。"""
        if not allow_foreground:
            raise AccessibilityUnavailable("点击操作需要 allow_foreground=True")
        try:
            from Quartz import (
                CGEventCreateMouseEvent,
                CGEventPost,
                CGPoint,
                kCGEventLeftMouseDown,
                kCGEventLeftMouseUp,
                kCGHIDEventTap,
            )
        except ImportError as exc:
            raise AccessibilityUnavailable("需要 Quartz 才能执行前台点击") from exc
        accessibility = self.imports.accessibility
        position_ref = ax_get(element, accessibility.kAXPositionAttribute, self.imports)
        size_ref = ax_get(element, accessibility.kAXSizeAttribute, self.imports)
        if position_ref is None or size_ref is None:
            raise AccessibilityUnavailable("无法获得目标 AX 元素的位置或大小")
        ok_position, position = accessibility.AXValueGetValue(
            position_ref, accessibility.kAXValueCGPointType, None
        )
        ok_size, size = accessibility.AXValueGetValue(size_ref, accessibility.kAXValueCGSizeType, None)
        if not ok_position or not ok_size:
            raise AccessibilityUnavailable("无法解析目标 AX 元素的边界")
        point = CGPoint(position.x + size.width / 2, position.y + size.height / 2)
        CGEventPost(kCGHIDEventTap, CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, point, 0))
        CGEventPost(kCGHIDEventTap, CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, point, 0))
