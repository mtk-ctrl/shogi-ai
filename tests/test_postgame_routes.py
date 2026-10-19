import copy
import unittest
from tools.research.postgame_routes import research,make_memory,select

def frame(move,value=0,depth=3):
    return dict(bestmove=move,status='recorded',kind='cp',value_stm=value,depth=depth,
                bound='exact',pv_head_matches=True,research_decision_id=None)

class RouteTests(unittest.TestCase):
    def test_more_time_is_not_automatically_better(self):
        case=dict(history_moves=[],actual_move='7g7f')
        values=iter([frame('7g7f'),frame('2g2f'),frame('2g2f'),frame('x',40),frame('x',-20)])
        r=research(case,lambda *_:next(values))
        self.assertTrue(r['time_need']);self.assertIsNone(r['verified_research_move'])

    def test_same_depth_and_own_research_required(self):
        case=dict(history_moves=[],actual_move='7g7f')
        values=[frame('7g7f'),frame('2g2f'),frame('2g2f'),frame('x',150),frame('x',-30)]
        r=research(case,lambda *_:values.pop(0));self.assertEqual(r['verified_research_move'],'2g2f')
        values=[frame('7g7f'),frame('2g2f'),frame('2g2f'),frame('x',150,2),frame('x',-300,3)]
        self.assertIsNone(research(case,lambda *_:values.pop(0))['verified_research_move'])

    def test_research_disagreement_does_not_become_hint(self):
        case=dict(history_moves=[],actual_move='7g7f')
        values=iter([frame('7g7f'),frame('2g2f'),frame('3g3f')])
        r=research(case,lambda *_:next(values));self.assertFalse(r['time_need']);self.assertIsNone(r['verified_research_move'])

    def test_conflicting_played_moves_are_not_silently_chosen(self):
        rows=[dict(key='board',move='7g7f',depth=3,game_hash='a'),dict(key='board',move='2g2f',depth=4,game_hash='b')]
        self.assertEqual(make_memory(rows,[]),{})

    def test_selection_covers_sides_and_bounds_each_source_game(self):
        rows=[dict(phase=p,side=s,priority=0,ply=i,game_hash=str((p,s,i//4)),key=str((p,s,i)))
              for p in range(3) for s in range(2) for i in range(20)]
        selected=select(rows);self.assertEqual(len(selected),24)
        self.assertEqual({(r['phase'],r['side']) for r in selected},set((p,s) for p in range(3) for s in range(2)))
        from collections import Counter
        self.assertLessEqual(max(Counter(r['game_hash'] for r in selected).values()),2)

if __name__=='__main__':unittest.main()
