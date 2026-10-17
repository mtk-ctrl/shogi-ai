import importlib.util
from pathlib import Path
import tempfile
import tarfile
import io
import os
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('spiral_backend_test',ROOT/'.github/scripts/run_postgame_spiral.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class BackendTest(unittest.TestCase):
    def test_tar_rejects_parent_paths_and_symlinks(self):
        for name,kind in (('../escape',tarfile.REGTYPE),('link',tarfile.SYMTYPE)):
            with tempfile.TemporaryDirectory() as td:
                p=Path(td)/'bad.tgz'
                with tarfile.open(p,'w:gz') as t:
                    i=tarfile.TarInfo(name);i.type=kind;i.size=0;i.linkname='/etc/passwd';t.addfile(i,io.BytesIO())
                with self.assertRaises(ValueError):m.safe_extract(p,Path(td)/'out')

    def test_dispatch_captures_exact_run_id_and_keeps_existing_workflow(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,GITHUB_RUN_ID='123'):
            b=m.Backend('mtk-ctrl/shogi-ai',td)
            b.active={'state':{'parent':{'knowledge_sha256':m.sha256(b'knowledge')}}}
            req=dict(ref_a='a'*40,ref_b='a'*40,games=2,shards=2,go_command='go movetime 200',max_plies=300,seed=1000,
                     options_a='{"PositionKnowledge":true,"EvalSafety":481}',options_b='{"PositionKnowledge":true,"EvalSafety":480}')
            responses=[{'content':__import__('base64').b64encode(b'knowledge').decode()},{'workflow_run_id':456}]
            with patch.object(m,'api',side_effect=responses) as call:
                self.assertEqual(b.dispatch(req),456)
                endpoint,payload=call.call_args.args
                self.assertTrue(endpoint.endswith('/engine-match.yml/dispatches'))
                self.assertTrue(payload['return_run_details']);self.assertEqual(payload['inputs']['games'],'2')
                self.assertNotIn('request_id',payload['inputs'])

    def test_no_cross_repository_or_unenrolled_body(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,GITHUB_RUN_ID='123'):
            with self.assertRaises(ValueError):m.Backend('elsewhere/repo',td)
            b=m.Backend('mtk-ctrl/shogi-ai',td)
            with patch.object(m,'api',return_value=dict(event='pull_request',path='.github/workflows/engine-match.yml')):
                with self.assertRaises(ValueError):b.match_status(456)

    def test_cli_wait_does_not_dispatch_or_cancel_a_run(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,GITHUB_RUN_ID='123'):
            b=m.Backend('mtk-ctrl/shogi-ai',td)
            with patch.object(m.subprocess,'run') as run:
                b.wait(dict(dispatch={'body_run':456}))
                self.assertEqual(run.call_args.args[0],['gh','run','watch','456','--repo','mtk-ctrl/shogi-ai','--interval','60'])

    def test_original_runtime_statistics_preserve_missing_fields_and_reject_missing_ponder(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'shard-0.json'
            row=dict(games=1,ponder={side:dict(hits=2,misses=3) for side in ('A','B')})
            p.write_text(json.dumps(row))
            observed=m.runtime_statistics([p])[0]
            self.assertEqual(observed['ponder'],row['ponder'])
            self.assertIsNone(observed['timing_ms'])
            self.assertIsNone(observed['search'])
            self.assertNotIn('details',observed)
            self.assertEqual(observed['source_sha256'],m.sha256(p.read_bytes()))
            row.pop('ponder');p.write_text(json.dumps(row))
            with self.assertRaises(ValueError):m.runtime_statistics([p])

    def test_new_explicit_cycle_carries_completed_parent_bank_and_exposure_index(self):
        import copy
        from tools.research.postgame_ranker import digest
        parent=dict(engine_ref='a'*40,knowledge_sha256='b'*64,parameters_sha256='c'*64)
        old=dict(state=dict(stage='complete',formal_adoption=False,parent=parent,
                           plan=dict(cycle_id='old',algorithm_sha256='same',seeds=[dict(source=1,screen=2,confirm=3)])),
                 formal_adoption=False,blocked=None,parent_options={'fixed':'fixture'},preparation_publication={'name':'preserved-bank'},
                 prior_signatures=['trajectory'],trajectory_index_sha256=digest(['trajectory']))
        new=dict(state=dict(plan=dict(parent=parent,algorithm_sha256='same',seeds=[dict(source=4,screen=5,confirm=6)])),
                 parent_options={'fixed':'fixture'})
        inherited=m.inherit_predecessor(copy.deepcopy(new),old)
        self.assertEqual(inherited['preparation_publication'],old['preparation_publication'])
        self.assertEqual(inherited['prior_signatures'],old['prior_signatures'])
        for kind in ('parent','seeds','unfinished','algorithm'):
            bad=copy.deepcopy(old)
            if kind=='parent':bad['parent_options']={'reset':'fixture'}
            elif kind=='seeds':bad['state']['plan']['seeds'][0]['source']=4
            elif kind=='unfinished':bad['state']['stage']='screen'
            else:bad['state']['plan']['algorithm_sha256']='changed'
            with self.assertRaises(ValueError,msg=kind):m.inherit_predecessor(copy.deepcopy(new),bad)

    def test_controller_fingerprint_binds_learning_and_executor_code(self):
        value=m.code_hash();self.assertRegex(value,'^[0-9a-f]{64}$')

    def test_new_explicit_cycle_cannot_reset_stagnation_and_research_queue(self):
        from tools.research.postgame_progress import POLICY_PROGRESS
        from tools.research.postgame_ranker import digest
        parent=dict(engine_ref='a'*40,knowledge_sha256='b'*64,parameters_sha256='c'*64)
        previous=dict(state=dict(stage='complete',formal_adoption=False,parent=parent,
                                progress_history=[{'preserved':'history'}],research_followup={'preserved':'queue'},
                                plan=dict(algorithm_sha256='same',progress_policy=POLICY_PROGRESS,
                                          cycle_id='old',seeds=[dict(source=1,screen=2,confirm=3)])),
                      blocked=None,formal_adoption=False,parent_options={},preparation_publication={},
                      prior_signatures=[],trajectory_index_sha256=digest([]))
        new=dict(state=dict(plan=dict(parent=parent,algorithm_sha256='same',progress_policy=POLICY_PROGRESS,
                                     seeds=[dict(source=4,screen=5,confirm=6)])),parent_options={})
        result=m.inherit_predecessor(new,previous)
        self.assertEqual(result['state']['progress_history'],previous['state']['progress_history'])
        self.assertEqual(result['state']['research_followup'],previous['state']['research_followup'])


if __name__=='__main__':unittest.main()
