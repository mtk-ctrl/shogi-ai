import ast, json, gzip, hashlib, tarfile, struct, collections, io, zipfile, pickle
from pathlib import Path
import numpy as np
import shogi

import argparse
ap=argparse.ArgumentParser(description='Read-only diagnostics of a neural20 correction checkpoint, without Torch or retraining.')
ap.add_argument('--source-dir',type=Path,required=True,help='Fixed tools/research source directory containing neural_model.py and train_nnue.py')
ap.add_argument('--checkpoint-dir',type=Path,required=True,help='Previously extracted checkpoint files')
ap.add_argument('--bundle',type=Path,required=True,help='SHA-verified final tgz')
ap.add_argument('--output',type=Path,required=True)
args=ap.parse_args();P=args.source_dir;D=args.checkpoint_dir
def read(p): return json.loads(p.read_text())
F=81*2*14+2*7*18+2;K=F+2*9*28*81
ns={'np':np,'shogi':shogi,'FEATURES':F,'KIND':{c:i+1 for i,c in enumerate('PLNSBRGK')}}
ns['hashlib']=hashlib
for filename,names in [('train_nnue.py',{'sparse_features'}),('neural_model.py',{'features','split_root'})]:
 tree=ast.parse((P/filename).read_text());exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),filename,'exec'),ns)
cache=read(D/'static-evaluation-cache.json')['values'];extra=read(D/'research-replay.json')
casegen={x['case']['case_id']:g for g in range(5) for x in read(D/'history'/f'g{g:03d}'/'deep-study.json')['results']}
rows=[];snapshots=[]
for name in ['source']+[f'g{g:03d}' for g in range(5)]:
 path=D/'archives'/name;manifest=read(path/'manifest.json');metas={s['source_id']:s['metadata'] for s in manifest['sources']}
 raw=(path/'played-games.jsonl.gz').read_bytes();assert hashlib.sha256(raw).hexdigest()==manifest['archive_sha256']
 for line in gzip.decompress(raw).splitlines():
  game=json.loads(line)
  if game['reason']=='move_limit':continue
  outcome=0 if game['winner'] is None else (1 if (game['winner']=='A')==game['a_black'] else -1)
  b=shogi.Board(game.get('start_sfen') or metas[game['source_id']].get('start_sfen') or shogi.STARTING_SFEN)
  n=len(game['moves']);chosen={min(n-1,k*n//64) for k in range(64)}
  for ply,m in enumerate(game['moves']):
   if ply in chosen and ply>=8:
    s=m.get('search',{});exact=s.get('score_status')=='recorded' and type(s.get('score_cp_stm')) is int and not s.get('score_lowerbound') and not s.get('score_upperbound') and s.get('depth',0)>0
    target=.8*outcome
    if exact:target=.85*np.clip(s['score_cp_stm']*(1 if b.turn==0 else -1)/1000,-6,6)+.15*outcome*.8
    rows.append({'root':game['game_id'],'sfen':b.sfen(),'target':float(target),'origin':'ordinary'})
   b.push_usi(m['move'])
 if name=='source':continue
 g=int(name[1:]);rs=rows+[r for r in extra if casegen[r['evidence']['case_id']]<=g];splits={}
 for r in rs:
  key=' '.join(r['sfen'].split()[:3]);splits.setdefault(key,set()).add(ns['split_root'](r['root'],20261021))
 kept=[r for r in rs if len(splits[' '.join(r['sfen'].split()[:3])])==1]
 val=[r for r in kept if ns['split_root'](r['root'],20261021)=='validation']
 report=read(D/'history'/name/'result.json')['student'];assert len(val)==report['sample_counts']['validation'],(g,len(val),report['sample_counts'])
 targets=np.array([r['target']*1000-cache[r['sfen']] for r in val]);floor=np.maximum(np.abs(targets)-600,0)
 info={'generation':g,'validation_rows':len(val),'targets_outside_600':int((np.abs(targets)>600).sum()),'outside_fraction':float((np.abs(targets)>600).mean()),'minimum_possible_mae_cp':float(floor.mean()),'selected_report_mae_cp':report['validation_mae_cp'],'best_new_epoch_mae_cp':min(x['validation_mae_cp'] for x in report['history'])}
 snapshots.append((info,val,targets))
 print('targets',json.dumps(info),flush=True)

with tarfile.open(args.bundle) as t:
 for info,val,targets in snapshots:
  g=info['generation'];blob=t.extractfile(f'history/g{g:03d}/candidate.nnue').read();magic,w,k=struct.unpack_from('<8sII',blob);assert magic==b'KMNNUE04' and k==K
  bias=np.frombuffer(blob,'<i4',w,16).astype(np.int64);off=16+w*4;emb=np.frombuffer(blob,'<i2',k*w,off).reshape(k,w);off+=k*w*2
  head=np.frombuffer(blob,'<i2',w,off).astype(np.int64);out=struct.unpack_from('<i',blob,off+w*2)[0]
  raw=[]
  for r in val:
   a=np.clip(bias+emb[ns['features'](r['sfen'])].sum(axis=0),0,1024);raw.append((int(a@head)+out)*1000/65536)
  raw=np.array(raw);pred=np.clip(np.sign(raw)*np.floor(np.abs(raw)+.5),-600,600)
  info.update(quantized_candidate_mae_cp=float(np.abs(pred-targets).mean()),quantized_raw_outside_600=int((np.abs(raw)>600).sum()),quantized_raw_outside_fraction=float((np.abs(raw)>600).mean()))
  print('candidate',json.dumps(info),flush=True)

def load_tensor_file(path):
 with zipfile.ZipFile(path) as z:
  root=next(n.rsplit('/',1)[0] for n in z.namelist() if n.endswith('/data.pkl'))
  class Reader(pickle.Unpickler):
   def find_class(self,module,name):
    if (module,name)==('collections','OrderedDict'):return collections.OrderedDict
    if (module,name)==('torch','FloatStorage'):return np.dtype('<f4')
    if (module,name)==('torch','LongStorage'):return np.dtype('<i8')
    if (module,name)==('torch','ByteStorage'):return np.dtype('u1')
    if (module,name)==('torch._utils','_rebuild_tensor_v2'):
     def tensor(storage,offset,size,stride,*args):
      return np.ndarray(shape=size,dtype=storage.dtype,buffer=storage,offset=offset*storage.dtype.itemsize,strides=tuple(s*storage.dtype.itemsize for s in stride))
     return tensor
    raise ValueError(('Unsupported pickle global',module,name))
   def persistent_load(self,pid):
    assert pid[0]=='storage';_,dtype,key,location,count=pid;return np.frombuffer(z.read(root+'/data/'+key),dtype=dtype,count=count)
  return Reader(io.BytesIO(z.read(root+'/data.pkl'))).load()

state=load_tensor_file(D/'learner/student/model.pt');resume=load_tensor_file(D/'learner/student/resume.pt')
params=state['model'];print('active parameter count',sum(v.size for k,v in params.items() if not k.startswith('policy.')),flush=True)
info,val,targets=snapshots[-1];sample=val;raw=[]
for r in sample:
 h=np.clip(params['embedding.weight'][ns['features'](r['sfen'])].sum(axis=0)+params['bias'],0,4)
 raw.append(float(h@params['value.weight'][0]+params['value.bias'][0])*1000)
raw=np.array(raw);mae=float(np.abs(np.clip(raw,-600,600)-targets).mean());assert abs(mae-info['selected_report_mae_cp'])<.01,(mae,info)
info.update(numpy_float_selected_mae_cp=mae,float_raw_outside_600=int((np.abs(raw)>600).sum()),float_raw_outside_fraction=float((np.abs(raw)>600).mean()),float_saturated_not_box_optimum=int(((np.abs(raw)>600)&(np.abs(np.clip(raw,-600,600)-np.clip(targets,-600,600))>.01)).sum()))
diff={k:int(np.count_nonzero(v!=resume['model'][k])) for k,v in params.items()}
result={'method':'read-only reconstruction from SHA-verified archive; NumPy inference, no retraining','parameter_counts':{'value_active':sum(v.size for k,v in params.items() if not k.startswith('policy.')),'stored_total':sum(v.size for v in params.values())},'validation_diagnostics':[i for i,_,_ in snapshots],'g4_selected_vs_last_epoch_changed_coefficients':diff,'limitations':['No PyTorch gradient or training replay; saturation fractions for g0-g3 use quantized candidate raw outputs, not exact floating checkpoints.','Validation labels reconstructed; all generation validation sample counts match reports; g4 floating inference matches report within 0.01cp.']}
args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2),flush=True)
