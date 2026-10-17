import base64
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('spiral_inspection_test',ROOT/'.github/scripts/inspect_postgame_spiral.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
from tests.test_postgame_cycle import plan
from tools.research import postgame_cycle as core
from tools.research.postgame_ranker import digest


class InspectionTest(unittest.TestCase):
    def test_incomplete_cycle_cannot_be_reported_complete(self):
        with self.assertRaises(ValueError):m.inspect(object(),dict(state={'stage':'screen'}))

    def test_receipts_are_replayed_and_altered_saved_result_is_rejected(self):
        p=plan(games=0);p['algorithm_sha256']='fixed-test-algorithm'
        state=core.start(p);state=core.request(state,dict(parent=p['parent']),0)
        binding=state['pending']['payload'];op=state['pending']['operation_id']
        pub=dict(sha256='e'*64,bytes=100,readback_verified=True,api_digest_verified=True)
        prep=dict(learning=dict(status='needs_data',options=None,parameter_updates=0),candidate_knowledge=[],
                  split_registry={},example_bank={},examples=[],bank_pairs_reused=0)
        evidence=dict(input_sha256=state['pending']['input_sha256'],parent=state['parent'],publication=pub,preparation=prep)
        state=core.finish(state,op,evidence)
        env=dict(state=state,blocked=None,plan_ref='a'*40,trajectory_index_sha256=digest([]))
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            (folder/'binding.json').write_text(json.dumps(binding))
            (folder/'stage-result.json').write_text(json.dumps(dict(preparation=prep,analysis_summary={})))
            (folder/'preparation.json').write_text(json.dumps(prep))
            class ReadOnly:
                repo='mtk-ctrl/shogi-ai'
                def reference_index(self,plan):return []
                def unpack(self,pub):return folder
            # Backend has no dispatch/upload/analysis methods at all.
            response=dict(content=base64.b64encode(json.dumps(p).encode()).decode())
            with patch.object(m,'api',return_value=response),patch.object(m,'algorithm_hash',return_value='fixed-test-algorithm'):
                r=m.inspect(ReadOnly(),env)
                self.assertTrue(r['controller_ledger_replayed']);self.assertEqual(r['used_games'],0)
                altered=copy.deepcopy(prep);altered['learning']['parameter_updates']=1
                (folder/'stage-result.json').write_text(json.dumps(dict(preparation=altered,analysis_summary={})))
                (folder/'preparation.json').write_text(json.dumps(altered))
                with self.assertRaisesRegex(ValueError,'evidence hash'):m.inspect(ReadOnly(),env)


if __name__=='__main__':unittest.main()
