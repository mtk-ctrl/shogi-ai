"""Frozen lineage and fresh-seed contract for repeated contextual learning."""
import json
import re
from pathlib import Path

def validate_execution(execution,model,base,core):
    if execution.get('schema')!='structured-cycle-execution-v1' or execution.get('max_games')!=1600:
        raise ValueError('fixed per-cycle execution budget required')
    if not re.fullmatch('[a-z0-9][a-z0-9-]{3,90}',execution.get('cycle_id','')):
        raise ValueError('one immutable cycle identifier is required')
    parent=execution['comparison_parent']
    if not re.fullmatch('[0-9a-f]{40}',parent.get('engine_ref','')):
        raise ValueError('immutable comparison-parent engine required')
    if parent.get('model_sha256')!=model.get('parent_model_sha256'):
        raise ValueError('the learned parent cannot be reset or exchanged')
    expected=dict(base,**core)
    if parent['model_sha256'] is not None:
        if not re.fullmatch('[0-9a-f]{64}',parent['model_sha256']):raise ValueError('invalid parent model identity')
        expected.update(StructuredEval=True,StructuredScale=model['parent_scale'])
    if parent.get('options')!=expected:raise ValueError('comparison must use the actual frozen parent configuration')
    seeds=execution['seeds']
    if set(seeds)!={'screens','confirmation','next_source'} or len(seeds['screens'])!=3:
        raise ValueError('three fixed candidate seeds, one confirmation and one next-source seed required')
    all_seeds=seeds['screens']+[seeds['confirmation'],seeds['next_source']]
    if len(set(all_seeds))!=5 or any(type(s)is not int or not 0<=s<=2145483647 for s in all_seeds):
        raise ValueError('fresh seed entries must leave room for all shards')
    if set(all_seeds)&set(execution.get('used_seed_bases',[])):
        raise ValueError('used evaluation seeds cannot be presented as fresh')
    # Each body can add up to 19*100000 plus per-game offsets. A new base
    # must not reuse an old lane's effective seed under a different label.
    block=2000000
    if any(abs(seed-old)<block for seed in all_seeds for old in execution.get('used_seed_bases',[])):
        raise ValueError('effective shard seeds overlap previously used games')
    if any(abs(seeds['confirmation']-s)<block for s in seeds['screens']):
        raise ValueError('confirmation overlaps candidate-selection shard seeds')
    if any(abs(seeds['next_source']-s)<block for s in seeds['screens']+[seeds['confirmation']]):
        raise ValueError('next source overlaps already used comparison shard seeds')
    if not execution.get('training_publications'):raise ValueError('actual source publications required')
    return parent,seeds

def comparison_request(candidate_ref,parent,base,core,scale,games,shards,seed,own=False):
    oa=dict(base,**core,StructuredEval=True,StructuredScale=scale)
    return dict(ref_a=candidate_ref,ref_b=candidate_ref if own else parent['engine_ref'],
        games=games,shards=shards,seed=seed,go_command='go movetime 200',max_plies=300,
        options_a=json.dumps(oa,sort_keys=True),options_b=json.dumps(oa if own else parent['options'],sort_keys=True))
