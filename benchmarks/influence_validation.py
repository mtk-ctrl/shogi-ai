"""Controlled common-position choices and exact OFF equivalence for influence."""
import argparse,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmarks.arena import Engine
import shogi

def evaluation(engine,moves):
    engine.send('position startpos'+(' moves '+' '.join(moves) if moves else ''))
    engine.send('eval')
    line=engine.wait_prefix('info string evaluation ',10).split()[3:]
    return dict(zip(line[::2],map(int,line[1::2])))

def main():
    p=argparse.ArgumentParser();p.add_argument('--engine',required=True);p.add_argument('--baseline',required=True)
    p.add_argument('--source',default='benchmarks/results/2026-10-05_v019-mate-assist-50ms-100games-run2.json')
    p.add_argument('--output',required=True);p.add_argument('--options-on',default='{}')
    p.add_argument('--expect-equivalent',action='store_true');args=p.parse_args()
    options_on=json.loads(args.options_on)
    if not isinstance(options_on,dict):raise SystemExit('Options must be a JSON object')
    games=json.loads(Path(args.source).read_text())['details'];positions=[];seen=set()
    for game in games:
        for ply in (8,16,24,32,48,64,80,100):
            moves=game['moves'][:ply]
            if len(moves)<ply:continue
            board=shogi.Board()
            for m in moves:board.push_usi(m)
            key=' '.join(board.sfen().split()[:3])
            if key in seen or board.is_game_over():continue
            seen.add(key);positions.append(moves)
        if len(positions)>=100:break
    positions=positions[:100]
    opts={'ExperienceCache':False,'OpeningBook':False,'MateAssist':False,'Quiescence':False}
    engines=[Engine(args.engine,'ON',{**opts,'EvalInfluence':True,**options_on},'go depth 2'),
             Engine(args.engine,'OFF',{**opts,'EvalInfluence':False},'go depth 2'),
             Engine(args.baseline,'original',opts,'go depth 2')]
    rows=[]
    try:
        for i,moves in enumerate(positions):
            values=[evaluation(e,moves) for e in engines]
            for e in engines:e.configure_game(2026100610+i)
            choices=[e.bestmove(moves) for e in engines]
            stats=[e.last_search for e in engines]
            assert values[1]==values[2],('OFF evaluation changed',i,values)
            assert choices[1]==choices[2],('OFF choice changed',i,choices)
            assert (stats[1].get('score_cp'),stats[1].get('score_mate'),stats[1].get('nodes'))==\
                (stats[2].get('score_cp'),stats[2].get('score_mate'),stats[2].get('nodes')),('OFF search changed',i)
            if args.expect_equivalent:
                assert values[0]==values[1] and choices[0]==choices[1],('cost control changed evaluation/choice',i)
                assert tuple(stats[0].get(k) for k in ('score_cp','score_mate','nodes'))==\
                    tuple(stats[1].get(k) for k in ('score_cp','score_mate','nodes')),('cost control changed search',i)
            board=shogi.Board()
            for m in moves:board.push_usi(m)
            assert all(shogi.Move.from_usi(m) in board.legal_moves for m in choices)
            rows.append({'moves':moves,'sfen':board.sfen(),'eval_on':values[0],'eval_off':values[1],
                         'move_on':choices[0],'move_off':choices[1],
                         'search_on':stats[0],'search_off':stats[1]})
        out={'samples':len(rows),'fixed_depth':2,'quiescence':False,'book':False,'options_on':options_on,
             'expected_equivalence':args.expect_equivalent,
             'changed_moves':sum(r['move_on']!=r['move_off'] for r in rows),
             'changed_evaluations':sum(r['eval_on']!=r['eval_off'] for r in rows),
             'off_equivalence':'evaluation, bestmove, score and nodes exactly match original on all samples',
             'rows':rows}
        Path(args.output).parent.mkdir(parents=True,exist_ok=True)
        Path(args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({k:v for k,v in out.items() if k!='rows'},ensure_ascii=False),flush=True)
        if not args.expect_equivalent and not out['changed_moves']:raise SystemExit('Influence did not affect choices; do not run match')
    finally:
        for e in engines:e.close()
if __name__=='__main__':main()
