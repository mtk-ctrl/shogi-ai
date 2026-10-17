import copy
import unittest
from tools.research.postgame_cycle import score_interval
from tools.research.postgame_runtime import initialize, advance, comparison_request
from tools.research.postgame_ranker import BASE, OPTIONS, POLICY, digest
from tools.research.postgame_eval_preflight import POLICY_LIVE, live_preflight, tactical_cases


def plan(generations=2,budget=4):
    params=dict(zip(OPTIONS,BASE))
    return dict(cycle_id='synthetic-runtime-test',purpose='integration_smoke',max_generations=generations,
                max_new_games=budget,source_games=2,generate_initial_source=True,candidate_kind='evaluation',
                runner_capacity=20,learning_policy=POLICY,live_policy=POLICY_LIVE,
                parent=dict(engine_ref='a'*40,knowledge_sha256='b'*64,parameters_sha256=digest(params)),
                seeds=[dict(source=1000+i*100,screen=1001+i*100,confirm=1002+i*100) for i in range(generations)])


def pub(number):
    return dict(readback_verified=True,api_digest_verified=True,bytes=100,sha256=digest(number))


class FakeBackend:
    """Synthetic effects only; NEVER claimed as live games or strength evidence."""
    run_id=1
    def __init__(self,ready=False,preflight_ok=True,confirm_wins=125):
        self.saved=[];self.launched=[];self.ready=ready;self.preflight_ok=preflight_ok
        self.confirm_wins=confirm_wins;self.prepare_parents=[];self.free=19
    def save(self,e):self.saved.append(copy.deepcopy(e))
    def free_runners(self,c):return self.free
    def dispatch(self,r):self.launched.append(copy.deepcopy(r));return 100+len(self.launched)
    def match_status(self,body):return 'success'
    def consume_match(self,e):
        s=e['state'];n=s['pending']['payload']['games']
        wins=55 if s['stage']=='screen' else self.confirm_wins if s['stage']=='confirm' else n//2
        counts=dict(wins=wins,losses=n-wins,draws=0)
        audit=dict(all_moves_legal=True,all_terminations_verified=True,conditions_verified=True,binary_verified=True,
                   knowledge_snapshot_verified=True,duplicates_checked=True,games=n,candidate_knowledge_uses=0,
                   prior_and_internal_duplicates_excluded=counts,
                   trajectory_outcomes=[dict(sha256=digest([s['generation'],s['stage'],i])) for i in range(n)])
        return dict(result=counts,audit=audit,started_lanes=e['match_request']['shards'],publication=pub(len(self.saved)))
    def prepare(self,e):
        self.prepare_parents.append(copy.deepcopy(e['parent_options']))
        params=dict(e['parent_options']);params['EvalSafety']+=1
        r=dict(learning=dict(status='requires_engine_validation' if self.ready else 'needs_data',options=params if self.ready else None),
               split_registry={'heldout-preserved':dict(split='quarantine',heldout_consumed=True)},
               example_bank=dict(schema='postgame-example-bank-v1',examples=[],parent_context=e['state']['parent']),candidate_knowledge=[])
        return dict(preparation=r,publication=pub(len(self.saved)))
    def preflight(self,e):
        return dict(preflight=dict(completed=True,disabled_exact=True,regressions=0,depth_ratio=1.,
                                   heldout_improved=int(self.preflight_ok)),publication=pub(len(self.saved)))


def drive(backend,p):
    e=initialize(p,dict(zip(OPTIONS,BASE)),'c'*64)
    for _ in range(12):
        e=advance(e,backend)
        if e['state']['stage']=='complete':return e
    raise AssertionError('cycle did not stop')


class RuntimeTest(unittest.TestCase):
    def test_two_generations_shortage_automatically_generate_unique_sources_and_stop(self):
        b=FakeBackend();e=drive(b,plan())
        self.assertEqual([r['seed'] for r in b.launched],[1000,1100])
        self.assertEqual([r['games'] for r in b.launched],[2,2])
        self.assertEqual((e['state']['generation'],e['state']['used_games'],e['state']['stage']),(2,4,'complete'))
        self.assertEqual([h['stage'] for h in e['state']['history']],['initial_source','prepare','collect_source','prepare'])
        self.assertFalse(e['formal_adoption'])

    def test_real_comparison_stages_and_research_parent_feedback_are_all_connected(self):
        b=FakeBackend(ready=True);e=drive(b,plan(budget=604))
        self.assertEqual([r['games'] for r in b.launched],[2,100,200,2,100,200])
        self.assertEqual(b.prepare_parents[1]['EvalSafety'],481)
        self.assertEqual(e['parent_options']['EvalSafety'],482)
        self.assertEqual(e['state']['parent']['engine_ref'],'a'*40)
        self.assertEqual(e['state']['parent']['knowledge_sha256'],'b'*64)
        self.assertFalse(e['state']['formal_adoption'])

    def test_preflight_rejection_retains_parent_and_collects_next_material(self):
        b=FakeBackend(ready=True,preflight_ok=False);e=drive(b,plan())
        self.assertEqual([r['games'] for r in b.launched],[2,2])
        self.assertEqual(e['parent_options'],dict(zip(OPTIONS,BASE)))
        self.assertEqual(e['state']['result'],'retain_parent_preflight_rejected')

    def test_failed_confirmation_retains_parameters_in_next_source(self):
        b=FakeBackend(ready=True,confirm_wins=100);e=drive(b,plan(budget=604))
        self.assertEqual(b.prepare_parents[0],b.prepare_parents[1])
        self.assertEqual(json_options(b.launched[3],'a')['EvalSafety'],480)

    def test_no_free_capacity_does_not_dispatch_or_spend(self):
        b=FakeBackend();b.free=0;e=advance(initialize(plan(),dict(zip(OPTIONS,BASE)),'c'*64),b)
        self.assertTrue(e['capacity_waiting']);self.assertEqual(b.launched,[]);self.assertEqual(e['state']['used_games'],0)

    def test_lost_dispatch_response_cannot_be_blindly_retried(self):
        b=FakeBackend();e=initialize(plan(),dict(zip(OPTIONS,BASE)),'c'*64)
        def lost(r):raise ConnectionError('unknown response')
        b.dispatch=lost
        with self.assertRaises(ConnectionError):advance(e,b)
        saved=b.saved[-1];self.assertTrue(saved['dispatch']['attempted']);self.assertIsNone(saved['dispatch']['body_run'])
        b.dispatch=lambda r:999
        with self.assertRaisesRegex(ValueError,'uncertain'):advance(saved,b)
        self.assertEqual(len(b.launched),0)

    def test_known_running_body_and_duplicate_completion_do_not_relaunch(self):
        b=FakeBackend();e=advance(initialize(plan(),dict(zip(OPTIONS,BASE)),'c'*64),b)
        b.match_status=lambda body:'waiting'
        self.assertEqual(advance(e,b),e);self.assertEqual(len(b.launched),1)
        b.match_status=lambda body:'success';e=advance(e,b)
        self.assertEqual(len(b.launched),2)
        e=advance(e,b);e=advance(e,b)
        self.assertEqual(len(b.launched),2);self.assertEqual(e['state']['used_games'],4)

    def test_all_available_lanes_and_actual_parent_candidate_options(self):
        b=FakeBackend(ready=True);e=advance(initialize(plan(budget=604),dict(zip(OPTIONS,BASE)),'c'*64),b)
        e=advance(e,b);req=b.launched[-1]
        self.assertEqual(req['shards'],19)
        self.assertEqual(json_options(req,'a')['EvalSafety'],481)
        self.assertEqual(json_options(req,'b')['EvalSafety'],480)
        self.assertTrue(json_options(req,'a')['USI_Ponder'])

    def test_policy_change_or_unsupported_knowledge_route_is_refused(self):
        p=plan();p['learning_policy']=dict(POLICY,epochs=101)
        with self.assertRaises(ValueError):initialize(p,dict(zip(OPTIONS,BASE)),'c'*64)
        p=plan();p['candidate_kind']='knowledge'
        with self.assertRaises(ValueError):initialize(p,dict(zip(OPTIONS,BASE)),'c'*64)


def json_options(r,side):
    return __import__('json').loads(r['options_'+side])


class PreflightTest(unittest.TestCase):
    def test_controls_are_legal_and_have_one_king_per_side(self):
        import shogi
        for c in tactical_cases():
            b=shogi.Board(c['start_sfen']);self.assertFalse(b.is_check())
            self.assertEqual(sum(p.piece_type==shogi.KING for p in [b.piece_at(i) for i in range(81) if b.piece_at(i)]),2)
            self.assertTrue(any(m.usi().startswith(c['expected_prefix']) for m in b.legal_moves))

    def test_actual_probe_measurements_gate_both_regression_and_unused_improvement(self):
        parent=dict(zip(OPTIONS,BASE));candidate=dict(parent,EvalSafety=481)
        rows=[dict(case_id='h',split='heldout'),dict(case_id='t',split='train')]
        cases=[dict(case_id=i,start_sfen='test-only',history_moves=[],history_key='hash',research_move='7g7f') for i in ('h','t')]
        def probe(c,opts,ms,depth):
            move=c.get('expected_prefix','7g7f' if opts==candidate else '2g2f')
            return dict(bestmove=move,status='recorded',kind='cp',value_stm=10,depth=depth or 4,bound='exact',pv_head_matches=True,history_key='hash')
        r=live_preflight(parent,candidate,dict(examples=rows),cases,probe)
        self.assertTrue(r['disabled_exact']);self.assertEqual((r['regressions'],r['heldout_improved'],r['depth_ratio']),(0,1,1.))
        def broken(c,opts,ms,depth):
            r=probe(c,opts,ms,depth)
            if opts==candidate:r['bestmove']='resign';r['depth']=1
            return r
        r=live_preflight(parent,candidate,dict(examples=rows),cases,broken)
        self.assertEqual(r['heldout_improved'],0);self.assertGreater(r['regressions'],0);self.assertLess(r['depth_ratio'],.9)

    def test_missing_original_history_cannot_pass(self):
        p=dict(zip(OPTIONS,BASE));c=dict(p,EvalSafety=481)
        with self.assertRaisesRegex(ValueError,'history'):
            live_preflight(p,c,dict(examples=[dict(case_id='missing',split='heldout')]),[],lambda *args:None)


if __name__=='__main__':unittest.main()
