import copy
import json
from pathlib import Path
import tempfile
import unittest

import shogi
from tools.research.postgame_knowledge import propose, validate_snapshot, preflight, stage, staged_options
from tools.research.postgame_progress import describe
from tools.research.postgame_spiral import prepare
from tools.research.postgame_cases import sha256
from tools.research.postgame_ranker import BASE, OPTIONS, digest
from tools.research.postgame_analyze import OPTIONS as ANALYSIS_OPTIONS
from tests.test_postgame_spiral import diagnosis
from tests.test_postgame_ranker import terms


def fixture(split='train'):
    board=shogi.Board()
    for move in ['7g7f','3c3d']:board.push_usi(move)
    base=('# position-knowledge-v1-active\n'+' '.join(board.sfen().split()[:3])+'\t2g2f\tfixture-base\t1\n').encode()
    params=dict(zip(OPTIONS,BASE))
    parent=dict(engine_ref='a'*40,knowledge_sha256=sha256(base),parameters_sha256=digest(params))
    row=diagnosis();row['case']['evidence_purpose']='synthetic_fixture'
    row['root_short']['requested_ms']=50;row['root_deep']['requested_ms']=500
    original=copy.deepcopy(row['root_deep']);original['bestmove']=row['case']['actual_move']
    # This wiring fixture deliberately uses exact synthetic research frames.
    # It is never research training or a real strength-improvement result.
    for i in range(100):
        report=prepare([row],lambda _:[original,copy.deepcopy(original)],lambda _:terms(),str(i),
                       parent_context=parent,parent_options=params,track_decisions=True)
        if report['case_decisions'][0]['split']==split:break
    else:raise AssertionError('fixture grouping unavailable')
    summary=dict(source_games=2,source_plies=100,selected_cases=1,routes=report['routes'],verification_pairs=1,seconds=0.)
    summary.update(evaluation_options=params,options=ANALYSIS_OPTIONS)
    report['progress']=describe(report,summary,[row],parent)
    return base,params,parent,row,report,original


def proposal():
    base,params,parent,row,report,original=fixture()
    data,manifest=propose(base,report,[row],parent,'synthetic-memory-fixture',lambda _:copy.deepcopy(original),'integration_smoke')
    return base,params,row,data,manifest


def fake_live(manifest,case,which,ms,depth,enabled):
    row=manifest['accepted'][0]
    target=case.get('expected_prefix',row['selected_move'])
    best=target if 'expected_prefix' in case or which=='candidate' and enabled else row['actual_move']
    return dict(status='recorded',kind='cp',bound='exact',value_stm=0,depth=depth or 4,
                bestmove=best,history_key=case.get('history_key'),pv_head_matches=True,
                research_decision_id=row['research_id'] if which=='candidate' and enabled and 'expected_prefix' not in case else None)


class KnowledgeTest(unittest.TestCase):
    def test_one_training_case_can_be_remembered_without_32_evaluation_pairs(self):
        base,params,parent,row,report,original=fixture()
        self.assertEqual(report['learning']['status'],'needs_data')
        candidate,m=propose(base,report,[row],parent,'synthetic-memory-fixture',lambda _:original,'integration_smoke')
        validate_snapshot(base,candidate,m)
        self.assertTrue(candidate.startswith(base))
        self.assertEqual((m['base_positions'],m['candidate_positions'],m['combined_positions']),(1,1,2))
        self.assertFalse(m['production_match_eligible']);self.assertFalse(m['formal_adoption'])

    def test_validation_and_heldout_cannot_become_remembered_moves(self):
        for split in ('validation','heldout'):
            base,_,parent,row,report,_=fixture(split)
            candidate,m=propose(base,report,[row],parent,'synthetic-memory-fixture',lambda _:self.fail('test-data probe'),'integration_smoke')
            self.assertIsNone(candidate);self.assertEqual(m['candidate_positions'],0)

    def test_solved_parent_and_unstable_choice_do_not_spawn_useless_snapshot(self):
        for moves,expected in ((['2g2f','2g2f'],'already_correct'),(['7g7f','2g2f'],'unstable_parent'),
                               (['5i5h','5i5h'],'parent_changed_to_uncompared_move')):
            base,_,parent,row,report,original=fixture();moves=iter(moves)
            def probe(_):return dict(original,bestmove=next(moves))
            candidate,m=propose(base,report,[row],parent,'synthetic-memory-fixture',probe,'integration_smoke')
            self.assertIsNone(candidate);self.assertEqual(m['rejected'][0]['reason'],expected)

    def test_forged_source_history_or_queue_is_rejected(self):
        for mutation in ('history','parent','split','row'):
            base,_,parent,row,report,original=fixture()
            if mutation=='history':report['progress']['work_items'][0]['case']['history_moves']=['7g7f']
            elif mutation=='parent':parent['engine_ref']='b'*40
            elif mutation=='split':report['case_decisions'][0]['split']='heldout'
            else:row['followup']['actual']['value_stm']=0
            with self.assertRaises(ValueError):propose(base,report,[row],parent,'synthetic-memory-fixture',lambda _:original,'integration_smoke')

    def test_incomplete_parent_observation_cannot_be_called_a_miss(self):
        base,_,parent,row,report,original=fixture();original['kind']='mate'
        with self.assertRaises(ValueError):propose(base,report,[row],parent,'synthetic-memory-fixture',lambda _:original,'integration_smoke')

    def test_synthetic_fixture_cannot_enter_real_research(self):
        base,_,parent,row,report,original=fixture()
        with self.assertRaisesRegex(ValueError,'synthetic'):propose(base,report,[row],parent,'no-fixture-as-research',lambda _:original,'research')

    def test_snapshot_preserves_all_base_bytes_and_rejects_tampering(self):
        base,_,_,candidate,m=proposal()
        for b,c,manifest in ((base+b'\n',candidate,m),(base,candidate+b'\n',m),
                             (base,candidate,dict(m,combined_positions=3))):
            with self.assertRaises(ValueError):validate_snapshot(b,c,manifest)

    def test_live_target_correction_provenance_and_disabled_equality_are_required(self):
        _,_,_,_,m=proposal()
        result=preflight(m,lambda *args:fake_live(m,*args))
        self.assertTrue(result['passed']);self.assertEqual(result['targeted_corrections'],1)
        self.assertEqual(result['candidate_knowledge_hits'],1)
        for failure in ('no-hit','already-correct','third-move','off-mismatch','slow','regression'):
            def probe(case,which,ms,depth,enabled):
                result=fake_live(m,case,which,ms,depth,enabled)
                if failure=='no-hit':result['research_decision_id']=None
                if failure=='already-correct' and which=='base' and enabled and 'expected_prefix' not in case:
                    result['bestmove']=m['accepted'][0]['selected_move']
                if failure=='third-move' and which=='base' and enabled and 'expected_prefix' not in case:
                    result['bestmove']='5i5h'
                if failure=='off-mismatch' and which=='candidate' and not enabled:result['value_stm']=99
                if failure=='slow' and which=='candidate' and depth is None:result['depth']=1
                if failure=='regression' and which=='candidate' and enabled and 'expected_prefix' in case:result['bestmove']='resign'
                return result
            self.assertFalse(preflight(m,probe)['passed'],failure)

    def test_separate_staging_delivers_candidate_only_to_A_and_preserves_parent(self):
        base,params,_,candidate,m=proposal();check=preflight(m,lambda *args:fake_live(m,*args))
        with tempfile.TemporaryDirectory() as td:
            directory=Path(td)/'stage';p=stage(base,candidate,m,check,directory,params)
            options=staged_options(directory,p)
            self.assertEqual((directory/'A.tsv').read_bytes(),candidate)
            self.assertEqual((directory/'B.tsv').read_bytes(),base)
            self.assertEqual(options['A']['EvalSafety'],options['B']['EvalSafety'])
            self.assertNotEqual(options['A']['PositionKnowledgeFile'],options['B']['PositionKnowledgeFile'])
            self.assertFalse(p['production_match_eligible']);self.assertFalse(p['match_dispatch_connected'])
            bad=copy.deepcopy(p);bad['common_options']['SearchThreads']=1
            with self.assertRaises(ValueError):staged_options(directory,bad)
            with self.assertRaises(FileExistsError):stage(base,candidate,m,check,directory,params)
            (directory/'A.tsv').write_bytes(base)
            with self.assertRaises(ValueError):staged_options(directory,p)

    def test_failed_preflight_cannot_be_staged(self):
        base,params,_,candidate,m=proposal();check=preflight(m,lambda *args:fake_live(m,*args));check['passed']=False
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):stage(base,candidate,m,check,Path(td)/'no-stage',params)

    def test_runtime_freezes_the_knowledge_policy_before_execution(self):
        from tools.research.postgame_knowledge import POLICY_KNOWLEDGE
        from tools.research.postgame_progress import POLICY_PROGRESS
        from tools.research.postgame_runtime import initialize
        from tests.test_postgame_runtime import plan
        p=plan();p['knowledge_policy']=POLICY_KNOWLEDGE
        with self.assertRaises(ValueError):initialize(p,dict(zip(OPTIONS,BASE)),'c'*64)
        p['progress_policy']=POLICY_PROGRESS
        self.assertEqual(initialize(p,dict(zip(OPTIONS,BASE)),'c'*64)['state']['plan']['knowledge_policy'],POLICY_KNOWLEDGE)
        p['knowledge_policy']=dict(POLICY_KNOWLEDGE,max_tasks=9)
        with self.assertRaises(ValueError):initialize(p,dict(zip(OPTIONS,BASE)),'c'*64)

    def test_conflicting_studies_of_one_position_are_not_arbitrarily_selected(self):
        from tools.research.postgame_cases import position_command
        base,params,parent,first,_,original=fixture()
        second=copy.deepcopy(first);second['case']['case_id']='b'*64;second['case']['source']['game_id']='second-fixture'
        second['research_move']='5i5h'
        for key in ('root_short','root_deep'):second[key]['bestmove']='5i5h'
        command=position_command(shogi.STARTING_SFEN,('5i5h',))
        second['followup']['research'].update(position_command=command,history_key=sha256(command.encode()))
        rows=[first,second]
        for i in range(100):
            report=prepare(rows,lambda _:[original,copy.deepcopy(original)],lambda _:terms(),str(i),
                           parent_context=parent,parent_options=params,track_decisions=True)
            if len(report['candidate_knowledge'])==2:break
        else:self.fail('training fixture unavailable')
        summary=dict(source_games=2,source_plies=100,selected_cases=2,routes=report['routes'],verification_pairs=2,seconds=0.)
        summary.update(evaluation_options=params,options=ANALYSIS_OPTIONS)
        report['progress']=describe(report,summary,rows,parent)
        data,m=propose(base,report,rows,parent,'synthetic-conflict',lambda _:self.fail('do not test/select a contradictory study'),'integration_smoke')
        self.assertIsNone(data)
        self.assertEqual([r['reason'] for r in m['rejected']],['conflicting_research_moves']*2)

    def test_research_cannot_silently_change_timing_or_parent_weights(self):
        for mutation in ('timing','evaluation'):
            base,_,parent,row,report,original=fixture()
            if mutation=='timing':row['root_short']['requested_ms']=500
            else:report['progress']['analysis']['evaluation_options']=dict(report['learning']['parent_options'],EvalSafety=481)
            with self.assertRaises(ValueError):propose(base,report,[row],parent,'synthetic-protocol-mismatch',lambda _:original,'integration_smoke')


if __name__=='__main__':unittest.main()
