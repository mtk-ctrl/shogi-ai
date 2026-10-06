"""Paired cold games: effective legal-response hand-drop validation vs current geometric ordering."""
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
        engines=[]
        try:
            engines=[Engine(engine,'A',oa,go),Engine(engine,'B',ob,go)]
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
    p.add_argument('--seed',type=int,default=2026100620)
    p.add_argument('--max-plies',type=int,default=240)
    p.add_argument('--output-dir',required=True)
    p.add_argument('--go-command',default='go movetime 200')
    args=p.parse_args()
    common={'ExperienceCache':False,'OpeningBook':True,'MateAssist':True,'HandDropTactics':True}
    oa={**common,'HandDropResponseCheck':True}
    ob={**common,'HandDropResponseCheck':False}
    engine=str(Path(args.engine).resolve())
    out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    config={'engine_sha256':hashlib.sha256(Path(engine).read_bytes()).hexdigest(),
            'book_sha256':hashlib.sha256(Path('shogi-ai-book.tsv').read_bytes()).hexdigest(),
            'pairs':args.pairs,'seed':args.seed,'max_plies':args.max_plies,
            'go_command':args.go_command,'options_a':oa,'options_b':ob,
            'A':'effective legal-response validation','B':'current geometric hand-drop ordering',
            'paired_seed_policy':'same Black seed and White seed within each swapped pair',
            'lanes':args.lanes,'host':platform.platform(),'logical_cpus':os.cpu_count()}
    atomic(out/'identity.json',config)
    started=time.monotonic(); games=[]
    jobs=[(pair,engine,str(out),args.seed,args.max_plies,oa,ob,args.go_command)
          for pair in range(args.pairs)]
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.lanes) as pool:
        for rows in pool.map(pair_task,jobs):
            games.extend(rows)
            wa=sum(g['winner']=='A' for g in games); wb=sum(g['winner']=='B' for g in games)
            print(f'{len(games)}/{args.pairs*2}: EFFECTIVE {wa}W {len(games)-wa-wb}D {wb}L',flush=True)
    games.sort(key=lambda g:g['game_index'])
    wa=sum(g['winner']=='A' for g in games); wb=sum(g['winner']=='B' for g in games); n=len(games)
    reasons={}; timing={}; search={}
    for g in games: reasons[g['reason']]=reasons.get(g['reason'],0)+1
    for label in ('A','B'):
        count=sum(g['timing'][label]['moves'] for g in games)
        timing[label]={'moves':count,'mean':sum(g['timing'][label]['total_ms'] for g in games)/count,
                       'max':max(g['timing'][label]['max_ms'] for g in games)}
        totals={}
        for g in games:
            for k,v in (g['search'][label] or {}).items():
                if k.endswith('_total') or k=='samples': totals[k]=totals.get(k,0)+v
        search[label]=totals
    by_color={str(color):{'wins':sum(g['winner']=='A' for g in games if g['a_black']==color),
                          'losses':sum(g['winner']=='B' for g in games if g['a_black']==color),
                          'draws':sum(g['winner'] is None for g in games if g['a_black']==color)}
              for color in (True,False)}
    pair_scores=[sum(1 if g['winner']=='A' else 0.5 if g['winner'] is None else 0
                     for g in games if g['pair']==pair)/2 for pair in range(args.pairs)]
    mean=sum(pair_scores)/len(pair_scores)
    se=(sum((x-mean)**2 for x in pair_scores)/(len(pair_scores)-1)/len(pair_scores))**0.5
    d={'config':config,'games':n,'wins_effective':wa,'draws':n-wa-wb,'wins_geometric':wb,
       'score_effective':mean,
       'paired_normal_approx_interval':[max(0,mean-1.96*se),min(1,mean+1.96*se)],
       'illegal_games':sum('illegal_by' in g for g in games),'reasons':reasons,
       'effective_by_color':by_color,'average_plies':sum(g['plies'] for g in games)/n,
       'timing_ms':timing,'search':search,'elapsed_seconds':time.monotonic()-started,'details':games}
    atomic(out/'result.json',d)
    atomic(out/'summary.json',{k:v for k,v in d.items() if k!='details'})
    print(json.dumps({k:v for k,v in d.items() if k not in ('details','config')},ensure_ascii=False,indent=2),flush=True)
    if d['illegal_games']: raise SystemExit('illegal games')
if __name__=='__main__': main()
