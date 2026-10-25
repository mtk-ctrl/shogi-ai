"""Resumable paired evaluation using the normal arena and fixed native options."""
import json
import math
import queue
from pathlib import Path
import time

from benchmarks.arena import Engine, play_game, position_knowledge_metadata, search_summary
from tools.research.nnue_cycle import atomic_json
from tools.research.neural_model import digest


class CheckedEngine(Engine):
    """A failed model load must not be counted as an ordinary resignation."""
    def __init__(self,*args,**kwargs):
        self.handshake=[]
        try:
            super().__init__(*args,**kwargs)
            if 'id name KUMOJI v2.0.21' not in self.handshake:
                raise ValueError('unexpected own-engine identity')
            if not any('position_knowledge loaded 163 positions file ' in s for s in self.handshake):
                raise ValueError('adopted knowledge not loaded')
            if self.options.get('EvalNeural') and not any('neural_evaluation loaded width ' in s for s in self.handshake):
                raise ValueError('neural model load not confirmed')
        except BaseException:
            if hasattr(self,'proc'):
                self.close()
            raise

    def wait_prefix(self,prefix,timeout):
        deadline=time.monotonic()+timeout
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:
                raise TimeoutError('neural arena handshake timed out')
            try:
                line=self.lines.get(timeout=remaining)
            except queue.Empty as ex:
                raise TimeoutError('neural arena handshake timed out') from ex
            if any(s in line for s in ('neural_evaluation error','search error','invalid position')):
                raise ValueError('native engine rejected research input: '+line)
            self.handshake.append(line)
            if line.startswith(prefix):
                return line


def options(knowledge, model=None):
    result = dict(PositionKnowledge=True,PositionKnowledgeFile=str(Path(knowledge).resolve()),
        SearchThreads=2,USI_Ponder=True,AdaptiveLongThink=True,RiskVerify=True,
        OpeningRandomNonLance=True)
    if model:
        with Path(model).open('rb') as source:
            correction = source.read(8) == b'KMNNUE04'
        result.update(EvalNeuralFile=str(Path(model).resolve()),EvalNeural=True,EvalNeuralPolicy=not correction)
    return result


def paired_match(binary, knowledge, output, games, seed, candidate=None, parent=None,
                 max_plies=400, movetime=200, pair_offset=0):
    if games < 2 or games%2 or movetime < 1 or pair_offset < 0:
        raise ValueError('even paired games and positive time required')
    if seed < 0 or seed + 2 * (pair_offset + games//2) > 2147483647:
        raise ValueError('paired seeds exceed the USI integer range')
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    oa,ob=options(knowledge,candidate),options(knowledge,parent)
    identity=dict(binary_sha256=digest(binary),knowledge_sha256=digest(knowledge),
        candidate_sha256=digest(candidate) if candidate else None,
        parent_sha256=digest(parent) if parent else None,games=games,seed=seed,
        max_plies=max_plies,movetime=movetime)
    if pair_offset:
        identity['pair_offset']=pair_offset
    plan=output/'plan.json'
    if plan.exists() and json.loads(plan.read_text()) != identity:
        raise ValueError('match resume inputs changed')
    atomic_json(plan,identity)
    paths=[]
    for pair in range(pair_offset,pair_offset+games//2):
        path=output/f'pair-{pair:05d}.json'
        paths.append(path)
        if path.exists():
            existing=json.loads(path.read_text())
            if len(existing['details']) != 2 or existing.get('identity') != identity:
                raise ValueError('invalid saved match pair')
            continue
        a=CheckedEngine(str(Path(binary).resolve()),'A',oa,f'go movetime {movetime}')
        b=None
        started=time.monotonic()
        try:
            b=CheckedEngine(str(Path(binary).resolve()),'B',ob,f'go movetime {movetime}')
            details=[]
            for index in range(2):
                # Same black/white seeds in both colors; disjoint across pairs.
                g=play_game(a,b,index,max_plies,seed+pair*2-index*2)
                details.append(g)
            record=dict(identity=identity,engine_a=str(Path(binary).resolve()),
                engine_b=str(Path(binary).resolve()),sha256_a=digest(binary),sha256_b=digest(binary),
                options_a=oa,options_b=ob,seed=seed+pair*2,paired_seeds=True,
                games=2,game_offset=pair*2,go_command=f'go movetime {movetime}',max_plies=max_plies,
                wins_a=sum(g['winner']=='A' for g in details),wins_b=sum(g['winner']=='B' for g in details),
                draws=sum(g['winner'] is None for g in details),
                illegal_games=sum('illegal_by' in g for g in details),details=details,
                position_knowledge={'A':position_knowledge_metadata(oa),'B':position_knowledge_metadata(ob)},
                search={'A':search_summary(a),'B':search_summary(b)},
                elapsed_seconds=time.monotonic()-started,telemetry_schema_version=1)
            atomic_json(path,record)
            print(json.dumps(dict(pair=pair-pair_offset+1,total=games//2,wins_a=record['wins_a'],
                                  wins_b=record['wins_b'],draws=record['draws'])),flush=True)
        finally:
            a.close()
            if b:
                b.close()
    records=[json.loads(p.read_text()) for p in paths]
    result=summarize_records(records,paths,movetime)
    atomic_json(output/'summary.json',result)
    return result


def summarize_records(records, paths, movetime=200):
    """Aggregate complete color pairs; workers never average rounded win rates."""
    if not records or any(len(r['details']) != 2 for r in records):
        raise ValueError('complete paired records required')
    # Bounded pair scores, including two correlated colors in one observation.
    scores=[(r['wins_a']+.5*r['draws'])/2 for r in records]
    invalid=[g for r in records for g in r['details']
             if 'illegal_by' in g or g['reason'] in ('move_limit','max_plies','error','timeout')]
    result=dict(games=2*len(records),pairs=len(scores),score=sum(scores)/len(scores),
        pair_scores=scores,invalid_games=len(invalid),movetime=movetime,
        wins=sum(r['wins_a'] for r in records),losses=sum(r['wins_b'] for r in records),
        draws=sum(r['draws'] for r in records),files=[str(p.resolve()) for p in paths],
        elapsed_seconds=sum(r['elapsed_seconds'] for r in records))
    return result


def gate(parent_match, baseline_match, generation, total_generations, min_games=200):
    # Fixed-size, preregistered gate. Bonferroni across parents/baselines and
    # all generations + Hoeffding for bounded paired observations. No peeking
    # at partial wins, no training from these evaluation games.
    alpha=.05/(2*total_generations)
    def lower(match):
        scores=match['pair_scores']
        return sum(scores)/len(scores)-math.sqrt(math.log(1/alpha)/(2*len(scores)))
    lp,lb=lower(parent_match),lower(baseline_match)
    valid=all(m['games']>=min_games and m['movetime']==200 and m['invalid_games']==0
              for m in (parent_match,baseline_match))
    accepted=valid and lp>.5 and lb>.5
    return dict(accepted=accepted,generation=generation,alpha_per_comparison=alpha,
        parent_lower=lp,baseline_lower=lb,minimum_games=min_games,
        reason='independent_matches_passed' if accepted else 'insufficient_or_nonimproving_evidence',
        formal_engine_adopted=False)
