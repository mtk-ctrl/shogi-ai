"""Outcome-learning, serialization and independent C++ numerical checks."""
import importlib.util
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('selfplay_learn',ROOT/'research/selfplay-learning-20261016/learn.py')
learn=importlib.util.module_from_spec(spec);spec.loader.exec_module(learn)

class LearningTests(unittest.TestCase):
    def test_split_is_deterministic_and_isolates_shards(self):
        for n in (6,10,19,20):
            s=[learn.split_for_shard(i,n) for i in range(n)]
            self.assertEqual(set(s),{'train','validation','test'})
            self.assertEqual(s,[learn.split_for_shard(i,n) for i in range(n)])
        self.assertEqual([learn.split_for_shard(i,20) for i in range(14)],['train']*14)

    def test_fit_generalization_reproducibility_and_symmetry(self):
        rng=np.random.default_rng(7);x=rng.normal(0,.7,(700,12));base=x[:,0]*900
        y=learn.sigmoid((base+400*np.tanh(x[:,2]-x[:,3]))/900)
        train=(x[:500],base[:500],y[:500],np.ones(500))
        val=(x[500:],base[500:],y[500:],np.ones(200))
        models=[]
        for _ in range(2):
            m=learn.Residual(4,600);learn.fit(m,train,val,900,.001)
            models.append(m)
        self.assertLess(learn.metric(models[0],val,900)['brier'],learn.metric(None,val,900)['brier']*.2)
        self.assertEqual(models[0].text(),models[1].text())
        restored=learn.Residual.from_text(models[0].text())
        np.testing.assert_array_equal(restored.predict(x),models[0].predict(x))
        np.testing.assert_allclose(restored.predict(-x),-restored.predict(x),atol=1e-12)
        self.assertTrue((abs(restored.predict(x))<=600).all())

    def test_cross_split_positions_cannot_leak(self):
        start='lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b - '
        other='8k/9/9/9/9/9/2P6/9/K8 b - '
        rows=[{'split':'test','sfen':other+'900'},
              {'split':'train','sfen':start+'1'},
              {'split':'validation','sfen':start+'777'},
              {'split':'train','sfen':start+'5'},
              {'split':'validation','sfen':other+'7'}]
        kept,removed=learn.exclude_cross_split(rows)
        self.assertEqual([r['split'] for r in kept],['train','train','validation'])
        self.assertEqual(dict(removed),{'validation':1,'test':1})

    def test_invalid_models(self):
        for s in ('','other 12 1 100 END','KUMOJI_SELFPLAY_RESIDUAL_V1 12 9 100 END',
                  'KUMOJI_SELFPLAY_RESIDUAL_V1 12 1 100 '+'nan '*13+'END'):
            with self.assertRaises((ValueError,IndexError)):learn.Residual.from_text(s)

    def test_metrics_use_the_actual_integer_runtime_correction(self):
        m=learn.Residual(4,600);m.w2[:]=.000001
        x=np.ones((20,12));data=(x,np.zeros(20),np.ones(20),np.ones(20))
        self.assertTrue((abs(m.predict(x))<.5).all())
        self.assertEqual(learn.metric(m,data,900),learn.metric(None,data,900))

    def test_cpp_inference_and_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);source=tmp/'probe.cpp';binary=tmp/'probe'
            source.write_text('''#include "strategy/selfplay_model.h"
#include <iostream>
int main(int argc,char**argv){shogi::strategy::SelfPlayModel m;
if(argc!=2 || !m.load_file(argv[1])){std::cout<<"REJECTED\\n";return 2;}
shogi::strategy::SelfPlayModel::Features x{};
while(std::cin>>x[0]){for(int i=1;i<12;++i)std::cin>>x[i];std::cout<<m.correction(x)<<"\\n";}}
''')
            subprocess.run(['g++','-std=c++17','-O2','-I'+str(ROOT/'engine'),str(source),'-o',str(binary)],check=True)
            rng=np.random.default_rng(29);m=learn.Residual(8,600)
            m.w2=rng.normal(0,.5,8);m.w1=rng.normal(0,.4,(8,12))
            x=np.concatenate([np.zeros((1,12)),rng.normal(0,3,(1000,12))])
            model=tmp/'model.txt';model.write_text(m.text())
            run=subprocess.run([str(binary),str(model)],input=''.join(' '.join(map(str,row))+'\n' for row in x),text=True,capture_output=True,check=True)
            prediction=m.predict(x);expected=np.sign(prediction)*np.floor(abs(prediction)+.5)
            np.testing.assert_array_equal(np.array(list(map(int,run.stdout.split()))),expected)
            for invalid in (m.text()+'trailing',m.text().replace(' 600\n',' -1\n'),m.text().replace('END','')):
                model.write_text(invalid);r=subprocess.run([str(binary),str(model)],capture_output=True,text=True)
                self.assertEqual(r.returncode,2)

    def test_legal_replay_and_no_fake_draw_teacher(self):
        import shogi
        b=shogi.Board();b.push_usi('7g7f')
        g={'winner':None,'reason':'move_limit','plies':1,'a_black':True,
           'final_sfen':b.sfen(),'moves':[{'move':'7g7f','ply':1,'engine':'A','side_to_move':'black'}]}
        positions,label=learn.validate_game(g)
        self.assertEqual(len(positions),1);self.assertIsNone(label)
        g['reason']='checkmate'
        with self.assertRaises(ValueError):learn.validate_game(g)
        g['moves'][0]['move']='7g7e'
        with self.assertRaises(ValueError):learn.validate_game(g)

    def test_full_archive_provenance_dedup_and_tamper_rejection(self):
        import shogi
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'shards').mkdir();engine=root/'binary';engine.write_bytes(b'unit fixture')
            binary_hash=hashlib.sha256(engine.read_bytes()).hexdigest();ref='a'*40
            knowledge={side:{'enabled':True,'available':True,'positions':163,
                'sha256':'6da204cd1e65600ccdbb9f3dbe463627687d6cf7eb8347da6a103239129dac4c'} for side in ('A','B')}
            moves=['7i6h','3a4b','6h7i','4b3a']*3;b=shogi.Board()
            for move in moves:b.push_usi(move)
            sources=[];games=[]
            for i in range(6):
                black=i%2==0
                g={'winner':None,'reason':'fourfold_repetition','plies':12,
                   'a_black':black,'final_sfen':b.sfen(),'moves':moves}
                md={'sha256_a':binary_hash,'sha256_b':binary_hash,'options_a':{},'options_b':{},
                    'go_command':'go movetime 200','position_knowledge':knowledge,'seed':i}
                raw=json.dumps({**md,'game_offset':i,'details':[g]}).encode();sid=hashlib.sha256(raw).hexdigest()
                file=f'shard-{i}.json';(root/'shards'/file).write_bytes(raw)
                sources.append({'source_id':sid,'file':file,'bytes':len(raw),'metadata':md})
                records=[{'move':move,'ply':ply+1,'side_to_move':'black' if ply%2==0 else 'white',
                          'engine':'A' if (ply%2==0)==black else 'B'} for ply,move in enumerate(moves)]
                games.append({**g,'game_id':sid+':0','source_id':sid,'source_game_index':0,'moves':records})
            archive=root/'played-games.jsonl.gz'
            with gzip.open(archive,'wt') as f:
                for game in games:f.write(json.dumps(game)+'\n')
            learn.save(root/'manifest.json',{'archive':archive.name,'archive_sha256':learn.digest(archive.read_bytes()),
                'games':6,'plies':72,'run_id':99,'requested_ref_a':ref,'requested_ref_b':ref,'sources':sources})
            learn.save(root/'aggregate.json',{'ref_a':ref,'ref_b':ref,'games':6,'illegal_games':0,
                'go_command':'go movetime 200','position_knowledge':knowledge})
            proof=root/'proof.json';learn.save(proof,{'run_id':99,'observed_ref_a':ref,'observed_ref_b':ref,
                'binary_sha256_a':binary_hash,'binary_sha256_b':binary_hash})
            class Static:
                def __init__(self,*a):pass
                def score(self,s):return [0.0]*12,0
                def close(self):pass
            with patch.object(learn,'StaticFeatures',Static):
                report=learn.prepare(root,root/'samples.jsonl',engine,proof)
                self.assertEqual(report['legal_plies'],72)
                self.assertEqual(report['counts']['duplicate_games'],5)
                self.assertEqual(report['counts']['samples/train'],4)
                path=root/'shards/shard-0.json';path.write_bytes(path.read_bytes()+b' ')
                with self.assertRaises(ValueError):learn.prepare(root,root/'bad.jsonl',engine,proof)
if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':
        m=learn.Residual(8,600);rng=np.random.default_rng(47)
        m.w1=rng.normal(0,.4,(8,12));m.w2=rng.normal(0,.4,8)
        Path(sys.argv[2]).write_text(m.text());sys.argv=sys.argv[:1]
    unittest.main()
