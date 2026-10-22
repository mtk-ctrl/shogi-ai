"""Distribution, immutable results, data reuse, and promotion boundary tests."""
import copy
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.research import neural_cluster as nc
from tools.research import neural_arena as arena


class ClusterTests(unittest.TestCase):
    def test_twenty_lanes_cover_every_pair_once_and_balance_work(self):
        for games in (40,100,1000,2000):
            items=nc.game_items(games,100)
            shards=nc.partition(items,20)
            self.assertEqual(len(shards),20)
            self.assertEqual([p for shard in shards for p in shard],items)
            self.assertLessEqual(max(map(len,shards))-min(map(len,shards)),1)
        self.assertEqual(list(map(len,nc.partition(list(range(40)),20))),[2]*20)
        self.assertEqual(len(nc.partition([0,1],20)),2)

    def test_pair_seeds_and_colors_independent_of_shard_count(self):
        seen=[]
        class Engine:
            def __init__(self,*a,**kw):pass
            def close(self):pass
        def play(a,b,index,max_plies,base):
            seen.append((index,base+index*2,base+index*2+1))
            return dict(winner='A' if index==0 else 'B',a_black=index==0,reason='resign')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);binary=root/'engine';binary.write_text('own engine')
            knowledge=root/'knowledge';knowledge.write_text('knowledge')
            with patch.object(arena,'CheckedEngine',Engine),patch.object(arena,'play_game',play),\
                 patch.object(arena,'position_knowledge_metadata',lambda options:{}),\
                 patch.object(arena,'search_summary',lambda engine:{}):
                arena.paired_match(binary,knowledge,root/'serial',8,100)
                serial=seen[:];seen.clear()
                arena.paired_match(binary,knowledge,root/'a',4,100,pair_offset=0)
                arena.paired_match(binary,knowledge,root/'b',4,100,pair_offset=2)
                self.assertEqual(serial,seen)
                seen.clear()
                arena.paired_match(binary,knowledge,root/'b',4,100,pair_offset=2)
                self.assertEqual(seen,[],'completed pairs must not run again')
        self.assertEqual(serial,[(0,100,101),(1,100,101),(0,102,103),(1,102,103),
                                 (0,104,105),(1,104,105),(0,106,107),(1,106,107)])

    def test_worker_receipts_reject_missing_duplicate_and_corrupt_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=root/'run';work.mkdir()
            tasks=dict(key='expected',stage='study',assignments=[dict(lane=0),dict(lane=1)])
            nc.atomic_json(work/'tasks.json',tasks)
            for lane in range(2):
                out=root/'results'/f'lane-{lane:02d}';out.mkdir(parents=True)
                (out/'result.json').write_text('{}')
                nc.atomic_json(out/'receipt.json',dict(task_key='expected',lane=lane,status='completed',
                    elapsed_seconds=1,files=nc.file_manifest(out)))
            self.assertEqual(len(nc.collect_outputs(work,root/'results')[1]),2)
            out=root/'results/lane-01'
            (out/'result.json').write_text('{"tampered":true}')
            with self.assertRaisesRegex(ValueError,'changed'):nc.collect_outputs(work,root/'results')
            (out/'result.json').write_text('{}')
            r=nc.read(out/'receipt.json');r['task_key']='wrong model';nc.atomic_json(out/'receipt.json',r)
            with self.assertRaisesRegex(ValueError,'different task'):nc.collect_outputs(work,root/'results')
            (out/'receipt.json').unlink()
            with self.assertRaisesRegex(ValueError,'missing worker'):nc.collect_outputs(work,root/'results')

    def test_research_replay_retains_old_positions_and_distinct_origins(self):
        row=dict(root='g',sfen='position',origin='own_deep_search',target=1)
        newer=dict(row,target=2)
        mcts=dict(row,origin='own_mcts',target=.5)
        result=nc.replay_merge([row],[newer,mcts])
        self.assertEqual(len(result),2)
        self.assertEqual({r['origin']:r['target'] for r in result},
                         {'own_deep_search':2,'own_mcts':.5})
        self.assertEqual(nc.replay_merge(result,[]),result)

    def test_bundle_roundtrip_preserves_all_actual_moves_and_omits_pv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'src';src.mkdir()
            data={'moves':['7g7f','3c3d'],'pv':['2g2f'],'observation':{'pv':'x','value':25}}
            nc.atomic_json(src/'research.json',data)
            (src/'model.nnue').write_bytes(b'weights')
            nc.pack(src,root/'checkpoint.tgz',durable=True)
            first=nc.sha(root/'checkpoint.tgz')
            nc.pack(src,root/'again.tgz',durable=True)
            self.assertEqual(first,nc.sha(root/'again.tgz'))
            nc.unpack(root/'checkpoint.tgz',root/'restored')
            self.assertEqual(nc.read(root/'restored/research.json'),
                {'moves':data['moves'],'observation':{'value':25}})
            self.assertEqual((root/'restored/model.nnue').read_bytes(),b'weights')
            # A modified file with an unchanged embedded manifest is rejected.
            with tarfile.open(root/'checkpoint.tgz') as t:
                entries=[(m,t.extractfile(m).read()) for m in t.getmembers()]
            import io
            with tarfile.open(root/'bad.tgz','w:gz') as t:
                for m,content in entries:
                    if m.name=='model.nnue':content=b'changed'
                    m.size=len(content);t.addfile(m,io.BytesIO(content))
            with self.assertRaisesRegex(ValueError,'checksum'):nc.unpack(root/'bad.tgz',root/'bad')

    def test_standard_profile_cannot_silently_become_smoke_or_exceed_budget(self):
        p=nc.parameters({})
        self.assertEqual((p['runners'],p['cases'],p['match_games']),(20,40,1000))
        for change in ({'runners':21},{'selfplay_games':41},{'match_games':40},
                       {'screen_games':0},{'generations':4},{'unexpected':1}):
            with self.assertRaises(ValueError):nc.parameters(change)
        self.assertEqual(nc.parameters({'mode':'smoke'})['screen_games'],0)

    def test_holdout_and_repeat_cases_are_not_selected(self):
        from tools.research.nnue_deep_study import choose
        class Game:
            def __init__(self,gid):
                self.row={'game_id':gid};self.moves=['m']*30;self.outcome_status='finished'
        games=[Game('train-a'),Game('holdout'),Game('train-b')]
        def case(game,ply):
            return dict(case_id=f"{game.row['game_id']}:{ply}",position_key=f"{game.row['game_id']}:{ply}")
        with patch('tools.research.nnue_deep_study.observed_actor_drop',lambda g,p:None),\
             patch('tools.research.nnue_deep_study.make_case',case):
            first=choose(games,2,2,{'train-a','train-b'},selection_seed=1)
            second=choose(games,2,2,{'train-a','train-b'},
                excluded_positions={c['position_key'] for c in first},selection_seed=2)
        self.assertEqual(len(first),2);self.assertEqual(len(second),2)
        self.assertTrue(set(c['position_key'] for c in first).isdisjoint(c['position_key'] for c in second))
        self.assertTrue(all('holdout' not in c['case_id'] for c in first+second))

    def test_smoke_cannot_promote_even_a_winning_candidate_and_rejection_keeps_learner(self):
        for mode,screen in (('smoke',True),('standard',False)):
            with tempfile.TemporaryDirectory() as tmp:
                work=Path(tmp);current=work/'current';current.mkdir()
                plan={'parameters':dict(mode=mode,generations=1)}
                state=dict(next_generation=0,accepted=0,parent=None,seen_positions=[],completed=[])
                for kind in ('teacher','student'):
                    (current/kind).mkdir()
                    (current/kind/'model.pt').write_bytes(b'learned weights')
                    nc.atomic_json(current/kind/'report.json',{})
                (current/'candidate.nnue').write_bytes(b'native candidate')
                nc.atomic_json(current/'cases.json',[{'position_key':'studied-position'}])
                nc.atomic_json(work/'research-replay.json',[])
                nc.atomic_json(current/'screen-decision.json',dict(pass_screen=screen))
                if screen:
                    nc.atomic_json(current/'evaluate-parent.json',dict(games=1000,pair_scores=[1]*500,
                        movetime=200,invalid_games=0))
                (work/'tasks.json').write_text('{}')
                with patch.object(nc,'context',return_value=(work,plan,state)):
                    result=nc.finish(work)
                self.assertFalse(result['decision']['accepted'])
                self.assertIsNone(nc.read(work/'state.json')['parent'])
                self.assertEqual((work/'learner/student/model.pt').read_bytes(),b'learned weights')
                self.assertIn('studied-position',nc.read(work/'state.json')['seen_positions'])

    def test_finalization_recovers_after_copy_move_and_state_save_without_double_promotion(self):
        # These are destructive boundaries: a fresh runner must finish from
        # uploaded state even when current/models or current itself is gone.
        for failure in ('learner_copy','history_move','state_saved'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);work=root/'run';current=work/'current';current.mkdir(parents=True)
                plan={'parameters':dict(mode='standard',generations=1)}
                state=dict(next_generation=0,accepted=0,parent=None,seen_positions=[],completed=[])
                nc.atomic_json(work/'state.json',state)
                for kind in ('teacher','student'):
                    (current/kind).mkdir()
                    (current/kind/'model.pt').write_bytes(b'learned weights')
                    (current/kind/'resume.pt').write_bytes(b'optimizer state')
                    nc.atomic_json(current/kind/'report.json',{})
                (current/'candidate.nnue').write_bytes(b'native candidate')
                nc.atomic_json(current/'cases.json',[{'position_key':'studied-position'}])
                nc.atomic_json(work/'research-replay.json',[])
                nc.atomic_json(current/'screen-decision.json',dict(pass_screen=True))
                nc.atomic_json(current/'evaluate-parent.json',dict(games=1000,pair_scores=[1]*500,
                    movetime=200,invalid_games=0))
                (work/'tasks.json').write_text('{}')
                atomic=nc.atomic_json;unlink=Path.unlink
                def fail_copy(source,destination,*args,**kwargs):
                    Path(destination).mkdir(parents=True)
                    (Path(destination)/'model.pt').write_bytes(b'partial')
                    raise OSError('injected learner copy interruption')
                def fail_state(path,value):
                    if Path(path).name=='state.json':raise OSError('injected history move interruption')
                    return atomic(path,value)
                def fail_unlink(path,*args,**kwargs):
                    if path.name=='finalization.json':raise OSError('injected state save interruption')
                    return unlink(path,*args,**kwargs)
                with patch.object(nc,'context',side_effect=lambda path:(Path(path),plan,nc.read(Path(path)/'state.json'))):
                    target,attribute,replacement=(
                        (nc.shutil,'copytree',fail_copy) if failure=='learner_copy' else
                        (nc,'atomic_json',fail_state) if failure=='history_move' else
                        (Path,'unlink',fail_unlink))
                    with patch.object(target,attribute,replacement),self.assertRaisesRegex(OSError,'injected'):
                        nc.finish(work)
                    self.assertTrue((work/'finalization.json').exists())
                    nc.pack(work,root/'interrupted.tgz')
                    restored=root/'fresh-runner';nc.unpack(root/'interrupted.tgz',restored)
                    result=nc.finish(restored)
                after=nc.read(restored/'state.json')
                self.assertTrue(result['decision']['accepted'])
                self.assertEqual((after['accepted'],after['next_generation'],len(after['completed'])),(1,1,1))
                self.assertEqual(after['seen_positions'],['studied-position'])
                self.assertEqual((restored/'parent.nnue').read_bytes(),b'native candidate')
                self.assertEqual((restored/'learner/student/resume.pt').read_bytes(),b'optimizer state')
                self.assertFalse((restored/'current').exists())
                self.assertFalse((restored/'finalization.json').exists())
                self.assertEqual(nc.read(restored/'history/g000/result.json'),result)


if __name__=='__main__':unittest.main()
