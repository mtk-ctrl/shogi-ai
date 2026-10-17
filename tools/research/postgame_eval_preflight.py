#!/usr/bin/env python3
"""Actual own-binary candidate gates, separate from the learning surrogate."""
from __future__ import annotations
import copy
import shogi
from tools.research.postgame_analyze import Analyzer, exact_cp
from tools.research.postgame_ranker import OPTIONS, POLICY, digest, parent_values, require

POLICY_LIVE = dict(fixed_depth=2, fixed_timeout_ms=5000, probe_ms=200,
                   speed_cases=16, min_depth_ratio=.9, tactical_cases=12,
                   heldout_limit=96, trials=1)


def tactical_cases():
    """Small own-authored hanging-piece controls; no external teacher."""
    rows=[]
    for target in (shogi.SILVER, shogi.GOLD, shogi.BISHOP):
        for source, destination in (("5e", "5c"), ("4e", "4c")):
            for rotated in (False, True):
                b=shogi.Board(); b.clear()
                for square, kind, color in (("9i",shogi.KING,0),("1a",shogi.KING,1),
                                            (source,shogi.ROOK,0),(destination,target,1)):
                    sq=shogi.SQUARE_NAMES.index(square)
                    if rotated: sq,color=80-sq,1-color
                    b.set_piece_at(sq,shogi.Piece(kind,color))
                b.turn=int(rotated)
                src=shogi.SQUARE_NAMES[80-shogi.SQUARE_NAMES.index(source)] if rotated else source
                dst=shogi.SQUARE_NAMES[80-shogi.SQUARE_NAMES.index(destination)] if rotated else destination
                rows.append(dict(case_id="capture-"+digest([source,destination,target,rotated])[:16],
                                 start_sfen=b.sfen(),history_moves=[],expected_prefix=src+dst))
    return rows


def live_preflight(parent_options, candidate_options, preparation, cases, probe):
    """probe(case, options, milliseconds, optional_depth)->validated own search."""
    parent_values(parent_options); parent_values(candidate_options)
    require(parent_options != candidate_options, "unchanged candidate")
    require(all(abs(candidate_options[k]-parent_options[k]) <= parent_options[k]*POLICY['max_fraction']+1e-9
                for k in OPTIONS), "candidate exceeded frozen parent-relative update bound")
    rows=preparation['examples']; lookup={c['case_id']:c for c in cases}
    require(len(lookup)==len(cases), "duplicate case histories")
    require(all(r['case_id'] in lookup for r in rows), "missing original eligible case history")
    heldout=sorted((r for r in rows if r['split']=='heldout'),key=lambda r:r['case_id'])
    require(0<len(heldout)<=POLICY_LIVE['heldout_limit'], "unused-case preflight bound exceeded")
    observations=[]; regressions=0; improved=0; disabled=True
    controls=tactical_cases()
    for case in controls:
        pair=[probe(case,parent_options,5000,2) for _ in range(2)]
        keys=('bestmove','kind','value_stm','depth','bound','status')
        disabled &= all(exact_cp(p) and p.get('depth')==2 for p in pair) and all(pair[0].get(k)==pair[1].get(k) for k in keys)
        actual=[probe(case,opts,200,None) for opts in (parent_options,candidate_options)]
        ok=[p['bestmove'].startswith(case['expected_prefix']) for p in actual]
        # Broken parent control invalidates the gate too; it is not credited as
        # candidate improvement and is not silently removed after seeing results.
        regressions += int(not all(ok))
        observations.append(dict(case_id=case['case_id'],kind='tactical',parent=actual[0],candidate=actual[1],correct=ok))
    for row in heldout:
        case=lookup[row['case_id']]
        pair=[probe(case,opts,200,None) for opts in (parent_options,candidate_options)]
        require(all(p['history_key']==case['history_key'] for p in pair), "unused-case history was changed")
        correct=[p['bestmove']==case['research_move'] for p in pair]
        usable=all(exact_cp(p) for p in pair)
        improved += int(usable and correct == [False,True])
        regressions += int(correct == [True,False])
        observations.append(dict(case_id=case['case_id'],kind='heldout',parent=pair[0],candidate=pair[1],correct=correct))
    # Speed positions are chosen from train/validation only, before timings.
    speed=sorted((r for r in rows if r['split']!='heldout'),key=lambda r:digest(['speed-v1',r['case_id']]))[:16]
    require(speed, "no fixed speed controls")
    depths=[0,0]; missing=0
    for row in speed:
        case=lookup[row['case_id']]
        pair=[probe(case,opts,200,None) for opts in (parent_options,candidate_options)]
        for i,p in enumerate(pair):
            if type(p.get('depth')) is int and p['depth']>0: depths[i]+=p['depth']
            else: missing+=1
        observations.append(dict(case_id=case['case_id'],kind='speed',parent=pair[0],candidate=pair[1]))
    ratio=depths[1]/depths[0] if depths[0] else 0.
    if missing: regressions+=missing
    return dict(schema='postgame-live-preflight-v1',completed=True,disabled_exact=bool(disabled),
                regressions=regressions,heldout_improved=improved,depth_ratio=ratio,
                depth_sum_parent=depths[0],depth_sum_candidate=depths[1],missing_depth=missing,
                policy=POLICY_LIVE,observations=observations,
                parent_parameters_sha256=digest(parent_options),candidate_parameters_sha256=digest(candidate_options),
                limitation='Fixed small regression/selected-case gate, not proof of general strength.',formal_adoption=False)


def run(binary, knowledge, parent_options, candidate_options, preparation, cases):
    def probe(case,options,ms,depth):
        e=Analyzer(binary,knowledge,evaluation_options=options)
        try: return e.search(case['start_sfen'],tuple(case['history_moves']),ms,depth)
        finally: e.close()
    return live_preflight(parent_options,candidate_options,preparation,cases,probe)
