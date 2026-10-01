"""对 BiboyQG/WeChat-MCP 的精简、安全边界明确的适配层。"""

from .ax import AccessibilityUnavailable, WeChatAccessibility
from .reader import WeChatReader

__all__ = ["AccessibilityUnavailable", "WeChatAccessibility", "WeChatReader"]
