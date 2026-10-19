"""Contracts for a contextual learner, not a nine-parameter adjustment."""
import json
from pathlib import Path
import unittest
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.github/scripts'))
from structured_execution import validate_execution,comparison_request

class StructuredModelContract(unittest.TestCase):
    def test_frozen_model_is_supported_and_not_a_tiny_axis_vector(self):
        model=json.loads((ROOT/'research/structured-eval-20261019/model.json').read_text())
        self.assertEqual(model['features'],4893)
        self.assertEqual(sum(model['feature_families'].values())*3,4893)
        self.assertGreater(sum(p!=0 or d!=0 for p,d in zip(model['parent_weights'],model['weights'])),1000)
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

    def test_fine_grained_parent_is_retained_for_next_generation_comparison(self):
        base=dict(SearchThreads=2);core=dict(EvalSafety=540)
        model=dict(parent_model_sha256='a'*64,parent_scale=50)
        execution=dict(schema='structured-cycle-execution-v1',cycle_id='next-fine-round',max_games=1600,
            comparison_parent=dict(engine_ref='b'*40,model_sha256='a'*64,
                options=dict(base,**core,StructuredEval=True,StructuredScale=50)),
            seeds=dict(screens=[10000000,20000000,30000000],confirmation=40000000,next_source=50000000),used_seed_bases=[],
            training_publications=[dict(name='declared-own-source')])
        parent,seeds=validate_execution(execution,model,base,core)
        request=comparison_request('c'*40,parent,base,core,100,100,19,seeds['screens'][0])
        self.assertEqual(request['ref_b'],'b'*40)
        baseline=json.loads(request['options_b'])
        self.assertTrue(baseline['StructuredEval'])
        self.assertEqual(baseline['StructuredScale'],50)
        execution['comparison_parent']['options'].pop('StructuredEval')
        with self.assertRaises(ValueError):validate_execution(execution,model,base,core)

    def test_used_seeds_are_not_reset_for_a_new_generation(self):
        base={};core={};model=dict(parent_model_sha256=None)
        execution=dict(schema='structured-cycle-execution-v1',cycle_id='fresh-round',max_games=1600,
            comparison_parent=dict(engine_ref='b'*40,model_sha256=None,options={}),
            seeds=dict(screens=[10000000,20000000,30000000],confirmation=40000000,next_source=50000000),used_seed_bases=[40000000],
            training_publications=[dict(name='declared-own-source')])
        with self.assertRaises(ValueError):validate_execution(execution,model,base,core)

    def test_a_new_base_cannot_reuse_an_old_shards_seed(self):
        execution=json.loads((ROOT/'research/structured-eval-20261019/EXECUTION.json').read_text())
        model=json.loads((ROOT/'research/structured-eval-20261019/model.json').read_text())
        parent=execution['comparison_parent'];all_options=parent['options']
        core={k:v for k,v in all_options.items() if k.startswith('Eval')};base={k:v for k,v in all_options.items() if k not in core}
        execution['used_seed_bases'].append(execution['seeds']['screens'][0]+100000)
        with self.assertRaises(ValueError):validate_execution(execution,model,base,core)

if __name__=='__main__':unittest.main()
