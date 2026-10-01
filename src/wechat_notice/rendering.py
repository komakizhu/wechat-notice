from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class FlowchartBox:
    id: str
    label: str
    kind: str = "normal"


@dataclass(frozen=True)
class FlowchartLayout:
    rows: tuple[tuple[FlowchartBox, ...], ...]
    edges: tuple[tuple[str, str, str], ...] = ()


def _font(size: int):
    from PIL import ImageFont

    candidates = (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_by_width(text: str, font, max_width: int) -> list[str]:
    from PIL import Image, ImageDraw

    if not text:
        return [""]
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines: list[str] = []
    for original in text.splitlines() or [""]:
        current = ""
        for character in original:
            candidate = current + character
            left, top, right, bottom = probe.textbbox((0, 0), candidate, font=font)
            if current and right - left > max_width:
                lines.append(current)
                current = character
            else:
                current = candidate
        lines.append(current)
    return lines


def _draw_wrapped(draw, xy: tuple[int, int], text: str, font, fill, max_width: int, spacing: int = 8) -> int:
    lines = _wrap_by_width(text, font, max_width)
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        bbox = draw.textbbox((x, y), line or " ", font=font)
        y += bbox[3] - bbox[1] + spacing
    return y


def render_summary_png(text: str, output_path: str | Path, *, title: str = "省流版") -> str:
    """Render a phone-readable summary card using local fonts and Pillow."""
    from PIL import Image, ImageDraw

    width = 1400
    title_font = _font(54)
    body_font = _font(36)
    small_font = _font(27)
    content_width = width - 160
    body_lines = _wrap_by_width(text, body_font, content_width)
    height = 150 + max(1, len(body_lines)) * 58 + 100
    image = Image.new("RGB", (width, height), "#F7F9FC")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((35, 35, width - 35, height - 35), radius=28, fill="white", outline="#D6DFEA", width=3)
    draw.text((80, 75), title, font=title_font, fill="#16324F")
    y = 170
    for line in body_lines:
        draw.text((80, y), line, font=body_font, fill="#243447")
        y += 58
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="PNG", optimize=True)
    return "pillow"


def _linear_layout(nodes: Iterable[str]) -> FlowchartLayout:
    boxes = tuple(FlowchartBox(f"node{index}", str(node)) for index, node in enumerate(nodes))
    edges = tuple(
        (boxes[index].id, boxes[index + 1].id, "")
        for index in range(max(0, len(boxes) - 1))
    )
    return FlowchartLayout(rows=(boxes,), edges=edges)


def _draw_arrow(draw, start: tuple[float, float], end: tuple[float, float], *, fill: str, width: int) -> None:
    draw.line((start, end), fill=fill, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    length = 13
    spread = math.pi / 7
    points = [
        end,
        (
            end[0] - length * math.cos(angle - spread),
            end[1] - length * math.sin(angle - spread),
        ),
        (
            end[0] - length * math.cos(angle + spread),
            end[1] - length * math.sin(angle + spread),
        ),
    ]
    draw.polygon(points, fill=fill)


def render_flowchart_png(
    nodes: Iterable[str],
    output_path: str | Path,
    *,
    title: str = "办理流程",
    layout: FlowchartLayout | None = None,
) -> str:
    """Render a compact deterministic fallback when Mermaid CLI is absent."""
    from PIL import Image, ImageDraw

    layout = layout or _linear_layout(nodes)
    rows = tuple(row for row in layout.rows if row)
    if not rows:
        rows = ((FlowchartBox("empty", "未说明"),),)
    width = 1600
    margin = 60
    row_gap = 52
    title_font = _font(46)
    node_font = _font(28)
    small_font = _font(22)
    content_width = width - (2 * margin)

    positions: dict[str, tuple[float, float, float, float]] = {}
    wrapped_by_id: dict[str, list[str]] = {}
    row_heights: list[int] = []
    for row in rows:
        count = len(row)
        gap = 28
        box_width = (content_width - gap * (count - 1)) / count
        row_height = 78
        for box in row:
            wrapped = _wrap_by_width(box.label, node_font, int(box_width - 44))
            wrapped_by_id[box.id] = wrapped
            row_height = max(row_height, 30 + len(wrapped) * 39)
        row_heights.append(row_height)

    content_top = 125
    # Reserve a real footer band so the attribution never overlaps the last node.
    height = content_top + sum(row_heights) + row_gap * (len(rows) - 1) + 120
    image = Image.new("RGB", (width, height), "#F7F9FC")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((35, 35, width - 35, height - 35), radius=28, fill="white", outline="#D6DFEA", width=3)
    draw.text((margin, 62), title, font=title_font, fill="#16324F")

    y = content_top
    row_index: dict[str, int] = {}
    for index, row in enumerate(rows):
        count = len(row)
        gap = 28
        box_width = (content_width - gap * (count - 1)) / count
        if count == 1:
            left_start = (width - box_width) / 2
        else:
            left_start = margin
        for box_index, box in enumerate(row):
            left = left_start + box_index * (box_width + gap)
            right = left + box_width
            top = y
            bottom = y + row_heights[index]
            positions[box.id] = (left, top, right, bottom)
            row_index[box.id] = index
        y += row_heights[index] + row_gap

    edge_color = "#5079A6"
    for source_id, target_id, label in layout.edges:
        source = positions.get(source_id)
        target = positions.get(target_id)
        if source is None or target is None:
            continue
        source_row = row_index[source_id]
        target_row = row_index[target_id]
        if source_row == target_row and source[2] <= target[0]:
            start = ((source[2], (source[1] + source[3]) / 2))
            end = ((target[0], (target[1] + target[3]) / 2))
        else:
            start = (((source[0] + source[2]) / 2), source[3])
            end = (((target[0] + target[2]) / 2), target[1])
        _draw_arrow(draw, start, end, fill=edge_color, width=4)
        if label:
            midpoint = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
            draw.text(midpoint, label, font=small_font, fill="#52677D", anchor="mm")

    fills = {
        "primary": ("#EAF3FF", "#6D9ED7"),
        "decision": ("#FFF4CC", "#D99A27"),
        "warning": ("#FFF0F0", "#D96B6B"),
        "branch": ("#F0F8EC", "#7FAF71"),
        "muted": ("#F5F8FC", "#A5B8CB"),
        "normal": ("#F5F8FC", "#7FA6D5"),
    }
    for row in rows:
        for box in row:
            left, top, right, bottom = positions[box.id]
            fill, outline = fills.get(box.kind, fills["normal"])
            draw.rounded_rectangle(
                (left, top, right, bottom),
                radius=18,
                fill=fill,
                outline=outline,
                width=3,
            )
            lines = wrapped_by_id[box.id]
            line_height = 39
            text_top = top + max(16, (bottom - top - len(lines) * line_height) / 2)
            for line_index, line in enumerate(lines):
                draw.text((left + 22, text_top + line_index * line_height), line, font=node_font, fill="#243447")

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="PNG", optimize=True)
    return "fallback"


def render_mermaid(
    source: str,
    output_path: str | Path,
    fallback_nodes: Iterable[str],
    *,
    mmdc: str | None = None,
    fallback_layout: FlowchartLayout | None = None,
    fallback_title: str = "办理流程",
) -> str:
    """Use Mermaid CLI if present, otherwise produce a visible local fallback."""
    executable = shutil.which(mmdc or "mmdc")
    destination = Path(output_path)
    if executable:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".mmd", prefix="wechat-notice-", encoding="utf-8", delete=False
            ) as handle:
                handle.write(source)
                temporary = Path(handle.name)
            completed = subprocess.run(
                [executable, "-i", str(temporary), "-o", str(destination), "-b", "white"],
                capture_output=True,
                text=True,
                check=False,
                timeout=90,
            )
            if completed.returncode == 0 and destination.is_file() and destination.stat().st_size > 0:
                return "mermaid_cli"
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return render_flowchart_png(
        fallback_nodes,
        destination,
        title=fallback_title,
        layout=fallback_layout,
    )
