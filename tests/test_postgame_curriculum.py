import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_postgame_practice import source_and_root,observation
from tools.research import postgame_curriculum as c
from tools.research.postgame_cases import make_case,position_command,sha256
from tools.research.postgame_ranker import digest,OPTIONS,BASE
from tools.research.postgame_spiral import leakage_keys
from tools.research.postgame_eval_preflight import tactical_cases
from tests.test_postgame_progress import PARENT
import shogi


def fixture():
    source,_=source_and_root(('5i6h','5a6b','6h5i','6b5a'))
    for row in source.row['moves']:row['search']=dict(phase_stage='opening',score_status='recorded',score_cp_stm=0)
    previous=dict(split_registry={'game:1:g':dict(group='training',split='train',heldout_consumed=False)},
                  example_bank=dict(parent_context=PARENT),learning=dict(parent_options=dict(zip(OPTIONS,BASE))))
    return source,previous


class CurriculumTest(unittest.TestCase):
    def test_selection_is_deterministic_and_balances_side_cells(self):
        source,previous=fixture()
        p=c.build_plan([source],previous,PARENT,'a'*64,set(),1000)
        self.assertEqual(p,c.build_plan([source],previous,PARENT,'a'*64,set(),1000))
        self.assertEqual({r['case']['side_to_move'] for r in p['selected']},{'black','white'})
        self.assertEqual(p['available_cells']['end:black'],0)
        self.assertEqual(len({r['case']['history_key'] for r in p['selected']}),len(p['selected']))

    def test_protected_and_completed_positions_never_become_practice(self):
        source,previous=fixture();previous['split_registry']['game:1:g']['split']='heldout'
        self.assertEqual(c.build_plan([source],previous,PARENT,'a'*64,set(),1000)['selected'],[])
        source,previous=fixture();first=c.build_plan([source],previous,PARENT,'a'*64,set(),1000)
        done={r['case']['history_key'] for r in first['selected']}
        second=c.build_plan([source],previous,PARENT,'a'*64,done,1000)
        self.assertFalse(done&{r['case']['history_key'] for r in second['selected']})
        previous['split_registry'][leakage_keys(shogi.Board())[0]]=dict(group='test',split='heldout',heldout_consumed=True)
        third=c.build_plan([source],previous,PARENT,'a'*64,set(),1000)
        self.assertNotIn(make_case(source,1)['history_key'],{r['case']['history_key'] for r in third['selected']})

    def test_profiles_keep_parent_and_change_only_opponent_hypotheses(self):
        base=dict(zip(OPTIONS,BASE));profiles=c.opponents(base)
        self.assertEqual(profiles[0]['options'],base)
        self.assertEqual(base['EvalSafety'],480)
        self.assertEqual(profiles[1]['options']['EvalPressure'],456)
        self.assertEqual(profiles[2]['options']['EvalSafety'],576)
        self.assertEqual({k for k in base if profiles[2]['options'][k]!=base[k]},{'EvalSafety','EvalPressure'})

    def test_no_distinct_observation_means_actual_branch_only(self):
        source,previous=fixture();p=c.build_plan([source],previous,PARENT,'a'*64,set(),1000)
        registry,_=c.protected_registry([source],previous);frames=[]
        for row in p['selected']:
            case=row['case'];frames.append([dict(observation(case,tuple(case['history_moves']),ms),bestmove=case['actual_move']) for ms in (50,500)])
        roots=c.branch_roots(p,frames,registry)
        self.assertTrue(all(r['alternative_move'] is None for r in roots))
        frames[0][0]['history_key']='bad'
        with self.assertRaisesRegex(ValueError,'binding'):c.branch_roots(p,frames,registry)

    def test_handoff_is_bounded_and_ignores_diagnosis_or_winner(self):
        class Game:
            def __init__(self,n):self.row=dict(game_id=str(n),source_id=str(n))
        games=[Game(i) for i in range(20)]
        infos={str(i):dict(practice_id='root-'+str(i%6),scenario=dict(name=str(i%3))) for i in range(20)}
        rows=[dict(game_id=str(i),ply=1) for i in range(20)]
        result=c.bounded_handoff(rows,games,infos)
        self.assertEqual(len(result),8)
        self.assertEqual(len({infos[r['game_id']]['practice_id'] for r in result}),6)
        self.assertEqual(result,c.bounded_handoff(list(reversed(rows)),games,infos))

    def test_retained_suite_requires_exact_history_budget_and_correct_capture(self):
        frames=[]
        for case in tactical_cases():
            command=position_command(case['start_sfen'],())
            frames.append(dict(position_command=command,history_key=sha256(command.encode()),requested_ms=200,
                requested_depth=None,bestmove=case['expected_prefix']))
        self.assertTrue(c.retention(frames)['passed'])
        changed=copy.deepcopy(frames);changed[0]['bestmove']='resign'
        self.assertFalse(c.retention(changed)['passed'])
        changed[0]['requested_ms']=50
        with self.assertRaisesRegex(ValueError,'binding'):c.retention(changed)

    def test_existing_output_and_asset_mismatch_fail_before_new_games(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'preserve'):c.run({},[],{},{},'x','y',tmp)
            binary=Path(tmp)/'binary';binary.write_bytes(b'wrong');knowledge=Path(tmp)/'knowledge';knowledge.write_bytes(b'wrong')
            with self.assertRaisesRegex(ValueError,'assets'):c.run(dict(binary_sha256='a'*64),[],{},{},binary,knowledge,Path(tmp)/'new')

    def test_actual_profile_assignment_raw_replay_and_tamper_rejection(self):
        source,previous=fixture();controls={r['start_sfen']:r for r in tactical_cases()}
        class Engine:
            def __init__(self,*args,**kwargs):self.options=kwargs['evaluation_options']
            def send(self,*args):pass
            def close(self):pass
            def search(self,start,history,ms,**kwargs):
                case=dict(start_sfen=start);frame=observation(case,tuple(history),ms)
                if start in controls:frame['bestmove']=controls[start]['expected_prefix']
                frame.update(value_stm=self.options['EvalPressure'],played_telemetry=dict(phase_maturity=0))
                return frame
        with tempfile.TemporaryDirectory() as tmp:
            binary=Path(tmp)/'binary';binary.write_bytes(b'own-test');knowledge=Path(tmp)/'knowledge';knowledge.write_text('test\n')
            parent=dict(PARENT,knowledge_sha256=sha256(knowledge.read_bytes()))
            previous['example_bank']['parent_context']=parent
            plan=c.build_plan([source],previous,parent,sha256(binary.read_bytes()),set(),1000)
            registry,_=c.protected_registry([source],previous);out=Path(tmp)/'trial'
            with patch.object(c,'Analyzer',Engine),patch.object(c.practice,'prepare_candidates'),patch.object(c.practice,'verify_handoff',return_value={}):
                audit=c.run(plan,[source],previous,registry,binary,knowledge,out)
                self.assertTrue(audit['raw_archive_reproduced']);self.assertTrue(audit['retention']['after']['passed'])
                import json
                report=json.loads((out/'result.json').read_text())
                for saved in report['results']:
                    row=json.loads((out/saved['file']).read_text());prefix=saved['info']['prefix_plies']
                    for move in row['details'][0]['move_records'][prefix+1:]:
                        self.assertEqual(move['search']['score_cp_stm'],row['options_'+move['engine'].lower()]['EvalPressure'])
                path=out/report['results'][0]['file'];row=json.loads(path.read_text())
                row['options_b']['EvalPressure']+=1;c.practice.dump(path,row)
                report['results'][0]['sha256']=sha256(path.read_bytes());c.practice.dump(out/'result.json',report)
                with self.assertRaisesRegex(ValueError,'options'):c.verify_saved(plan,[source],previous,registry,knowledge,out)


if __name__=='__main__':unittest.main()
