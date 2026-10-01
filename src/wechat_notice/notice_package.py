from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

from .date_rules import collection_suggestion, format_deadline, serialize_deadline
from .models import AppSettings
from .rendering import (
    FlowchartBox,
    FlowchartLayout,
    render_mermaid,
    render_summary_png,
)


def _tuple_text(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    return tuple(str(item) for item in value if str(item).strip())


def _text_or_unknown(value: Any) -> str:
    if value is None:
        return "未说明"
    text = str(value).strip()
    return text or "未说明"


@dataclass(frozen=True)
class DecisionPoint:
    question: str
    yes: str
    no: str

    @classmethod
    def from_value(cls, value: Any) -> "DecisionPoint":
        if isinstance(value, dict):
            return cls(
                question=_text_or_unknown(value.get("question")),
                yes=_text_or_unknown(value.get("yes", value.get("if_yes", "未说明"))),
                no=_text_or_unknown(value.get("no", value.get("if_no", "未说明"))),
            )
        return cls(question=_text_or_unknown(value), yes="按通知要求", no="待确认")

    def to_dict(self) -> dict[str, str]:
        return {"question": self.question, "yes": self.yes, "no": self.no}


@dataclass(frozen=True)
class FlowchartChapter:
    chapter_id: str
    title: str
    mermaid: str
    nodes: tuple[str, ...]
    layout: FlowchartLayout

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter_id": self.chapter_id,
            "title": self.title,
            "mermaid": self.mermaid,
            "nodes": list(self.nodes),
        }


@dataclass(frozen=True)
class NoticeFacts:
    """Facts extracted by the Skill before any outward-facing wording."""

    notice_id: str
    title: str
    audience: str = "未说明"
    task: str = "未说明"
    item_type: str = "unknown"
    materials: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    submission_method: str = "未说明"
    collection_required: bool = False
    original_deadline: str | None = None
    class_deadline: str | None = None
    reminders_enabled: bool = True
    steps_relation: str = "sequential"
    target_group: str | None = None
    source_message_ids: tuple[str, ...] = ()
    attachment_names: tuple[str, ...] = ()
    attachment_paths: tuple[str, ...] = ()
    source_urls: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    decision_points: tuple[DecisionPoint, ...] = ()
    advance_days: int | None = None
    show_original_deadline: bool | None = None
    reminder_offsets: tuple[int, ...] | None = None
    reminder_template: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "NoticeFacts":
        decisions = tuple(
            DecisionPoint.from_value(item) for item in value.get("decision_points", ())
        )
        offsets = value.get("reminder_offsets")
        return cls(
            notice_id=str(value.get("notice_id", "notice-simulated")),
            title=str(value.get("title", "未命名通知")),
            audience=_text_or_unknown(value.get("audience")),
            task=_text_or_unknown(value.get("task")),
            item_type=(
                "unknown"
                if value.get("item_type") is None
                else _text_or_unknown(value.get("item_type"))
            ),
            materials=_tuple_text(value.get("materials")),
            steps=_tuple_text(value.get("steps")),
            submission_method=_text_or_unknown(value.get("submission_method")),
            collection_required=bool(value.get("collection_required", False)),
            original_deadline=(
                None
                if value.get("original_deadline") in (None, "")
                else str(value.get("original_deadline"))
            ),
            class_deadline=value.get("class_deadline"),
            reminders_enabled=value.get("reminders_enabled", True),
            steps_relation=value.get("steps_relation", "sequential"),
            target_group=(
                None if value.get("target_group") in (None, "") else str(value["target_group"])
            ),
            source_message_ids=_tuple_text(value.get("source_message_ids")),
            attachment_names=_tuple_text(value.get("attachment_names")),
            attachment_paths=_tuple_text(value.get("attachment_paths")),
            source_urls=_tuple_text(value.get("source_urls")),
            notes=_tuple_text(value.get("notes")),
            uncertainties=_tuple_text(value.get("uncertainties")),
            decision_points=decisions,
            advance_days=(None if value.get("advance_days") is None else int(value["advance_days"])),
            show_original_deadline=(
                None
                if value.get("show_original_deadline") is None
                else bool(value["show_original_deadline"])
            ),
            reminder_offsets=(
                None
                if offsets is None
                else tuple(sorted({int(item) for item in offsets}))
            ),
            reminder_template=(
                None if value.get("reminder_template") in (None, "") else str(value["reminder_template"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "notice_id": self.notice_id,
            "title": self.title,
            "audience": self.audience,
            "task": self.task,
            "item_type": self.item_type,
            "materials": list(self.materials),
            "steps": list(self.steps),
            "submission_method": self.submission_method,
            "collection_required": self.collection_required,
            "original_deadline": self.original_deadline,
            "class_deadline": self.class_deadline,
            "reminders_enabled": self.reminders_enabled,
            "steps_relation": self.steps_relation,
            "target_group": self.target_group,
            "source_message_ids": list(self.source_message_ids),
            "attachment_names": list(self.attachment_names),
            "attachment_paths": list(self.attachment_paths),
            "source_urls": list(self.source_urls),
            "notes": list(self.notes),
            "uncertainties": list(self.uncertainties),
            "decision_points": [item.to_dict() for item in self.decision_points],
            "advance_days": self.advance_days,
            "show_original_deadline": self.show_original_deadline,
            "reminder_offsets": None if self.reminder_offsets is None else list(self.reminder_offsets),
            "reminder_template": self.reminder_template,
        }


@dataclass(frozen=True)
class NoticePackage:
    facts: NoticeFacts
    class_deadline: str | None
    effective_advance_days: int
    show_original_deadline: bool
    reminder_offsets: tuple[int, ...]
    polished_text: str
    concise_text: str
    mermaid: str
    review_notes: str
    reminder_preview: str
    flowchart_nodes: tuple[str, ...] = ()
    flowchart_chapters: tuple[FlowchartChapter, ...] = ()
    artifact_paths: dict[str, str] = field(default_factory=dict)
    chapter_artifact_paths: dict[str, dict[str, str]] = field(default_factory=dict)
    rendering: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "notice_id": self.facts.notice_id,
            "title": self.facts.title,
            "facts": self.facts.to_dict(),
            "class_deadline": self.class_deadline,
            "effective_advance_days": self.effective_advance_days,
            "show_original_deadline": self.show_original_deadline,
            "reminder_offsets": list(self.reminder_offsets),
            "polished_text": self.polished_text,
            "concise_text": self.concise_text,
            "mermaid": self.mermaid,
            "review_notes": self.review_notes,
            "reminder_preview": self.reminder_preview,
            "flowchart_nodes": list(self.flowchart_nodes),
            "flowchart_chapters": [item.to_dict() for item in self.flowchart_chapters],
            "artifact_paths": dict(self.artifact_paths),
            "chapter_artifact_paths": {
                chapter_id: dict(paths)
                for chapter_id, paths in self.chapter_artifact_paths.items()
            },
            "rendering": dict(self.rendering),
        }


def _display_items(items: Iterable[str], *, empty: str = "未说明") -> str:
    values = [str(item).strip() for item in items if str(item).strip()]
    return "；".join(values) if values else empty


def _safe_deadline(value: str | None) -> str:
    try:
        return format_deadline(value)
    except ValueError:
        return f"原文日期无法解析：{value or '未提供'}"


def _mermaid_label(value: str) -> str:
    clean = " ".join(str(value).replace("\n", " ").split())
    clean = clean.replace("[", "（").replace("]", "）")
    clean = clean.replace("{", "（").replace("}", "）")
    return html.escape(clean, quote=True)


def _mermaid_source(layout: FlowchartLayout) -> str:
    lines = ["flowchart LR"]
    for row in layout.rows:
        for box in row:
            if box.kind == "decision":
                lines.append(f'  {box.id}{{"{_mermaid_label(box.label)}"}}')
            else:
                lines.append(f'  {box.id}["{_mermaid_label(box.label)}"]')
    for source, target, label in layout.edges:
        if label:
            lines.append(f"  {source} -->|{_mermaid_label(label)}| {target}")
        else:
            lines.append(f"  {source} --> {target}")
    return "\n".join(lines) + "\n"


def _layout_nodes(layout: FlowchartLayout) -> tuple[str, ...]:
    return tuple(box.label for row in layout.rows for box in row)


def _flowchart_box(node_id: str, label: str, kind: str = "normal") -> FlowchartBox:
    return FlowchartBox(node_id, label, kind)


def _combined_length(values: Iterable[str]) -> int:
    items = tuple(str(value) for value in values)
    return sum(len(value) for value in items) + max(0, len(items) - 1)


def _requires_flowchart_chapters(
    facts: NoticeFacts,
    *,
    reminder_offsets: tuple[int, ...],
) -> tuple[bool, bool, bool]:
    """Return whether materials/steps, decisions, or reminders need their own page."""
    material_overflow = (
        len(facts.materials) > 2
        or _combined_length(facts.materials) > 28
    )
    step_overflow = (
        len(facts.steps) > 3
        or _combined_length(facts.steps) > 34
    )
    detail_overflow = material_overflow or step_overflow
    decision_overflow = bool(facts.decision_points)
    reminder_overflow = len(reminder_offsets) > 3
    return detail_overflow, decision_overflow, reminder_overflow


def _deadline_label(
    facts: NoticeFacts,
    *,
    class_deadline: str | None,
    show_original_deadline: bool,
    reminder_offsets: tuple[int, ...],
    detail_overflow: bool,
    decision_overflow: bool,
    reminder_overflow: bool,
) -> str:
    label = f"截止：{_safe_deadline(class_deadline)}" if class_deadline else ""
    if show_original_deadline and facts.original_deadline and facts.original_deadline != class_deadline:
        label += f"；上级原截止：{_safe_deadline(facts.original_deadline)}"
    return label


def _build_overview_chapter(
    facts: NoticeFacts,
    *,
    class_deadline: str | None,
    show_original_deadline: bool,
    reminder_offsets: tuple[int, ...],
    detail_overflow: bool,
    decision_overflow: bool,
    reminder_overflow: bool,
) -> FlowchartChapter:
    boxes = []
    info = "；".join(label + value for label, value in (("对象：", facts.audience), ("事项：", facts.task)) if _known(value))
    if info:
        boxes.append(_flowchart_box("info", info))
    if facts.materials and not detail_overflow:
        boxes.append(_flowchart_box("materials", "材料：" + _display_items(facts.materials)))
    if class_deadline:
        boxes.append(_flowchart_box("deadline", _deadline_label(facts, class_deadline=class_deadline, show_original_deadline=show_original_deadline, reminder_offsets=(), detail_overflow=False, decision_overflow=False, reminder_overflow=False), "primary"))
    if _known(facts.submission_method):
        boxes.append(_flowchart_box("submit", "提交：" + facts.submission_method))
    rows = [(_flowchart_box("start", facts.title, "primary"),)]
    if boxes:
        rows.append(tuple(boxes))
    edges = [("start", box.id, "") for box in boxes]
    if facts.steps and not detail_overflow:
        step_boxes = tuple(_flowchart_box(f"step{i}", f"{i}、{step}") for i, step in enumerate(facts.steps, 1))
        rows.append(step_boxes)
        if facts.steps_relation == "sequential":
            edges.append(("start", step_boxes[0].id, ""))
            edges.extend((a.id, b.id, "") for a, b in zip(step_boxes, step_boxes[1:]))
        elif facts.steps_relation == "parallel":
            edges.extend(("start", box.id, "") for box in step_boxes)
        else:
            raise ValueError("steps_relation must be sequential or parallel after semantic review")
    layout = FlowchartLayout(rows=tuple(rows), edges=tuple(edges))
    return FlowchartChapter(chapter_id="overview", title="一页总览", mermaid=_mermaid_source(layout), nodes=_layout_nodes(layout), layout=layout)


def _chunks(values: tuple[str, ...], size: int) -> list[tuple[str, ...]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _build_detail_chapters(
    facts: NoticeFacts,
    *,
    detail_overflow: bool,
) -> tuple[FlowchartChapter, ...]:
    if not detail_overflow:
        return ()
    materials = facts.materials
    material_chunks = _chunks(materials, 4)
    step_chunks = _chunks(facts.steps, 4) or [()]
    page_count = max(len(material_chunks), len(step_chunks))
    chapters: list[FlowchartChapter] = []
    for page_index in range(page_count):
        material_part = material_chunks[page_index] if page_index < len(material_chunks) else ()
        step_part = step_chunks[page_index] if page_index < len(step_chunks) else ()
        rows: list[tuple[FlowchartBox, ...]] = []
        edges: list[tuple[str, str, str]] = []
        if material_part:
            material_boxes = tuple(
                _flowchart_box(
                    f"material{index}",
                    f"材料：{item}",
                )
                for index, item in enumerate(material_part, 1)
            )
            rows.append(material_boxes)

        if step_part:
            step_offset = page_index * 4
            step_boxes = tuple(
                _flowchart_box(
                    f"step{step_offset + index}",
                    f"{step_offset + index}、{step}",
                )
                for index, step in enumerate(step_part, 1)
            )
            rows.append(step_boxes)
            if facts.steps_relation == "sequential":
                edges.extend((step_boxes[index].id, step_boxes[index + 1].id, "") for index in range(len(step_boxes) - 1))
            elif facts.steps_relation != "parallel":
                raise ValueError("steps_relation must be sequential or parallel after semantic review")
            if page_index == page_count - 1 and _known(facts.submission_method):
                submit = _flowchart_box("submit", "提交：" + facts.submission_method, "primary")
                rows.append((submit,))
                if facts.steps_relation == "sequential":
                    edges.append((step_boxes[-1].id, submit.id, ""))
                else:
                    edges.extend((box.id, submit.id, "") for box in step_boxes)

        layout = FlowchartLayout(rows=tuple(rows), edges=tuple(edges))
        suffix = f"（{page_index + 1}/{page_count}）" if page_count > 1 else ""
        chapter_id = "details" if page_count == 1 else f"details-{page_index + 1}"
        chapters.append(
            FlowchartChapter(
                chapter_id=chapter_id,
                title=f"办理细节{suffix}",
                mermaid=_mermaid_source(layout),
                nodes=_layout_nodes(layout),
                layout=layout,
            )
        )
    return tuple(chapters)


def _build_decision_chapters(facts: NoticeFacts, *, decision_overflow: bool) -> tuple[FlowchartChapter, ...]:
    if not decision_overflow:
        return ()
    chapters: list[FlowchartChapter] = []
    for index, point in enumerate(facts.decision_points, 1):
        start = _flowchart_box("start", "办理前核对", "primary")
        decision = _flowchart_box("decision", point.question, "decision")
        yes = _flowchart_box("yes", f"是：{point.yes}", "branch")
        no = _flowchart_box("no", f"否：{point.no}", "warning")
        layout = FlowchartLayout(
            rows=((start,), (decision,), ((yes, no))),
            edges=(
                ("start", "decision", ""),
                ("decision", "yes", "是"),
                ("decision", "no", "否"),
            ),
        )
        chapters.append(
            FlowchartChapter(
                chapter_id=f"decision-{index}",
                title=f"判断分支 {index}",
                mermaid=_mermaid_source(layout),
                nodes=_layout_nodes(layout),
                layout=layout,
            )
        )
    return tuple(chapters)


def build_flowchart_chapters(
    facts: NoticeFacts,
    *,
    class_deadline: str | None,
    show_original_deadline: bool,
    reminder_offsets: tuple[int, ...] = (),
) -> tuple[FlowchartChapter, ...]:
    detail_overflow, decision_overflow, reminder_overflow = _requires_flowchart_chapters(
        facts,
        reminder_offsets=reminder_offsets,
    )
    chapters = [
        _build_overview_chapter(
            facts,
            class_deadline=class_deadline,
            show_original_deadline=show_original_deadline,
            reminder_offsets=reminder_offsets,
            detail_overflow=detail_overflow,
            decision_overflow=decision_overflow,
            reminder_overflow=reminder_overflow,
        )
    ]
    chapters.extend(_build_detail_chapters(facts, detail_overflow=detail_overflow))
    chapters.extend(_build_decision_chapters(facts, decision_overflow=decision_overflow))
    return tuple(chapters)


def build_mermaid(
    facts: NoticeFacts,
    *,
    class_deadline: str | None,
    show_original_deadline: bool,
    reminder_offsets: tuple[int, ...] = (),
) -> tuple[str, tuple[str, ...]]:
    """Build the one-screen overview graph; long facts are linked to later chapters."""
    chapter = build_flowchart_chapters(
        facts,
        class_deadline=class_deadline,
        show_original_deadline=show_original_deadline,
        reminder_offsets=reminder_offsets,
    )[0]
    return chapter.mermaid, chapter.nodes


def _known(value: str | None) -> bool:
    return bool(value and value.strip() not in {"未说明", "未提供", "未知"})


def _build_polished_text(facts: NoticeFacts, *, class_deadline: str | None, show_original_deadline: bool) -> str:
    # Technical draft only: the lite Skill creates both semantically reviewed candidates.
    lines = [f"【{facts.title}】"]
    for label, value in (("适用对象", facts.audience), ("事项", facts.task)):
        if _known(value):
            lines.append(f"{label}：{value}")
    if facts.materials:
        lines.append("所需材料：" + _display_items(facts.materials))
    lines.extend(f"{index}、{step}" for index, step in enumerate(facts.steps, 1))
    if class_deadline:
        lines.append("截止时间：" + _safe_deadline(class_deadline))
    if _known(facts.submission_method):
        lines.append("提交方式：" + facts.submission_method)
    if show_original_deadline and facts.original_deadline and facts.original_deadline != class_deadline:
        lines.append("上级原截止时间：" + _safe_deadline(facts.original_deadline))
    lines.extend("注意：" + note for note in facts.notes)
    return "\n".join(lines)


def _build_concise_text(facts: NoticeFacts, *, class_deadline: str | None, show_original_deadline: bool) -> str:
    lines = [f"【省流】{facts.title}"]
    for label, value in (("谁", facts.audience), ("事项", facts.task)):
        if _known(value):
            lines.append(f"{label}：{value}")
    if class_deadline:
        lines.append("时间：" + _safe_deadline(class_deadline))
    if _known(facts.submission_method):
        lines.append("渠道：" + facts.submission_method)
    if facts.materials:
        lines.append("材料：" + _display_items(facts.materials))
    if show_original_deadline and facts.original_deadline and facts.original_deadline != class_deadline:
        lines.append("上级原截止：" + _safe_deadline(facts.original_deadline))
    if facts.notes:
        lines.append("注意：" + _display_items(facts.notes))
    return "\n".join(lines)


def _build_review_notes(
    facts: NoticeFacts,
    *,
    class_deadline: str | None,
    effective_advance_days: int,
    show_original_deadline: bool,
    reminder_offsets: tuple[int, ...],
) -> str:
    lines = [
        f"- 分类：{facts.item_type}；班级统一收交={'是' if facts.collection_required else '否'}。",
        f"- 收交建议参数：提前 {effective_advance_days} 个自然日的北京时间 12:00；未确认前不应用。",
        f"- 班级对外截止：{_safe_deadline(class_deadline)}。",
        f"- 上级原截止（内部核对）：{_safe_deadline(facts.original_deadline)}。",
        f"- 额外上级截止对外展示：{'是' if show_original_deadline else '否'}。",
        f"- 提醒节点：截止前 {', '.join(str(item) for item in reminder_offsets) or '无'} 天。",
        f"- 来源消息：{_display_items(facts.source_message_ids, empty='未登记')}。",
        f"- 原件：{_display_items(facts.attachment_names, empty='无已登记原件')}。",
        f"- 网页来源：{_display_items(facts.source_urls, empty='无')}。",
        f"- 目标群：{facts.target_group or '未指定，不能批准发送'}。",
    ]
    lines.append("- 辅助生成器仅提供技术草稿，正式两版候选须由 lite 语义理解后生成。")
    if facts.collection_required and facts.original_deadline and not facts.class_deadline:
        try:
            suggestion = collection_suggestion(facts.original_deadline, effective_advance_days)
            lines.append(f"**收交建议：建议于{format_deadline(suggestion)}收齐。**（仅给用户看，未经确认未改动通知时间。）")
        except ValueError:
            pass
    if not facts.collection_required:
        lines.append("- 个人/非班级事项未提前，未套用收交提前规则。")
    if facts.uncertainties:
        lines.append("- 待确认：" + "；".join(facts.uncertainties) + "。")
    if facts.notes:
        lines.append("- 原文注意事项：" + "；".join(facts.notes) + "。")
    lines.append("- 发送状态：当前仅生成草稿，需用户审核；未代表已发送或已送达。")
    return "\n".join(lines)


def _render_reminder(
    facts: NoticeFacts,
    *,
    class_deadline: str | None,
    show_original_deadline: bool,
) -> str:
    values = {
        "title": facts.title,
        "class_deadline": _safe_deadline(class_deadline),
        "submission_method": facts.submission_method if _known(facts.submission_method) else facts.task if _known(facts.task) else facts.title,
        "original_deadline": _safe_deadline(facts.original_deadline) if show_original_deadline else "",
    }
    template = facts.reminder_template or "提醒：{title}，截止时间为{class_deadline}。"
    try:
        text = template.format(**values)
    except (KeyError, ValueError):
        text = f"提醒：{facts.title}请于{values['class_deadline']}前完成{facts.submission_method}。"
    if show_original_deadline and facts.original_deadline != class_deadline and facts.original_deadline and "{original_deadline}" not in template:
        text = f"{text}（上级截止：{values['original_deadline']}）"
    if not show_original_deadline and facts.original_deadline:
        text = re.sub(r"（?上级原?截止(?:时间)?：[^）)]*）?", "", text)
    return text


def build_notice_package(
    facts: NoticeFacts | dict[str, Any],
    settings: AppSettings | None = None,
) -> NoticePackage:
    facts = facts if isinstance(facts, NoticeFacts) else NoticeFacts.from_dict(facts)
    settings = settings or AppSettings()
    settings.validate()
    effective_advance = settings.collection_advance_days if facts.advance_days is None else facts.advance_days
    if effective_advance < 0:
        raise ValueError("advance_days must be non-negative")
    show_original = (
        settings.show_original_deadline
        if facts.show_original_deadline is None
        else facts.show_original_deadline
    )
    reminder_offsets = tuple(
        dict.fromkeys(
            settings.reminder_offsets
            if facts.reminder_offsets is None
            else facts.reminder_offsets
        )
    )
    if any(offset < 0 for offset in reminder_offsets):
        raise ValueError("reminder offsets must be non-negative")
    if not facts.reminders_enabled or not (facts.class_deadline or facts.original_deadline):
        reminder_offsets = ()
    try:
        class_deadline = serialize_deadline(facts.class_deadline or facts.original_deadline)
    except ValueError as exc:
        class_deadline = None
        facts = replace(
            facts,
            uncertainties=tuple(
                [*facts.uncertainties, f"截止日期无法解析，需人工确认（{exc}）"]
            ),
        )
    polished = _build_polished_text(
        facts,
        class_deadline=class_deadline,
        show_original_deadline=show_original,
    )
    concise = _build_concise_text(
        facts,
        class_deadline=class_deadline,
        show_original_deadline=show_original,
    )
    chapters = build_flowchart_chapters(
        facts,
        class_deadline=class_deadline,
        show_original_deadline=show_original,
        reminder_offsets=reminder_offsets,
    )
    mermaid = chapters[0].mermaid
    nodes = chapters[0].nodes
    review_notes = _build_review_notes(
        facts,
        class_deadline=class_deadline,
        effective_advance_days=effective_advance,
        show_original_deadline=show_original,
        reminder_offsets=reminder_offsets,

    )
    reminder = _render_reminder(
        facts,
        class_deadline=class_deadline,
        show_original_deadline=show_original,
    ) if reminder_offsets and class_deadline else ""
    return NoticePackage(
        facts=facts,
        class_deadline=class_deadline,
        effective_advance_days=effective_advance,
        show_original_deadline=show_original,
        reminder_offsets=reminder_offsets,
        polished_text=polished,
        concise_text=concise,
        mermaid=mermaid,
        review_notes=review_notes,
        reminder_preview=reminder,
        flowchart_nodes=nodes,
        flowchart_chapters=chapters,
    )


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    return cleaned[:80] or "notice"


def _markdown(
    package: NoticePackage,
    *,
    chapter_links: tuple[tuple[str, str, str], ...] = (),
) -> str:
    facts = package.facts
    originals_lines: list[str] = []
    for index, name in enumerate(facts.attachment_names):
        path = facts.attachment_paths[index] if index < len(facts.attachment_paths) else "路径未登记"
        originals_lines.append(f"- `{name}`：`{path}`（原件需按审核清单核对）")
    originals = "\n".join(originals_lines) or "- 无已登记原件"
    sources = "\n".join(f"- {item}" for item in facts.source_urls) or "- 无"
    links = chapter_links or (("一页总览", "flowchart.mmd", "flowchart.png"),)
    flowchart_lines = [
        f"## 流程图（按章节，共 {len(links)} 张）",
        "优先一屏一图；事项较长时按章节查看，不把所有步骤压缩进一张长图。",
    ]
    for index, (title, mermaid_name, image_name) in enumerate(links, 1):
        flowchart_lines.extend(
            [
                "",
                f"### 图{index}：{title}",
                f"![图{index}：{title}]({image_name})",
                f"[Mermaid 源码]({mermaid_name})",
            ]
        )
        if index == 1:
            flowchart_lines.extend(["", "```mermaid", package.mermaid.rstrip(), "```"])
    return "\n".join(
        [
            f"# 通知包：{facts.title}",
            "",
            "## 通知润色版",
            package.polished_text,
            "",
            "## 省流版",
            package.concise_text,
            "",
            *flowchart_lines,
            "",
            "## 文件原件",
            originals,
            "",
            "## 网页来源",
            sources,
            "",
            "## 提醒预览",
            f"提醒节点：截止前 {', '.join(str(item) for item in package.reminder_offsets) or '无'} 天。",
            package.reminder_preview,
            "",
            "## 审核说明",
            package.review_notes,
            "",
            "## 审核动作",
            "请核对事项归类、日期、附件归属和目标群；未明确批准前不发送。",
            "",
        ]
    )


def write_notice_package(
    facts: NoticeFacts | dict[str, Any],
    output_root: str | Path,
    *,
    settings: AppSettings | None = None,
    mmdc: str | None = None,
) -> NoticePackage:
    package = build_notice_package(facts, settings)
    directory = Path(output_root).expanduser().resolve() / _safe_id(package.facts.notice_id)
    directory.mkdir(parents=True, exist_ok=True)
    markdown_path = directory / "notice.md"
    mermaid_path = directory / "flowchart.mmd"
    flowchart_path = directory / "flowchart.png"
    summary_path = directory / "summary.png"
    package_json_path = directory / "package.json"
    chapters = package.flowchart_chapters or (
        FlowchartChapter(
            chapter_id="overview",
            title="一页总览",
            mermaid=package.mermaid,
            nodes=package.flowchart_nodes,
            layout=FlowchartLayout(
                rows=((_flowchart_box("node", package.facts.title, "primary"),),),
            ),
        ),
    )
    chapter_paths: dict[str, dict[str, str]] = {}
    chapter_links: list[tuple[str, str, str]] = []
    chapter_rendering: dict[str, str] = {}
    for index, chapter in enumerate(chapters):
        suffix = "" if index == 0 else f"-{index + 1:02d}-{_safe_id(chapter.chapter_id)}"
        chapter_mermaid_path = directory / f"flowchart{suffix}.mmd"
        chapter_image_path = directory / f"flowchart{suffix}.png"
        chapter_mermaid_path.write_text(chapter.mermaid, encoding="utf-8")
        status = render_mermaid(
            chapter.mermaid,
            chapter_image_path,
            chapter.nodes,
            mmdc=mmdc,
            fallback_layout=chapter.layout,
            fallback_title=chapter.title,
        )
        chapter_paths[chapter.chapter_id] = {
            "mermaid": str(chapter_mermaid_path),
            "flowchart": str(chapter_image_path),
        }
        chapter_links.append(
            (chapter.title, chapter_mermaid_path.name, chapter_image_path.name)
        )
        chapter_rendering[chapter.chapter_id] = status
        if index == 0:
            mermaid_path = chapter_mermaid_path
            flowchart_path = chapter_image_path
    summary_rendering = render_summary_png(package.concise_text, summary_path, title="省流版")
    rendering = {
        "flowchart": chapter_rendering[chapters[0].chapter_id],
        "summary": summary_rendering,
        **{f"flowchart:{key}": value for key, value in chapter_rendering.items()},
    }
    paths = {
        "markdown": str(markdown_path),
        "mermaid": str(mermaid_path),
        "flowchart": str(flowchart_path),
        "summary": str(summary_path),
        "package_json": str(package_json_path),
    }
    package = NoticePackage(
        facts=package.facts,
        class_deadline=package.class_deadline,
        effective_advance_days=package.effective_advance_days,
        show_original_deadline=package.show_original_deadline,
        reminder_offsets=package.reminder_offsets,
        polished_text=package.polished_text,
        concise_text=package.concise_text,
        mermaid=package.mermaid,
        review_notes=package.review_notes,
        reminder_preview=package.reminder_preview,
        flowchart_nodes=package.flowchart_nodes,
        flowchart_chapters=chapters,
        artifact_paths=paths,
        chapter_artifact_paths=chapter_paths,
        rendering=rendering,
    )
    markdown_path.write_text(
        _markdown(package, chapter_links=tuple(chapter_links)),
        encoding="utf-8",
    )
    package_json_path.write_text(
        json.dumps(package.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return package
