"""Validate independent material deltas, mirrored fixtures and saved PVs."""
import json
from pathlib import Path
import sys
import unittest
import shogi

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/research'))
from diagnose_hand_drops import delta, fixtures, material


class HandDropDiagnosisTest(unittest.TestCase):
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
        report=json.loads((ROOT/'benchmarks/results/2026-10-06_real-hand-drop-screen.json').read_text())
        self.assertTrue(report['complete'])
        source=json.loads((ROOT/report['source']).read_text())
        for row in report['rows']:
            game=source['details'][row['game_index']]
            self.assertEqual(game['moves'][:row['ply']],row['history'])
            replay=shogi.Board()
            for move in row['history']: replay.push_usi(move)
            self.assertEqual(replay.sfen(),row['sfen'])
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
