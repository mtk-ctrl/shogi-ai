"""Three-level 10-factor Evaluation-v2 orthogonal-array screen.

729 configurations (3^6 runs) cover every level combination of every 1-, 2-,
and 3-factor subset evenly. Each configuration is played as one color-swapped
pair against v1. Raw per-configuration results are intentionally noisy; factor
and interaction estimates aggregate across the balanced design.
"""
import argparse,concurrent.futures,itertools,json,math,subprocess,sys
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
RELATIVE_LEVELS=(50,100,200)

# Ten GF(3)^6 columns. Any three are linearly independent, so the 3^6 design
# has strength 3: every triple of factors sees all 27 level triples 27 times.
VECTORS=(
    (1,0,0,0,0,0),
    (0,1,0,0,0,0),
    (0,0,1,0,0,0),
    (0,0,0,1,0,0),
    (0,0,0,0,1,0),
    (0,0,0,0,0,1),
    (0,0,0,1,1,1),
    (0,0,1,0,1,1),
    (0,0,1,1,0,1),
    (0,0,1,1,1,0),
)

def rank_mod3(rows):
    a=[list(r) for r in rows]
    rank=0
    for col in range(6):
        pivot=next((i for i in range(rank,len(a)) if a[i][col]%3),None)
        if pivot is None: continue
        a[rank],a[pivot]=a[pivot],a[rank]
        inv=1 if a[rank][col]%3==1 else 2
        a[rank]=[(x*inv)%3 for x in a[rank]]
        for i in range(len(a)):
            if i!=rank and a[i][col]%3:
                q=a[i][col]%3
                a[i]=[(a[i][j]-q*a[rank][j])%3 for j in range(6)]
        rank+=1
    return rank

def validate_design():
    assert len(FACTORS)==len(VECTORS)==10
    for cols in itertools.combinations(VECTORS,3):
        assert rank_mod3(cols)==3, cols

def rows():
    validate_design()
    out=[]
    for idx,x in enumerate(itertools.product(range(3),repeat=6)):
        codes=[sum(v[j]*x[j] for j in range(6))%3 for v in VECTORS]
        opts={
            "EvalV2":True,
            "AdaptiveLongThink":False,
            "EvalPositionalCap":5000,
        }
        rel={}
        for name,code in zip(FACTORS,codes):
            pct=RELATIVE_LEVELS[code]
            rel[name]=pct
            opts[name]=max(1,int(round(BASE[name]*pct/100)))
        out.append({"index":idx,"codes":codes,"relative":rel,"options":opts})
    # Strength-3 sanity checks.
    for cols in itertools.combinations(range(10),3):
        counts={}
        for row in out:
            key=tuple(row["codes"][c] for c in cols)
            counts[key]=counts.get(key,0)+1
        assert len(counts)==27 and set(counts.values())=={27}
    return out

def run_one(job):
    row,engine,out_root,seed=job
    out=Path(out_root)/f"cfg-{row['index']:03d}"
    out.mkdir(parents=True,exist_ok=True)
    result=out/"summary.json"
    if result.exists():
        return row["index"]
    oa={
        "OpeningBook":False,"ExperienceCache":False,"MateAssist":True,
        **row["options"],
    }
    ob={
        "OpeningBook":False,"ExperienceCache":False,"MateAssist":True,
        "EvalV2":False,"AdaptiveLongThink":False,
    }
    cmd=[
        sys.executable,"benchmarks/eval_v2_match.py",
        "--engine",engine,"--pairs","1","--lanes","1",
        "--seed",str(seed+row["index"]*8),"--max-plies","240",
        "--go-command","go movetime 200",
        "--output-dir",str(out),
        "--options-a",json.dumps(oa,separators=(",",":")),
        "--options-b",json.dumps(ob,separators=(",",":")),
    ]
    subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL)
    meta={"index":row["index"],"codes":row["codes"],"relative":row["relative"],"options":oa}
    (out/"design.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n")
    return row["index"]

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--engine",required=True)
    p.add_argument("--output-dir",required=True)
    p.add_argument("--shard",type=int,required=True)
    p.add_argument("--shards",type=int,default=27)
    p.add_argument("--parallel",type=int,default=4)
    p.add_argument("--seed",type=int,default=2026109000)
    args=p.parse_args()
    design=rows()
    chosen=[r for r in design if r["index"]%args.shards==args.shard]
    root=Path(args.output_dir)
    root.mkdir(parents=True,exist_ok=True)
    (root/"shard-design.json").write_text(json.dumps({
        "shard":args.shard,"shards":args.shards,"factors":FACTORS,
        "base":BASE,"relative_levels":RELATIVE_LEVELS,
        "rows":chosen,
    },ensure_ascii=False,indent=2)+"\n")
    jobs=[(r,str(Path(args.engine).resolve()),str(root),args.seed) for r in chosen]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
        done=0
        for idx in pool.map(run_one,jobs):
            done+=1
            print(f"shard {args.shard}: {done}/{len(chosen)} config {idx}",flush=True)

if __name__=="__main__":
    main()
