"""Synthetic wiring evidence only; never real strength/training evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import shogi
from tools.research import postgame_horizon as h
from tools.research.postgame_cases import position_command,sha256
from tools.research.postgame_ranker import digest
from tools.research.postgame_knowledge import validate_snapshot,preflight,stage
from tools.research.postgame_runtime import initialize,POLICY_KNOWLEDGE_EXECUTION
from tests.test_postgame_knowledge import fixture,fake_live
from tests.test_postgame_runtime import plan,pub


def inputs():
    base,params,parent,row,prep,_=fixture()
    row['route']='search_horizon_candidate'
    # The synthetic tag is removed only to test this pure selector's mechanics;
    # this fixture is never dispatched, saved as real evidence or strength data.
    row['case'].pop('evidence_purpose')
    row['root_short']['bestmove']=row['case']['actual_move']
    return base,params,parent,row,prep


def fake_probe(root,current='5i5h',mutation=None):
    def probe(case,ms,depth=None,move=None):
        history=tuple(case['history_moves'])+((move,) if move else ())
        command=position_command(case['start_sfen'],history)
        result=dict(status='recorded',kind='cp',bound='exact',value_stm=300 if move==current else 0,
            depth=depth or 4,bestmove=(current if ms==200 else root['target']),pv_head_matches=True,
            requested_ms=ms,requested_depth=depth,position_command=command,history_key=sha256(command.encode()))
        if mutation:mutation(result,ms,depth,move)
        return result
    return probe


def proposal(mutation=None):
    base,params,parent,row,prep=inputs();frozen=h.selection(prep,[row],parent)
    observed=[h.evaluate(r,fake_probe(r,mutation=mutation)) for r in frozen['roots']]
    candidate,manifest=h.propose(base,frozen,observed,'synthetic-horizon-test')
    return base,params,prep,[row],frozen,observed,candidate,manifest


class HorizonTest(unittest.TestCase):
    def test_deeper_move_can_be_remembered_despite_short_disagreement_and_third_parent_move(self):
        base,_,_,_,_,observed,candidate,manifest=proposal()
        self.assertEqual(observed[0]['status'],'validated_horizon_memory')
        evidence=manifest['accepted'][0]
        self.assertEqual(evidence['compared_parent_move'],'5i5h')
        self.assertNotEqual(evidence['actual_move'],evidence['compared_parent_move'])
        validate_snapshot(base,candidate,manifest)
        self.assertFalse(manifest['formal_adoption'])
        self.assertEqual(manifest['schema'],'postgame-horizon-proposal-v1')

    def test_source_aliases_deduplicate_without_fabricating_independent_groups(self):
        base,_,parent,row,prep=inputs();second=copy.deepcopy(row)
        second['case']['case_id']='f'*64;prep['case_decisions'].append(dict(prep['case_decisions'][0],case_id='f'*64))
        frozen=h.selection(prep,[row,second],parent)
        self.assertEqual(len(frozen['roots']),1);self.assertEqual(len(frozen['roots'][0]['aliases']),2)
        self.assertEqual(frozen['split_registry_sha256'],digest(prep['split_registry']))

    def test_test_exposure_or_synthetic_inputs_cannot_enter_route(self):
        for kind in ('heldout','validation','quarantine','consumed','synthetic'):
            _,_,parent,row,prep=inputs()
            if kind=='synthetic':row['case']['evidence_purpose']='synthetic_fixture'
            else:
                for entry in prep['split_registry'].values():
                    if kind=='consumed':entry['heldout_consumed']=True
                    else:entry['split']=kind
            if kind=='synthetic':
                with self.assertRaisesRegex(ValueError,'synthetic'):h.selection(prep,[row],parent)
            else:self.assertEqual(h.selection(prep,[row],parent)['roots'],[])

    def test_current_parent_already_correct_generates_no_useless_memory(self):
        base,_,parent,row,prep=inputs();frozen=h.selection(prep,[row],parent);root=frozen['roots'][0]
        observed=h.evaluate(root,fake_probe(root,current=root['target']))
        candidate,manifest=h.propose(base,frozen,[observed],'synthetic-horizon-test')
        self.assertIsNone(candidate);self.assertEqual(manifest['rejected'][0]['reason'],'already_correct')

    def test_incomplete_mate_or_unstable_deeper_score_never_passes(self):
        for kind in ('missing','mate','bound','head','wrong-target','shallow','small-gap'):
            def mutate(result,ms,depth,move):
                if kind=='missing' and ms==2000:result['status']='missing'
                if kind=='mate' and ms==2000:result['kind']='mate'
                if kind=='bound' and ms==2000:result['bound']='lowerbound'
                if kind=='head' and ms==2000:result['pv_head_matches']=False
                if kind=='wrong-target' and ms==2000:result['bestmove']='7g7f'
                if kind=='shallow' and ms==500 and move:result['depth']=1
                if kind=='small-gap' and depth:result['value_stm']=0
            self.assertIsNone(proposal(mutate)[-2],kind)

    def test_probe_history_timing_and_saved_decision_tampering_are_rejected(self):
        for kind in ('history','timing'):
            def mutate(result,ms,depth,move):
                if ms==2000:result['history_key' if kind=='history' else 'requested_ms']='forged'
            with self.assertRaises(ValueError):proposal(mutate)
        base,_,_,_,frozen,observed,_,_=proposal();observed[0]['status']='already_correct'
        with self.assertRaises(ValueError):h.propose(base,frozen,observed,'synthetic-horizon-test')

    def test_knowledge_preflight_checks_actual_compared_parent_and_direct_use(self):
        base,params,_,_,_,_,candidate,manifest=proposal()
        def probe(*args):
            result=fake_live(manifest,*args)
            case,which,ms,depth,enabled=args
            if which=='base' and enabled and 'expected_prefix' not in case:result['bestmove']='5i5h'
            return result
        check=preflight(manifest,probe)
        self.assertTrue(check['passed']);self.assertEqual(check['targeted_corrections'],1)
        with tempfile.TemporaryDirectory() as td:
            package=stage(base,candidate,manifest,check,Path(td)/'staged',params)
            self.assertEqual(package['snapshots']['A']['positions'],2)
            self.assertEqual(package['snapshots']['B']['positions'],1)

    def test_saved_replay_requires_no_engine_or_additional_searches(self):
        base,_,prep,diagnosis,frozen,observed,candidate,manifest=proposal()
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            for name,value in (('selection',frozen),('observations',observed)):h.dump(p/(name+'.json'),value)
            (p/'candidate.tsv').write_bytes(candidate)
            replay=h.verify_saved(p,base,prep,diagnosis,frozen,dict(manifest=manifest))
            self.assertEqual(replay['new_engine_runs'],0)
            observed[0]['fixed'][0]['comparison']['improvement_cp']=9999;h.dump(p/'observations.json',observed)
            with self.assertRaises(ValueError):h.verify_saved(p,base,prep,diagnosis,frozen,dict(manifest=manifest))

    def test_only_explicit_bounded_saved_source_cycle_uses_new_policy(self):
        _,params,_,_,_,_,_,_=proposal()
        # Use actual selector for parent/selection identity.
        _,_,_,_,frozen,_,_,_=proposal();parent=frozen['parent']
        p=plan(1,300);p.update(source_games=100,candidate_kind='knowledge',purpose='bounded_horizon_return',parent=parent,
            knowledge_builder='horizon',generate_initial_source=False,knowledge_policy=h.POLICY_HORIZON,
            knowledge_execution_policy=POLICY_KNOWLEDGE_EXECUTION,horizon_selection=frozen,
            source_publication=pub(1),horizon_input_publication=pub(2))
        env=initialize(p,params,'c'*64)
        self.assertEqual(env['state']['stage'],'prepare');self.assertEqual(env['source_publication'],pub(1))
        for mutation in ({'max_generations':2},{'max_new_games':600},{'generate_initial_source':True},
                         {'knowledge_builder':None},{'purpose':'integration_smoke'}):
            with self.assertRaises(ValueError):initialize(dict(p,**mutation),params,'c'*64)
