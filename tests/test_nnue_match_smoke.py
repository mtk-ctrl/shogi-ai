from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.research.nnue_match_smoke import assert_arena_options


class AuditTest(unittest.TestCase):
    def test_arena_adds_documented_risk_verify_true(self):
        a = dict(EvalNeural=True, EvalNeuralFile="model.nnue",
                 PositionKnowledge=True)
        b = dict(EvalNeural=False, PositionKnowledge=True)
        actual = dict(options_a=dict(a, RiskVerify=True),
                      options_b=dict(b, RiskVerify=True))
        assert_arena_options(actual, a, b)
        actual["options_b"]["EvalNeural"] = True
        with self.assertRaisesRegex(ValueError, "options_b"):
            assert_arena_options(actual, a, b)
        actual["options_b"]["EvalNeural"] = False
        actual["options_a"]["RiskVerify"] = False
        with self.assertRaisesRegex(ValueError, "options_a"):
            assert_arena_options(actual, a, b)


if __name__ == "__main__":
    unittest.main()
