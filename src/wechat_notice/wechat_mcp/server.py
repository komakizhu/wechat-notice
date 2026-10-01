from __future__ import annotations

import argparse
import os
import platform
from pathlib import Path
from typing import Any

from ..storage import NoticeStore
from ..service import NoticeService
from ..models import DeliveryStatus, NoticeStatus
from .reader import WeChatReader
from .sender import WeChatSender


def _data_root() -> Path:
    return Path(os.environ.get("WECHAT_NOTICE_DATA_ROOT", "data"))


def check_wechat_capabilities() -> dict[str, Any]:
    try:
        return WeChatReader().capabilities()
    except Exception as exc:
        return {
            "platform": "macOS",
            "macos_version": platform.mac_ver()[0] or None,
            "wechat_version": "unknown_until_verified",
            "accessibility_permission": "unavailable",
            "pyobjc": False,
            "background_ax_read": "unavailable",
            "message_read": "unavailable",
            "history_paging": "unavailable",
            "foreground_navigation": "requires_explicit_authorization",
            "attachment_download": "unavailable",
            "text_send": "unavailable",
            "file_send": "unavailable",
            "error": str(exc),
        }


def fetch_messages_by_chat(
    chat_name: str,
    last_n: int = 50,
    *,
    persist: bool = True,
    data_root: str | None = None,
) -> dict[str, Any]:
    """保留上游入口名称，返回消息与完整性说明，并可保存读取批次。"""
    result = WeChatReader().fetch_messages_by_chat(chat_name, last_n=last_n)
    payload = result.to_dict()
    payload["persisted"] = False
    if persist and (result.messages or result.error is None):
        service = NoticeService(NoticeStore(data_root or _data_root()))
        batch_id = service.ingest_batch(
            source_group=chat_name,
            messages=result.messages,
            read_complete=result.complete,
            read_stop_reason=result.stop_reason,
            metadata={"source": "wechat_mcp", "missing_fields": list(result.missing_fields)},
        )
        payload["batch_id"] = batch_id
        payload["persisted"] = True
    return payload


def get_attachment_for_message(
    attachment_id: str,
    *,
    data_root: str | None = None,
) -> dict[str, Any]:
    store = NoticeStore(data_root or _data_root())
    attachment = store.get_attachment(attachment_id)
    if attachment is None:
        return {"found": False, "attachment_id": attachment_id, "reason": "附件登记不存在"}
    if not attachment.stored_path or not Path(attachment.stored_path).is_file():
        return {
            "found": False,
            "registered": True,
            **attachment.to_dict(),
            "reason": "附件原件尚未取得或暂存文件已不存在",
        }
    return {"found": True, **attachment.to_dict()}


def send_reviewed_text(
    chat_name: str,
    text: str,
    *,
    notice_id: str,
    notice_revision: int,
    approved: bool = False,
    allow_foreground: bool = False,
) -> dict[str, Any]:
    store = NoticeStore(_data_root())
    notice = store.get_notice(notice_id)
    if notice is None:
        return {"sent": False, "status": "invalid_notice", "reason": "通知不存在"}
    if notice.status != NoticeStatus.APPROVED:
        return {"sent": False, "status": "blocked", "reason": "通知尚未审核通过"}
    if notice.revision != notice_revision:
        return {"sent": False, "status": "blocked", "reason": "通知版本已变化，请重新审核"}
    if not notice.target_group or not notice.target_group.strip():
        return {"sent": False, "status": "blocked", "reason": "审核记录没有明确目标群"}
    if notice.target_group != chat_name:
        return {"sent": False, "status": "blocked", "reason": "目标群与审核记录不一致"}
    if not notice.polished_text.strip():
        return {"sent": False, "status": "blocked", "reason": "审核通过版本为空"}
    if notice.polished_text != text:
        return {"sent": False, "status": "blocked", "reason": "发送内容与审核通过版本不一致"}
    if notice.delivery_status != DeliveryStatus.NOT_ATTEMPTED:
        return {
            "sent": False,
            "status": "blocked",
            "reason": "该通知已有发送或不确定记录，请先由用户核对，不能自动重发",
            "delivery_status": notice.delivery_status.value,
        }
    if not approved:
        return {"sent": False, "status": "blocked", "reason": "需要用户明确审核通过"}

    result = WeChatSender().send_reviewed_text(
        chat_name,
        text,
        approved=approved,
        allow_foreground=allow_foreground,
    )
    delivery_status = DeliveryStatus.RESULT_UNCERTAIN if result.get("sent") else DeliveryStatus.NOT_ATTEMPTED
    delivery_id = store.record_delivery(
        notice_id=notice_id,
        notice_revision=notice_revision,
        content_type="text",
        target_group=chat_name,
        status=delivery_status,
        detail=str(result.get("reason") or result.get("status") or "send_called"),
    )
    store.set_delivery_status(notice_id, delivery_status)
    result["notice_id"] = notice_id
    result["notice_revision"] = notice_revision
    result["delivery_id"] = delivery_id
    return result


def send_reviewed_file(
    chat_name: str,
    path: str,
    *,
    notice_id: str,
    notice_revision: int,
    attachment_id: str,
    approved: bool = False,
    allow_foreground: bool = False,
) -> dict[str, Any]:
    store = NoticeStore(_data_root())
    notice = store.get_notice(notice_id)
    if notice is None:
        return {"sent": False, "status": "invalid_notice", "reason": "通知不存在"}
    if notice.status != NoticeStatus.APPROVED:
        return {"sent": False, "status": "blocked", "reason": "通知尚未审核通过"}
    if notice.revision != notice_revision:
        return {"sent": False, "status": "blocked", "reason": "通知版本已变化，请重新审核"}
    if not notice.target_group or notice.target_group != chat_name:
        return {"sent": False, "status": "blocked", "reason": "目标群与审核记录不一致"}
    if attachment_id not in notice.attachment_ids:
        return {"sent": False, "status": "blocked", "reason": "附件不属于审核通过的通知"}
    if any(
        row["content_type"] == "file"
        and row["attachment_id"] == attachment_id
        and row["notice_revision"] == notice_revision
        for row in store.list_deliveries(notice_id)
    ):
        return {
            "sent": False,
            "status": "blocked",
            "reason": "该附件已有投递记录，请先由用户核对，不能自动重试",
        }
    attachment = store.get_attachment(attachment_id)
    if attachment is None or not attachment.stored_path:
        return {"sent": False, "status": "blocked", "reason": "审核通过的原件不存在"}
    if Path(attachment.stored_path).resolve() != Path(path).expanduser().resolve():
        return {"sent": False, "status": "blocked", "reason": "发送路径与审核通过的原件不一致"}
    if not approved:
        return {"sent": False, "status": "blocked", "reason": "需要用户明确审核通过"}
    result = WeChatSender().send_reviewed_file(
        chat_name,
        path,
        approved=approved,
        allow_foreground=allow_foreground,
    )
    delivery_id = store.record_delivery(
        notice_id=notice_id,
        notice_revision=notice_revision,
        content_type="file",
        attachment_id=attachment_id,
        target_group=chat_name,
        status=DeliveryStatus.NOT_ATTEMPTED,
        detail=str(result.get("reason") or result.get("status") or "file_send_unverified"),
    )
    result.update(
        {
            "notice_id": notice_id,
            "notice_revision": notice_revision,
            "attachment_id": attachment_id,
            "delivery_id": delivery_id,
        }
    )
    return result


def _build_mcp() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError("请先安装可选依赖 mcp，再启动微信 MCP") from exc

    mcp = FastMCP("WeChat Notice MCP")
    mcp.tool()(check_wechat_capabilities)
    mcp.tool()(fetch_messages_by_chat)
    mcp.tool()(get_attachment_for_message)
    mcp.tool()(send_reviewed_text)
    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="微信通知处理 MCP")
    parser.add_argument("--transport", choices=["stdio", "streamable-http", "sse"], default="stdio")
    args = parser.parse_args(argv)
    if args.transport != "stdio" and os.environ.get("WECHAT_NOTICE_ALLOW_NETWORK_MCP") != "1":
        raise RuntimeError(
            "HTTP/SSE MCP 默认关闭；如确需在受信本机启用，请显式设置 "
            "WECHAT_NOTICE_ALLOW_NETWORK_MCP=1"
        )
    mcp = _build_mcp()
    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
