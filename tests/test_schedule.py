from datetime import datetime
import os
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from scripts.main import current_schedule_slot


TZ = ZoneInfo("Asia/Shanghai")


def beijing(hour: int, minute: int) -> datetime:
    return datetime(2026, 10, 4, hour, minute, tzinfo=TZ)


class ScheduleSlotTests(unittest.TestCase):
    def test_before_slot_is_not_due(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(current_schedule_slot({}, beijing(11, 59)))

    def test_missed_slot_is_still_due_after_default_window(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(current_schedule_slot({}, beijing(14, 11)), "1200")

    def test_completed_slot_is_not_due_again(self):
        state = {"slot_done": {"2026-10-04": ["1200"]}}
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(current_schedule_slot(state, beijing(14, 11)))

    def test_multiple_due_slots_choose_the_latest(self):
        env = {"SLOT_TIMES": "08:30,12:00,21:30"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(current_schedule_slot({}, beijing(22, 0)), "2130")

    def test_explicit_window_can_disable_old_slot(self):
        env = {"SLOT_WINDOW_MINUTES": "120"}
        with patch.dict(os.environ, env, clear=True):
            self.assertIsNone(current_schedule_slot({}, beijing(14, 11)))


if __name__ == "__main__":
    unittest.main()
