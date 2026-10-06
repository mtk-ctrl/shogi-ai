"""Overnight multi-stage search for Evaluation-v2.

Design goals:
- search all ten evaluation axes simultaneously;
- use a five-level logarithmic range (0.2x,0.5x,1x,2x,5x);
- preserve pair/triple interaction information with a strength-3 OA(3125);
- use 100ms as cheap broad evidence, while calibrating it against 50/200ms;
- prune conservatively, retaining high-uncertainty and diverse candidates.
"""
import argparse,concurrent.futures,glob,itertools,json,math,os,random,subprocess,sys
from pathlib import Path

FACTORS=[
    "EvalMaterialWeight","EvalSafety","EvalPressure","EvalActivity","EvalDanger",
    "EvalInfluence","EvalPotential","EvalCoordination","EvalHandPotential","EvalThreat",
]
BASE={
    "EvalMaterialWeight":100,
    "EvalSafety":50,
    "EvalPressure":150,
    "EvalActivity":150,
    "EvalDanger":200,
    "EvalInfluence":60,
    "EvalPotential":25,
    "EvalCoordination":50,
    "EvalHandPotential":60,
    "EvalThreat":25,
}
MULT=(0.2,0.5,1.0,2.0,5.0)
LABEL=("0.2x","0.5x","1x","2x","5x")
# GF(5)^5 columns. Any three are independent; verified at runtime.
VECTORS=(
    (1,0,0,0,0),
    (0,1,0,0,0),
    (0,0,1,0,0),
    (0,0,0,1,0),
    (0,0,0,0,1),
    (1,3,2,3,4),
    (1,4,4,4,2),
    (0,1,1,3,1),
    (1,1,4,2,1),
    (0,1,0,4,3),
)

def rank_mod5(rows):
    a=[list(r) for r in rows];rank=0
    if not a:return 0
    for c in range(len(a[0])):
        p=next((i for i in range(rank,len(a)) if a[i][c]%5),None)
        if p is None:continue
        a[rank],a[p]=a[p],a[rank]
        inv=pow(a[rank][c]%5,-1,5)
        a[rank]=[(x*inv)%5 for x in a[rank]]
        for i in range(len(a)):
            if i!=rank and a[i][c]%5:
                q=a[i][c]%5
                a[i]=[(a[i][j]-q*a[rank][j])%5 for j in range(len(a[0]))]
        rank+=1
        if rank==len(a):break
    return rank

def design_rows():
    for cols in itertools.combinations(VECTORS,3):
        assert rank_mod5(cols)==3, cols
    rows=[]
    for idx,x in enumerate(itertools.product(range(5),repeat=5)):
        codes=[sum(v[j]*x[j] for j in range(5))%5 for v in VECTORS]
        opts={"EvalV2":True,"AdaptiveLongThink":False,"EvalPositionalCap":5000}
        relative={}
        for name,code in zip(FACTORS,codes):
            relative[name]=LABEL[code]
            opts[name]=max(1,int(round(BASE[name]*MULT[code])))
        rows.append({"index":idx,"codes":codes,"relative":relative,"options":opts})
    assert len(rows)==3125
    # Strength-3 check: each triple of factors has 125 cells, 25 runs/cell.
    for cols in itertools.combinations(range(10),3):
        counts={}
        for row in rows:
            key=tuple(row["codes"][c] for c in cols)
            counts[key]=counts.get(key,0)+1
        assert len(counts)==125 and set(counts.values())=={25}
    return rows

def atomic(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    tmp.replace(path)

def load_candidates(path):
    if not path:return design_rows()
    data=json.loads(Path(path).read_text(encoding="utf-8"))
    return data["candidates"] if isinstance(data,dict) else data

def match_one(row,engine,out_root,games,movetime,seed,opening_book=False,match_lanes=1):
    if games%2:raise ValueError("games must be even for exact color balance")
    out=Path(out_root)/f"cfg-{row['index']:04d}"
    result=out/"summary.json"
    if result.exists():return row["index"]
    oa={
        "OpeningBook":opening_book,"ExperienceCache":False,"MateAssist":True,
        **row["options"],
    }
    ob={
        "OpeningBook":opening_book,"ExperienceCache":False,"MateAssist":True,
        "EvalV2":False,"AdaptiveLongThink":False,
    }
    cmd=[
        sys.executable,"benchmarks/eval_v2_match.py",
        "--engine",str(Path(engine).resolve()),
        "--pairs",str(games//2),"--lanes",str(match_lanes),
        "--seed",str(seed+row["index"]*32+movetime),
        "--max-plies","240","--go-command",f"go movetime {movetime}",
        "--output-dir",str(out),
        "--options-a",json.dumps(oa,separators=(",",":")),
        "--options-b",json.dumps(ob,separators=(",",":")),
    ]
    subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL)
    atomic(out/"design.json",row)
    return row["index"]

def cmd_run(args):
    rows=load_candidates(args.candidates)
    chosen=[r for pos,r in enumerate(rows) if pos%args.shards==args.shard]
    root=Path(args.output_dir);root.mkdir(parents=True,exist_ok=True)
    atomic(root/"stage.json",{
        "shard":args.shard,"shards":args.shards,"games":args.games,
        "movetime":args.movetime,"candidate_count":len(rows),
        "chosen":len(chosen),"factors":FACTORS,"base":BASE,"multipliers":MULT,
    })
    jobs=[(r,args.engine,root,args.games,args.movetime,args.seed,args.opening_book,args.match_lanes) for r in chosen]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
        done=0
        for idx in pool.map(lambda j:match_one(*j),jobs):
            done+=1
            print(f"shard {args.shard}: {done}/{len(chosen)} cfg={idx}",flush=True)

def fidelity_subset(rows,n=250,seed=20261006):
    # Deterministic maximin-ish sample: random order, greedily prefer vectors
    # far in Hamming distance from selected. Keeps calibration broad.
    rng=random.Random(seed)
    pool=rows[:];rng.shuffle(pool)
    selected=[pool.pop()]
    while len(selected)<n and pool:
        batch=pool[:min(len(pool),500)]
        best=max(batch,key=lambda r:min(sum(a!=b for a,b in zip(r["codes"],s["codes"])) for s in selected[-80:]))
        selected.append(best);pool.remove(best)
    return sorted(selected,key=lambda r:r["index"])

def cmd_fidelity(args):
    rows=fidelity_subset(design_rows(),args.sample,args.seed)
    chosen=[r for pos,r in enumerate(rows) if pos%args.shards==args.shard]
    root=Path(args.output_dir);root.mkdir(parents=True,exist_ok=True)
    for movetime in args.movetimes:
        stage=root/f"{movetime}ms"
        jobs=[(r,args.engine,stage,args.games,movetime,args.seed+movetime*1000,False,args.match_lanes) for r in chosen]
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
            done=0
            for idx in pool.map(lambda j:match_one(*j),jobs):
                done+=1
                print(f"fidelity {movetime}ms shard {args.shard}: {done}/{len(chosen)} cfg={idx}",flush=True)

def collect_pattern(pattern):
    out={}
    for sp in glob.glob(pattern,recursive=True):
        d=Path(sp).parent/"design.json"
        if not d.exists():continue
        row=json.loads(d.read_text(encoding="utf-8"))
        out[row["index"]]={"row":row,"result":json.loads(Path(sp).read_text(encoding="utf-8"))}
    return out

def collect(root):
    return collect_pattern(str(Path(root)/"**/summary.json"))

def game_score(result):
    return result["score_a"],result["games"]

def main_effects(data):
    total_games=sum(x["result"]["games"] for x in data.values())
    total_points=sum((x["result"]["wins_a"]+0.5*x["result"]["draws"]) for x in data.values())
    mu=total_points/total_games
    effects={}
    for fi,f in enumerate(FACTORS):
        vals=[]
        for level in range(5):
            grp=[x["result"] for x in data.values() if x["row"]["codes"][fi]==level]
            g=sum(r["games"] for r in grp)
            p=sum(r["wins_a"]+0.5*r["draws"] for r in grp)
            vals.append(p/g if g else mu)
        effects[f]=vals
    return mu,effects

def pair_effects(data,mu,main):
    pairs={}
    ranked=[]
    for i,j in itertools.combinations(range(10),2):
        table={}
        residual=[]
        for a in range(5):
            for b in range(5):
                grp=[x["result"] for x in data.values() if x["row"]["codes"][i]==a and x["row"]["codes"][j]==b]
                g=sum(r["games"] for r in grp)
                p=sum(r["wins_a"]+0.5*r["draws"] for r in grp)
                s=p/g if g else mu
                r=s-mu-(main[FACTORS[i]][a]-mu)-(main[FACTORS[j]][b]-mu)
                table[(a,b)]=r;residual.append(r)
        rms=math.sqrt(sum(x*x for x in residual)/len(residual))
        pairs[(i,j)]=table
        ranked.append(((i,j),rms,max(abs(x) for x in residual)))
    ranked.sort(key=lambda x:(x[1],x[2]),reverse=True)
    return pairs,ranked

def predict_rows(rows,mu,main,pairs,ranked,top_pairs=15):
    use=[x[0] for x in ranked[:top_pairs]]
    pred={}
    for row in rows:
        codes=row["codes"]
        s=mu+sum(main[f][codes[i]]-mu for i,f in enumerate(FACTORS))
        for ij in use:s+=0.65*pairs[ij][(codes[ij[0]],codes[ij[1]])]
        pred[row["index"]]=max(0.01,min(0.99,s))
    return pred,use

def ranks(vals):
    order=sorted(range(len(vals)),key=lambda i:vals[i])
    out=[0]*len(vals)
    for r,i in enumerate(order):out[i]=r
    return out

def corr(a,b):
    if len(a)<3:return 0.0
    ma=sum(a)/len(a);mb=sum(b)/len(b)
    va=sum((x-ma)**2 for x in a);vb=sum((y-mb)**2 for y in b)
    return sum((x-ma)*(y-mb) for x,y in zip(a,b))/math.sqrt(max(1e-15,va*vb))

def calibration_correlations(broad,f50,f200):
    ids=sorted(set(broad)&set(f50)&set(f200))
    raw={}
    for label,d in (("50",f50),("100",broad),("200",f200)):
        raw[label]=[d[i]["result"]["score_a"] for i in ids]
    # Config-level correlation is noisy but still useful.
    out={
        "configs":len(ids),
        "config_50_200_pearson":corr(raw["50"],raw["200"]),
        "config_100_200_pearson":corr(raw["100"],raw["200"]),
        "config_50_200_spearman":corr(ranks(raw["50"]),ranks(raw["200"])),
        "config_100_200_spearman":corr(ranks(raw["100"]),ranks(raw["200"])),
    }
    # Main-effect level correlation is more stable: 50 cells, many games/cell.
    vectors={}
    for label,d in (("50",f50),("100",broad),("200",f200)):
        _,m=main_effects({i:d[i] for i in ids})
        vectors[label]=[m[f][level] for f in FACTORS for level in range(5)]
    out["main_50_200_pearson"]=corr(vectors["50"],vectors["200"])
    out["main_100_200_pearson"]=corr(vectors["100"],vectors["200"])
    out["main_50_200_spearman"]=corr(ranks(vectors["50"]),ranks(vectors["200"]))
    out["main_100_200_spearman"]=corr(ranks(vectors["100"]),ranks(vectors["200"]))
    return out

def hamming(a,b):return sum(x!=y for x,y in zip(a["codes"],b["codes"]))

def conservative_select(rows,evidence,k,min_level,seed=20261006):
    # evidence[index] = (posterior_mean, uncertainty)
    ordered=sorted(rows,key=lambda r:(evidence[r["index"]][0],r["index"]),reverse=True)
    selected=[]
    selected_ids=set()
    def add(r):
        if r["index"] not in selected_ids:
            selected.append(r);selected_ids.add(r["index"])
    # 60% strongest posterior.
    for r in ordered[:max(1,int(k*0.60))]:add(r)
    # 20% optimistic uncertainty bound.
    ucb=sorted(rows,key=lambda r:(evidence[r["index"]][0]+evidence[r["index"]][1],r["index"]),reverse=True)
    for r in ucb:
        if len(selected)>=int(k*0.80):break
        add(r)
    # Explicit level safeguards before diversity fill.
    for fi in range(10):
        for level in range(5):
            while sum(r["codes"][fi]==level for r in selected)<min_level and len(selected)<k:
                cand=next((r for r in ucb if r["index"] not in selected_ids and r["codes"][fi]==level),None)
                if cand is None:break
                add(cand)
    # Diversity among candidates that are not clearly poor.
    viable=ucb[:max(k*4,k)]
    while len(selected)<k:
        pool=[r for r in viable if r["index"] not in selected_ids]
        if not pool:pool=[r for r in rows if r["index"] not in selected_ids]
        cand=max(pool,key=lambda r:(min((hamming(r,s) for s in selected),default=10),
                                    evidence[r["index"]][0]+0.5*evidence[r["index"]][1]))
        add(cand)
    return selected[:k]

def cmd_select_broad(args):
    rows=design_rows();broad=collect(args.broad)
    f50=collect_pattern(str(Path(args.fidelity)/"**/50ms/**/summary.json"))
    f200=collect_pattern(str(Path(args.fidelity)/"**/200ms/**/summary.json"))
    if len(f50) != 250 or len(f200) != 250:
        raise SystemExit(f"fidelity incomplete: 50ms={len(f50)}/250 200ms={len(f200)}/250")
    if len(broad)!=3125:raise SystemExit(f"broad incomplete: {len(broad)}/3125")
    cal=calibration_correlations(broad,f50,f200)
    mu,main=main_effects(broad);pairs,ranked=pair_effects(broad,mu,main)
    pred,use=predict_rows(rows,mu,main,pairs,ranked)
    # If 100ms does not transfer well, retain more candidates rather than
    # pretending cheap evidence is decisive.
    transfer=cal["main_100_200_spearman"]
    target=625 if transfer>=0.65 else 800 if transfer>=0.40 else 1000
    evidence={}
    for r in rows:
        idx=r["index"];p=pred[idx]
        # own 6-game result contributes lightly; model aggregates much more data.
        own=broad[idx]["result"];own_score=own["score_a"]
        est=0.75*p+0.25*own_score
        n_eff=24
        if idx in f200:
            s=f200[idx]["result"]["score_a"]
            est=0.55*est+0.45*s;n_eff+=f200[idx]["result"]["games"]
        unc=math.sqrt(max(est*(1-est),0.05)/n_eff)
        evidence[idx]=(est,unc)
    selected=conservative_select(rows,evidence,target,min_level=max(20,target//12))
    payload={
        "stage":"broad100_to_refine200","target":target,"calibration":cal,
        "broad_overall":mu,
        "main_effects":{f:{LABEL[i]:v for i,v in enumerate(main[f])} for f in FACTORS},
        "top_pair_interactions":[{"pair":[FACTORS[i],FACTORS[j]],"rms":rms,"max":mx} for (i,j),rms,mx in ranked[:20]],
        "pair_terms_used":[[FACTORS[i],FACTORS[j]] for i,j in use],
        "candidates":[{**r,"prior_score":evidence[r["index"]][0],"prior_uncertainty":evidence[r["index"]][1]} for r in selected],
    }
    atomic(args.output,payload)
    print(json.dumps({"target":target,"calibration":cal,"overall":mu,
                      "top_pairs":payload["top_pair_interactions"][:8]},ensure_ascii=False,indent=2))

def cmd_select_stage(args):
    prior=json.loads(Path(args.candidates).read_text(encoding="utf-8"))
    rows=prior["candidates"];results=collect(args.results)
    missing=[r["index"] for r in rows if r["index"] not in results]
    if missing:raise SystemExit(f"stage incomplete: missing {len(missing)} configs, first={missing[:10]}")
    evidence={}
    for r in rows:
        idx=r["index"];res=results[idx]["result"];n=res["games"];s=res["score_a"]
        prior_mean=float(r.get("prior_score",0.5))
        prior_strength=args.prior_strength
        est=(s*n+prior_mean*prior_strength)/(n+prior_strength)
        unc=math.sqrt(max(est*(1-est),0.05)/(n+prior_strength))
        evidence[idx]=(est,unc)
    selected=conservative_select(rows,evidence,args.keep,args.min_level)
    payload={
        "stage":args.stage,"source_count":len(rows),"result_games":args.games,
        "candidates":[{**r,"prior_score":evidence[r["index"]][0],
                       "prior_uncertainty":evidence[r["index"]][1],
                       "last_score":results[r["index"]]["result"]["score_a"]}
                      for r in selected],
    }
    atomic(args.output,payload)
    print(json.dumps({"stage":args.stage,"source":len(rows),"keep":len(selected),
        "top":[{"index":r["index"],"score":evidence[r["index"]][0],
                "unc":evidence[r["index"]][1],"relative":r["relative"]} for r in selected[:5]]
    },ensure_ascii=False,indent=2))

def cmd_final3(args):
    prior=json.loads(Path(args.candidates).read_text(encoding="utf-8"))
    rows=prior["candidates"];results=collect(args.results)
    missing=[r["index"] for r in rows if r["index"] not in results]
    if missing:raise SystemExit(f"final stage incomplete: {missing}")
    ranked=[]
    for r in rows:
        res=results[r["index"]]["result"];n=res["games"];s=res["score_a"]
        pm=float(r.get("prior_score",0.5));ps=args.prior_strength
        est=(s*n+pm*ps)/(n+ps)
        se=math.sqrt(max(est*(1-est),0.05)/(n+ps))
        ranked.append((est,se,r,res))
    ranked.sort(key=lambda x:(x[0],x[2]["index"]),reverse=True)
    # End with three candidates; prefer distinct parameter philosophies if
    # alternatives are statistically close.
    chosen=[ranked[0]]
    for item in ranked[1:]:
        if len(chosen)>=3:break
        distance=min(hamming(item[2],x[2]) for x in chosen)
        best=ranked[0][0]
        if distance>=2 or item[0]>=best-0.01:chosen.append(item)
    while len(chosen)<3:chosen.append(ranked[len(chosen)])
    out={"stage":"overnight_final3","source_count":len(rows),"candidates":[],"ranking":[]}
    for est,se,r,res in ranked:
        rec={"index":r["index"],"score":est,"se":se,"games":res["games"],
             "wins":res["wins_a"],"draws":res["draws"],"losses":res["wins_b"],
             "relative":r["relative"],"options":r["options"]}
        out["ranking"].append(rec)
    out["candidates"]=[next(x for x in out["ranking"] if x["index"]==r["index"]) for _,_,r,_ in chosen]
    atomic(args.output,out)
    print(json.dumps(out["candidates"],ensure_ascii=False,indent=2))

def parser():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest="cmd",required=True)
    q=sub.add_parser("design");q.add_argument("--output",required=True)
    r=sub.add_parser("run");r.add_argument("--engine",required=True);r.add_argument("--output-dir",required=True)
    r.add_argument("--candidates");r.add_argument("--games",type=int,required=True);r.add_argument("--movetime",type=int,required=True)
    r.add_argument("--shard",type=int,required=True);r.add_argument("--shards",type=int,required=True);r.add_argument("--parallel",type=int,default=4)
    r.add_argument("--seed",type=int,default=20261006);r.add_argument("--opening-book",action="store_true");r.add_argument("--match-lanes",type=int,default=1)
    f=sub.add_parser("fidelity");f.add_argument("--engine",required=True);f.add_argument("--output-dir",required=True)
    f.add_argument("--games",type=int,default=6);f.add_argument("--movetimes",type=int,nargs="+",default=[50,200])
    f.add_argument("--sample",type=int,default=250);f.add_argument("--shard",type=int,required=True);f.add_argument("--shards",type=int,required=True)
    f.add_argument("--parallel",type=int,default=4);f.add_argument("--match-lanes",type=int,default=1);f.add_argument("--seed",type=int,default=20261006)
    b=sub.add_parser("select-broad");b.add_argument("--broad",required=True);b.add_argument("--fidelity",required=True);b.add_argument("--output",required=True)
    s=sub.add_parser("select-stage");s.add_argument("--candidates",required=True);s.add_argument("--results",required=True);s.add_argument("--output",required=True)
    s.add_argument("--stage",required=True);s.add_argument("--keep",type=int,required=True);s.add_argument("--min-level",type=int,default=0)
    s.add_argument("--games",type=int,required=True);s.add_argument("--prior-strength",type=float,default=12)
    z=sub.add_parser("final3");z.add_argument("--candidates",required=True);z.add_argument("--results",required=True);z.add_argument("--output",required=True)
    z.add_argument("--prior-strength",type=float,default=50)
    return p

def main():
    p=parser();args=p.parse_args()
    if args.cmd=="design":
        atomic(args.output,{"factors":FACTORS,"base":BASE,"multipliers":MULT,"candidates":design_rows()})
    elif args.cmd=="run":cmd_run(args)
    elif args.cmd=="fidelity":cmd_fidelity(args)
    elif args.cmd=="select-broad":cmd_select_broad(args)
    elif args.cmd=="select-stage":cmd_select_stage(args)
    elif args.cmd=="final3":cmd_final3(args)

if __name__=="__main__":main()
