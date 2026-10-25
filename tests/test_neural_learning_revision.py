"""Regression gates for the diagnosed learning failure, without strength claims."""
import copy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import shogi
import torch
from tools.research import neural_model as nm, neural_residual as nr
from tools.research.nnue_labels import labels_from_diagnosis
from tools.research.postgame_cases import load_archive, make_case
from test_nnue_labels import archive


class LearningRevisionTests(unittest.TestCase):
    def test_saturated_wrong_prediction_receives_a_corrective_gradient(self):
        net=nm.Network(16,correction=True)
        batch=nm.tensors([dict(features=nm.features(shogi.Board().sfen()))],'cpu')
        with torch.no_grad():net.value.bias.fill_(3)
        clipped,_=net(*batch)
        (clipped-.2).square().mean().backward()
        self.assertEqual(net.value.bias.grad.item(),0)
        net.zero_grad()
        raw,_=net(*batch,unbounded=True)
        loss=torch.nn.functional.smooth_l1_loss(raw,torch.tensor([.2]))
        loss.backward()
        self.assertGreater(net.value.bias.grad.item(),0)
        with torch.no_grad():net.value.bias-=.01*net.value.bias.grad
        self.assertLess(net.value.bias.item(),3)
        self.assertLessEqual(net(*batch)[0].item(),.600001)

    def test_target_projection_retains_the_original_goal_for_audit(self):
        row=dict(root='g',sfen=shogi.Board().sfen(),target=2.,policy_weight=1)
        parts={s:[copy.deepcopy(row)] for s in ('train','validation','test')}
        with tempfile.TemporaryDirectory() as tmp:
            binary=Path(tmp)/'binary';binary.write_bytes(b'own')
            with patch.object(nr,'StaticOracle') as oracle:
                oracle.return_value.evaluate.return_value=500
                result=nr.correction_targets(parts,binary,Path(tmp)/'cache.json')
            for split in result:
                r=result[split][0]
                self.assertAlmostEqual(r['target'],.6)
                self.assertAlmostEqual(r['unbounded_correction_target'],1.5)
                self.assertEqual(r['absolute_target'],2.)
                self.assertEqual(r['policy_weight'],0)
            self.assertEqual(parts['train'][0]['target'],2.)

    def test_rare_research_validation_is_not_drowned_by_ordinary_rows(self):
        rows=[dict(features=[0],target=0.,origin='own_outcome') for _ in range(100)]
        rows.append(dict(features=[1],target=0.,origin='own_deep_search'))
        class Model:
            def __init__(self,ordinary,research):self.a,self.b=ordinary,research
            def __call__(self,ids,offsets):
                return torch.where(ids==0,self.a,self.b),None
        old=Model(0.,1.);new=Model(.1,.1)
        self.assertLess(nm.error(old,rows,'cpu'),nm.error(new,rows,'cpu'))
        self.assertGreater(nm.selection_metrics(old,rows)['score_cp'],
                           nm.selection_metrics(new,rows)['score_cp'])

    def test_unconfirmed_changed_move_is_rejected_then_admitted_after_refutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive(tmp);game=load_archive(tmp)[0];case=make_case(game,1)
            board=shogi.Board(game.start_sfen)
            move=next(m.usi() for m in board.legal_moves if m.usi()!=case['actual_move'])
            deep=dict(status='recorded',kind='cp',bound='exact',pv_head_matches=True,
                      depth=8,value_stm=200,requested_ms=3000000,bestmove=move,
                      position_command=case['analysis_position_command'],history_key=case['history_key'])
            result=dict(case=case,root_deep=deep,branches={})
            self.assertFalse(labels_from_diagnosis([result],{game.row['game_id']:game})[0])
            def child(token,value):
                return dict(status='recorded',kind='cp',bound='exact',pv_head_matches=True,
                            depth=6,value_stm=value,requested_ms=600000,
                            position_command=case['analysis_position_command']+' '+token)
            result['branches']={'actual':child(case['actual_move'],100),'research':child(move,200)}
            self.assertFalse(labels_from_diagnosis([result],{game.row['game_id']:game})[0])
            result['branches']['research']['value_stm']=-100
            labels,_=labels_from_diagnosis([result],{game.row['game_id']:game})
            self.assertEqual(labels[0]['evidence']['branch_confirmation']['improvement_cp'],200)


if __name__=='__main__':unittest.main()
