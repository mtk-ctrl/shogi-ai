"""Synthetic effect tests; no result here is live strength/training evidence."""
import copy
import unittest
import tempfile,json
from pathlib import Path
from tools.research import postgame_practice_cycle as pc
from tools.research import postgame_cycle as core
from tools.research.postgame_runtime import initialize,advance,POLICY_KNOWLEDGE_EXECUTION
from tools.research.postgame_knowledge import POLICY_KNOWLEDGE
from tools.research.postgame_progress import POLICY_PROGRESS
from tools.research.postgame_ranker import BASE,OPTIONS,digest
from tests.test_postgame_runtime import FakeBackend,plan,pub
from tests.test_postgame_followup import fixture


def prepared(split='train'):
    p,row=fixture(split);p['progress']['analysis']['analyzer_binary_sha256']='a'*64
    return p,row


def cycle_plan(generations=1,budget=2):
    p=plan(generations,budget)
    p.update(candidate_kind='knowledge',knowledge_policy=POLICY_KNOWLEDGE,
             knowledge_execution_policy=POLICY_KNOWLEDGE_EXECUTION,progress_policy=POLICY_PROGRESS,
             practice_cycle_policy=copy.deepcopy(pc.POLICY_PRACTICE_CYCLE))
    for i,seeds in enumerate(p['seeds']):seeds['practice']=2000+i
    return p


def knowledge(parent,ready=False):
    return dict(manifest=dict(parent=parent,purpose='research',production_match_eligible=True,formal_adoption=False,
                              candidate_positions=int(ready),candidate_sha256='e'*64),
                preflight=dict(completed=True,passed=True,disabled_exact=True,regressions=0,depth_ratio=1.,
                               targeted_corrections=1,candidate_knowledge_hits=1))


def receipt(s):
    offer=s['practice_offer'];p=offer['plan']
    return dict(schema='postgame-practice-cycle-receipt-v1',parent=s['parent'],plan_sha256=p['plan_sha256'],
        practice_ids=[r['practice_id'] for r in p['roots']],games=offer['games'],new_plies=64,
        replayed_prefix_plies=0,handoff_available=True,selected_cases=8,trajectory_signatures=[digest('synthetic-practice')],
        analysis_reservation_ms=offer['analysis_reservation_ms'],requested_analysis_ms=1000,
        verification={k:True for k in ('all_moves_legal','all_terminations_verified','settings_verified','full_history_verified',
                                       'raw_archive_reproduced','handoff_reproduced')},
        formal_adoption=False,strength_improvement_demonstrated=False)


class PracticeBackend(FakeBackend):
    def __init__(self,ready=False,split='train'):
        super().__init__();self.ready_practice=ready;self.split=split;self.practiced=[]
    def prepare(self,e):
        p,row=prepared(self.split)
        offer=pc.make_offer(p,[row],e['state']['parent'],e['state']['plan']['seeds'][0]['practice'],e['state']['practice_ledger'])
        return dict(preparation=p,knowledge_stage=knowledge(e['state']['parent']),practice_offer=offer,publication=pub(len(self.saved)))
    def practice(self,e,execute):
        if not execute:raise ValueError('unknown practice outcome; do not regenerate')
        self.practiced.append(copy.deepcopy(e));p,_=prepared(self.split)
        return dict(preparation=p,knowledge_stage=knowledge(e['state']['parent'],self.ready_practice),
                    practice=receipt(e['state']),publication=pub(len(self.saved)))
    def preflight(self,e):
        return dict(preflight=e['knowledge_candidate']['preflight'],publication=pub(len(self.saved)))
    def consume_match(self,e):
        r=super().consume_match(e);r['audit']['candidate_knowledge_uses']=1;return r


def finish(b,p):
    e=initialize(p,dict(zip(OPTIONS,BASE)),'c'*64)
    for _ in range(8):
        e=advance(e,b)
        if e['state']['stage']=='complete':return e
    raise AssertionError('cycle did not finish')


class PracticeCycleTest(unittest.TestCase):
    def test_shortage_inserts_practice_and_reanalysis_without_another_source(self):
        b=PracticeBackend();e=finish(b,cycle_plan())
        self.assertEqual([r['games'] for r in b.launched],[2]);self.assertEqual(len(b.practiced),1)
        self.assertEqual([r['stage'] for r in e['state']['history']],['initial_source','prepare','practice'])
        self.assertEqual(e['state']['practice_used_games'],4);self.assertEqual(e['state']['used_games'],2)
        self.assertEqual(e['state']['practice_analysis_reserved_ms'],600000)
        self.assertEqual(e['state']['result'],'research_review_required');self.assertEqual(e['state']['parent'],cycle_plan()['parent'])
        self.assertIn(digest('synthetic-practice'),e['prior_signatures'])

    def test_practice_candidate_reaches_existing_gates_and_research_parent_only(self):
        b=PracticeBackend(ready=True);e=finish(b,cycle_plan(budget=302))
        self.assertEqual([r['games'] for r in b.launched],[2,100,200])
        self.assertEqual([r['stage'] for r in e['state']['history']],['initial_source','prepare','practice','preflight','screen','confirm'])
        self.assertEqual(e['state']['parent']['knowledge_sha256'],'e'*64)
        self.assertIsNotNone(e['parent_knowledge_publication']);self.assertFalse(e['formal_adoption'])

    def test_validation_or_heldout_cannot_be_practiced(self):
        for split in ('validation','heldout'):
            b=PracticeBackend(split=split);e=finish(b,cycle_plan())
            self.assertEqual(b.practiced,[]);self.assertEqual(e['state']['practice_used_games'],0)

    def test_same_parent_completed_tasks_are_excluded_and_cost_caps_stop_work(self):
        p,row=prepared();offer=pc.make_offer(p,[row],cycle_plan()['parent'],2000)
        s=core.start(cycle_plan());self.assertTrue(pc.available(s,offer)[0])
        done=[dict(parent=s['parent'],practice_ids=[offer['plan']['roots'][0]['practice_id']])]
        self.assertFalse(pc.make_offer(p,[row],s['parent'],2000,done)['plan']['roots'])
        for key,value,reason in (('practice_used_games',5,'game_budget'),('practice_analysis_reserved_ms',800000,'analysis_budget')):
            bad=copy.deepcopy(s);bad[key]=value
            self.assertFalse(pc.available(bad,offer)[0]);self.assertIn(reason,pc.available(bad,offer)[1])

    def test_lost_execution_is_persisted_and_never_regenerated_on_resume(self):
        b=PracticeBackend();e=advance(initialize(cycle_plan(),dict(zip(OPTIONS,BASE)),'c'*64),b)
        original=b.practice
        def lost(e,execute):
            if execute:raise ConnectionError('lost after practice intent')
            return original(e,execute)
        b.practice=lost
        with self.assertRaises(ConnectionError):advance(e,b)
        saved=b.saved[-1];self.assertTrue(saved['practice_execution']['attempted'])
        with self.assertRaisesRegex(ValueError,'do not regenerate'):advance(saved,b)
        self.assertEqual(b.practiced,[]);self.assertEqual(len(b.launched),1)

    def test_receipt_tampering_or_missing_audit_is_rejected(self):
        b=PracticeBackend();finish(b,cycle_plan());s=b.practiced[0]['state'];r=receipt(s)
        self.assertEqual(pc.accept(s,r)['practice_used_games'],4)
        for key,value in (('games',5),('new_plies',65),('requested_analysis_ms',600001),('selected_cases',9),
                          ('plan_sha256','f'*64),('practice_ids',[]),('formal_adoption',True)):
            bad=copy.deepcopy(r);bad[key]=value
            with self.assertRaises(ValueError,msg=key):pc.accept(s,bad)
        bad=copy.deepcopy(r);bad['verification']['handoff_reproduced']=False
        with self.assertRaises(ValueError):pc.accept(s,bad)

    def test_practice_seed_and_source_are_bound_to_pending_intent(self):
        b=PracticeBackend();finish(b,cycle_plan());s=copy.deepcopy(b.practiced[0]['state']);s['pending']=None
        for args in ({'practice_plan_sha256':'wrong'},{'preparation_publication_sha256':'wrong'}):
            inputs=dict(parent=s['parent'],practice_plan_sha256=s['practice_offer']['plan']['plan_sha256'],
                        preparation_publication_sha256=s['practice_preparation_publication_sha256'],**{})
            inputs.update(args)
            with self.assertRaises(ValueError):core.request(s,inputs,s['revision'])

    def test_policy_changes_and_seed_reuse_are_not_silent_extensions(self):
        for key in ('max_attempts','max_practice_games','analysis_reservation_ms_per_attempt'):
            p=cycle_plan();p['practice_cycle_policy'][key]+=1
            with self.assertRaises(ValueError):initialize(p,dict(zip(OPTIONS,BASE)),'c'*64)
        p=cycle_plan();p['seeds'][0]['practice']=p['seeds'][0]['source']
        with self.assertRaises(ValueError):initialize(p,dict(zip(OPTIONS,BASE)),'c'*64)

    def test_old_exposure_and_completion_history_imports_no_old_feature_bank(self):
        p,row=prepared();offer=pc.make_offer(p,[row],cycle_plan()['parent'],2000);old=offer['plan']
        spec=dict(schema='postgame-training-history-v1',preparation_sha256=digest(p),
                  completed_practice_ids=[r['practice_id'] for r in old['roots']])
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'practice';(root/'handoff').mkdir(parents=True)
            (root/'plan.json').write_text(json.dumps(old));(root/'handoff/preparation.json').write_text(json.dumps(p))
            (root/'result.json').write_text(json.dumps(dict(plan_sha256=old['plan_sha256'],completed_practice_ids=spec['completed_practice_ids'])))
            self.assertEqual(pc.training_history(td,spec,old['parent']),p['split_registry'])
            self.assertEqual(pc.make_offer(p,[row],old['parent'],2000,prior_ids=spec['completed_practice_ids'])['plan']['roots'],[])
            spec['completed_practice_ids']=[]
            with self.assertRaises(ValueError):pc.training_history(td,spec,old['parent'])

    def test_explicit_successor_preserves_practice_cost_and_ids(self):
        from tests.test_postgame_backend import m
        p=cycle_plan();s=core.start(p);s.update(stage='complete',practice_ledger=[dict(parent=s['parent'],practice_ids=['f'*64])],
                      practice_used_games=4,practice_analysis_reserved_ms=600000)
        s['plan']['algorithm_sha256']='fixed'
        old=dict(state=s,blocked=None,formal_adoption=False,parent_options={},preparation_publication={},
                 prior_signatures=[],trajectory_index_sha256=digest([]))
        newplan=copy.deepcopy(p);newplan.update(algorithm_sha256='fixed',seeds=[dict(source=3000,screen=3001,confirm=3002,practice=3003)])
        new=dict(state=core.start(newplan),parent_options={})
        inherited=m.inherit_predecessor(new,old)
        self.assertEqual(inherited['state']['practice_ledger'],s['practice_ledger'])
        self.assertEqual(inherited['state']['practice_used_games'],4)
        self.assertEqual(inherited['state']['practice_analysis_reserved_ms'],600000)


if __name__=='__main__':unittest.main()
