from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import (
    AppSettings,
    DeliveryStatus,
    MessageRecord,
    MessageRelation,
    ReminderStatus,
)
from .service import AttachmentInput, NoticeService
from .storage import NoticeStore
from .wechat_mcp.server import check_wechat_capabilities
from .material_reader import MaterialReader
from .notice_package import NoticeFacts, write_notice_package


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _messages(values: list[dict[str, Any]], source_group: str) -> list[MessageRecord]:
    result = []
    for index, value in enumerate(values):
        result.append(
            MessageRecord(
                local_id=str(value.get("local_id", f"manual-{index:06d}")),
                source_group=str(value.get("source_group", source_group)),
                sequence=int(value.get("sequence", index)),
                text=str(value.get("text", "")),
                message_type=str(value.get("message_type", "unknown")),
                sender=value.get("sender"),
                timestamp=value.get("timestamp"),
                quote_id=value.get("quote_id"),
                attachment_ids=tuple(value.get("attachment_ids", [])),
                metadata=dict(value.get("metadata", {})),
            )
        )
    return result


def _relations(values: list[dict[str, Any]]) -> list[MessageRelation]:
    return [
        MessageRelation(
            source_message_id=str(value["source_message_id"]),
            related_message_id=str(value["related_message_id"]),
            relation_type=str(value["relation_type"]),
            confirmed=bool(value.get("confirmed", False)),
            note=str(value.get("note", "")),
        )
        for value in values
    ]


def _service(data_root: str) -> NoticeService:
    return NoticeService(NoticeStore(data_root))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="微信群通知处理工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("capabilities", help="只读检查微信 MCP 能力")

    ingest = subparsers.add_parser("ingest", help="导入一批消息及附件描述 JSON")
    ingest.add_argument("--input", required=True, help="JSON 文件路径")
    ingest.add_argument("--data-root", default="data")

    context = subparsers.add_parser("context", help="输出交给 Codex 的批次上下文")
    context.add_argument("--batch-id", required=True)
    context.add_argument("--data-root", default="data")

    batch_materials = subparsers.add_parser("read-batch-materials", help="读取并保存批次中的网页/公众号材料")
    batch_materials.add_argument("--batch-id", required=True)
    batch_materials.add_argument("--data-root", default="data")

    create = subparsers.add_parser("create-notice", help="从 JSON 创建一条通知草稿")
    create.add_argument("--input", required=True)
    create.add_argument("--data-root", default="data")

    update = subparsers.add_parser("update-notice", help="从 JSON 更新通知参数并回到待审核")
    update.add_argument("--notice-id", required=True)
    update.add_argument("--input", required=True, help="只包含要更新的 NoticeService 参数")
    update.add_argument("--data-root", default="data")

    cancel = subparsers.add_parser("cancel-notice", help="取消通知及未发送提醒")
    cancel.add_argument("--notice-id", required=True)
    cancel.add_argument("--data-root", default="data")

    delivery = subparsers.add_parser("delivery-status", help="记录通知整体投递状态")
    delivery.add_argument("--notice-id", required=True)
    delivery.add_argument("--status", required=True, choices=[status.value for status in DeliveryStatus])
    delivery.add_argument("--data-root", default="data")

    reminder_status = subparsers.add_parser("reminder-status", help="记录单条提醒审核或发送状态")
    reminder_status.add_argument("--reminder-id", required=True, type=int)
    reminder_status.add_argument("--status", required=True, choices=[status.value for status in ReminderStatus])
    reminder_status.add_argument("--at")
    reminder_status.add_argument("--data-root", default="data")

    deliveries = subparsers.add_parser("deliveries", help="查看通知的逐项投递记录")
    deliveries.add_argument("--notice-id", required=True)
    deliveries.add_argument("--data-root", default="data")

    delivery_item = subparsers.add_parser("delivery-item-status", help="记录单个文字或附件投递状态")
    delivery_item.add_argument("--delivery-id", required=True, type=int)
    delivery_item.add_argument("--status", required=True, choices=[status.value for status in DeliveryStatus])
    delivery_item.add_argument("--at")
    delivery_item.add_argument("--data-root", default="data")

    review = subparsers.add_parser("review", help="保存审核后的两版文案")
    review.add_argument("--notice-id", required=True)
    review.add_argument("--polished-file", required=True)
    review.add_argument("--concise-file", required=True)
    review.add_argument("--notes-file")
    review.add_argument("--approved", action="store_true")
    review.add_argument("--data-root", default="data")

    packet = subparsers.add_parser("packet", help="输出一条通知的审核包")
    packet.add_argument("--notice-id", required=True)
    packet.add_argument("--data-root", default="data")

    settings = subparsers.add_parser("settings", help="查看或更新全局参数")
    settings.add_argument("--collection-advance-days", type=int)
    settings.add_argument("--show-original-deadline", action="store_true", default=None)
    settings.add_argument("--hide-original-deadline", action="store_false", dest="show_original_deadline", default=None)
    settings.add_argument("--reminder-offsets", help="逗号分隔的提前天数，例如 2,1")
    settings.add_argument("--reminder-time")
    settings.add_argument("--working-days", action="store_true", default=None)
    settings.add_argument("--natural-days", action="store_false", dest="working_days", default=None)
    settings.add_argument("--data-root", default="data")

    reminders = subparsers.add_parser("reminders", help="幂等计算并生成到期的待审核提醒")
    reminders.add_argument("--at", help="ISO 时间，仅用于离线验证")
    reminders.add_argument("--data-root", default="data")

    materials = subparsers.add_parser("read-material", help="读取网页或公众号材料并尝试 OCR 图片")
    materials.add_argument("--url", action="append", required=True, help="可重复传入多个 HTTP(S) URL")

    monitor = subparsers.add_parser("monitor-once", help="模拟或执行一次增量消息窗口检查")
    monitor.add_argument("--input", required=True, help="包含 source_group 和 messages 的 JSON")
    monitor.add_argument("--data-root", default="data")

    package = subparsers.add_parser("generate-package", help="从结构化事实生成通知包和图稿")
    package.add_argument("--input", required=True, help="单条事实或包含 notices/settings 的 JSON")
    package.add_argument("--output-dir", default="data/artifacts")
    package.add_argument("--mmdc", help="可选 Mermaid CLI 路径；未提供时使用本地备用渲染")

    simulate = subparsers.add_parser("simulate", help="用三条合成通知生成验收产物")
    simulate.add_argument("--input", help="模拟样本 JSON，默认使用 examples/simulated_notices.json")
    simulate.add_argument("--output-dir", default="data/simulated")
    simulate.add_argument("--mmdc", help="可选 Mermaid CLI 路径；未提供时使用本地备用渲染")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "capabilities":
        print(json.dumps(check_wechat_capabilities(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "ingest":
        payload = _load_json(args.input)
        source_group = str(payload["source_group"])
        attachments = [
            AttachmentInput(
                attachment_id=str(item["attachment_id"]),
                source_group=str(item.get("source_group", source_group)),
                source_message_id=item.get("source_message_id"),
                original_name=str(item.get("original_name", Path(item.get("source_path", "attachment")).name)),
                source_path=item.get("source_path"),
                mime_type=item.get("mime_type"),
            )
            for item in payload.get("attachments", [])
        ]
        batch_id = _service(args.data_root).ingest_batch(
            source_group=source_group,
            messages=_messages(payload.get("messages", []), source_group),
            attachments=attachments,
            relations=_relations(payload.get("relations", [])),
            batch_id=payload.get("batch_id"),
            read_complete=bool(payload.get("read_complete", False)),
            read_stop_reason=payload.get("read_stop_reason"),
            metadata=payload.get("metadata"),
        )
        print(json.dumps({"batch_id": batch_id}, ensure_ascii=False))
        return 0

    if args.command == "context":
        print(json.dumps(_service(args.data_root).context_for_codex(args.batch_id), ensure_ascii=False, indent=2))
        return 0

    if args.command == "read-batch-materials":
        results = _service(args.data_root).read_batch_materials(args.batch_id)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    if args.command == "create-notice":
        payload = _load_json(args.input)
        notice = _service(args.data_root).create_notice(**payload)
        print(json.dumps(notice.__dict__, ensure_ascii=False, default=str, indent=2))
        return 0

    if args.command == "update-notice":
        payload = _load_json(args.input)
        notice = _service(args.data_root).update_notice_parameters(args.notice_id, **payload)
        print(json.dumps(notice.__dict__, ensure_ascii=False, default=str, indent=2))
        return 0

    if args.command == "cancel-notice":
        notice = _service(args.data_root).cancel_notice(args.notice_id)
        print(json.dumps(notice.__dict__, ensure_ascii=False, default=str, indent=2))
        return 0

    if args.command == "delivery-status":
        notice = _service(args.data_root).set_delivery_status(args.notice_id, args.status)
        print(json.dumps(notice.__dict__, ensure_ascii=False, default=str, indent=2))
        return 0

    if args.command == "reminder-status":
        store = NoticeStore(args.data_root)
        store.set_reminder_status(
            args.reminder_id,
            ReminderStatus(args.status),
            at=args.at,
        )
        print(json.dumps({"reminder_id": args.reminder_id, "status": args.status}, ensure_ascii=False))
        return 0

    if args.command == "deliveries":
        print(json.dumps(_service(args.data_root).store.list_deliveries(args.notice_id), ensure_ascii=False, indent=2))
        return 0

    if args.command == "delivery-item-status":
        store = NoticeStore(args.data_root)
        store.update_delivery_status(
            args.delivery_id,
            DeliveryStatus(args.status),
            at=args.at,
        )
        print(json.dumps({"delivery_id": args.delivery_id, "status": args.status}, ensure_ascii=False))
        return 0

    if args.command == "review":
        service = _service(args.data_root)
        notes = Path(args.notes_file).read_text(encoding="utf-8") if args.notes_file else ""
        notice = service.save_review(
            args.notice_id,
            polished_text=Path(args.polished_file).read_text(encoding="utf-8"),
            concise_text=Path(args.concise_file).read_text(encoding="utf-8"),
            review_notes=notes,
            approved=args.approved,
        )
        print(service.render_review_packet(notice.notice_id))
        return 0

    if args.command == "packet":
        print(_service(args.data_root).render_review_packet(args.notice_id))
        return 0

    if args.command == "settings":
        service = _service(args.data_root)
        current = service.settings
        changed = any(
            value is not None
            for value in (
                args.collection_advance_days,
                args.show_original_deadline,
                args.reminder_offsets,
                args.reminder_time,
                args.working_days,
            )
        )
        if changed:
            offsets = current.reminder_offsets
            if args.reminder_offsets is not None:
                try:
                    offsets = [int(item.strip()) for item in args.reminder_offsets.split(",") if item.strip()]
                except ValueError as exc:
                    raise SystemExit("--reminder-offsets 必须是逗号分隔的整数") from exc
            settings = AppSettings(
                collection_advance_days=(
                    current.collection_advance_days
                    if args.collection_advance_days is None
                    else args.collection_advance_days
                ),
                show_original_deadline=(
                    current.show_original_deadline
                    if args.show_original_deadline is None
                    else args.show_original_deadline
                ),
                reminder_offsets=offsets,
                timezone=current.timezone,
                reminder_time=current.reminder_time if args.reminder_time is None else args.reminder_time,
                use_working_days=current.use_working_days if args.working_days is None else args.working_days,
                allow_item_overrides=current.allow_item_overrides,
            )
            service.update_settings(settings)
            current = settings
        print(json.dumps(current.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "reminders":
        service = _service(args.data_root)
        at = datetime.fromisoformat(args.at) if args.at else None
        print(json.dumps(service.prepare_due_reminders(at), ensure_ascii=False, indent=2, default=str))
        return 0

    if args.command == "read-material":
        results = MaterialReader().read_urls(args.url)
        print(json.dumps([item.to_dict() for item in results], ensure_ascii=False, indent=2))
        return 0

    if args.command == "monitor-once":
        payload = _load_json(args.input)
        service = _service(args.data_root)
        result = service.monitor_once(
            str(payload["source_group"]),
            _messages(payload.get("messages", []), str(payload["source_group"])),
            read_complete=bool(payload.get("read_complete", True)),
            stop_reason=payload.get("stop_reason"),
            cursor=payload.get("cursor"),
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "generate-package":
        payload = _load_json(args.input)
        settings = AppSettings.from_dict(payload.get("settings", {})) if isinstance(payload, dict) else AppSettings()
        values = payload.get("notices", [payload]) if isinstance(payload, dict) else payload
        if not isinstance(values, list):
            raise SystemExit("输入必须是单条事实对象或 notices 数组")
        packages = [
            write_notice_package(NoticeFacts.from_dict(item), args.output_dir, settings=settings, mmdc=args.mmdc)
            for item in values
        ]
        print(json.dumps([item.to_dict() for item in packages], ensure_ascii=False, indent=2))
        return 0

    if args.command == "simulate":
        default_path = Path(__file__).resolve().parents[2] / "examples" / "simulated_notices.json"
        payload = _load_json(args.input or default_path)
        settings = AppSettings.from_dict(payload.get("settings", {}))
        packages = [
            write_notice_package(NoticeFacts.from_dict(item), args.output_dir, settings=settings, mmdc=args.mmdc)
            for item in payload["notices"]
        ]
        print(
            json.dumps(
                {
                    "mode": "simulated",
                    "wechat_connected": False,
                    "notice_count": len(packages),
                    "packages": [item.to_dict() for item in packages],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    raise AssertionError(f"unhandled command: {args.command}")
