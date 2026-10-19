"""Contracts for a contextual learner, not a nine-parameter adjustment."""
import json
from pathlib import Path
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]

class StructuredModelContract(unittest.TestCase):
    def test_frozen_model_is_supported_and_not_a_tiny_axis_vector(self):
        model=json.loads((ROOT/'research/structured-eval-20261019/model.json').read_text())
        self.assertEqual(model['features'],4893)
        self.assertEqual(sum(model['feature_families'].values())*3,4893)
        self.assertGreater(model['nonzero_coefficients'],1000)
        self.assertEqual(model['nonzero_coefficients'],sum(v!=0 for v in model['weights']))
        self.assertTrue(model['eligible'])
        self.assertGreaterEqual(model['baseline']['validation']['mixed_loss']-model['learned']['validation']['mixed_loss'],.002)

    def test_selected_scale_can_be_carried_exactly_to_a_new_parent(self):
        model=json.loads((ROOT/'research/structured-eval-20261019/model.json').read_text())
        q=np.asarray(model['weights'],dtype=np.int64);parent=np.asarray(model['parent_weights'],dtype=np.int64)
        rng=np.random.default_rng(2031101901)
        for scale in (50,100,150):
            scaled=q*scale
            self.assertTrue(np.all(scaled%100==0))
            carried=parent+scaled//100
            for _ in range(32):
                x=rng.integers(-100,101,size=4893,dtype=np.int64)
                old=np.dot(x,parent)*100+np.dot(x,q)*scale
                new=np.dot(x,carried)*100
                self.assertEqual(int(old),int(new))

    def test_actual_binary_checks_are_recorded(self):
        checks=json.loads((ROOT/'research/structured-eval-20261019/preflight.json').read_text())
        self.assertTrue(checks['disabled_exact'])
        self.assertTrue(checks['integer_evaluation_exact'])
        self.assertEqual(checks['feature_rotation_positions'],128)
        self.assertTrue(any(checks['candidates_passed']))
        for row in checks['speed']:
            self.assertTrue(all(o.get('structured_eval_calls',0)>0 for o in row['observations'][1:]))

if __name__=='__main__':unittest.main()
