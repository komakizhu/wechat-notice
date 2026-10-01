import unittest

from wechat_notice.material_reader import (
    FetchedContent,
    MaterialReader,
    extract_urls,
)
from wechat_notice.ocr import OCRResult


class MaterialReaderTests(unittest.TestCase):
    def test_extract_urls_removes_message_punctuation_and_keeps_distinct_urls(self) -> None:
        urls = extract_urls("看这里：https://example.com/a；重复 https://example.com/a。以及 http://example.org/x")

        self.assertEqual(urls, ("https://example.com/a", "http://example.org/x"))

    def test_article_body_and_lazy_loaded_image_are_read_and_ocr_is_located(self) -> None:
        pages = {
            "https://mp.weixin.qq.com/s/demo": FetchedContent(
                "<html><title>报名通知</title><body>请完成报名。<img data-src='https://cdn.example.org/poster.png'></body></html>".encode(),
                "text/html",
            ),
            "https://cdn.example.org/poster.png": FetchedContent(b"image-bytes", "image/png"),
        }

        def fetcher(url: str) -> FetchedContent:
            return pages[url]

        def ocr(data: bytes, suffix: str) -> OCRResult:
            self.assertEqual(data, b"image-bytes")
            self.assertEqual(suffix, ".png")
            return OCRResult("extracted", "图片里的截止时间：9月18日")

        result = MaterialReader(fetcher=fetcher, ocr_runner=ocr).read_url(
            "https://mp.weixin.qq.com/s/demo"
        )

        self.assertEqual(result.kind, "wechat_article")
        self.assertEqual(result.status, "extracted")
        self.assertIn("请完成报名", result.text)
        self.assertIn("图片里的截止时间", result.text)
        self.assertEqual(result.ocr_locations, ("image 1 (OCR)",))
        self.assertEqual(result.image_urls, ("https://cdn.example.org/poster.png",))

    def test_failed_image_read_remains_a_review_gap(self) -> None:
        result = MaterialReader(
            fetcher=lambda _url: (_ for _ in ()).throw(RuntimeError("network down")),
            ocr_runner=lambda _data, _suffix: "never",
        ).read_url("https://example.org/page")

        self.assertEqual(result.status, "failed")
        self.assertIn("network down", result.error or "")

    def test_private_address_is_rejected_before_fetch(self) -> None:
        called = False

        def fetcher(_url: str) -> FetchedContent:
            nonlocal called
            called = True
            return FetchedContent(b"", "text/plain")

        result = MaterialReader(fetcher=fetcher).read_url("http://127.0.0.1/secret")

        self.assertEqual(result.status, "failed")
        self.assertFalse(called)
        self.assertIn("内网", result.error or "")


if __name__ == "__main__":
    unittest.main()
