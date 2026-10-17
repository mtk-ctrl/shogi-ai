import copy
import unittest
from tools.research.postgame_followup import tasks_from,execute,POLICY_FOLLOWUP
from tools.research.postgame_analyze import OPTIONS as ANALYSIS_OPTIONS
from tools.research.postgame_cases import position_command,sha256
from tools.research.postgame_progress import describe
from tools.research.postgame_ranker import BASE,OPTIONS
from tests.test_postgame_progress import measured,PARENT
from tests.test_postgame_spiral import diagnosis


def fixture(split='train'):
    row=diagnosis();row['route']='hold'
    report=measured(split=split)
    report['progress']['analysis'].update(evaluation_options=dict(zip(OPTIONS,BASE)),options=ANALYSIS_OPTIONS)
    bare={k:v for k,v in report.items() if k!='progress'}
    report['progress']=describe(bare,report['progress']['analysis'],[row],PARENT)
    return report,row


def fake(case,history,ms,depth):
    command=position_command(case['start_sfen'],history)
    return dict(status='recorded',kind='cp',bound='exact',value_stm=300 if history and history[-1]==case['actual_move'] else 0,
                depth=depth or 4,bestmove='2g2f',pv_head_matches=True,position_command=command,
                history_key=sha256(command.encode()),requested_ms=ms,requested_depth=depth)


class FollowupTest(unittest.TestCase):
    def test_saved_training_queue_is_recomputed_and_test_data_cannot_enter(self):
        p,row=fixture();self.assertEqual(len(tasks_from(p,[row],PARENT)),1)
        for split in ('validation','heldout'):
            p,row=fixture(split);self.assertEqual(tasks_from(p,[row],PARENT),[])
        p,row=fixture();p['progress']['work_items'][0]['split']='train-forged'
        with self.assertRaises(ValueError):tasks_from(p,[row],PARENT)

    def test_stable_improvement_uses_full_children_and_exact_same_depth(self):
        p,row=fixture();task,_=tasks_from(p,[row],PARENT)[0];calls=[]
        def probe(*args):calls.append(args);return fake(*args)
        result,new=execute(task,row,probe,lambda _:self.fail('cp is not mate'))
        self.assertTrue(result['knowledge_ready']);self.assertEqual(len(calls),8)
        self.assertEqual([x[2] for x in calls],[50,50,500,500,500,500,5000,5000])
        self.assertEqual(new['followup']['comparison']['improvement_cp'],300)
        self.assertEqual(calls[-1][3],4)

    def test_actual_support_and_short_or_deep_instability_are_not_candidates(self):
        p,row=fixture();task,_=tasks_from(p,[row],PARENT)[0]
        for kind in ('actual','short-unstable','deep-unstable','missing'):
            index=0
            def probe(*args):
                nonlocal index
                r=fake(*args);index+=1
                if kind=='actual' or kind=='short-unstable' and index==1 or kind=='deep-unstable' and index==3:r['bestmove']=row['case']['actual_move']
                if kind=='missing':r['status']='missing'
                return r
            result,new=execute(task,row,probe,lambda _:None)
            self.assertFalse(result['knowledge_ready'],kind);self.assertIsNone(new);self.assertEqual(index,4)

    def test_mate_stays_separate_and_not_proven_does_not_mean_no_mate(self):
        p,row=fixture();task,_=tasks_from(p,[row],PARENT)[0]
        def probe(*args):return dict(fake(*args),kind='mate',value_stm=3)
        result,new=execute(task,row,probe,lambda _:dict(status='not_proven_within_budget'))
        self.assertEqual(result['status'],'mate_requires_separate_learning_path');self.assertIsNone(new)
        self.assertFalse(result['knowledge_ready'])

    def test_incomplete_fixed_depth_and_bad_history_do_not_pass(self):
        p,row=fixture();task,_=tasks_from(p,[row],PARENT)[0]
        for kind in ('depth','history','bound'):
            def probe(*args):
                r=fake(*args)
                if args[3] is not None:
                    if kind=='depth':r['depth']=1
                    elif kind=='history':r['history_key']='bad'
                    else:r['bound']='lower'
                return r
            if kind=='history':
                with self.assertRaises(ValueError):execute(task,row,probe,lambda _:None)
            else:self.assertFalse(execute(task,row,probe,lambda _:None)[0]['knowledge_ready'])



class FollowupLedgerTest(unittest.TestCase):
    def test_investigated_tasks_are_recorded_and_skipped_results_need_prior_evidence(self):
        from tools.research import postgame_cycle as core
        from tests.test_postgame_runtime import plan,pub
        p,row=fixture();t,_=tasks_from(p,[row],PARENT)[0]
        def supported(*args):return dict(fake(*args),bestmove=row['case']['actual_move'])
        observation,_=execute(t,row,supported,lambda _:None)
        followup=dict(parent=PARENT,formal_adoption=False,completed_task_ids=[t['task_id']],results=[observation],previously_completed_task_ids=[])
        policy=plan();policy.update(parent=PARENT,progress_policy=__import__('tools.research.postgame_progress',fromlist=['POLICY_PROGRESS']).POLICY_PROGRESS,
                                   followup_policy=POLICY_FOLLOWUP)
        s=core.start(policy);s['stage']='prepare';s=core.request(s,dict(parent=PARENT),s['revision'])
        def evidence(state,research):
            return dict(input_sha256=state['pending']['input_sha256'],parent=PARENT,preparation=p,publication=pub(1),followup=research)
        completed=core.finish(s,s['pending']['operation_id'],evidence(s,followup))
        task=completed['research_followup']['work_items'][0]
        self.assertTrue(task['executor_connected']);self.assertTrue(task['status'].startswith('investigated_'))
        self.assertIn(t['task_id'],completed['research_followup']['completed'])
        completed.update(stage='prepare',generation=2,pending=None)
        completed=core.request(completed,dict(parent=PARENT,split_registry_sha256=completed['split_registry_sha256'],
                                             example_bank_sha256=completed['example_bank_sha256']),completed['revision'])
        skipped=dict(followup,completed_task_ids=[],results=[],previously_completed_task_ids=[t['task_id']])
        again=core.finish(completed,completed['pending']['operation_id'],evidence(completed,skipped))
        self.assertEqual(again['research_followup']['completed'],completed['research_followup']['completed'])
        skipped['previously_completed_task_ids']=['unknown']
        with self.assertRaises(ValueError):core.finish(completed,completed['pending']['operation_id'],evidence(completed,skipped))

if __name__=='__main__':unittest.main()
