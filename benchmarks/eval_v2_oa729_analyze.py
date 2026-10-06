"""Aggregate the 729-run Evaluation-v2 orthogonal-array screen."""
import argparse,glob,itertools,json,math
from pathlib import Path

FACTORS=[
    "EvalMaterialWeight","EvalSafety","EvalPressure","EvalActivity","EvalDanger",
    "EvalInfluence","EvalPotential","EvalCoordination","EvalHandPotential","EvalThreat",
]
LABELS=(50,100,200)

def score(rows):
    n=sum(r["games"] for r in rows)
    w=sum(r["wins_a"] for r in rows)
    d=sum(r["draws"] for r in rows)
    l=sum(r["wins_b"] for r in rows)
    return {"games":n,"wins":w,"draws":d,"losses":l,"score":(w+0.5*d)/n if n else 0}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    samples=[]
    for sp in glob.glob(str(Path(args.input)/"**/summary.json"),recursive=True):
        d=Path(sp).parent/"design.json"
        if not d.exists(): continue
        s=json.load(open(sp,encoding="utf-8"))
        design=json.load(open(d,encoding="utf-8"))
        samples.append({**design,"result":s})
    if len(samples)!=729:
        raise SystemExit(f"expected 729 configs, got {len(samples)}")

    overall=score([x["result"] for x in samples])
    mu=overall["score"]
    main_effects={}
    main_delta={}
    for fi,f in enumerate(FACTORS):
        rows=[]
        for code,label in enumerate(LABELS):
            group=[x["result"] for x in samples if x["codes"][fi]==code]
            q=score(group);q["relative_level"]=label
            rows.append(q)
        main_effects[f]=rows
        main_delta[f]=[r["score"]-mu for r in rows]

    interactions=[]
    pair_tables={}
    for i,j in itertools.combinations(range(10),2):
        table=[]
        residuals=[]
        for a in range(3):
            row=[]
            for b in range(3):
                group=[x["result"] for x in samples if x["codes"][i]==a and x["codes"][j]==b]
                q=score(group)
                residual=q["score"]-mu-main_delta[FACTORS[i]][a]-main_delta[FACTORS[j]][b]
                row.append({"a":LABELS[a],"b":LABELS[b],"score":q["score"],"residual":residual,"games":q["games"]})
                residuals.append(abs(residual))
            table.append(row)
        key=f"{FACTORS[i]} x {FACTORS[j]}"
        pair_tables[key]=table
        interactions.append({"pair":key,"max_abs_residual":max(residuals),"rms_residual":math.sqrt(sum(x*x for x in residuals)/len(residuals))})
    interactions.sort(key=lambda x:(x["rms_residual"],x["max_abs_residual"]),reverse=True)

    # Use the balanced main effects plus the 12 strongest pair interactions as
    # a transparent surrogate over all 3^10=59,049 combinations.
    top_pairs=interactions[:12]
    pair_lookup={}
    for pinfo in top_pairs:
        key=pinfo["pair"]; f1,f2=key.split(" x ")
        i,j=FACTORS.index(f1),FACTORS.index(f2)
        vals={}
        for row in pair_tables[key]:
            for cell in row:
                vals[(LABELS.index(cell["a"]),LABELS.index(cell["b"]))]=cell["residual"]
        pair_lookup[(i,j)]=vals

    predicted=[]
    for codes in itertools.product(range(3),repeat=10):
        pred=mu+sum(main_delta[f][codes[i]] for i,f in enumerate(FACTORS))
        for (i,j),vals in pair_lookup.items():
            pred+=vals[(codes[i],codes[j])]
        predicted.append((pred,codes))
    predicted.sort(reverse=True)
    top=[]
    seen=set()
    for pred,codes in predicted:
        # Keep diversity: do not retain exact duplicate level vectors (defensive).
        if codes in seen: continue
        seen.add(codes)
        top.append({
            "predicted_score":pred,
            "relative":{f:LABELS[codes[i]] for i,f in enumerate(FACTORS)},
        })
        if len(top)>=24: break

    out={
        "design":"OA729 strength 3; all 10 factors varied simultaneously",
        "overall":overall,
        "main_effects":main_effects,
        "interactions_ranked":interactions,
        "pair_tables":pair_tables,
        "surrogate_top24":top,
        "surrogate_uses_top_pair_interactions":[x["pair"] for x in top_pairs],
    }
    Path(args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")

    print("## Evaluation-v2 OA729 screen")
    print(f"- overall V2 score across 1458 games: {overall['score']:.1%}")
    print("### Main effects")
    for f in FACTORS:
        vals=" / ".join(f"{r['relative_level']}={r['score']:.1%}" for r in main_effects[f])
        print(f"- {f}: {vals}")
    print("### Strongest pair interactions")
    for x in interactions[:12]:
        print(f"- {x['pair']}: rms={x['rms_residual']:.3%}, max={x['max_abs_residual']:.3%}")
    print("### Surrogate top 5")
    for x in top[:5]:
        print(f"- predicted {x['predicted_score']:.1%}: {x['relative']}")

if __name__=="__main__":
    main()
