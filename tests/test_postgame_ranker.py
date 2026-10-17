import copy
import unittest

from tools.research.postgame_ranker import AXES, BASE, OPTIONS, fit, loss_gradient


def terms(**parts):
    out = dict.fromkeys((*AXES, "material_term", "clamp", "total"), 0)
    out.update(parts)
    out["total"] = out["material_term"] + sum(out[k] for k in AXES)
    return out


def dataset():
    rows = []
    for split, groups in (("train", 16), ("validation", 8), ("heldout", 8)):
        for i in range(groups):
            rows.append(dict(case_id=f"{split}-{i}", game=f"{split}-{i}",
                             group=f"{split}-{i}", split=split, reward=None,
                             root=terms(), actual=terms(safety=100), research=terms(pressure=99)))
    return rows


class RankerTest(unittest.TestCase):
    def test_pair_updates_are_bounded_representable_and_not_a_strength_claim(self):
        result = fit(dataset())
        self.assertEqual(result["status"], "requires_engine_validation")
        self.assertFalse(result["formal_adoption"])
        self.assertGreater(result["heldout"]["candidate"]["preferred"], 0)
        for key, base in zip(OPTIONS, BASE):
            self.assertTrue(.95*base <= result["options"][key] <= 1.05*base)

    def test_analytic_gradient_matches_finite_difference(self):
        rows = dataset()[:5]
        rows[0]["root"] = terms(safety=120, material_term=-60)
        rows[0]["reward"] = -1
        delta = [.01]*len(AXES)
        _, gradient = loss_gradient(rows, delta)
        for i, g in enumerate(gradient):
            left, right = delta.copy(), delta.copy()
            left[i] -= 1e-6; right[i] += 1e-6
            finite = (loss_gradient(rows, right)[0]-loss_gradient(rows, left)[0])/2e-6
            self.assertAlmostEqual(g, finite, places=7)

    def test_winner_reward_does_not_change_counterfactual_pair_labels(self):
        rows = dataset()[:1]
        rows[0]["reward"] = 1
        a = loss_gradient(rows, [0.]*9)
        rows[0]["reward"] = -1
        # Root has zero adjustable terms: reward cannot label a hypothetical move.
        b = loss_gradient(rows, [0.]*9)
        self.assertEqual(a, b)

    def test_equal_total_weight_for_games_despite_many_selected_positions(self):
        rows = dataset()[:2]
        rows[1]["actual"] = terms(pressure=50)
        a = loss_gradient(rows, [0.]*9)
        duplicated = [rows[0]] + [copy.deepcopy(rows[1]) for _ in range(4)]
        b = loss_gradient(duplicated, [0.]*9)
        self.assertAlmostEqual(a[0], b[0])
        for x, y in zip(a[1], b[1]): self.assertAlmostEqual(x, y)

    def test_two_examples_cannot_produce_parameters(self):
        result = fit(dataset()[:2])
        self.assertEqual(result["status"], "needs_data")
        self.assertIsNone(result["options"])

    def test_next_generation_starts_from_its_research_parent_not_formal_defaults(self):
        parent = dict(zip(OPTIONS, BASE)); parent["EvalSafety"] = 510
        report = fit(dataset(), parent)
        self.assertEqual(report["parent_options"], parent)
        self.assertGreaterEqual(report["options"]["EvalSafety"], 485)

    def test_holdout_regression_rejects_without_retuning(self):
        rows = dataset()
        for r in rows:
            if r["split"] == "heldout":
                r["actual"], r["research"] = r["research"], r["actual"]
        result = fit(rows)
        self.assertEqual(result["status"], "retain_parent")
        self.assertEqual(result["trials"], 1)

    def test_reject_leakage_clamping_and_duplicate_examples(self):
        for kind in ("game", "group", "duplicate", "clamp"):
            rows = dataset()
            if kind in ("game", "group"): rows[-1][kind] = rows[0][kind]
            elif kind == "duplicate": rows[-1]["case_id"] = rows[0]["case_id"]
            else: rows[0]["actual"]["clamp"] = 1
            with self.assertRaises(ValueError): fit(rows)


if __name__ == "__main__": unittest.main()
