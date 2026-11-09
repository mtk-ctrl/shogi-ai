"""Statistics helpers of the self-agreement probe (no engine is run)."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
import agreement_probe as ap


class AgreementProbeTest(unittest.TestCase):
    def test_wilson_interval(self):
        lo, hi = ap.wilson(50, 100)
        self.assertAlmostEqual(lo, 0.4038, places=3)
        self.assertAlmostEqual(hi, 0.5962, places=3)
        self.assertEqual(ap.wilson(0, 0), (0.0, 1.0))
        lo, hi = ap.wilson(480, 480)
        self.assertGreater(lo, 0.99)
        self.assertLessEqual(hi, 1.0 + 1e-12)

    def test_mcnemar_exact(self):
        self.assertEqual(ap.mcnemar_exact(0, 0), 1.0)
        self.assertEqual(ap.mcnemar_exact(5, 5), 1.0)
        # 10 vs 0 discordant: p = 2 * 0.5**10
        self.assertAlmostEqual(ap.mcnemar_exact(10, 0), 2 * 0.5 ** 10)
        self.assertEqual(ap.mcnemar_exact(3, 8), ap.mcnemar_exact(8, 3))

    def test_defaults_disable_stored_moves(self):
        options = ap.load_options("")
        self.assertIs(options["PositionKnowledge"], False)
        self.assertIs(ap.load_options('{"SearchThreads": 1}')["SearchThreads"], 1)


if __name__ == "__main__":
    unittest.main()
