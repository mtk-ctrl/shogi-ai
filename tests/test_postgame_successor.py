"""Frozen successor lineage gates. No GitHub dispatch or engine games."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".github/scripts"))
from prepare_structured_successor import prepare
from structured_execution import validate_execution
from tools.research.train_structured_value import PARENT
import selfplay_trial_transport as transport

class SuccessorLineage(unittest.TestCase):
    def setup_case(self, folder):
        parent_sha = "a"*64
        options = dict(transport.BASE, **PARENT, StructuredEval=True, StructuredScale=50)
        model = dict(features=4893, eligible=True, parent_model_sha256=parent_sha,
                     parent_scale=50, parent_options=dict(PARENT),
                     weights=[0]*4893, parent_weights=[0]*4893)
        model["weights"][4] = 2
        model["parent_weights"][4] = 7
        raw = (json.dumps(model, sort_keys=True)+"\n").encode()
        p = folder/"saved"
        (p/"next-model").mkdir(parents=True)
        (p/"next-model/model.json").write_bytes(raw)
        result = dict(research_parent_updated=True, next_selfplay_completed=True,
                      model_sha256=parent_sha, selected_scale=50,
                      next_model_sha256=hashlib.sha256(raw).hexdigest(),
                      research_parent=dict(engine_ref="b"*40, model_sha256=parent_sha,
                                           options=options),
                      next_publication=dict(release="records-2026-10-01",
                                            name="frozen-source.tgz"),
                      screens=[], confirmation_publication=dict(release="records-2026-10-01",
                                                                 name="confirmed.tgz"))
        (p/"result.json").write_text(json.dumps(result))
        prior = dict(used_seed_bases=[2080101901, 2081101901, 2082101901,
                     2085101901, 2090101901, 2106101901, 2108101901,
                     2110101901, 2113101901],
                     training_publications=[dict(release="records-2026-10-01", name="first-source.tgz")],
                     seeds=dict(screens=[2080101901, 2081101901, 2082101901],
                                confirmation=2085101901, next_source=2090101901))
        return p, model, result, prior

    def test_successor_fixes_exact_parent_identity_and_fresh_seeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p, model, result, old = self.setup_case(root)
            execution, actual = prepare(p,old,[], "structured-value-20261020-g2",
                         2120101901,root/"successor",transport.BASE,PARENT)
            self.assertEqual(execution["comparison_parent"]["model_sha256"], "a"*64)
            self.assertEqual(execution["comparison_parent"]["options"]["StructuredScale"],50)
            self.assertEqual(execution["training_publications"],[result["next_publication"]])
            self.assertEqual(execution["max_games"],1600)
            self.assertEqual(execution["seeds"]["next_source"],2132101901)
            self.assertEqual(execution["used_seed_bases"][-1],2113101901)
            self.assertTrue((root/"successor/structured_value_weights.h").exists())
            validate_execution(execution,actual,transport.BASE,PARENT)
            execution["comparison_parent"]["model_sha256"]="c"*64
            with self.assertRaises(ValueError):
                validate_execution(execution,actual,transport.BASE,PARENT)

    def test_rejects_unconfirmed_or_swapped_predecessor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p, model, result, old = self.setup_case(root)
            result["research_parent_updated"]=False
            (p/"result.json").write_text(json.dumps(result))
            with self.assertRaises(ValueError):
                prepare(p,old,[], "structured-value-20261020-g2",
                        2120101901,root/"bad",transport.BASE,PARENT)
            result["research_parent_updated"]=True
            result["model_sha256"]="d"*64
            (p/"result.json").write_text(json.dumps(result))
            with self.assertRaises(ValueError):
                prepare(p,old,[], "structured-value-20261020-g2",
                        2120101901,root/"bad2",transport.BASE,PARENT)

    def test_refuses_seed_collision_with_previous_route_experiments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p, model, result, old = self.setup_case(root)
            # 2,000,000 effective-seed separation must include the other routes.
            with self.assertRaises(ValueError):
                prepare(p,old,[], "structured-value-20261020-g2",
                        2113101901,root/"collision",transport.BASE,PARENT)

if __name__ == "__main__":
    unittest.main()
