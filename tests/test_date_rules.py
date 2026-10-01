import unittest
from datetime import date, datetime

from wechat_notice.date_rules import (
    calculate_class_deadline,
    collection_suggestion,
    format_deadline,
    is_expired,
    reminder_schedule,
)


class DateRuleTests(unittest.TestCase):
    def test_only_class_collection_moves_the_deadline(self) -> None:
        original = date(2026, 9, 20)
        self.assertEqual(
            calculate_class_deadline(original, collection_required=True, advance_days=2),
            date(2026, 9, 18),
        )
        self.assertEqual(
            calculate_class_deadline(original, collection_required=False, advance_days=2),
            original,
        )

    def test_reminders_are_unique_and_use_local_clock(self) -> None:
        points = reminder_schedule(
            date(2026, 9, 18),
            [2, 1, 2],
            reminder_time="09:00",
            timezone="Asia/Shanghai",
        )
        self.assertEqual(
            points,
            [
                datetime.fromisoformat("2026-09-16T09:00:00+08:00"),
                datetime.fromisoformat("2026-09-17T09:00:00+08:00"),
            ],
        )

    def test_working_day_subtraction_skips_weekend(self) -> None:
        points = reminder_schedule(
            date(2026, 9, 21),
            [1],
            reminder_time="09:00",
            timezone="Asia/Shanghai",
            working_days=True,
        )
        self.assertEqual(points[0].date(), date(2026, 9, 18))

    def test_reminder_uses_configured_timezone_for_zoned_deadline(self) -> None:
        points = reminder_schedule(
            "2026-09-19T17:30:00+00:00",
            [0],
            reminder_time="09:00",
            timezone="Asia/Shanghai",
        )

        self.assertEqual(points[0].date(), date(2026, 9, 20))

    def test_datetime_format_keeps_time_but_date_only_does_not_invent_one(self) -> None:
        self.assertEqual(format_deadline("2026-09-20"), "2026年09月20日")
        self.assertEqual(format_deadline("2026-09-20T17:00:00+08:00"), "2026年09月20日 17:00")

    def test_display_converts_utc_to_beijing_and_rolls_date(self) -> None:
        self.assertEqual(format_deadline("2026-10-20T09:00:00Z"), "2026年10月20日 17:00")
        self.assertEqual(format_deadline("2026-10-20T20:30:00Z"), "2026年10月21日 04:30")

    def test_suggestion_counts_deadline_as_day_one_and_crosses_month(self) -> None:
        self.assertEqual(collection_suggestion("2026-10-18"), "2026-10-16T12:00:00+08:00")
        self.assertEqual(collection_suggestion("2026-10-01"), "2026-09-29T12:00:00+08:00")

    def test_date_only_deadline_expires_on_the_following_local_day(self) -> None:
        self.assertFalse(is_expired("2026-09-20", datetime.fromisoformat("2026-09-20T23:59:00+08:00")))
        self.assertTrue(is_expired("2026-09-20", datetime.fromisoformat("2026-09-21T00:00:00+08:00")))


if __name__ == "__main__":
    unittest.main()
