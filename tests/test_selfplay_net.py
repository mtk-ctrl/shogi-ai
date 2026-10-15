"""Independent NumPy encoding/inference oracle for the frozen C++ self-play net."""
import json,re,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'research/nn'))
from network import PositionNet,encode_sfen,INPUT_SIZE
from benchmarks.arena import Engine
text=(ROOT/'engine/models/selfplay_net_v217.h').read_text()
model=PositionNet(hidden=16)
for name,shape in [('w1',(INPUT_SIZE,16)),('b1',(16,)),('w2',(16,1)),('b2',(1,))]:
    body=re.search(r'float '+name+r'\[\] = \{(.*?)\};',text,re.S).group(1)
    values=np.asarray([float(v) for v in re.findall(r'([-+\d.eE]+)f',body)],dtype=np.float32)
    setattr(model,name,values.reshape(shape))
rows=[json.loads(s) for s in Path(sys.argv[2]).read_text().splitlines()]
engine=Engine(sys.argv[1],'selfplay-net',{'EvalNeuralBlend':25,'OpeningRandomNonLance':False})
try:
    errors=[]
    for row in rows:
        engine.send('position sfen '+row['sfen']);engine.send('neuralprobe')
        parts=engine.wait_prefix('info string neuralprobe ',10).split()
        cpp=float(parts[parts.index('probability')+1])
        expected=float(model.predict(encode_sfen(row['sfen'])[None,:])[0])
        errors.append(abs(cpp-expected))
    assert max(errors)<2e-6,max(errors)
    print('PASS C++ vs NumPy encoding/inference:',len(errors),'positions; max probability error',max(errors))
finally:engine.close()
