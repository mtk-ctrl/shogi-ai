import datetime
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "floodgate"))
from chain import decide  # noqa: E402

CFG = dict(enabled=True, session_minutes=210, pause_dates_jst=["2026-12-06"])
T = datetime.datetime(2026, 11, 15, 3, 0)  # 12:00 JST


def d(cfg=CFG, **kw):
    base = dict(mode="live", continuous="yes", outcome="success", fail_count=0, now_utc=T)
    base.update(kw)
    return decide(cfg, **base)


class ChainTests(unittest.TestCase):
    def test_success_chains(self):
        r = d()
        self.assertTrue(r["dispatch"]); self.assertEqual(r["next_fail_count"], 0)

    def test_disabled_stops(self):
        self.assertFalse(d(dict(CFG, enabled=False))["dispatch"])

    def test_non_continuous_never_chains(self):
        self.assertFalse(d(continuous="no")["dispatch"])

    def test_pause_date_stops(self):
        self.assertFalse(d(now_utc=datetime.datetime(2026, 12, 6, 1, 0))["dispatch"])
        # 次の回が停止日に差しかかる場合も起動しない（12/5 23:00 JST + 210分）
        self.assertFalse(d(now_utc=datetime.datetime(2026, 12, 5, 14, 0))["dispatch"])

    def test_failure_retries_up_to_three(self):
        for n, ok in ((0, True), (1, True), (2, True), (3, False)):
            r = d(outcome="failure", fail_count=n)
            self.assertEqual(r["dispatch"], ok, n)
        self.assertEqual(d(outcome="skipped", fail_count=0)["next_fail_count"], 1)

    def test_success_resets_failures(self):
        self.assertEqual(d(fail_count=2)["next_fail_count"], 0)

    def test_selftest(self):
        self.assertTrue(d(continuous="selftest", mode="probe")["dispatch"])
        self.assertFalse(d(continuous="selftest", mode="probe", outcome="failure")["dispatch"])


if __name__ == "__main__":
    unittest.main()
