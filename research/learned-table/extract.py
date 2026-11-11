# Build training rows: for every position (ply>=10) of every decisive game:
# label = 1 if Black eventually wins; features = material (Black-White, engine values), stm,
# and king-relative piece-square indicators (own-king table A, enemy-king table B), Black +1 / White -1.
import json,sys,glob,numpy as np,scipy.sparse as sp,shogi
BASE=[0,120,310,440,650,1250,1650,750,0]; PROM=[0,760,810,860,920,1850,2400,0,0]; HAND=[0,180,460,630,900,1850,2350,1060,0]
# python-shogi piece types -> engine kind, promoted
PT={shogi.PAWN:(1,0),shogi.LANCE:(2,0),shogi.KNIGHT:(3,0),shogi.SILVER:(4,0),shogi.BISHOP:(5,0),shogi.ROOK:(6,0),shogi.GOLD:(7,0),
    shogi.PROM_PAWN:(1,1),shogi.PROM_LANCE:(2,1),shogi.PROM_KNIGHT:(3,1),shogi.PROM_SILVER:(4,1),shogi.PROM_BISHOP:(5,1),shogi.PROM_ROOK:(6,1)}
NT=13; NA=NT*17*17
def tindex(kind,prom): return (kind-1) if not prom else 6+kind   # 0..6, 7..12
def feats(b):
    ks=[None,None]
    for c in (0,1):
        k=b.king_squares[c]
        if k is None: return None
        ks[c]=(8-k%9,k//9)
    mat=0; idx={}
    for sq in range(81):
        pc=b.piece_at(sq)
        if pc is None or pc.piece_type==shogi.KING: continue
        kind,prom=PT[pc.piece_type]; c=pc.color; sgn=1 if c==0 else -1
        mat+=sgn*(PROM[kind] if prom else BASE[kind])
        f,r=8-sq%9,sq//9; t=tindex(kind,prom)
        for tab,(kf,kr) in ((0,ks[c]),(1,ks[1-c])):
            dx,dy=(f-kf,r-kr) if c==0 else (kf-f,kr-r)
            i=tab*NA+(t*17+dx+8)*17+dy+8
            idx[i]=idx.get(i,0)+sgn
    for c in (0,1):
        sgn=1 if c==0 else -1
        for pt,n in b.pieces_in_hand[c].items(): mat+=sgn*n*HAND[PT[pt][0]]
    return mat,idx
def games():
    # yields (moves, black_wins, {position index (moves played) -> search score from Black's view})
    for path in sys.argv[2:]:
        if path.endswith('.jsonl'):
            for l in open(path):
                g=json.loads(l)
                if g['winner'] not in('A','B'): continue
                off=len(g['moves'])-len(g['ev']); sc={}
                for i,e in enumerate(g['ev']):
                    if e[1] is None: continue
                    k=off+i; sc[k]=e[1] if k%2==0 else -e[1]
                yield g['moves'], (g['winner']=='A')==bool(g['a_black']), sc
        else:
            d=json.load(open(path))
            for g in d['details']:
                if g['winner'] not in('A','B'): continue
                sc={}
                for r in g['move_records']:
                    v=(r.get('search') or {}).get('score_black_cp')
                    if v is not None: sc[r['ply']-1]=v
                yield g['moves'], (g['winner']=='A')==bool(g['a_black']), sc
rows=[];cols=[];vals=[];mats=[];stms=[];ys=[];gid=[];scs=[];n=0
for gi,(moves,black_wins,sc) in enumerate(games()):
    b=shogi.Board()
    for ply,m in enumerate(moves):
        # position before move index `ply`
        if ply>=8 and ply in sc and not b.is_check():
            r=feats(b)
            if r is None: break
            mat,idx=r
            for i,v in idx.items():
                if v: rows.append(n);cols.append(i);vals.append(v)
            mats.append(mat);stms.append(1 if b.turn==0 else -1);ys.append(1 if black_wins else 0);gid.append(gi);scs.append(max(-3000,min(3000,sc[ply])));n+=1
        try: b.push_usi(m)
        except Exception: break
X=sp.csr_matrix((vals,(rows,cols)),shape=(n,2*NA),dtype=np.float32)
sp.save_npz(sys.argv[1]+'_X.npz',X); np.savez(sys.argv[1]+'_m.npz',mat=np.array(mats),stm=np.array(stms),y=np.array(ys),gid=np.array(gid),sc=np.array(scs))
print('rows',n,'games',gi+1,'black win rate',np.mean(ys))
