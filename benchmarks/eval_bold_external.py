#!/usr/bin/env python3
"""Research-only fixed external comparison; opponent moves never used for learning."""
import json, subprocess, sys
from pathlib import Path
from eval_bold_league import options

PROFILES=("M","W","P0","P4","P5","P1")
LEVELS=(50,55)

def main():
    shard=int(sys.argv[1])
    if not 0<=shard<20: raise SystemExit("shard must be 0..19")
    output=Path("results")
    output.mkdir(exist_ok=True)
    for level in LEVELS:
        nodes=subprocess.check_output([sys.executable,"benchmarks/external_levels.py","--level",str(level),"--nodes-only"],text=True).strip()
        for profile in PROFILES:
            path=output/f"{profile}-lv{level}-shard{shard:02d}.json"
            cmd=[sys.executable,"benchmarks/external_match.py",
                "--self-engine","build/engine","--opponent-engine","external/YaneuraOu/source/YaneuraOu-by-gcc",
                "--self-options",json.dumps(options(profile)),
                "--opponent-options",json.dumps({"Threads":1,"USI_Hash":16,"USI_OwnBook":False}),
                "--self-go","go movetime 200","--opponent-go",f"go nodes {nodes}",
                "--games","5","--game-offset",str(shard*5),"--seed",str(202610100+shard*1000+level),
                "--output",str(path)]
            subprocess.run(cmd,check=True)
            data=json.loads(path.read_text())
            if data["games"]!=5 or data["illegal_games"]: raise SystemExit("invalid games")
            if data["self_engine"]["options"].get("AdaptiveLongThink")!="true": raise SystemExit("long think missing")
            if data["self_engine"]["options"].get("PositionKnowledge")!="true": raise SystemExit("knowledge missing")
    print("completed shard",shard)

if __name__=="__main__":main()
