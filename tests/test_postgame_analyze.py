"""Tests of score attribution and uncertainty gates, independent of score values."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.research.postgame_analyze import score_frame, exact_cp, compare_children, route_result


def result(value, depth=4, kind='cp', bound='exact'):
    return dict(status='recorded',kind=kind,value_stm=value,depth=depth,bound=bound,pv_head_matches=True)


class PostgameAnalyzeTest(unittest.TestCase):
    def test_type_and_bound_belong_to_latest_score_frame(self):
        frame=score_frame(['info depth 4 score cp 123 lowerbound pv 7g7f',
                           'info depth 5 score mate -3 pv 2g2f',
                           'info nodes 900 string cutoffs 4','bestmove 2g2f'],'2g2f')
        self.assertEqual(frame['kind'],'mate')
        self.assertEqual(frame['value_stm'],-3)
        self.assertEqual(frame['bound'],'exact')
        self.assertEqual(frame['depth'],5)
        self.assertFalse(exact_cp(frame))

    def test_score_cannot_be_assigned_to_different_final_move(self):
        frame=score_frame(['info depth 4 score cp 120 pv 7g7f','bestmove 2g2f'],'2g2f')
        self.assertEqual(frame['status'],'unmatched_final_move')
        self.assertFalse(exact_cp(frame))

    def test_missing_depth_and_missing_score_remain_unknown(self):
        for lines in ([],['info depth 0 score cp 0 pv 7g7f'],['info score cp 0 pv 7g7f']):
            self.assertFalse(exact_cp(score_frame(lines,'7g7f')))
        self.assertIsNone(score_frame([],'7g7f')['value_stm'])

    def test_postmove_scores_are_both_negated_to_actor_view(self):
        pair=compare_children(result(700),result(-100))
        self.assertEqual(pair['improvement_cp'],800)
        self.assertEqual(pair['status'],'comparable')
        self.assertEqual(compare_children(result(-100),result(700))['improvement_cp'],-800)

    def test_horizon_and_bound_mismatch_do_not_make_teachers(self):
        self.assertEqual(compare_children(result(700,4),result(-100,5))['status'],'depth_mismatch')
        for bad in (result(700,bound='lower'),result(700,kind='mate'),result(700,depth=0)):
            self.assertEqual(compare_children(bad,result(-100))['status'],'unusable_score')

    def test_provisional_routes_do_not_claim_evaluation_causality(self):
        r=dict(same_as_actual=False,case={'actual_move':'7g7f'},research_move='2g2f',
               root_short={'bestmove':'7g7f'},root_deep={'bestmove':'2g2f'},followup=None,
               child_pairs={'500':{'comparison':{'status':'depth_mismatch','improvement_cp':800}}})
        self.assertEqual(route_result(r),'hold')
        r['followup']={'comparison':{'status':'comparable','improvement_cp':800}}
        self.assertEqual(route_result(r),'search_horizon_candidate')
        r['root_short']['bestmove']='2g2f'
        self.assertEqual(route_result(r),'stable_research_move_candidate')
        r['followup']['comparison']['status']='fixed_depth_incomplete'
        self.assertEqual(route_result(r),'hold')


if __name__=='__main__':unittest.main()
