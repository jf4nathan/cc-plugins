import json
import math
import tempfile
import unittest
from pathlib import Path

from statusplus_test_utils import run_script


class CostDisplayTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.home = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def render(self, live, sid="session"):
        return run_script(
            "cost-display.py",
            {"session_id": sid, "cost": {"total_cost_usd": live}},
            self.home,
        )

    def test_out_of_order_render_does_not_double_count(self):
        self.assertEqual(self.render(10).stdout, "10.00\n")
        self.assertEqual(self.render(9.5).stdout, "10.00\n")
        self.assertEqual(self.render(11).stdout, "11.00\n")

    def test_state_is_atomic_per_session_json(self):
        self.assertEqual(self.render(4).stdout, "4.00\n")
        state_path = self.home / ".claude" / ".session_cost" / "session.json"
        self.assertEqual(
            json.loads(state_path.read_text(encoding="utf-8")),
            {"prev_live": 4.0, "total": 4.0},
        )
        self.assertEqual(list(state_path.parent.glob(".tmp-*")), [])

    def test_legacy_state_migrates_once(self):
        root = self.home / ".claude"
        (root / ".session_cost").mkdir(parents=True)
        (root / ".session_cost_displayed").mkdir()
        (root / ".session_cost" / "legacy").write_text("7", encoding="utf-8")
        (root / ".session_cost_displayed" / "legacy").write_text("5", encoding="utf-8")
        self.assertEqual(self.render(8, "legacy").stdout, "6.00\n")
        state = json.loads(
            (root / ".session_cost" / "legacy.json").read_text(encoding="utf-8")
        )
        self.assertEqual(state, {"prev_live": 8.0, "total": 6.0})

    def test_clear_creates_and_consumes_reset_marker(self):
        hook = run_script(
            "clear-cost-baseline.py",
            {
                "hook_event_name": "SessionStart",
                "source": "clear",
                "session_id": "cleared",
            },
            self.home,
        )
        self.assertEqual(hook.returncode, 0)
        marker = self.home / ".claude" / ".session_cost_reset" / "cleared"
        self.assertTrue(marker.exists())
        self.assertEqual(self.render(25, "cleared").stdout, "0.00\n")
        self.assertFalse(marker.exists())
        state = json.loads(
            (
                self.home
                / ".claude"
                / ".session_cost"
                / "cleared.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(state, {"prev_live": 25.0, "total": 0.0})

    def test_resume_hook_does_not_create_cross_session_carry(self):
        result = run_script(
            "clear-cost-baseline.py",
            {
                "hook_event_name": "SessionStart",
                "source": "resume",
                "session_id": "resumed",
            },
            self.home,
        )
        self.assertEqual(result.returncode, 0)
        carry = self.home / ".claude" / ".session_cost_carry"
        self.assertFalse(carry.exists())

    def test_invalid_or_negative_live_is_silent(self):
        payloads = [
            {"session_id": "s", "cost": {"total_cost_usd": -1}},
            {"session_id": "s", "cost": {"total_cost_usd": math.nan}},
            {"session_id": "s", "cost": {"total_cost_usd": "not-a-number"}},
            {"session_id": "s", "cost": {}},
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                result = run_script("cost-display.py", payload, self.home)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
