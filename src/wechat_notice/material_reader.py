from __future__ import annotations

import ipaddress
import mimetypes
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable, Protocol
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from .models import MessageRecord
from .ocr import OCRResult, ocr_image_bytes


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
URL_RE = re.compile(r"https?://[^\s<>\[\]{}，。；：！？、）》】〉”’'\"]+", re.IGNORECASE)
TRAILING_URL_PUNCTUATION = ".,;:!?，。；：！？）》】〉》”’'\""


@dataclass(frozen=True)
class FetchedContent:
    data: bytes
    content_type: str = ""
    charset: str | None = None


class ContentFetcher(Protocol):
    def __call__(self, url: str) -> FetchedContent: ...


@dataclass(frozen=True)
class MaterialReadResult:
    source_url: str
    kind: str
    status: str
    title: str = ""
    text: str = ""
    locations: tuple[str, ...] = ()
    linked_urls: tuple[str, ...] = ()
    image_urls: tuple[str, ...] = ()
    ocr_locations: tuple[str, ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "source_url": self.source_url,
            "kind": self.kind,
            "status": self.status,
            "title": self.title,
            "text": self.text,
            "locations": list(self.locations),
            "linked_urls": list(self.linked_urls),
            "image_urls": list(self.image_urls),
            "ocr_locations": list(self.ocr_locations),
            "error": self.error,
        }


def extract_urls(text: str) -> tuple[str, ...]:
    """Extract only HTTP(S) URLs from a message without following them."""
    result: list[str] = []
    for match in URL_RE.findall(text):
        candidate = match.rstrip(TRAILING_URL_PUNCTUATION)
        if candidate and candidate not in result:
            result.append(candidate)
    return tuple(result)


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("仅允许读取 HTTP(S) 网页，已拒绝该地址")
    if parsed.username or parsed.password:
        raise ValueError("不读取带账号密码的 URL")
    hostname = (parsed.hostname or "").strip("[]").lower()
    if not hostname:
        raise ValueError("URL 缺少主机名")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
        raise ValueError("不读取指向本机或内网地址的 URL")


def default_fetcher(url: str, *, timeout: int = 20) -> FetchedContent:
    _validate_url(url)
    request = Request(
        url,
        headers={
            "User-Agent": "wechat-notice/0.1 (material reader)",
            "Accept": "text/html,text/plain,image/*;q=0.8,*/*;q=0.2",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL is validated above
        headers = response.headers
        return FetchedContent(
            data=response.read(),
            content_type=headers.get_content_type() if headers else "",
            charset=headers.get_content_charset() if headers else None,
        )


class _HTMLMaterialParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.linked_urls: list[str] = []
        self.image_urls: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = {key.lower(): value for key, value in attrs}
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "template"}:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = normalized.get("href")
            if href:
                self.linked_urls.append(href)
        if tag == "img":
            for key in ("src", "data-src", "data-original", "data-lazy-src"):
                value = normalized.get(key)
                if value:
                    self.image_urls.append(value)
                    break

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() in {"script", "style", "noscript", "template"}:
            self._skip_depth = max(self._skip_depth - 1, 0)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "template"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        clean = " ".join(data.split())
        if not clean:
            return
        if self._in_title:
            self.title_parts.append(clean)
            return
        self.text_parts.append(clean)


def _decode_html(data: bytes, charset: str | None) -> str:
    encodings = [charset, "utf-8", "gb18030", "big5"]
    for encoding in encodings:
        if not encoding:
            continue
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def _is_image(url: str, content_type: str) -> bool:
    return content_type.lower().split(";", 1)[0].strip().startswith("image/") or Path(
        urlparse(url).path
    ).suffix.lower() in IMAGE_SUFFIXES


def _ocr_content(data: bytes, suffix: str) -> OCRResult:
    return ocr_image_bytes(data, suffix=suffix)


class MaterialReader:
    """Read web material and article images with injectable I/O for tests."""

    def __init__(
        self,
        *,
        fetcher: ContentFetcher | None = None,
        ocr_runner: Callable[[bytes, str], str | OCRResult] | None = None,
    ) -> None:
        self.fetcher = fetcher or default_fetcher
        self.ocr_runner = ocr_runner or _ocr_content

    def read_url(self, url: str) -> MaterialReadResult:
        try:
            _validate_url(url)
            fetched = self.fetcher(url)
        except Exception as exc:
            return MaterialReadResult(
                source_url=url,
                kind="wechat_article" if "mp.weixin.qq.com" in url else "web",
                status="failed",
                error=str(exc),
            )

        kind = "wechat_article" if "mp.weixin.qq.com" in url else "web"
        if _is_image(url, fetched.content_type):
            try:
                result = self.ocr_runner(
                    fetched.data,
                    Path(urlparse(url).path).suffix.lower() or ".png",
                )
            except Exception as exc:
                result = OCRResult("failed", error=str(exc))
            if isinstance(result, OCRResult):
                ocr_result = result
            else:
                text = str(result).strip()
                ocr_result = OCRResult("extracted" if text else "empty", text=text)
            return MaterialReadResult(
                source_url=url,
                kind="image",
                status=(
                    "extracted"
                    if ocr_result.text
                    else ("failed" if ocr_result.status == "failed" else "needs_review")
                ),
                text=ocr_result.text,
                locations=("image (OCR)",) if ocr_result.text else (),
                ocr_locations=("image (OCR)",) if ocr_result.text else (),
                error=ocr_result.error,
            )

        content_type = fetched.content_type.lower().split(";", 1)[0].strip()
        if content_type in {"text/html", "application/xhtml+xml", ""}:
            parser = _HTMLMaterialParser()
            parser.feed(_decode_html(fetched.data, fetched.charset))
            text = "\n".join(parser.text_parts)
            title = " ".join(parser.title_parts)
            linked_urls = tuple(
                urljoin(url, item) for item in parser.linked_urls if item
            )
            image_urls = tuple(
                urljoin(url, item)
                for item in parser.image_urls
                if item and not item.lower().startswith("data:")
            )
        else:
            text = _decode_html(fetched.data, fetched.charset).strip()
            title = ""
            linked_urls = ()
            image_urls = ()

        blocks: list[str] = []
        locations: list[str] = []
        if title:
            blocks.append(title)
            locations.append("title")
        if text and text != title:
            blocks.append(text)
            locations.append("article body")

        errors: list[str] = []
        ocr_locations: list[str] = []
        for index, image_url in enumerate(image_urls, 1):
            try:
                _validate_url(image_url)
                image = self.fetcher(image_url)
                result = self.ocr_runner(
                    image.data,
                    Path(urlparse(image_url).path).suffix.lower() or ".png",
                )
                ocr_result = result if isinstance(result, OCRResult) else OCRResult(
                    "extracted" if str(result).strip() else "empty", text=str(result).strip()
                )
                if ocr_result.text:
                    location = f"image {index} (OCR)"
                    blocks.append(ocr_result.text)
                    locations.append(location)
                    ocr_locations.append(location)
                elif ocr_result.error:
                    errors.append(f"{image_url}: {ocr_result.error}")
            except Exception as exc:
                errors.append(f"{image_url}: {exc}")

        return MaterialReadResult(
            source_url=url,
            kind=kind,
            status="needs_review" if errors else ("extracted" if blocks else "no_text"),
            title=title,
            text="\n".join(blocks),
            locations=tuple(locations),
            linked_urls=linked_urls,
            image_urls=image_urls,
            ocr_locations=tuple(ocr_locations),
            error="；".join(errors) if errors else None,
        )

    def read_urls(self, urls: Iterable[str]) -> list[MaterialReadResult]:
        return [self.read_url(url) for url in dict.fromkeys(urls)]


def read_message_materials(
    messages: Iterable[MessageRecord],
    *,
    reader: MaterialReader | None = None,
) -> list[MaterialReadResult]:
    urls: list[str] = []
    for message in messages:
        urls.extend(extract_urls(message.text))
        metadata_url = message.metadata.get("url")
        if isinstance(metadata_url, str):
            urls.append(metadata_url)
    return (reader or MaterialReader()).read_urls(urls)
