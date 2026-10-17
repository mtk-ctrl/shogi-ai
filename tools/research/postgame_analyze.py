#!/usr/bin/env python3
"""Bounded own-engine postgame diagnosis; never an automatic adoption tool."""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import shogi
from benchmarks.arena import parse_info_line
from tools.research.postgame_cases import load_archive, make_case, position_command, require, sha256

OPTIONS = dict(SearchResearchMask=23, SearchEfficiencyMask=8, SearchReuseMask=6,
               SearchNextMask=4, SearchProbeMask=7, SearchThreads=2, RiskVerify=True,
               PositionKnowledge=True, AdaptiveLongThink=False, USI_Ponder=False,
               OpeningRandomNonLance=False, RandomSeed=2031101701)
FEATURES = ('material_term','safety','pressure','activity','danger','influence','potential',
            'coordination','hand_potential','threat','clamp','total')


def dump(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


class Analyzer:
    """Fresh process per search; no TT, clock or research-line carryover."""
    def __init__(self, binary, knowledge, expected_positions=163):
        self.proc = subprocess.Popen([str(Path(binary).resolve())], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1)
        self.lines = queue.Queue()
        self.reader = threading.Thread(target=self._reader, daemon=True)
        self.reader.start()
        try:
            self.send('usi')
            handshake = self.until('usiok', 15)
            names = {s.split(' type ', 1)[0][12:] for s in handshake if s.startswith('option name ')}
            self.name = next(s[8:] for s in handshake if s.startswith('id name '))
            require(self.name == 'KUMOJI v2.0.21', 'unexpected analyzer identity: ' + self.name)
            options = dict(OPTIONS, PositionKnowledgeFile=str(Path(knowledge).resolve()))
            require(set(options) <= names, 'unsupported analyzer options')
            for key, value in options.items():
                text = str(value).lower() if isinstance(value, bool) else str(value)
                require('\n' not in text and '\r' not in text, 'invalid option value')
                self.send(f'setoption name {key} value {text}')
            self.send('isready')
            ready = self.until('readyok', 15)
            require(type(expected_positions) is int and expected_positions > 0,
                    'invalid expected knowledge count')
            expected = f'info string position_knowledge loaded {expected_positions} positions file '
            require(any(s.startswith(expected) for s in ready), 'knowledge load not confirmed')
        except BaseException:
            self.close()
            raise

    def _reader(self):
        for line in self.proc.stdout:
            self.lines.put(line.rstrip())
        self.lines.put(None)

    def send(self, line):
        require('\n' not in line and '\r' not in line, 'embedded USI command')
        self.proc.stdin.write(line + '\n')
        self.proc.stdin.flush()

    def until(self, prefix, timeout):
        end = time.monotonic() + timeout
        lines = []
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('analyzer response timeout: ' + prefix)
            try:
                line = self.lines.get(timeout=remaining)
            except queue.Empty as ex:
                raise TimeoutError('analyzer response timeout: ' + prefix) from ex
            require(line is not None, 'analyzer exited early')
            require(not line.startswith('info string invalid position') and 'search error' not in line,
                    'analyzer rejected input: ' + line)
            lines.append(line)
            if line.startswith(prefix):
                return lines

    def static(self, sfen):
        # Pure board evaluation only. Search below always uses full actual history.
        self.send('position sfen ' + sfen)
        self.send('eval')
        line = self.until('info string evaluation ', 15)[-1]
        parts = line.split()[3:]
        values = {k: int(v) for k, v in zip(parts[::2], parts[1::2])}
        require(set(FEATURES) <= values.keys(), 'missing evaluation terms')
        return {k: values[k] for k in FEATURES}

    def search(self, start_sfen, history, ms, depth=None):
        board = shogi.Board(start_sfen)
        for token in history:
            board.push_usi(token)
        self.send('usinewgame')
        command = position_command(start_sfen, history)
        self.send(command)
        go = f'go movetime {ms}' + (f' depth {depth}' if depth is not None else '')
        started = time.monotonic()
        self.send(go)
        lines = self.until('bestmove ', max(15, ms/1000 + 5))
        chosen = lines[-1].split()[1]
        if chosen not in ('resign', 'win'):
            require(shogi.Move.from_usi(chosen) in board.legal_moves, 'illegal analyzer move')
        result = score_frame(lines, chosen)
        direct = next((line.split()[4] for line in lines
                       if line.startswith('info string research_decision id ')), None)
        result.update(bestmove=chosen, requested_ms=ms, requested_depth=depth,
                      research_decision_id=direct,
                      elapsed_ms=round((time.monotonic()-started)*1000, 3),
                      history_key=sha256(command.encode()), position_command=command)
        return result

    def close(self):
        if self.proc.poll() is None:
            try:
                self.send('quit')
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()
                self.proc.wait(timeout=3)
        self.reader.join(timeout=1)
        for stream in (self.proc.stdin, self.proc.stdout):
            if stream:
                stream.close()


def score_frame(lines, chosen):
    frame = {'status': 'missing', 'kind': None, 'value_stm': None, 'depth': None,
             'bound': 'unknown', 'pv_head_matches': False}
    for line in lines:
        info = parse_info_line(line)
        kind = 'cp' if 'score_cp' in info else 'mate' if 'score_mate' in info else None
        if kind:
            frame = dict(status='recorded', kind=kind, value_stm=info['score_' + kind],
                         depth=info.get('depth'),
                         bound='lower' if info.get('score_lowerbound') else 'upper' if info.get('score_upperbound') else 'exact',
                         pv_head_matches=bool(info.get('pv')) and info['pv'][0] == chosen)
    if frame['status'] == 'recorded' and not frame['pv_head_matches']:
        frame['status'] = 'unmatched_final_move'
    return frame


def exact_cp(result):
    return (result.get('status') == 'recorded' and result.get('kind') == 'cp'
            and result.get('bound') == 'exact' and result.get('pv_head_matches') is True
            and type(result.get('depth')) is int and result['depth'] > 0)


def compare_children(actual, improved):
    # Both scores describe the opponent to move, so negate each to the actor view.
    if not exact_cp(actual) or not exact_cp(improved):
        return {'status': 'unusable_score', 'improvement_cp': None}
    gap = actual['value_stm'] - improved['value_stm']
    return {'status': 'comparable' if actual['depth'] == improved['depth'] else 'depth_mismatch',
            'improvement_cp': gap, 'actual_depth': actual['depth'], 'improved_depth': improved['depth']}


def select_cases(games, static_values):
    # The original live engine scores never decide the teaching label.
    groups = {category: collections.defaultdict(list) for category in ('static_loss','static_gain','quiet')}
    for g in games:
        board = shogi.Board(g.start_sfen)
        for ply, row in enumerate(g.row['moves'], 1):
            before = static_values[board.sfen()]
            actor_sign = 1 if board.turn == shogi.BLACK else -1
            key = ' '.join(board.sfen().split()[:3])
            move = shogi.Move.from_usi(row['move'])
            quiet = not board.is_check() and board.piece_at(move.to_square) is None and not move.promotion
            color = 'black' if board.turn == shogi.BLACK else 'white'
            actor = 'A' if (board.turn == shogi.BLACK) == g.row['a_black'] else 'B'
            outcome = 'draw' if g.row['winner'] is None else 'win' if g.row['winner'] == actor else 'loss'
            board.push(move)
            after = static_values[board.sfen()]
            loss = (before['total'] - after['total'])*actor_sign
            if ply < 8 or ply > len(g.moves)-4:
                continue
            category = 'static_loss' if loss >= 150 else 'static_gain' if loss <= -150 else 'quiet' if quiet and abs(loss) <= 50 else None
            if category is None:
                continue
            stage = row.get('search', {}).get('phase_stage', 'unknown')
            seed = sha256(f'{g.row["game_id"]}:{ply}'.encode())
            rank = (-abs(loss), seed) if category != 'quiet' else (0, seed)
            groups[category][(stage, color, outcome)].append((rank, g, ply, key, loss, before, after))
    used, counts, selected = set(), collections.Counter(), []
    for category, buckets in groups.items():
        queues = {k: collections.deque(sorted(v, key=lambda x:x[0])) for k,v in buckets.items()}
        size = 0
        while size < 32:
            progress = False
            for bucket in sorted(queues):
                candidates = queues[bucket]
                while candidates:
                    rank,g,ply,key,loss,before,after = candidates.popleft()
                    identity = (g.run_id, g.row['game_id'])
                    if key in used or counts[identity] >= 4:
                        continue
                    used.add(key); counts[identity] += 1
                    case = make_case(g, ply)
                    case['triage'] = dict(category=category, static_loss_candidate_cp=loss,
                                          fixed_static_before=before, fixed_static_after=after,
                                          recorded_phase_stage=bucket[0])
                    selected.append(case); size += 1; progress = True
                    break
                if size == 32:
                    break
            if not progress:
                break
    require(0 < len(selected) <= 96, 'no eligible diagnosis cases')
    return selected


def search(binary, knowledge, case, history, ms, depth=None):
    engine = Analyzer(binary, knowledge)
    try:
        return engine.search(case['start_sfen'], tuple(history), ms, depth)
    finally:
        engine.close()


def analyze_case(binary, knowledge, case):
    history = tuple(case['history_moves'])
    short = search(binary, knowledge, case, history, 50)
    deep = search(binary, knowledge, case, history, 500)
    alt = deep['bestmove']
    result = dict(case=case, root_short=short, root_deep=deep, research_move=alt,
                  same_as_actual=alt == case['actual_move'], followup=None)
    if alt in ('resign','win') or case['actual_move'] == alt:
        result['route'] = 'knowledge_reference_candidate' if alt == short['bestmove'] and exact_cp(deep) else 'hold'
        result['local_comparison'] = None
        return result
    pairs = {}
    for ms in (50,500):
        actual = search(binary, knowledge, case, history+(case['actual_move'],), ms)
        better = search(binary, knowledge, case, history+(alt,), ms)
        pairs[str(ms)] = dict(actual=actual, research=better, comparison=compare_children(actual, better))
    result['child_pairs'] = pairs
    result['local_comparison'] = pairs['500']['comparison']
    result['route'] = 'needs_verification'
    return result


def route_result(result):
    if result['same_as_actual']:
        return result.get('route','hold')
    pair = result.get('followup') or result.get('child_pairs',{}).get('500')
    if not pair or pair['comparison']['status'] != 'comparable':
        return 'hold'
    if pair['comparison']['improvement_cp'] < 150:
        return 'hold'
    case = result['case']
    if result['root_short']['bestmove'] == case['actual_move']:
        return 'search_horizon_candidate'
    # A deep preference is a provisional research label, never a proof of evaluation causality.
    if result['root_short']['bestmove'] == result['research_move']:
        return 'stable_research_move_candidate'
    return 'mixed_or_unstable'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive-dirs',type=Path,nargs='+',required=True)
    p.add_argument('--binary',type=Path,required=True)
    p.add_argument('--knowledge',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args()
    require(not args.output_dir.exists(), 'output exists; do not overwrite previous diagnosis')
    require(sha256(args.knowledge.read_bytes())=='6da204cd1e65600ccdbb9f3dbe463627687d6cf7eb8347da6a103239129dac4c','knowledge hash mismatch')
    args.output_dir.mkdir(parents=True)
    lock=args.output_dir/'operation.lock'
    with lock.open('x') as f:f.write(str(os.getpid()))
    started=time.monotonic()
    try:
        games=[]
        for directory in args.archive_dirs:games.extend(load_archive(directory))
        engine=Analyzer(args.binary,args.knowledge)
        values={}
        try:
            for index,g in enumerate(games,1):
                board=shogi.Board(g.start_sfen)
                for row in g.row['moves']+[None]:
                    sfen=board.sfen()
                    if sfen not in values:values[sfen]=engine.static(sfen)
                    if row is not None:board.push_usi(row['move'])
                if index%50==0:print(json.dumps({'stage':'static_scan','games':index,'unique_static_positions':len(values)}),flush=True)
        finally:engine.close()
        cases=select_cases(games,values)
        dump(args.output_dir/'selected-cases.json',cases)
        results=[]
        for index,case in enumerate(cases,1):
            result=analyze_case(args.binary,args.knowledge,case)
            results.append(result)
            dump(args.output_dir/'checkpoint.json',dict(completed=index,total=len(cases),pid=os.getpid(),results=results))
            print(json.dumps({'stage':'analysis','completed':index,'total':len(cases),'route':result['route']}),flush=True)
        # Follow-up selected once by provisional loss and disagreement, never by game outcome.
        pending=[r for r in results if r.get('child_pairs') and
                 all(exact_cp(r['child_pairs']['500'][side]) for side in ('actual','research'))]
        pending.sort(key=lambda r:(-(r['local_comparison'].get('improvement_cp') or 0),r['case']['case_id']))
        for r in pending[:16]:
            depth=min(r['child_pairs']['500'][side]['depth'] for side in ('actual','research'))
            history=tuple(r['case']['history_moves'])
            a=search(args.binary,args.knowledge,r['case'],history+(r['case']['actual_move'],),5000,depth)
            b=search(args.binary,args.knowledge,r['case'],history+(r['research_move'],),5000,depth)
            comp=compare_children(a,b)
            if a.get('depth')!=depth or b.get('depth')!=depth:comp['status']='fixed_depth_incomplete'
            r['followup']=dict(requested_depth=depth,actual=a,research=b,comparison=comp)
        for r in results:r['route']=route_result(r)
        dump(args.output_dir/'diagnosis.json',results)
        summary=dict(source_games=len(games),source_plies=sum(len(g.moves) for g in games),
                     unique_static_positions=len(values),selected_cases=len(cases),
                     categories=dict(collections.Counter(c['triage']['category'] for c in cases)),
                     selected_side=dict(collections.Counter(c['side_to_move'] for c in cases)),
                     selected_reward=dict(collections.Counter(str(c['outcome']['terminal_reward_stm']) for c in cases)),
                     routes=dict(collections.Counter(r['route'] for r in results)),
                     verification_pairs=sum(r['followup'] is not None for r in results),
                     analyzer_binary_sha256=sha256(args.binary.read_bytes()),knowledge_sha256=sha256(args.knowledge.read_bytes()),
                     options=OPTIONS,fresh_process_per_search=True,
                     seconds=round(time.monotonic()-started,3),environment=dict(platform=platform.platform(),cpu_count=os.cpu_count()),
                     status='diagnosis_completed',learning_status='not_run',formal_adoption=False,
                     limitation='Provisional own-engine diagnosis; deeper search and fixed-depth pairing do not prove correct play or evaluation causality.')
        dump(args.output_dir/'summary.json',summary)
        print(json.dumps(summary),flush=True)
    finally:
        lock.unlink(missing_ok=True)


if __name__=='__main__':main()
