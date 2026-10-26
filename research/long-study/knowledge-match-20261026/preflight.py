import subprocess,queue,threading,json,hashlib,pathlib,sys
folder=pathlib.Path(sys.argv[1]).resolve();engine=pathlib.Path(sys.argv[2]).resolve();m=json.loads((folder/'candidate.manifest.json').read_text())
p=subprocess.Popen([str(engine)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1);q=queue.Queue()
def reader():
 for line in p.stdout:q.put(line.strip())
threading.Thread(target=reader,daemon=True).start()
def send(line):p.stdin.write(line+'\n');p.stdin.flush()
def until(prefix):
 lines=[]
 while True:
  line=q.get(timeout=30);lines.append(line)
  if line.startswith(prefix):return lines
send('usi');until('usiok');send('setoption name PositionKnowledgeFile value '+str(folder/'candidate.tsv'));send('setoption name OpeningRandomNonLance value false');send('isready');ready=until('readyok');assert any('390 positions' in x for x in ready),ready
for e in m['entries']:
 send('usinewgame');send('position sfen '+e['position_key']+' 1');send('go movetime 200');lines=until('bestmove');assert lines[-1].split()[1]==e['move'];assert any('research_decision id '+e['research_id']+' ' in s for s in lines)
send('quit');p.wait(timeout=10)
r={'engine_commit':'671012c5540a22275652ae548847bffc0da963f7','engine_sha256':hashlib.sha256(engine.read_bytes()).hexdigest(),'native_loaded':390,'direct_selections_verified':len(m['entries']),'position_mode':'each added SFEN with clean history','candidate_sha256':m['candidate_sha256']};(folder/'preflight.json').write_text(json.dumps(r,indent=2)+'\n');print(r)
