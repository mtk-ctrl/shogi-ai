"""Validate independent material deltas, mirrored fixtures and saved PVs."""
import json
import csv
from pathlib import Path
import sys
import unittest
import shogi

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/research'))
from diagnose_hand_drops import delta, fixtures, make_case, material, rotated
from mine_hand_drop_forks import drop_targets, immediate_capture_screen


class HandDropDiagnosisTest(unittest.TestCase):
    def test_fork_inventory_reciprocity_and_capture_chains(self):
        with (ROOT/'benchmarks/positions/gold_silver_fork_inventory.csv').open() as stream:
            rows=list(csv.DictReader(stream))
        self.assertEqual(len(rows),25*13*13)
        self.assertEqual(len({(r['hand'],r['target_square_1'],r['target_square_2'],
                              r['target_kind_1'],r['target_kind_2']) for r in rows}),len(rows))
        def selected(hand,a,b):
            return [r for r in rows if r['hand']==hand and
                    sorted((r['target_kind_1'],r['target_kind_2']))==sorted((a,b))]
        for hand,a,b in (('銀','金','銀'),('金','金','金')):
            self.assertTrue(all(r['unsupported_no_direct_capture']=='False' for r in selected(hand,a,b)))
        for hand,a,b,count in (('銀','金','金',1),('金','銀','銀',3)):
            self.assertEqual(sum(r['unsupported_no_direct_capture']=='True' for r in selected(hand,a,b)),count)
        # Independently replay the concrete pawn-supported trades. A gain
        # after the recapture can disappear when the second gold captures it.
        for hand,gain3,gain4 in (('S',200,0),('G',0,-200)):
            case=make_case('inventory_trade','capture chain',
                           {'9i':'K','1a':'k','4d':'g','6d':'g','5f':'P'},
                           hand,hand+'*5e','observe','')
            base_line=[case['target'],'4d5e','5f5e','6d5e']
            for c in (case,rotated(case)):
                board=shogi.Board(c['sfen']); root=board.turn; initial=material(board,root)
                for index,usi in enumerate(base_line):
                    move=shogi.Move.from_usi(usi)
                    if c['id'].endswith('_white'):
                        move=shogi.Move(None if move.from_square is None else 80-move.from_square,
                                        80-move.to_square,move.promotion,move.drop_piece_type)
                    self.assertIn(move,board.legal_moves)
                    board.push(move)
                    if index==2: self.assertEqual(material(board,root)-initial,gain3)
                self.assertEqual(material(board,root)-initial,gain4)
            row=next(r for r in selected('銀' if hand=='S' else '金','金','金')
                     if (r['target_square_1'],r['target_square_2'])==('4d','6d'))
            self.assertEqual(int(row['best_worst_capture_recapture_3ply']),gain3)
            self.assertEqual(int(row['best_worst_same_square_capture_chain_4ply']),gain4)

    def test_broad_targets_and_capture_filter(self):
        for case in fixtures():
            if not case['id'].startswith('small_'): continue
            board=shogi.Board(case['sfen']); before=board.sfen()
            move=shogi.Move.from_usi(case['target'])
            direct,rear=drop_targets(board,move)
            self.assertGreaterEqual((direct|rear).bit_count(),2,case['id'])
            if 'small_lance_silver_gold' in case['id']:
                self.assertEqual(direct.bit_count(),1)
                self.assertEqual(rear.bit_count(),1)
            screen=immediate_capture_screen(board,move)
            self.assertEqual(screen['accepted'],case['expected']!='avoid',case['id'])
            self.assertEqual(board.sfen(),before)
        # Defended drops can still lose material; equal silver trades are
        # accepted. Legal captures, rather than geometric attacks, matter.
        for attacker, supported, accepted in (('s',False,False),('s',True,True),('p',True,False)):
            pieces={'9i':'K','1a':'k','4d':'r','6d':'r','5d':attacker}
            if supported: pieces['5f']='G'
            case=make_case('screen_trade','filter',pieces,'S','S*5e','observe','')
            for c in (case,rotated(case)):
                board=shogi.Board(c['sfen']); before=board.sfen()
                screen=immediate_capture_screen(board,shogi.Move.from_usi(c['target']))
                self.assertEqual(screen['accepted'],accepted)
                self.assertGreater(screen['legal_captures'],0)
                self.assertEqual(board.sfen(),before)
        pinned=make_case('screen_pin','filter',{'9i':'K','5i':'k','5a':'R','5d':'s','3d':'n'},
                         'S','S*4e','observe','')
        for c in (pinned,rotated(pinned)):
            board=shogi.Board(c['sfen']); move=shogi.Move.from_usi(c['target'])
            self.assertTrue(board.is_attacked_by(1-board.turn,move.to_square))
            screen=immediate_capture_screen(board,move)
            self.assertTrue(screen['accepted'])
            self.assertEqual(screen['legal_captures'],0)

    def test_material_delta_matches_board_update(self):
        # Test drops, quiet moves, captures of promoted pieces, and promotions
        # for both colors, using the actual independent board update.
        for case in fixtures():
            board=shogi.Board(case['sfen']); root=board.turn
            for path in ([],[case['target']]):
                replay=shogi.Board(case['sfen'])
                if path:
                    move=shogi.Move.from_usi(path[0])
                    if move not in replay.legal_moves: continue
                    replay.push(move)
                for move in list(replay.legal_moves):
                    before=material(replay,root)
                    predicted=delta(replay,move,root)
                    replay.push(move)
                    self.assertEqual(material(replay,root)-before,predicted,(case['id'],move.usi()))
                    replay.pop()

    def test_saved_report_pvs_and_exchange_witnesses(self):
        path=ROOT/'benchmarks/results/2026-10-06_hand-drop-diagnosis.json'
        report=json.loads(path.read_text())
        self.assertTrue(report['complete'])
        expected={case['id']:case for case in fixtures()}
        self.assertEqual(set(expected),{row['id'] for row in report['rows']})
        by_id={row['id']:row for row in report['rows']}
        for row in report['rows']:
            self.assertEqual(row['sfen'],expected[row['id']]['sfen'])
            board=shogi.Board(row['sfen']); root=board.turn
            self.assertEqual(row['certificate']['legal'],shogi.Move.from_usi(row['target']) in board.legal_moves)
            for result in [*row['core'].values(),*row['production'].values()]:
                replay=shogi.Board(row['sfen'])
                self.assertIn(shogi.Move.from_usi(result['bestmove']),replay.legal_moves)
                for move in result.get('pv',[]):
                    parsed=shogi.Move.from_usi(move)
                    self.assertIn(parsed,replay.legal_moves,(row['id'],move))
                    replay.push(parsed)
            for certificate in row['selected_certificates'].values():
                if 'worst_witness' not in certificate: continue
                replay=shogi.Board(row['sfen']); initial=material(replay,root)
                for move in certificate['worst_witness']:
                    parsed=shogi.Move.from_usi(move)
                    self.assertIn(parsed,replay.legal_moves,(row['id'],move))
                    replay.push(parsed)
                if abs(certificate['material_gain_4ply'])<10**7:
                    self.assertEqual(material(replay,root)-initial,certificate['material_gain_4ply'])
            if not row['id'].endswith('_white') and 'material_gain_4ply' in row['certificate']:
                self.assertEqual(row['certificate']['material_gain_4ply'],by_id[row['id']+'_white']['certificate']['material_gain_4ply'])

    def test_real_position_provenance_and_pvs(self):
        for path in ('2026-10-06_real-hand-drop-screen.json','2026-10-06_broad-hand-drop-screen.json'):
            self.validate_real_report(ROOT/'benchmarks/results'/path)

    def validate_real_report(self,path):
        report=json.loads(path.read_text())
        self.assertTrue(report['complete'])
        source=json.loads((ROOT/report['source']).read_text())
        for row in report['rows']:
            game=source['details'][row['game_index']]
            self.assertEqual(game['moves'][:row['ply']],row['history'])
            replay=shogi.Board()
            for move in row['history']: replay.push_usi(move)
            self.assertEqual(replay.sfen(),row['sfen'])
            if 'rear_squares' in row:
                direct,rear=drop_targets(replay,shogi.Move.from_usi(row['target']))
                self.assertEqual(row['attacked_squares'],[shogi.SQUARE_NAMES[s] for s in shogi.SQUARES if direct&(1<<s)])
                self.assertEqual(row['rear_squares'],[shogi.SQUARE_NAMES[s] for s in shogi.SQUARES if rear&(1<<s)])
                self.assertEqual(row['immediate_capture_screen'],immediate_capture_screen(replay,shogi.Move.from_usi(row['target'])))
            results=[*row['production'].values(),*row['core'].values(),
                     *row['selected_depth3'].values(),*row.get('repeat_50ms_core',[])]
            for result in results:
                replay=shogi.Board(row['sfen'])
                self.assertIn(shogi.Move.from_usi(result['bestmove']),replay.legal_moves)
                for move in result.get('pv',[]):
                    parsed=shogi.Move.from_usi(move)
                    self.assertIn(parsed,replay.legal_moves,(row['game_index'],row['ply'],move))
                    replay.push(parsed)


if __name__=='__main__': unittest.main()
