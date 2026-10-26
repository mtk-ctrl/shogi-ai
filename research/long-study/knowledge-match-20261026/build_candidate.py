"""Explicit candidate only. Input is the provenance-preserving catalog export."""
import collections,hashlib,json,pathlib,sys
import shogi
sha=lambda b:hashlib.sha256(b).hexdigest()
source,baseline,out=map(pathlib.Path,sys.argv[1:]);out.mkdir(exist_ok=True,parents=True)
base=baseline.read_bytes();raw=source.read_bytes();rows=[json.loads(l) for l in raw.splitlines()];old={l.split('\t')[0] for l in base.decode().splitlines() if l and not l.startswith('#')};assert len(old)==163
rows=[r for r in rows if r['group_id'].startswith(('neural20-standard-','neural20-correction-','neural20-repaired-'))];assert len(rows)==520
accepted=collections.defaultdict(list);decisions=[]
for row in rows:
 r=row['record'];c=r['case'];o=r.get('root_deep',{});reason=None;confirmation=None
 if c.get('learning_split')=='validation':reason='reserved_validation'
 elif c['position_key'] in old:reason='preserve_adopted_position'
 elif not(o.get('status')=='recorded' and o.get('kind')=='cp' and o.get('bound')=='exact' and o.get('pv_head_matches') is True and type(o.get('depth')) is int and o['depth']>0 and type(o.get('value_stm')) is int):reason='incomplete_or_non_cp'
 elif o.get('requested_ms')!=3000000 or o.get('elapsed_ms',0)<2990000:reason='long_search_not_complete'
 elif o.get('position_command')!=c['analysis_position_command'] or o.get('history_key')!=c['history_key']:reason='history_mismatch'
 elif o.get('research_decision_id'):reason='existing_knowledge_not_fresh_search'
 if not reason:
  b=shogi.Board(c['start_sfen'])
  if b.sfen()!=shogi.Board().sfen():reason='nonstandard_start_unsupported'
  else:
   for m in c['history_moves']:
    assert shogi.Move.from_usi(m) in b.legal_moves;b.push_usi(m)
   assert ' '.join(b.sfen().split()[:3])==c['position_key']
   if o.get('bestmove') in ('resign','win',None) or shogi.Move.from_usi(o['bestmove']) not in b.legal_moves:reason='nonlegal_move'
 if not reason and o['bestmove']!=c['actual_move']:
  a=r.get('branches',{}).get('actual',{});q=r.get('branches',{}).get('research',{})
  valid=all(x.get('status')=='recorded' and x.get('kind')=='cp' and x.get('bound')=='exact' and type(x.get('value_stm')) is int and x.get('pv_head_matches') is True for x in (a,q))
  valid=valid and a.get('requested_ms')==q.get('requested_ms')==600000 and type(a.get('depth')) is int and a['depth']>0 and a['depth']==q.get('depth')
  valid=valid and a.get('position_command')==c['analysis_position_command']+' '+c['actual_move'] and q.get('position_command')==c['analysis_position_command']+' '+o['bestmove']
  if not valid:reason='branch_comparison_inconclusive'
  elif a['value_stm']-q['value_stm']<30:reason='improvement_below_30cp'
  else:confirmation={'improvement_cp':a['value_stm']-q['value_stm'],'depth':a['depth'],'requested_ms':600000}
 d={'observation_id':row['observation_id'],'reason':reason,'branch_confirmation':confirmation};decisions.append(d)
 if not reason:accepted[c['position_key']].append((row,d))
lines=[];entries=[]
for key,group in sorted(accepted.items()):
 if len({r['record']['root_deep']['bestmove'] for r,d in group})>1:
  for r,d in group:d['reason']='conflicting_eligible_moves'
  continue
 row,d=sorted(group,key=lambda pair:pair[0]['observation_id'])[-1];c=row['record']['case'];o=row['record']['root_deep'];move=o['bestmove'];rid='longstudy-'+sha(row['observation_id'].encode())[:20]
 fields=[key,move,'longstudy-candidate-20261026',str(len(group)),str(int(o['elapsed_ms'])),str(o['depth']),'',o['kind'],str(o['value_stm']),'','research_decision',rid,move,' '.join(c['history_moves']) or '-'];lines.append('\t'.join(fields))
 entries.append({'research_id':rid,'position_key':key,'move':move,'source_observations':[r['observation_id'] for r,d in group],'recorded_nodes':None,'recorded_stability_ms':None,'pv_scope':'saved_bestmove_only_no_continuation','branch_confirmation':d['branch_confirmation']})
 for r,d in group:d['reason']='included'
candidate=base.rstrip(b'\n')+b'\n'+('\n'.join(lines)+'\n').encode();assert len(lines)==227;assert sha(candidate)=='45f8bcc6115e0fadc1030c5d1967551d27b377d5e0b2d007798ee61428da276e'
(out/'candidate.tsv').write_bytes(candidate)
report={'schema':'kumoji-explicit-knowledge-candidate-v1','formal_adoption':False,'source_jsonl_sha256':sha(raw),'baseline_sha256':sha(base),'candidate_sha256':sha(candidate),'baseline_positions':163,'added_positions':len(lines),'total_positions':163+len(lines),'reviewed_observations':520,'decisions':dict(collections.Counter(d['reason'] for d in decisions)),'missing_metrics':'blank TSV nodes/stable_ms mean unknown; loader may decode as zero, not measured zero','entries':entries,'observation_decisions':decisions}
(out/'candidate.manifest.json').write_text(json.dumps(report,ensure_ascii=False,separators=(',',':'))+'\n');print({k:v for k,v in report.items() if k not in ('entries','observation_decisions')})
