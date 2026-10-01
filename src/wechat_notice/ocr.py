from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OCRResult:
    status: str
    text: str = ""
    error: str | None = None


def ocr_image_path(
    path: str | Path,
    *,
    language: str = "chi_sim+chi_tra+eng",
    command: str | None = None,
    timeout: int = 45,
) -> OCRResult:
    """Run local Tesseract without modifying the source image."""
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        return OCRResult("failed", error="图片不存在或不是普通文件")
    try:
        data = candidate.read_bytes()
    except OSError as exc:
        return OCRResult("failed", error=f"读取图片失败: {exc}")
    return ocr_image_bytes(
        data,
        suffix=candidate.suffix or ".png",
        language=language,
        command=command,
        timeout=timeout,
    )


def ocr_image_bytes(
    data: bytes,
    *,
    suffix: str = ".png",
    language: str = "chi_sim+chi_tra+eng",
    command: str | None = None,
    timeout: int = 45,
) -> OCRResult:
    """OCR image bytes through a list-based subprocess call.

    The command is injectable for deterministic tests. No image bytes are
    retained after the process exits.
    """
    executable = command or shutil.which("tesseract")
    if not executable:
        return OCRResult("unavailable", error="本机未找到 Tesseract")
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, prefix="wechat-notice-", delete=True) as handle:
            handle.write(data)
            handle.flush()
            completed = subprocess.run(
                [executable, handle.name, "stdout", "-l", language, "--psm", "6"],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        return OCRResult("failed", error=f"Tesseract 执行失败: {exc}")
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"退出码 {completed.returncode}"
        return OCRResult("failed", error=f"Tesseract 识别失败: {detail}")
    text = completed.stdout.strip()
    if not text:
        return OCRResult("empty", error="Tesseract 未识别出文字")
    return OCRResult("extracted", text=text)
