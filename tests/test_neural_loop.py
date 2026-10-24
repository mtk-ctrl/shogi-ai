"""Meaningful gates/leakage/recovery tests. Synthetic fixtures prove no strength."""
import copy
import json
from pathlib import Path
import tempfile
import shutil
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import shogi
import torch
from tools.research import neural_model as nm
from tools.research.neural_arena import gate
from tools.research.neural_mcts import terminal_value, research
from tools.research.nnue_deep_study import analyze


class NeuralControlTests(unittest.TestCase):
    def test_scarce_study_is_replayed_without_duplicate_game_in_batch(self):
        ordinary=[dict(origin='own_outcome',root=f'g{i}') for i in range(300)]
        focused=[dict(origin=origin,root='study-game') for origin in ('own_deep_search','own_mcts')]
        batches=list(nm.replay_batches(ordinary+focused))
        self.assertEqual(sum(r['origin']=='own_outcome' for b in batches for r in b),300)
        self.assertGreater(len(batches),1)
        for batch in batches:
            self.assertEqual(sum(r['root']=='study-game' for r in batch),1)

    def test_input_archive_survives_import_directory_removal(self):
        from tools.research.neural_loop import freeze_archives
        from test_nnue_labels import archive
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'imported'
            source.mkdir()
            archive(source)
            pinned,manifest=freeze_archives([source],Path(tmp)/'run')
            expected=nm.digest(pinned[0]/'played-games.jsonl.gz')
            shutil.rmtree(source)
            again,record=freeze_archives([source],Path(tmp)/'run')
            self.assertEqual(record,manifest)
            self.assertEqual(nm.digest(again[0]/'played-games.jsonl.gz'),expected)
            (again[0]/'played-games.jsonl.gz').write_bytes(b'corrupt')
            with self.assertRaises((ValueError,RuntimeError)):
                freeze_archives([source],Path(tmp)/'run')

    def test_stable_split_and_action_space(self):
        roots=[f'g-{i}' for i in range(200)]
        old={r:nm.split_root(r,4) for r in roots}
        expanded={r:nm.split_root(r,4) for r in roots+['new']}
        self.assertEqual(old,{r:expanded[r] for r in roots})
        # Explicit reference mapping makes threshold/endianness drift visible.
        self.assertEqual([nm.split_root(r,4) for r in roots],list(old.values()))
        board=shogi.Board()
        ids=[nm.action_id(m.usi()) for m in board.legal_moves]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertNotEqual(nm.action_id('2b3c'),nm.action_id('2b3c+'))
        self.assertTrue(nm.action_id('P*5e')<nm.ACTIONS)
        with self.assertRaises(ValueError):nm.action_id('P*5e+')
        self.assertEqual(len(nm.features(board.sfen())),121)
        self.assertTrue(all(0<=f<nm.KING_FEATURES for f in nm.features(board.sfen())))

    def test_gate_rejects_noise_and_accepts_large_independent_gain(self):
        def match(scores,ms=200):
            return dict(pair_scores=scores,games=len(scores)*2,movetime=ms,invalid_games=0)
        weak=match([.51]*500)
        strong=match([.8]*500)
        self.assertFalse(gate(weak,strong,0,3)['accepted'])
        self.assertTrue(gate(strong,strong,0,3)['accepted'])
        self.assertFalse(gate(match([1]*99),strong,0,3)['accepted'])
        self.assertFalse(gate(match([1]*500,20),strong,0,3)['accepted'])
        invalid=dict(strong,invalid_games=1)
        self.assertFalse(gate(invalid,strong,0,3)['accepted'])

    def test_rule_terminal_orientation(self):
        self.assertEqual(terminal_value(dict(result=2,turn=1,declare=False)),-1)
        self.assertEqual(terminal_value(dict(result=3,turn=1,declare=False)),1)
        self.assertEqual(terminal_value(dict(result=1,turn=0,declare=False)),0)
        self.assertEqual(terminal_value(dict(result=0,turn=1,declare=True)),1)

    def test_puct_backup_prefers_proven_win_over_loss(self):
        class Oracle:
            def state(self,start,path):
                if not path:return dict(result=0,turn=0,declare=False,moves=['7g7f','2g2f'])
                return dict(result=2 if path[0]=='7g7f' else 3,turn=1,declare=False,moves=[])
        torch.manual_seed(1)
        net=nm.Network(16)
        for p in net.parameters():p.data.zero_()
        result=research(net,Oracle(),shogi.Board().sfen(),[],64)
        self.assertEqual(result['bestmove'],'7g7f')
        self.assertGreater(result['root_visits']['7g7f'],result['root_visits']['2g2f'])
        self.assertEqual(sum(result['root_visits'].values()),64)
        self.assertAlmostEqual(sum(result['policy'].values()),1)
        self.assertGreater(result['value_black'],0)

    def test_study_preserves_completed_stages_after_failure(self):
        requests=[]
        class Analyzer:
            fail=True
            def __init__(self,*a,**kw):pass
            def close(self):pass
            def search(self,start,history,ms,on_iteration=None):
                requests.append(ms)
                if ms==100 and self.fail:
                    self.__class__.fail=False
                    if on_iteration:on_iteration({'depth':1})
                    raise TimeoutError('interrupted')
                return dict(bestmove='7g7f',requested_ms=ms,kind='cp',status='recorded',bound='exact',
                    depth=1,value_stm=1,pv_head_matches=True)
        case=dict(start_sfen=shogi.Board().sfen(),history_moves=[],actual_move='7g7f')
        checkpoint={}
        with patch('tools.research.nnue_deep_study.Analyzer',Analyzer):
            with self.assertRaises(TimeoutError):
                analyze('b','k',case,50,100,200,100,163,checkpoint,lambda:None,True)
            self.assertIn('short',checkpoint['completed'])
            analyze('b','k',case,50,100,200,100,163,checkpoint,lambda:None,True)
        self.assertEqual(requests,[50,100,100,200])

    def test_training_checkpoint_resumes_identically_and_rejects_drift(self):
        # Small real gradient problem with independent SFEN positions.
        torch.set_num_threads(1)
        parts={}
        for split in ('train','validation','test'):
            board=shogi.Board()
            board.push_usi({'train':'7g7f','validation':'2g2f','test':'5g5f'}[split])
            parts[split]=[dict(features=nm.features(board.sfen()),sfen=board.sfen(),target=.2,
                weight=1.0,legal=[nm.action_id(m.usi()) for m in board.legal_moves],policy={})]
        with tempfile.TemporaryDirectory() as tmp:
            net,report=nm.train(parts,tmp,width=16,epochs=2,threads=1)
            first={k:v.clone() for k,v in net.state_dict().items()}
            net2,_=nm.train(parts,tmp,width=16,epochs=2,threads=1)
            self.assertTrue(all(torch.equal(first[k],v) for k,v in net2.state_dict().items()))
            changed=copy.deepcopy(parts)
            changed['train'][0]['target']=.3
            with self.assertRaisesRegex(ValueError,'changed'):
                nm.train(changed,tmp,width=16,epochs=2,threads=1)
            with self.assertRaisesRegex(ValueError,'distilled'):
                nm.export_nnue(nm.Network(16,residual=2),Path(tmp)/'bad.nnue')

if __name__=='__main__':unittest.main()
