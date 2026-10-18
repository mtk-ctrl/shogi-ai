#!/usr/bin/env python3
"""Enumerate relative gold/silver drop layouts and one-piece protectors.

This is a geometric inventory, NOT a sufficient test of a winning fork.
Kings, pins, checks, promotion zones, extra pieces and other enemy replies
belong to validation in the actual position. Material columns describe only
capture at the drop square -> recapture -> capture at the same square again.
"""
import csv
import itertools
import json
from pathlib import Path
import shogi
from diagnose_hand_drops import ROOT, VALUES, UNPROMOTE, sq

KINDS=tuple(k for k in VALUES if k!=shogi.KING)
LABEL={1:'歩',2:'香',3:'桂',4:'銀',5:'金',6:'角',7:'飛',9:'と',10:'成香',
       11:'成桂',12:'成銀',13:'馬',14:'龍'}
CENTER=sq('5e')
OFFSETS={shogi.SILVER:((-1,-1),(0,-1),(1,-1),(-1,1),(1,1)),
         shogi.GOLD:((-1,-1),(0,-1),(1,-1),(-1,0),(1,0),(0,1))}


def square(offset):
    dx,dy=offset
    return sq(str(5+dx)+chr(ord('e')+dy))


def capture_value(kind):
    # Capturing a promoted piece removes its board value and adds the
    # unpromoted kind to the capturer's hand.
    return VALUES[kind]+VALUES[UNPROMOTE.get(kind,kind)]


def attacks(kind,origin,occupied,color,destination):
    return bool(shogi.Board.attacks_from(kind,origin,occupied,color)&(1<<destination))


def inventory():
    empty=shogi.Occupied(0,0)
    protector_origins={k:[s for s in shogi.SQUARES if s!=CENTER and
                         attacks(k,s,empty,shogi.BLACK,CENTER)] for k in KINDS}
    rows=[]
    for hand,offsets in OFFSETS.items():
        for o1,o2 in itertools.combinations(offsets,2):
            s1,s2=square(o1),square(o2)
            occupied=shogi.Occupied(1<<CENTER,(1<<s1)|(1<<s2))
            for k1,k2 in itertools.product(KINDS,repeat=2):
                capturers=[(s,k) for s,k in ((s1,k1),(s2,k2))
                           if attacks(k,s,occupied,shogi.WHITE,CENTER)]
                best3=best4=None; example3=example4=''
                count=safe_count=0
                for support in KINDS:
                    for origin in protector_origins[support]:
                        if origin in (s1,s2): continue
                        occupied.ixor(1<<origin,shogi.BLACK,origin)
                        protects=attacks(support,origin,occupied,shogi.BLACK,CENTER)
                        vulnerable=any(attacks(k,s,occupied,shogi.WHITE,origin)
                                       for s,k in ((s1,k1),(s2,k2)))
                        if protects:
                            count+=1
                            if not vulnerable:
                                safe_count+=1
                                # No capture of the drop is a pressure candidate,
                                # not a proof of future material gain.
                                value3=min((capture_value(k)-capture_value(hand)
                                            for s,k in capturers),default=0)
                                value4=min((capture_value(k)-capture_value(hand)
                                            -(capture_value(support) if len(capturers)>1 else 0)
                                            for s,k in capturers),default=0)
                                example=LABEL[support]+shogi.SQUARE_NAMES[origin]
                                if best3 is None or value3>best3: best3,example3=value3,example
                                if best4 is None or value4>best4: best4,example4=value4,example
                        occupied.ixor(1<<origin,shogi.BLACK,origin)
                rows.append({'hand':LABEL[hand],'target_square_1':shogi.SQUARE_NAMES[s1],
                             'target_kind_1':LABEL[k1],'target_square_2':shogi.SQUARE_NAMES[s2],
                             'target_kind_2':LABEL[k2],
                             'target_1_can_capture_drop':(s1,k1) in capturers,
                             'target_2_can_capture_drop':(s2,k2) in capturers,
                             'unsupported_no_direct_capture':not capturers,
                             'one_support_patterns':count,'support_not_attacked_by_targets_patterns':safe_count,
                             'best_worst_capture_recapture_3ply':best3,
                             'example_support_3ply':example3,
                             'best_worst_same_square_capture_chain_4ply':best4,
                             'example_support_4ply':example4})
    return rows


def pair_summary(rows,hand,a,b):
    selected=[r for r in rows if r['hand']==hand and
              sorted((r['target_kind_1'],r['target_kind_2']))==sorted((a,b))]
    return {'hand':hand,'targets':a+'/'+b,'layouts':len(selected),
            'unsupported_no_direct_capture':sum(r['unsupported_no_direct_capture'] for r in selected),
            'one_support_3ply_nonlosing':sum(r['best_worst_capture_recapture_3ply'] is not None and
                                           r['best_worst_capture_recapture_3ply']>=0 for r in selected),
            'one_support_3ply_gain':sum(r['best_worst_capture_recapture_3ply'] is not None and
                                      r['best_worst_capture_recapture_3ply']>0 for r in selected),
            'one_support_4ply_nonlosing':sum(r['best_worst_same_square_capture_chain_4ply'] is not None and
                                           r['best_worst_same_square_capture_chain_4ply']>=0 for r in selected)}


def main():
    rows=inventory()
    out=ROOT/'benchmarks/positions/gold_silver_fork_inventory.csv'
    with out.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)
    normal=('歩','香','桂','銀','金','角','飛')
    summary=[pair_summary(rows,h,a,b) for h in ('銀','金')
             for a,b in itertools.combinations_with_replacement(normal,2)]
    report={'center':'5e','orientation':'black; reflect 180 degrees and swap colors for white',
            'enemy_kinds':[LABEL[k] for k in KINDS],'supporter_kinds':[LABEL[k] for k in KINDS],
            'layout_count':25,'rows':len(rows),'scope':'geometry and same-square capture chains only; no kings/pins/checks/promotion/other replies',
            'support_filter':'supporter is not initially attacked by either target; other threats are not modeled',
            'material':'engine piece values, board removal plus unpromoted hand acquisition',
            'summary':summary}
    (ROOT/'benchmarks/positions/gold_silver_fork_inventory_summary.json').write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('layouts',25,'placements',len(rows),'csv_bytes',out.stat().st_size,flush=True)
    for hand,a,b in (('銀','金','銀'),('金','金','金'),('銀','金','金'),('金','銀','銀')):
        print(pair_summary(rows,hand,a,b),flush=True)


if __name__=='__main__':main()
