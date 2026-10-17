import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import shogi
from tools.research.postgame_practice import (POLICY_PRACTICE,create_plan,verify_plan,play_branch,
    validate_game,replay_prefix,learning_inputs,dump,run,verify_saved)
from tools.research.postgame_cases import VerifiedGame,make_case,position_command,sha256
from tools.research.postgame_ranker import digest,BASE,OPTIONS
from tests.test_postgame_followup import fixture
from tests.test_postgame_progress import PARENT


def source_and_root(prefix=()):
    board=shogi.Board();rows=[]
    for i,t in enumerate((*prefix,'7g7f'),1):
        board.push_usi(t);rows.append(dict(ply=i,move=t,search={}))
    source=VerifiedGame(dict(a_black=True,moves=rows,plies=len(rows),game_id='g',winner=None,
                            reason='move_limit',final_sfen=board.sfen()),{},shogi.STARTING_SFEN,'unresolved','a'*64,'b'*64,1)
    case=make_case(source,len(rows));task=dict(task_id='c'*64,parent=PARENT,split='train',case=case,priority=3)
    root=dict(practice_id=digest(dict(parent=PARENT,task_id=task['task_id'],policy=POLICY_PRACTICE)),task=task,
              actual_move='7g7f',alternative_move='2g2f',lineage=dict(group='old-train',split='train',heldout_consumed=False))
    return source,root


def observation(case,history,ms):
    board=shogi.Board(case['start_sfen'])
    for t in history:board.push_usi(t)
    token=next(iter(board.legal_moves)).usi();cmd=position_command(case['start_sfen'],history)
    return dict(bestmove=token,position_command=cmd,history_key=sha256(cmd.encode()),requested_ms=ms,requested_depth=None,
                elapsed_ms=ms,status='recorded',kind='cp',bound='exact',pv_head_matches=True,value_stm=10,depth=2)


class PracticeTest(unittest.TestCase):
    def test_training_queue_only_frozen_policy_and_completion_skip(self):
        p,row=fixture();p['progress']['analysis']['analyzer_binary_sha256']='a'*64
        plan=create_plan([(p,[row])],PARENT,1000);self.assertEqual(len(plan['roots']),1);verify_plan(plan)
        done=[plan['roots'][0]['practice_id']]
        self.assertEqual(create_plan([(p,[row])],PARENT,1000,done)['roots'],[])
        for split in ('validation','heldout'):
            p,row=fixture(split);p['progress']['analysis']['analyzer_binary_sha256']='a'*64
            self.assertEqual(create_plan([(p,[row])],PARENT,1000)['roots'],[])
        changed=copy.deepcopy(plan);changed['policy']['max_new_plies']+=1
        with self.assertRaises(ValueError):verify_plan(changed)
        changed=copy.deepcopy(plan);changed['roots'][0]['lineage']['split']='heldout'
        with self.assertRaises(ValueError):verify_plan(changed)

    def test_full_history_forced_move_no_score_and_unresolved_limit(self):
        # A reversible legal prefix preserves all history without altering the
        # black pawn choices used in the test root.
        source,root=source_and_root(('5i6h','5a6b','6h5i','6b5a'));calls=[]
        def probe(c,h,ms):calls.append((h,ms));return observation(c,h,ms)
        game,info=play_branch(root,POLICY_PRACTICE['scenarios'][1],'alternative',source,probe)
        self.assertEqual(calls[0][0],tuple(root['task']['case']['history_moves'])+('2g2f',))
        self.assertEqual([x[1] for x in calls[:2]],[200,50])
        self.assertEqual(info['new_plies'],16);self.assertEqual(game['reason'],'move_limit')
        self.assertEqual(validate_game(game,info,root,POLICY_PRACTICE['scenarios'][1],source),'unresolved')
        self.assertNotIn('score_cp_stm',game['moves'][4]['search'])
        bad=copy.deepcopy(game);bad['moves'][4]['search']['score_cp_stm']=0
        with self.assertRaises(ValueError):validate_game(bad,info,root,POLICY_PRACTICE['scenarios'][1],source)

    def test_history_terminal_and_illegal_continuation_are_rejected(self):
        source,root=source_and_root();case=copy.deepcopy(root['task']['case'])
        case['history_moves']=['5i6h','5a6b','6h5i','6b5a']*3
        with self.assertRaisesRegex(ValueError,'terminal'):replay_prefix(case)
        def illegal(c,h,ms):return dict(observation(c,h,ms),bestmove='1a1b')
        with self.assertRaises(ValueError):play_branch(root,POLICY_PRACTICE['scenarios'][0],'actual',source,illegal)
        def wrong(c,h,ms):return dict(observation(c,h,ms),history_key='bad')
        with self.assertRaises(ValueError):play_branch(root,POLICY_PRACTICE['scenarios'][0],'actual',source,wrong)

    def test_unverified_resignation_stays_unresolved(self):
        source,root=source_and_root()
        def resign(c,h,ms):return dict(observation(c,h,ms),bestmove='resign')
        game,info=play_branch(root,POLICY_PRACTICE['scenarios'][0],'actual',source,resign)
        self.assertIsNone(game['winner']);self.assertEqual(game['reason'],'practice_resign_unverified')
        self.assertEqual(validate_game(game,info,root,POLICY_PRACTICE['scenarios'][0],source),'unresolved')
        game['winner']='A'
        with self.assertRaises(ValueError):validate_game(game,info,root,POLICY_PRACTICE['scenarios'][0],source)

    def test_forged_branch_prefix_and_winner_are_rejected(self):
        source,root=source_and_root();scenario=POLICY_PRACTICE['scenarios'][0]
        game,info=play_branch(root,scenario,'actual',source,observation)
        for field in ('branch','scenario','lineage'):
            bad=copy.deepcopy(info);bad[field]={'branch':'alternative','scenario':{},'lineage':{}}[field]
            with self.assertRaises(ValueError):validate_game(game,bad,root,scenario,source)
        bad=copy.deepcopy(game);bad['winner']='A'
        with self.assertRaises(ValueError):validate_game(bad,info,root,scenario,source)

    def test_all_descendants_keep_source_group_and_test_contact_quarantines(self):
        from tools.records.archive_played_moves import archive
        from tools.research.postgame_spiral import leakage_keys
        source,root=source_and_root();scenario=POLICY_PRACTICE['scenarios'][0]
        game,info=play_branch(root,scenario,'actual',source,observation)
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);raw=d/'raw.json'
            dump(raw,dict(games=1,max_plies=16,details=[dict(game,moves=[r['move'] for r in game['moves']],move_records=game['moves'])]))
            manifest=archive([raw],d/'played-archive','practice-test')
            report=dict(manifest=manifest,results=[dict(sha256=sha256(raw.read_bytes()),info=info)])
            plan=dict(split_registry={'game:1:g':root['lineage']})
            transfer=learning_inputs(plan,report,d)
            self.assertEqual(transfer['selected_cases'],2);self.assertEqual(transfer['training_games'],1)
            self.assertEqual(len({r['group'] for r in transfer['game_splits']}),1)
            # An exact descendant known to be held out quarantines its ancestor
            # and all siblings before that game can be selected for diagnosis.
            board=shogi.Board();board.push_usi('7g7f')
            plan['split_registry'][leakage_keys(board)[0]]=dict(group='old-test',split='heldout',heldout_consumed=True)
            transfer=learning_inputs(plan,report,d)
            self.assertEqual(transfer['selection'],[]);self.assertEqual(transfer['quarantined_games'],1)
            self.assertEqual(transfer['split_registry']['game:1:g']['split'],'quarantine')

    def test_existing_output_cannot_be_reexecuted_and_binary_mismatch_fails_before_intent(self):
        p,row=fixture();p['progress']['analysis']['analyzer_binary_sha256']='a'*64
        plan=create_plan([(p,[row])],PARENT,1000)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'existing practice'):run(plan,[],Path(tmp)/'binary',Path(tmp)/'knowledge',tmp)

    def test_raw_archive_readback_reproduces_and_tamper_cannot_pass(self):
        from tools.research.postgame_analyze import OPTIONS as SEARCH_OPTIONS
        source,root=source_and_root()
        class FakeAnalyzer:
            def __init__(self,*a,**k):pass
            def send(self,command):pass
            def close(self):pass
            def search(self,start,history,ms,**kwargs):
                return dict(observation(root['task']['case'],history,ms),played_telemetry=dict(phase_maturity=0))
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);binary=d/'binary';binary.write_bytes(b'own-test-engine');knowledge=d/'knowledge';knowledge.write_text('# test\na\n')
            parent=dict(PARENT,knowledge_sha256=sha256(knowledge.read_bytes()))
            root['task']['parent']=parent
            root['practice_id']=digest(dict(parent=parent,task_id=root['task']['task_id'],policy=POLICY_PRACTICE))
            plan=dict(parent=parent,parent_options=dict(zip(OPTIONS,BASE)),policy=POLICY_PRACTICE,roots=[root],seed=1000,
                binary_sha256=sha256(binary.read_bytes()),split_registry={'game:1:g':root['lineage']},
                purpose='training_practice',formal_adoption=False,strength_measurement=False)
            plan['plan_sha256']=digest(plan)
            with patch('tools.research.postgame_practice.Analyzer',FakeAnalyzer):
                report=run(plan,[source],binary,knowledge,d/'run')
            audit=verify_saved(plan,report,[source],d/'run')
            self.assertTrue(audit['raw_archive_reproduced']);self.assertEqual(audit['games'],4)
            for field in ('new_plies','searches'):
                bad=copy.deepcopy(report);bad[field]+=1
                with self.assertRaises(ValueError):verify_saved(plan,bad,[source],d/'run')
            raw=d/'run'/report['results'][0]['file'];raw.write_text(raw.read_text()+' ')
            with self.assertRaisesRegex(ValueError,'hash'):verify_saved(plan,report,[source],d/'run')
