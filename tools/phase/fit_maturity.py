#!/usr/bin/env python3
"""Iterative offline phase model comparison. Never changes production engine.

Historic end-ply percentage is ONE imperfect proxy, not a definition of
strategic phase. All features at prediction time come from the current
position. Train/validation/test split is by whole game. Validation and test
are not used to fit coefficients. Hypothesis families selected beforehand.
"""
import argparse, collections, json, math, random, statistics, sys
from pathlib import Path
import shogi

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.phase.analyze_games import select_games, run_probe
from tools.phase.correlate_terminal_ply import position_features

FAMILIES={
    "3軸基本":("development","battle","invasion"),
    "持ち駒追加":("development","battle","invasion","hand_stage"),
    "成り駒追加":("development","battle","invasion","hand_stage","promo_stage"),
    "前線展開追加":("development","battle","invasion","hand_stage","promo_stage","front_stage"),
    "大駒交換追加":("development","battle","invasion","hand_stage","promo_stage","major_stage"),
    "全現局面7軸":("development","battle","invasion","hand_stage","promo_stage","front_stage","major_stage"),
    "戦闘後半圧縮":("development","battle_sq","invasion","hand_stage","promo_stage","front_stage"),
    "累積履歴参考":("development","battle","invasion","hand_stage","promo_stage","captures_stage"),
}
ORIGINAL={"development":.2,"battle":.4,"invasion":.3,"king_threat":.1}

def stage(x):
    return int(x>=33.333)+int(x>=66.667)
def clamp(x):
    return max(0.,min(100.,x))
def load(paths, probe):
    data=[]; seen=set(); removed=collections.Counter()
    for path in paths:
        raw=json.loads(path.read_text(encoding="utf8"))
        games,dropped=select_games(raw["details"])
        removed.update(dropped)
        for g in games:
            signature=tuple(g["moves"])
            if signature in seen:
                removed["duplicates"]+=1
                continue
            seen.add(signature); data.append(g)
    rows=[]; sfens=[]
    for gid,g in enumerate(data):
        final=len(g["moves"])
        board=shogi.Board(g["sfens"][0])
        events=[]
        captures=promos=checks=0
        cumulative=[(0,0,0)]
        for move_token in g["moves"]:
            move=shogi.Move.from_usi(move_token)
            captured=bool(not move.drop_piece_type and board.piece_at(move.to_square))
            captures+=int(captured); promos+=int(move.promotion)
            board.push(move)
            in_check=bool(board.is_check()); checks+=int(in_check)
            events.append((int(captured),int(in_check)))
            cumulative.append((captures,promos,checks))
        for ply in sorted(set(range(0,final+1,10))|{final}):
            sfen=g["sfens"][ply]
            r={"game":gid,"ply":ply,"final":final,"target":100*ply/final}
            r.update(position_features(sfen))
            r.update({
                "captures_stage":clamp(cumulative[ply][0]*11),
                "hand_stage":clamp(r["hand_count"]*12),
                "promo_stage":clamp(r["promoted"]*18),
                "front_stage":clamp(r["frontline"]*8),
                "major_stage":clamp(r["hand_major"]*38),
                "check_next10":int(any(z[1] for z in events[ply:ply+10])),
                "capture_next10":int(any(z[0] for z in events[ply:ply+10])),
                "check_next20":int(any(z[1] for z in events[ply:ply+20])),
            })
            rows.append(r);sfens.append(sfen)
    scores=run_probe(probe,sfens)
    for r,p in zip(rows,scores):
        r.update(p)
        r["battle_sq"]=r["battle"]*r["battle"]/100
        r["urgency"]=max(r["king_threat"],80 if shogi.Board(sfens[len([])]).is_check() else 0) if False else r["king_threat"]
    for r,sfen in zip(rows,sfens):
        if shogi.Board(sfen).is_check():
            r["urgency"]=max(80,r["urgency"])
    return rows,{"eligible_games":len(data),"positions":len(rows),"exclusions":dict(removed)}

def per_game(rows, values):
    groups=collections.defaultdict(list)
    for r,v in zip(rows,values):
        groups[r["game"]].append(v)
    return statistics.mean(statistics.mean(x) for x in groups.values())
def pct_metrics(rows, preds):
    errs=[abs(r["target"]-p) for r,p in zip(rows,preds)]
    matches=[int(stage(r["target"])==stage(p)) for r,p in zip(rows,preds)]
    d={"mae":round(per_game(rows,errs),3),
       "three_stage_accuracy":round(per_game(rows,matches),4)}
    for ply in (20,40,60,80,100):
        sub=[(r,p) for r,p in zip(rows,preds) if r["ply"]==ply]
        if not sub:continue
        corr=corr_xy([r["target"] for r,p in sub],[p for r,p in sub])
        d["at_"+str(ply)]={"n":len(sub),"mae":round(statistics.mean(abs(r["target"]-p) for r,p in sub),2),
                           "corr":round(corr,4)}
    return d
def corr_xy(xs,ys):
    a=statistics.mean(xs);b=statistics.mean(ys)
    num=sum((x-a)*(y-b) for x,y in zip(xs,ys))
    aa=sum((x-a)**2 for x in xs);bb=sum((y-b)**2 for y in ys)
    return num/math.sqrt(aa*bb) if aa*bb>0 else 0
def auc(rows,score,truth):
    pairs=sorted((float(r[score]),r[truth]) for r in rows)
    ones=sum(label for _,label in pairs)
    zeros=len(pairs)-ones
    if not ones or not zeros:return None
    rank_sum=0.;i=0
    while i<len(pairs):
        j=i+1
        while j<len(pairs) and pairs[j][0]==pairs[i][0]:j+=1
        rank=(i+1+j)/2
        rank_sum+=sum(label for _,label in pairs[i:j])*rank
        i=j
    return round((rank_sum-ones*(ones+1)/2)/(ones*zeros),4)
def draw_weights(rng,n):
    z=[rng.gammavariate(.85,1) for _ in range(n)]
    s=sum(z)
    return tuple(x/s for x in z)
def measure(rows, features, w, gain=1.,shift=0.):
    return [clamp(gain*sum(a*r[f] for a,f in zip(w,features))+shift) for r in rows]
def loss(rows,features,w,gain=1.,shift=0.):
    vals=measure(rows,features,w,gain,shift)
    return per_game(rows,[abs(r["target"]-v) for r,v in zip(rows,vals)])
def split_games(rows):
    ids=sorted({r["game"] for r in rows})
    random.Random(20261011).shuffle(ids)
    n=len(ids); tr=set(ids[:int(n*.62)]);va=set(ids[int(n*.62):int(n*.8)]);te=set(ids[int(n*.8):])
    return [[r for r in rows if r["game"] in ids] for ids in (tr,va,te)]
def optimize(train,valid,features,seed):
    rng=random.Random(seed)
    n=len(features)
    initial=[]
    # Hand-designed seed distributions + broad non-negative simplex sampling.
    for j in range(n):
        w=[.05/(n-1)]*n;w[j]=.95
        initial.append(tuple(w))
    initial.append(tuple([1/n]*n))
    if n>=3:
        for first in ((.5,.2,.3),(.2,.4,.4),(.35,.35,.30)):
            w=list(first)+[.06]*(n-3);z=sum(w);initial.append(tuple(x/z for x in w))
    initial.extend(draw_weights(rng,n) for _ in range(290))
    candidates=[]
    for w in initial:
        for gain in (.85,1.,1.15):
            for offset in (-12.,-5.,0.,5.,12.):
                tr=loss(train,features,w,gain,offset)
                candidates.append((tr,w,gain,offset))
    candidates.sort(key=lambda x:x[0])
    # Iterative coordinate perturbation around promising training configurations.
    top=candidates[:8]
    for iteration in range(3):
        trials=[]
        for score,w,gain,offset in top:
            trials.append((score,w,gain,offset))
            for _ in range(28):
                j=rng.randrange(n);k=rng.randrange(n)
                if j==k:continue
                ww=list(w);delta=rng.choice((-.14,-.06,.06,.14))
                ww[j]=max(.005,ww[j]+delta)
                ww[k]=max(.005,ww[k]-delta)
                z=sum(ww);ww=tuple(x/z for x in ww)
                g=max(.7,min(1.4,gain+rng.choice((-.08,0,.08))))
                off=max(-20,min(20,offset+rng.choice((-5,0,5))))
                trials.append((loss(train,features,ww,g,off),ww,g,off))
        trials.sort(key=lambda x:x[0])
        top=trials[:8]
    # Validation set chooses *among models optimized on training only*.
    shortlist=sorted(candidates[:40]+top,key=lambda p:loss(valid,features,*p[1:]))
    chosen=shortlist[0]
    return {"train_mae":round(chosen[0],3),
            "validation_mae":round(loss(valid,features,*chosen[1:]),3),
            "features":features,
            "weights":{k:round(v,4) for k,v in zip(features,chosen[1])},
            "gain":round(chosen[2],3),"offset":round(chosen[3],3),
            "params":chosen[1:]}
def report(paths,probe):
    rows,meta=load(paths,probe)
    train,valid,test=split_games(rows)
    splits={"train_games":len(set(r["game"] for r in train)),
            "validation_games":len(set(r["game"] for r in valid)),
            "test_games":len(set(r["game"] for r in test))}
    models={}
    for i,(name,features) in enumerate(FAMILIES.items()):
        m=optimize(train,valid,features,seed=20261010+i)
        m["train"]=pct_metrics(train,measure(train,features,*m["params"]))
        m["validation"]=pct_metrics(valid,measure(valid,features,*m["params"]))
        models[name]=m
    # Validations are allowed for model selection; sealed game test is opened once.
    winner=min(models,key=lambda k:(models[k]["validation_mae"]+.08*len(FAMILIES[k])))
    for name,m in models.items():
        m["selected"]=name==winner
        if name==winner:m["test"]=pct_metrics(test,measure(test,m["features"],*m["params"]))
        del m["params"]
    def original(rs):
        return [r["progress"] for r in rs]
    baseline={
        "train":pct_metrics(train,original(train)),
        "validation":pct_metrics(valid,original(valid)),
        "test":pct_metrics(test,original(test))
    }
    # Exploratory alternate validity: can current danger identify future checking?
    danger={}
    for name,group in (("train",train),("validation",valid),("test",test)):
        danger[name]={
            "check_next10_base_rate":round(statistics.mean(r["check_next10"] for r in group),3),
            "king_threat_auc_next10_check":auc(group,"king_threat","check_next10"),
            "urgency_auc_next10_check":auc(group,"urgency","check_next10"),
            "battle_auc_next10_capture":auc(group,"battle","capture_next10"),
        }
    m=models[winner]
    winner_test=m["test"]
    baseline_test=baseline["test"]
    conclusion=("improves proxy in held-out games" if winner_test["mae"]<baseline_test["mae"]
                else "does not beat baseline proxy in held-out games")
    return {
        "schema":"phase-maturity-tuning-v2",
        "data":meta,"split":splits,
        "methods":{
            "validation":"whole games held out; tune weights on train, choose family with validation; test used only after selection",
            "target":"100 * current move / eventual last move: an IMPERFECT REFERENCE, NOT TRUE STRATEGIC MATURITY",
            "prediction_information":"current-position quantities only, except the marked historical control",
            "result_caution":"historical old engine v0.0.19; cannot conclude win-rate improvement, no head-to-head matches",
        },
        "baseline":baseline,
        "models":models,
        "chosen":winner,
        "chosen_test_comparison":{"new_mae":winner_test["mae"],
            "baseline_mae":baseline_test["mae"],"new_stage_accuracy":winner_test["three_stage_accuracy"],
            "baseline_stage_accuracy":baseline_test["three_stage_accuracy"],
            "finding":conclusion},
        "event_check":danger,
        "next_steps":"validate current-engine era, fixed same-ply strategic counterexamples and stage-weight ablation before adopting",
    }
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",type=Path,action="append",required=True)
    ap.add_argument("--probe",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    a=ap.parse_args()
    out=report(a.input,a.probe)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("PHASE_TUNING_RESULT "+json.dumps(out,ensure_ascii=False))
if __name__=="__main__":main()
