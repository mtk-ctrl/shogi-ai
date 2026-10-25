#!/usr/bin/env python3
"""Verify safe NNUE label extraction from an actual archive schema fixture."""
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import shogi
from tools.research import nnue_labels
from tools.research.postgame_cases import load_archive, make_case


def terminal_position():
    board = shogi.Board()
    board.clear()
    pieces = {'9i': 'K', '5a': 'k', '4a': 'l', '6a': 'l',
              '4b': 'p', '6b': 'p', '5c': 'P', '4c': 'G'}
    for sq, piece in pieces.items():
        board.set_piece_at(shogi.SQUARE_NAMES.index(sq), shogi.Piece.from_symbol(piece))
    return board.sfen()


def archive(directory, engine_b="KUMOJI"):
    start = terminal_position()
    board = shogi.Board(start)
    board.push_usi('5c5b')
    row = dict(schema_version=1, source_id='sample', source_game_index=0,
               game_id='sample:0', start_sfen=start, a_black=True,
               winner='A', reason='checkmate', plies=1,
               final_sfen=board.sfen(), moves=[dict(ply=1, move='5c5b',
               engine='A', search={}, side_to_move='black')])
    raw = gzip.compress((json.dumps(row) + '\n').encode(), mtime=0)
    d = Path(directory)
    (d / 'played-games.jsonl.gz').write_bytes(raw)
    meta = dict(schema_version=1, archive='played-games.jsonl.gz',
                archive_sha256=hashlib.sha256(raw).hexdigest(),
                archive_bytes=len(raw), games=1, plies=1, run_id=1,
                sources=[dict(source_id='sample',
                              metadata={'engine_a': 'KUMOJI', 'engine_b': engine_b})])
    (d / 'manifest.json').write_text(json.dumps(meta))


class LabelsTest(unittest.TestCase):
    def test_verified_terminal_and_long_search(self):
        with tempfile.TemporaryDirectory() as d:
            archive(d)
            game = load_archive(d)[0]
            case = make_case(game, 1)
            case["triage"] = {"category": "checkmate"}  # permitted selection metadata
            deep = dict(status="recorded", kind="cp", bound="exact",
                        pv_head_matches=True, depth=7, value_stm=320,
                        requested_ms=600000, bestmove="5c5b",
                        position_command=case["analysis_position_command"],
                        history_key=case["history_key"])
            diagnosis = [dict(case=case, root_deep=deep)]
            path = Path(d, 'diagnosis.json')
            path.write_text(json.dumps(diagnosis))
            labels, manifest = nnue_labels.convert([Path(d)], path, 8)
            self.assertEqual(manifest["labels_by_origin"],
                             {"selfplay_result": 1, "own_search": 1})
            self.assertEqual(labels[0]["outcome_black"], 1)
            self.assertEqual(labels[1]["cp_black"], 320)
            self.assertEqual(labels[1]["root_game_id"], labels[0]["root_game_id"])
            deep["bound"] = "lower"
            path.write_text(json.dumps(diagnosis))
            _, manifest = nnue_labels.convert([Path(d)], path, 8)
            self.assertEqual(manifest["diagnosis_rejection_reasons"],
                             {"incomplete_or_non_cp": 1})

    def test_external_engine_result_is_never_a_teacher(self):
        with tempfile.TemporaryDirectory() as d:
            archive(d, engine_b="external-yaneuraou")
            with self.assertRaisesRegex(ValueError, "not a proven all-KUMOJI"):
                nnue_labels.convert([Path(d)], None, 8)

    def test_own_binary_paths_require_matching_fixed_commit_and_sha256(self):
        with tempfile.TemporaryDirectory() as d:
            archive(d)
            path = Path(d, "manifest.json")
            manifest = json.loads(path.read_text())
            source = manifest["sources"][0]["metadata"]
            source.update(engine_a="build/engine-a", engine_b="build/engine-b",
                          sha256_a="a"*64, sha256_b="b"*64)
            manifest.update(requested_ref_a="c"*40, requested_ref_b="c"*40)
            path.write_text(json.dumps(manifest))
            rows, meta = nnue_labels.convert([Path(d)], None, 8)
            self.assertEqual(meta["independent_source_games"], 1)
            self.assertEqual(rows[0]["origin"], "selfplay_result")
            manifest["requested_ref_b"] = "d"*40
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "not a proven all-KUMOJI"):
                nnue_labels.convert([Path(d)], None, 8)

    def test_tampered_research_history_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            archive(d)
            case = make_case(load_archive(d)[0], 1)
            case["history_moves"].append("7g7f")
            Path(d, "diag.json").write_text(json.dumps([{"case": case, "root_deep": {}}]))
            with self.assertRaisesRegex(ValueError, "does not match"):
                nnue_labels.convert([Path(d)], Path(d, "diag.json"), 8)


if __name__ == "__main__":
    unittest.main()
