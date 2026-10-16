#!/usr/bin/env python3
"""Verify played archives and prepare selected, full-history postgame cases.

This is an input adapter, not an analyzer or learner. No PVs or unplayed
candidate lists are copied into its output. Termination proof is independent
of the scores recorded by the playing engines.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import shogi
from benchmarks.arena import Adjudicator, can_declare_win


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def label_for_color(color, a_black):
    return 'A' if (color == shogi.BLACK) == a_black else 'B'


@dataclass(frozen=True)
class VerifiedGame:
    row: dict
    metadata: dict
    start_sfen: str
    outcome_status: str
    archive_sha256: str
    manifest_sha256: str
    run_id: str | int | None

    @property
    def moves(self):
        return tuple(r['move'] for r in self.row['moves'])


def verify_game(game, metadata):
    require(type(game.get('a_black')) is bool, 'missing/invalid A color assignment')
    require(game.get('winner') in ('A', 'B', None), 'unknown winner')
    rows = game.get('moves')
    require(isinstance(rows, list), 'missing moves')
    require(type(game.get('plies')) is int and game['plies'] == len(rows), 'ply count mismatch')
    start = game.get('start_sfen') or metadata.get('start_sfen') or shogi.STARTING_SFEN
    board = shogi.Board(start)
    judge = Adjudicator(board)
    terminal = None
    for ply, row in enumerate(rows, 1):
        require(terminal is None, 'moves after terminal position')
        require(isinstance(row, dict) and row.get('ply') == ply, 'move row/ply mismatch')
        color = 'black' if board.turn == shogi.BLACK else 'white'
        require('side_to_move' not in row or row['side_to_move'] == color, 'side-to-move mismatch')
        expected = label_for_color(board.turn, game['a_black'])
        require('engine' not in row or row['engine'] == expected, 'mover assignment mismatch')
        move = shogi.Move.from_usi(row['move'])
        require(move in board.legal_moves, f'illegal move at {ply}: {row["move"]}')
        board.push(move)
        terminal = judge.after_move(board)
    require(board.sfen() == game.get('final_sfen'), 'final SFEN mismatch')
    reason = game.get('reason')
    if reason in ('checkmate', 'no_legal_moves', 'fourfold_repetition', 'perpetual_check'):
        require(terminal is not None and terminal[1] == reason, 'terminal reason not proved')
        color = terminal[0]
        expected = None if color is None else label_for_color(color, game['a_black'])
        require(game['winner'] == expected, 'terminal winner mismatch')
        status = 'verified_draw' if color is None else 'verified_win_loss'
    elif reason == 'declare_win':
        require(terminal is None and can_declare_win(board), 'invalid entering-king declaration')
        require(game['winner'] == label_for_color(board.turn, game['a_black']), 'declaration winner mismatch')
        status = 'verified_win_loss'
    elif reason == 'move_limit':
        limit = metadata.get('max_plies')
        require(type(limit) is int and limit > 0 and len(rows) == limit, 'move limit mismatch')
        require(terminal is None and game['winner'] is None, 'invalid move-limit outcome')
        status = 'unresolved'  # Never a draw target just because the runner stopped.
    else:
        raise ValueError(f'unsupported/unverified termination: {reason}')
    return start, status


def load_archive(directory):
    root = Path(directory)
    manifest_raw = (root / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_raw)
    require(manifest.get('schema_version') == 1, 'unsupported manifest schema')
    name = manifest.get('archive')
    require(isinstance(name, str) and name not in ('', '.', '..') and Path(name).name == name,
            'archive must be a local basename')
    raw = (root / name).read_bytes()
    digest = sha256(raw)
    require(digest == manifest.get('archive_sha256'), 'archive SHA256 mismatch')
    require(len(raw) == manifest.get('archive_bytes'), 'archive byte count mismatch')
    sources = manifest.get('sources')
    require(isinstance(sources, list), 'missing sources')
    source_map = {s['source_id']: s['metadata'] for s in sources}
    require(len(source_map) == len(sources), 'duplicate source ID')
    games, seen = [], set()
    for line in gzip.decompress(raw).splitlines():
        row = json.loads(line)
        require(row.get('schema_version') == 1, 'unsupported game schema')
        source = row.get('source_id')
        require(source in source_map, 'unknown source ID')
        index = row.get('source_game_index')
        require(type(index) is int and index >= 0, 'invalid source game index')
        require(row.get('game_id') == f'{source}:{index}', 'game identity mismatch')
        require(row['game_id'] not in seen, 'duplicate game ID')
        seen.add(row['game_id'])
        start, status = verify_game(row, source_map[source])
        games.append(VerifiedGame(row, source_map[source], start, status, digest,
                                  sha256(manifest_raw), manifest.get('run_id')))
    require(len(games) == manifest.get('games') and games, 'game count mismatch/empty archive')
    require(sum(len(g.moves) for g in games) == manifest.get('plies'), 'total ply count mismatch')
    return games


def position_command(start_sfen, moves):
    command = 'position sfen ' + start_sfen
    return command + (' moves ' + ' '.join(moves) if moves else '')


def make_case(game, ply):
    require(type(ply) is int and 1 <= ply <= len(game.moves), 'selected ply out of range')
    history = game.moves[:ply - 1]
    board = shogi.Board(game.start_sfen)
    for move in history:
        board.push_usi(move)
    actor = label_for_color(board.turn, game.row['a_black'])
    reward = None
    if game.outcome_status != 'unresolved':
        reward = 0 if game.row['winner'] is None else (1 if game.row['winner'] == actor else -1)
    command = position_command(game.start_sfen, history)
    history_key = sha256(command.encode())
    observed = game.row['moves'][ply - 1].get('search', {})
    # Copy only original observations required for diagnosis, never a whole search object.
    fields = ('score_status', 'score_cp_stm', 'score_mate_stm', 'score_lowerbound',
              'score_upperbound', 'depth', 'seldepth', 'phase_maturity', 'phase_stage',
              'phase_static_cp_black', 'decision_source')
    return {
        'schema_version': 1,
        'case_id': sha256(f'{game.archive_sha256}:{game.row["game_id"]}:{ply}'.encode()),
        'source': {'run_id': game.run_id, 'game_id': game.row['game_id'], 'ply': ply,
                   'archive_sha256': game.archive_sha256, 'manifest_sha256': game.manifest_sha256},
        'start_sfen': game.start_sfen, 'history_moves': list(history),
        'position_key': ' '.join(board.sfen().split()[:3]), 'history_key': history_key,
        'analysis_position_command': command,
        'actual_position_after_command': position_command(game.start_sfen, history + (game.moves[ply - 1],)),
        'actual_move': game.moves[ply - 1],
        'side_to_move': 'black' if board.turn == shogi.BLACK else 'white', 'actor': actor,
        'outcome': {'winner': game.row['winner'], 'reason': game.row['reason'],
                    'status': game.outcome_status, 'terminal_reward_stm': reward},
        'original_observation': {k: observed[k] for k in fields if k in observed},
        'analysis_status': 'not_run', 'cause': 'unclassified',
    }


def prepare_cases(games, selection, max_cases=96, max_per_game=4):
    require(type(max_cases) is int and 0 < max_cases <= 96, 'case budget out of range')
    require(type(max_per_game) is int and 0 < max_per_game <= 4, 'per-game budget out of range')
    require(isinstance(selection, list) and 0 < len(selection) <= max_cases, 'selection exceeds budget/empty')
    by_id = {g.row['game_id']: g for g in games}
    counts, seen, output = {}, set(), []
    for item in selection:
        gid, ply = item['game_id'], item['ply']
        require(gid in by_id, 'selected game not found')
        case = make_case(by_id[gid], ply)
        require(case['case_id'] not in seen, 'duplicate selected case')
        seen.add(case['case_id'])
        counts[gid] = counts.get(gid, 0) + 1
        require(counts[gid] <= max_per_game, 'per-game case budget exceeded')
        output.append(case)
    return output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive-dir', type=Path, required=True)
    p.add_argument('--selection', type=Path, required=True, help='JSON list of game_id/ply; no implicit all-move export')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    require(not args.output.exists(), 'output exists; preserve prior research')
    games = load_archive(args.archive_dir)
    cases = prepare_cases(games, json.loads(args.selection.read_text()))
    text = ''.join(json.dumps(c, ensure_ascii=False, separators=(',', ':')) + '\n' for c in cases)
    with args.output.open('x', encoding='utf-8') as stream:
        stream.write(text)
    print(json.dumps({'verified_games': len(games), 'verified_plies': sum(len(g.moves) for g in games),
                      'selected_cases': len(cases), 'output_sha256': sha256(text.encode()),
                      'analysis_status': 'not_run'}))


if __name__ == '__main__':
    main()
