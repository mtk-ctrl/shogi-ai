"""Archive integrity, terminal rewards and history-sensitive postgame inputs."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import shogi
from tools.research.postgame_cases import load_archive, make_case, prepare_cases, verify_game


def fixture(pieces, hand='-', turn='b'):
    board = shogi.Board()
    board.clear()
    for square, piece in pieces.items():
        board.set_piece_at(shogi.SQUARE_NAMES.index(square), shogi.Piece.from_symbol(piece))
    return shogi.Board(f'{board.sfen().split()[0]} {turn} {hand} 1')


def game_from(start, moves, winner=None, reason='move_limit', a_black=True):
    board = shogi.Board(start)
    rows = []
    for ply, token in enumerate(moves, 1):
        rows.append({'ply': ply, 'move': token,
                     'side_to_move': 'black' if board.turn == shogi.BLACK else 'white',
                     'engine': 'A' if (board.turn == shogi.BLACK) == a_black else 'B',
                     'search': {}})
        board.push_usi(token)
    return dict(schema_version=1, source_id='s', source_game_index=0, game_id='s:0',
                start_sfen=start, moves=rows, plies=len(rows), a_black=a_black,
                winner=winner, reason=reason, final_sfen=board.sfen())


class PostgameCasesTest(unittest.TestCase):
    def save(self, directory, games, metadata=None):
        raw = gzip.compress((''.join(json.dumps(g) + '\n' for g in games)).encode(), mtime=0)
        root = Path(directory)
        (root / 'played-games.jsonl.gz').write_bytes(raw)
        meta = {'max_plies': len(games[0]['moves'])} if metadata is None else metadata
        manifest = dict(schema_version=1, archive='played-games.jsonl.gz',
                        archive_sha256=hashlib.sha256(raw).hexdigest(), archive_bytes=len(raw),
                        games=len(games), plies=sum(g['plies'] for g in games), run_id='fixture',
                        sources=[{'source_id': 's', 'metadata': meta}])
        (root / 'manifest.json').write_text(json.dumps(manifest))
        return manifest

    def test_same_board_with_different_history_has_distinct_analysis_input(self):
        start = fixture({'5i': 'K', '5a': 'k'}).sfen()
        moves = ['5i6i', '5a6a', '6i5i', '6a5a'] * 3
        with tempfile.TemporaryDirectory() as d:
            self.save(d, [game_from(start, moves, reason='fourfold_repetition')])
            g = load_archive(d)[0]
            early, later = make_case(g, 1), make_case(g, 5)
        self.assertEqual(early['position_key'], later['position_key'])
        self.assertNotEqual(early['history_key'], later['history_key'])
        self.assertTrue(later['analysis_position_command'].endswith('moves ' + ' '.join(moves[:4])))
        self.assertTrue(later['actual_position_after_command'].endswith(' '.join(moves[:5])))
        self.assertEqual(later['outcome']['terminal_reward_stm'], 0)
        self.assertEqual(later['analysis_status'], 'not_run')

    def test_move_limit_is_unknown_not_a_draw_reward(self):
        with tempfile.TemporaryDirectory() as d:
            self.save(d, [game_from(shogi.STARTING_SFEN, ['7g7f', '3c3d'])])
            cases = [make_case(load_archive(d)[0], p) for p in (1, 2)]
        for c in cases:
            self.assertEqual(c['outcome']['status'], 'unresolved')
            self.assertIsNone(c['outcome']['terminal_reward_stm'])

    def test_perpetual_check_rewards_follow_actor_and_assignment(self):
        start = fixture({'9i': 'K', '5a': 'k', '4b': 'R'}).sfen()
        moves = ['4b5b', '5a4a', '5b4b', '4a5a'] * 3
        for a_black in (True, False):
            winner = 'B' if a_black else 'A'  # Black gave continuous check and loses.
            with tempfile.TemporaryDirectory() as d:
                self.save(d, [game_from(start, moves, winner, 'perpetual_check', a_black)])
                g = load_archive(d)[0]
                self.assertEqual(make_case(g, 1)['outcome']['terminal_reward_stm'], -1)
                self.assertEqual(make_case(g, 2)['outcome']['terminal_reward_stm'], 1)

    def test_false_result_final_board_and_mover_are_rejected(self):
        start = fixture({'9i': 'K', '5a': 'k', '4b': 'R'}).sfen()
        good = game_from(start, ['4b5b', '5a4a', '5b4b', '4a5a'] * 3, 'B', 'perpetual_check')
        for field, value in [('winner', 'A'), ('reason', 'fourfold_repetition'),
                             ('final_sfen', shogi.STARTING_SFEN), ('a_black', None)]:
            bad = dict(good, **{field: value})
            with self.assertRaises(ValueError):
                verify_game(bad, {'max_plies': 12})
        bad = copy.deepcopy(good)
        bad['moves'][0]['engine'] = 'B'
        with self.assertRaises(ValueError):
            verify_game(bad, {'max_plies': 12})

    def test_checkmate_and_entering_king_are_independently_checked(self):
        start = fixture({'9i':'K','5a':'k','4a':'l','6a':'l','4b':'p','6b':'p','5c':'P','4c':'G'}).sfen()
        good = game_from(start, ['5c5b'], 'A', 'checkmate')
        self.assertEqual(verify_game(good, {})[1], 'verified_win_loss')
        with self.assertRaises(ValueError):
            verify_game(game_from(shogi.STARTING_SFEN, [], 'A', 'declare_win'), {})
        camp = {f'{i}c': 'P' for i in range(1, 10)}
        camp.update({'5b': 'K', '4b': 'G', '9i': 'k'})
        declaration = game_from(fixture(camp, 'R2B3P').sfen(), [], 'A', 'declare_win')
        self.assertEqual(verify_game(declaration, {})[1], 'verified_win_loss')
        declaration['winner'] = 'B'
        with self.assertRaises(ValueError):
            verify_game(declaration, {})

    def test_moves_after_terminal_are_rejected(self):
        start = fixture({'5i': 'K', '5a': 'k'}).sfen()
        moves = ['5i6i', '5a6a', '6i5i', '6a5a'] * 3 + ['5i6i']
        with self.assertRaisesRegex(ValueError, 'moves after terminal'):
            verify_game(game_from(start, moves), {'max_plies': 13})

    def test_no_reuse_of_pv_or_missing_score_as_zero(self):
        g = game_from(shogi.STARTING_SFEN, ['7g7f', '3c3d'])
        g['moves'][0]['search'] = {'score_cp_stm': 0, 'score_mate_stm': 3, 'score_status': 'ambiguous',
                                  'pv': ['7g7f', '8c8d'], 'candidates': ['2g2f']}
        with tempfile.TemporaryDirectory() as d:
            self.save(d, [g])
            loaded = load_archive(d)[0]
            first, second = make_case(loaded, 1), make_case(loaded, 2)
        self.assertEqual(first['original_observation']['score_status'], 'ambiguous')
        self.assertEqual(first['original_observation']['score_cp_stm'], 0)
        self.assertNotIn('pv', first['original_observation'])
        self.assertNotIn('candidates', first['original_observation'])
        self.assertEqual(second['original_observation'], {})

    def test_integrity_provenance_and_counts_fail_closed(self):
        good = game_from(shogi.STARTING_SFEN, ['7g7f', '3c3d'])
        for mutation in ('hash', 'bytes', 'games', 'plies', 'archive', 'source', 'duplicate'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as d:
                manifest = self.save(d, [good, good] if mutation == 'duplicate' else [good])
                if mutation == 'hash':
                    manifest['archive_sha256'] = 'bad'
                elif mutation in ('bytes', 'games', 'plies'):
                    key = 'archive_bytes' if mutation == 'bytes' else mutation
                    manifest[key] += 1
                elif mutation == 'archive':
                    manifest['archive'] = '../played-games.jsonl.gz'
                elif mutation == 'source':
                    manifest['sources'][0]['source_id'] = 'unrelated'
                Path(d, 'manifest.json').write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    load_archive(d)

    def test_selection_budget_and_unknown_cases_are_rejected(self):
        start = fixture({'5i': 'K', '5a': 'k'}).sfen()
        with tempfile.TemporaryDirectory() as d:
            self.save(d, [game_from(start, ['5i6i', '5a6a', '6i5i', '6a5a'] * 3,
                                        reason='fourfold_repetition')])
            games = load_archive(d)
        select = lambda p: {'game_id': 's:0', 'ply': p}
        self.assertEqual(len(prepare_cases(games, [select(1), select(2)])), 2)
        for selection in ([select(1), select(1)], [select(p) for p in range(1, 6)],
                          [select(0)], [select(13)], [{'game_id': 'no-game', 'ply': 1}], []):
            with self.assertRaises(ValueError):
                prepare_cases(games, selection)


if __name__ == '__main__':
    unittest.main()
