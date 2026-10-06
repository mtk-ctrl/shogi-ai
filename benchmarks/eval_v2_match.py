"""Paired cold games for Evaluation-v2 parameter comparisons."""
import argparse,concurrent.futures,hashlib,json,os,platform,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmarks.arena import Engine,play_game,search_summary

def atomic(path,data):
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    tmp.replace(path)

def pair_task(job):
    pair,engine,out,seed,max_plies,oa,ob,go=job
    rows=[]
    for flip in (0,1):
        index=pair*2+flip
        path=Path(out)/f'game-{index:03d}.json'
        if path.exists():
            row=json.loads(path.read_text())
            assert row['pair']==pair and row['game_index']==index
            rows.append(row)
            continue
        engines=[]
        try:
            engines=[Engine(engine,'A',oa,go),Engine(engine,'B',ob,go)]
            # Keep the Black seed and White seed identical across the swapped pair.
            row=play_game(*engines,index,max_plies,seed+pair*2-index*2)
            row.update(pair=pair,game_index=index)
            row['timing']={e.label:{'moves':len(e.elapsed),'total_ms':1000*sum(e.elapsed),
                                   'max_ms':1000*max(e.elapsed,default=0)} for e in engines}
            row['search']={e.label:search_summary(e) for e in engines}
            atomic(path,row)
            if 'illegal_by' in row:
                raise RuntimeError(f'illegal move in game {index}')
            rows.append(row)
        finally:
            for e in engines:
                e.close()
    return rows

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--engine',required=True)
    p.add_argument('--pairs',type=int,default=50)
    p.add_argument('--lanes',type=int,default=4)
    p.add_argument('--seed',type=int,default=2026102000)
    p.add_argument('--max-plies',type=int,default=240)
    p.add_argument('--output-dir',required=True)
    p.add_argument('--options-a',required=True)
    p.add_argument('--options-b',required=True)
    p.add_argument('--go-command',default='go movetime 200')
    args=p.parse_args()
    if args.pairs<1 or args.lanes<1 or args.max_plies<1:
        raise SystemExit('invalid limits')
    if not args.go_command.startswith('go ') or '\n' in args.go_command or '\r' in args.go_command:
        raise SystemExit('invalid go command')
    oa=json.loads(args.options_a);ob=json.loads(args.options_b)
    if not isinstance(oa,dict) or not isinstance(ob,dict):
        raise SystemExit('options must be objects')
    common={'ExperienceCache':False,'OpeningBook':True,'MateAssist':True}
    oa={**common,**oa};ob={**common,**ob}
    engine=str(Path(args.engine).resolve())
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    config={'engine_sha256':hashlib.sha256(Path(engine).read_bytes()).hexdigest(),
            'book_sha256':hashlib.sha256(Path('shogi-ai-book.tsv').read_bytes()).hexdigest(),
            'pairs':args.pairs,'seed':args.seed,'max_plies':args.max_plies,
            'go_command':args.go_command,'options_a':oa,'options_b':ob,
            'paired_seed_policy':'same Black seed and White seed within swapped pair',
            'lanes':args.lanes,'host':platform.platform(),'logical_cpus':os.cpu_count()}
    cp=out/'identity.json'
    if cp.exists() and json.loads(cp.read_text())!=config:
        raise SystemExit('checkpoint identity mismatch')
    atomic(cp,config)
    started=time.monotonic();games=[]
    jobs=[(pair,engine,str(out),args.seed,args.max_plies,oa,ob,args.go_command)
          for pair in range(args.pairs)]
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.lanes) as pool:
        for rows in pool.map(pair_task,jobs):
            games.extend(rows)
            wa=sum(g['winner']=='A' for g in games);wb=sum(g['winner']=='B' for g in games)
            print(f'{len(games)}/{args.pairs*2}: A {wa}W {len(games)-wa-wb}D {wb}L',flush=True)
    games.sort(key=lambda g:g['game_index'])
    wa=sum(g['winner']=='A' for g in games);wb=sum(g['winner']=='B' for g in games);n=len(games)
    reasons={};timing={};search={}
    for g in games:reasons[g['reason']]=reasons.get(g['reason'],0)+1
    for label in ('A','B'):
        count=sum(g['timing'][label]['moves'] for g in games)
        timing[label]={'moves':count,
                       'mean':sum(g['timing'][label]['total_ms'] for g in games)/count if count else 0,
                       'max':max((g['timing'][label]['max_ms'] for g in games),default=0)}
        totals={}
        for g in games:
            for k,v in (g['search'][label] or {}).items():
                if isinstance(v,(int,float)) and (k.endswith('_total') or k=='samples'):
                    totals[k]=totals.get(k,0)+v
        search[label]=totals
    by_color={str(color):{'wins':sum(g['winner']=='A' for g in games if g['a_black']==color),
                          'losses':sum(g['winner']=='B' for g in games if g['a_black']==color),
                          'draws':sum(g['winner'] is None for g in games if g['a_black']==color)}
              for color in (True,False)}
    pair_scores=[sum(1 if g['winner']=='A' else 0.5 if g['winner'] is None else 0
                     for g in games if g['pair']==pair)/2 for pair in range(args.pairs)]
    mean=sum(pair_scores)/len(pair_scores)
    se=(sum((x-mean)**2 for x in pair_scores)/(len(pair_scores)-1)/len(pair_scores))**0.5 if len(pair_scores)>1 else 0
    summary={'config':config,'games':n,'wins_a':wa,'draws':n-wa-wb,'wins_b':wb,
             'score_a':mean,
             'paired_normal_approx_interval':[max(0,mean-1.96*se),min(1,mean+1.96*se)],
             'illegal_games':sum('illegal_by' in g for g in games),
             'reasons':reasons,'a_by_color':by_color,
             'average_plies':sum(g['plies'] for g in games)/n,
             'timing_ms':timing,'search':search,
             'elapsed_seconds':time.monotonic()-started}
    atomic(out/'summary.json',summary)
    atomic(out/'result.json',{**summary,'details':games})
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
    if summary['illegal_games']:
        raise SystemExit('illegal games')

if __name__=='__main__':
    main()
