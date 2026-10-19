"""Protect parent inheritance, evidence gates, budgets and duplicate dispatch."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.github/scripts'))
import run_selfplay_value_loop as loop
import run_selfplay_value as entry
from tools.research.postgame_ranker import OPTIONS,BASE

PARENT=dict(zip(OPTIONS,BASE))

def plan():
    return dict(schema='selfplay-value-loop-v1',rounds=2,max_games=3200,
        engine_ref=loop.transport.BASE_REF,formal_adoption=False,cycle_id='two-round-fixture',
        seeds=[[2070101901,2071101901,2072101901,2074101901,2076101901],
               [2080101901,2081101901,2082101901,2084101901,2086101901]])

class Tests(unittest.TestCase):
    def test_repair_launcher_only_resumes_an_inactive_failed_controller(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'.github').mkdir()
            request=dict(candidate_ref='a'*40,request_id='two-round-fixture',value_loop=True,repair=True)
            (root/'.github/selfplay-value-request.json').write_text(json.dumps(request))
            for status,conclusion,allowed in [('in_progress',None,False),('completed','success',False),('completed','failure',True)]:
                prior=dict(id=123,display_title='Spiral two-round-fixture',status=status,conclusion=conclusion)
                with patch.object(entry,'ROOT',root),patch.object(entry,'api',side_effect=[dict(workflow_runs=[prior]),dict(workflow_run_id=456)]) as api,patch.dict(os.environ,GITHUB_REF_NAME='research/value-learning-20261018'):
                    if allowed:
                        entry.launch();self.assertEqual(api.call_args.args[1]['inputs']['repair'],'true')
                    else:
                        with self.assertRaisesRegex(ValueError,'existing body'):entry.launch()
                        self.assertEqual(api.call_count,1)
    def test_model_tolerance_never_changes_integer_candidates_or_input_hash(self):
        original=dict(loss=.7201624438582374,candidates=[dict(weight=540)],samples_sha256='abc')
        repeated=dict(loss=.7201624438582372,candidates=[dict(weight=540)],samples_sha256='abc')
        self.assertTrue(loop.same_model(original,repeated))
        repeated['candidates'][0]['weight']=541
        self.assertFalse(loop.same_model(original,repeated))
        repeated=copy.deepcopy(original);repeated['samples_sha256']='def'
        self.assertFalse(loop.same_model(original,repeated))
    def test_comparison_inherits_current_parent_on_both_routes(self):
        parent=dict(PARENT,EvalSafety=540);candidate=dict(parent,EvalSafety=574)
        request=loop.requests(parent,candidate,1000,19,2074101901)
        self.assertEqual(json.loads(request['options_b'])['EvalSafety'],540)
        self.assertEqual(json.loads(request['options_a'])['EvalSafety'],574)
        source=loop.requests(parent,candidate,300,19,2076101901,new_parent=True)
        self.assertEqual(source['options_a'],source['options_b'])

    def test_tie_selects_smaller_change_and_both_intervals_are_required(self):
        candidates=[dict(candidate=dict(fraction=f,options=PARENT),report=dict(raw=dict(score=.52))) for f in (1,.5,.25)]
        selected,promoted=loop.decide(candidates,dict(raw=dict(lower=.51),unique=dict(lower=.5)))
        self.assertEqual(selected['fraction'],.25);self.assertFalse(promoted)
        self.assertTrue(loop.decide(candidates,dict(raw=dict(lower=.51),unique=dict(lower=.50001)))[1])
        self.assertEqual(loop.decide([]),(None,False))

    def test_fixed_budget_and_distinct_signed_integer_seeds(self):
        loop.validate_plan(plan())
        for key,value in [('rounds',3),('max_games',3201),('formal_adoption',True)]:
            p=plan();p[key]=value
            with self.assertRaises(ValueError):loop.validate_plan(p)
        p=plan();p['seeds'][1][0]=p['seeds'][0][0]
        with self.assertRaises(ValueError):loop.validate_plan(p)

    def test_missing_dispatch_id_never_redelivers(self):
        l=loop.Loop(plan(),None);l.guard=lambda:None
        l.state=dict(operations={'r1-screen-25':dict(status='intent_saved')})
        with patch.object(loop,'api') as api:
            with self.assertRaisesRegex(ValueError,'no response ID'):
                l.match('r1-screen-25',PARENT,PARENT,100,2070101901)
            api.assert_not_called()

    def test_checkpoint_revision_collision_never_overwrites(self):
        l=loop.Loop(plan(),None);l.state=dict(revision=2)
        l.latest=lambda:dict(revision=3)
        with self.assertRaisesRegex(ValueError,'collision'):l.checkpoint('anything')

    def test_completed_operation_is_read_back_without_dispatch(self):
        candidate=dict(PARENT,EvalSafety=540);request=loop.requests(PARENT,candidate,100,19,2070101901)
        class Backend:
            def unpack(self,p):return Path('verified-publication')
        l=loop.Loop(plan(),Backend());l.guard=lambda:None
        l.state=dict(operations={'r1-screen-25':dict(run_id=123,request=request,status='complete',
            publication=dict(sha256='saved'),report=dict(raw=dict(score=.51)))})
        with patch.object(loop,'api') as api:
            report,folder=l.match('r1-screen-25',PARENT,candidate,100,2070101901)
            self.assertEqual(report['raw']['score'],.51);api.assert_not_called()
        with self.assertRaisesRegex(ValueError,'changed frozen parent'):
            l.match('r1-screen-25',dict(PARENT,EvalSafety=900),candidate,100,2070101901)

    def test_preflight_uses_learned_parent_instead_of_formal_defaults(self):
        parent=dict(PARENT,EvalSafety=540);candidates=[dict(options=dict(parent,EvalSafety=550+i)) for i in range(3)]
        calls=[]
        def probe(binary,sfen,extra_options):
            calls.append(extra_options);return dict(move='5e5c',depth=3)
        case=dict(case_id='capture',start_sfen='unused',expected_prefix='5e5c')
        rows=[dict(sfen='unused',game_hash=str(i),ply=20) for i in range(16)]
        with patch.object(loop,'probe_module') as module,patch.object(loop,'tactical_cases',return_value=[case]):
            module.return_value.probe=probe
            result=loop.candidate_preflight('binary',rows,parent,candidates)
        self.assertTrue(all(result['candidates_passed']))
        self.assertTrue(all(calls[i]==parent for i in range(0,len(calls),4)))

    def test_two_rounds_promote_inherit_and_stop_at_budget(self):
        self.run_two_rounds(True)

    def test_two_failed_confirmations_keep_parent_and_skip_final_source(self):
        self.run_two_rounds(False)

    def run_two_rounds(self,passed):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            def model(parent):
                return dict(base_options=parent,eligible=True,candidates=[dict(fraction=f,
                    options=dict(parent,EvalSafety=parent['EvalSafety']+int(40*f))) for f in (.25,.5,1.)])
            initial=dict(research_parent_updated=True,next_selfplay_completed=True,selected=dict(options=PARENT),
                next_learning=model(PARENT),next_publication=dict(sha256='source'))
            (root/'result.json').write_text(json.dumps(initial))
            (root/'selected-actual-positions.jsonl').write_text('\n'.join(json.dumps(dict(split='train')) for _ in range(16)))
            class Backend:
                run_id=987
                def unpack(self,pub):return root
                def bytes(self,pub):return b'verified'
            class Trial(loop.Loop):
                def latest(self):return None
                def guard(self):pass
                def checkpoint(self,phase):self.state['phase']=phase
                def package(self,label,files):return dict(sha256=label)
                def binary(self,source):return 'unused'
                def learning(self,label,source,parent,initial_model=None):return dict(sha256=label),model(parent)
                def match(self,label,parent,candidate,games,seed,new_parent=False):
                    calls.append(dict(label=label,parent=copy.deepcopy(parent),candidate=copy.deepcopy(candidate),games=games))
                    self.state['used_games']+=games
                    report=dict(raw=dict(score=.6,lower=.51 if passed else .49),unique=dict(lower=.51 if passed else .49))
                    self.state['operations'][label]=dict(status='complete',report=report,publication=dict(sha256=label))
                    return report,root
            p=plan();p['initial_result']=dict(sha256='initial');calls=[]
            l=Trial(p,Backend());l.root=root
            with patch.object(loop,'candidate_preflight',return_value=dict(candidates_passed=[True]*3)),patch.dict(os.environ,PLAN_REF='frozen'):
                l.run()
            self.assertEqual(l.state['phase'],'complete');self.assertEqual(len(l.state['rounds']),2)
            self.assertEqual(l.state['used_games'],3200 if passed else 2900)
            self.assertEqual(l.state['result']['parent_updates'],2 if passed else 0)
            round2=next(c for c in calls if c['label']=='r2-screen-25')
            self.assertEqual(round2['parent']['EvalSafety'],PARENT['EvalSafety']+10 if passed else PARENT['EvalSafety'])
            self.assertEqual(any(c['label']=='r2-next-source' for c in calls),passed)
            self.assertFalse(any(c['label'].startswith('r3-') for c in calls))

if __name__=='__main__':unittest.main()
