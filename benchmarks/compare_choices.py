"""Common-position comparison with a material-only equivalence control."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmarks.arena import Engine
import shogi

p=argparse.ArgumentParser();p.add_argument('--current',required=True);p.add_argument('--baseline',required=True);p.add_argument('--probe',required=True);p.add_argument('--match',required=True);p.add_argument('--output',required=True);a=p.parse_args()
new=Engine(a.current,'features');old=Engine(a.baseline,'v009');control=Engine(a.current,'material control',{'EvalProfile':'material'})
records=json.loads(Path(a.match).read_text())['details'];positions=[[]]
for game in records[:3]:
    for ply in (16,32,48,64):
        if len(game['moves'])>ply:positions.append(game['moves'][:ply])
rows=[]
try:
    for i,moves in enumerate(positions):
        board=shogi.Board()
        for move in moves:board.push_usi(move)
        for e in (new,old,control):e.configure_game(70000+i)
        nm=new.bestmove(moves);om=old.bestmove(moves);cm=control.bestmove(moves)
        assert om==cm,(board.sfen(),om,cm)
        assert old.search_stats[-1]['nodes']==control.search_stats[-1]['nodes']
        def piece_at_move(move):
            if '*' in move:return move[0]+'*'
            return str(board.piece_at(shogi.SQUARE_NAMES.index(move[:2])))
        rows.append({'sfen':board.sfen(),'moves':moves,'seed':70000+i,'features_move':nm,'v009_move':om,
                     'features_piece':piece_at_move(nm),'v009_piece':piece_at_move(om),
                     'same_material_choice':True,'same_material_nodes':True,
                     'features_nodes':new.search_stats[-1]['nodes'],'v009_nodes':old.search_stats[-1]['nodes']})
finally:
    for e in (new,old,control):e.close()
result={'samples':len(rows),'changed':sum(r['features_move']!=r['v009_move'] for r in rows),
        'material_only_equivalence':'exact same choices and nodes as original v0.0.9 on every sample','positions':rows}
Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
