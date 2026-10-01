import json
import tempfile
import unittest
from pathlib import Path

from wechat_notice.models import AppSettings
from wechat_notice.notice_package import NoticeFacts, write_notice_package


class SimulationAcceptanceTests(unittest.TestCase):
    def test_three_synthetic_notice_types_produce_reviewable_artifacts(self) -> None:
        payload = json.loads(
            (Path(__file__).parents[1] / "examples" / "simulated_notices.json").read_text(
                encoding="utf-8"
            )
        )
        settings = AppSettings.from_dict(payload["settings"])
        with tempfile.TemporaryDirectory() as directory:
            packages = [
                write_notice_package(
                    NoticeFacts.from_dict(item),
                    directory,
                    settings=settings,
                    mmdc="__not-installed__",
                )
                for item in payload["notices"]
            ]

            self.assertEqual(len(packages), 3)
            self.assertEqual(packages[0].class_deadline, "2026-09-20")
            self.assertEqual(packages[1].class_deadline, "2026-10-01")
            self.assertEqual(packages[2].class_deadline, "2026-09-25")
            for package in packages:
                self.assertTrue(Path(package.artifact_paths["markdown"]).is_file())
                self.assertTrue(Path(package.artifact_paths["flowchart"]).is_file())
                self.assertTrue(Path(package.artifact_paths["summary"]).is_file())
                self.assertIn("需用户审核", package.review_notes)


if __name__ == "__main__":
    unittest.main()
