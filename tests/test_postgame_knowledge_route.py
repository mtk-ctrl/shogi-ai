import copy,json,tempfile,unittest
from pathlib import Path
from tools.research.postgame_knowledge_route import materialize,validate_intent,verify_materialization
from tools.research.postgame_knowledge import preflight,stage,POLICY_KNOWLEDGE
from tools.research.postgame_runtime import initialize,comparison_request,advance,POLICY_KNOWLEDGE_EXECUTION
from tools.research.postgame_progress import POLICY_PROGRESS
from tools.research.postgame_cycle import request
from tools.research.postgame_cases import sha256
from tools.research.postgame_ranker import digest,BASE,OPTIONS
from tests.test_postgame_knowledge import proposal,fake_live
from tests.test_postgame_runtime import plan,FakeBackend,pub,drive


def files_and_env(root):
    base,params,_,candidate,manifest=proposal();parent=manifest['parent']
    check=preflight(manifest,lambda *args:fake_live(manifest,*args))
    prep=root/'prep';target=prep/'knowledge-stage';target.mkdir(parents=True)
    staged=stage(base,candidate,manifest,check,target/'staged',params)
    binary=b'synthetic protocol fixture, never executed';binary_sha=sha256(binary)
    result=dict(status='ready_for_separate_match_adapter',manifest=manifest,preflight=check,staging=staged,binary_sha256=binary_sha)
    (target/'result.json').write_text(json.dumps(result))
    source=root/'source';(source/'build').mkdir(parents=True)
    (source/'build/engine-a').write_bytes(binary);(source/'build/position-knowledge-v1.tsv').write_bytes(base)
    audit=dict(all_moves_legal=True,all_terminations_verified=True,binary_verified=True,knowledge_snapshot_verified=True,
               parent_ref=parent['engine_ref'],actual_binary_sha256=dict(A=binary_sha,B=binary_sha))
    (source/'stage-result.json').write_text(json.dumps(dict(audit=audit)))
    p=plan(budget=604);p.update(candidate_kind='knowledge',parent=parent,knowledge_policy=POLICY_KNOWLEDGE,
                             progress_policy=POLICY_PROGRESS,knowledge_execution_policy=POLICY_KNOWLEDGE_EXECUTION)
    e=initialize(p,params,'c'*64);s=e['state'];s.update(stage='screen',expected_parameters_sha256=parent['parameters_sha256'],
                         expected_knowledge_sha256=manifest['candidate_sha256'],candidate=dict(parent,knowledge_sha256=manifest['candidate_sha256']))
    e.update(candidate_options=params,source_publication='source',preparation_publication='prep',knowledge_candidate=result)
    s['pending']=None;e['state']=request(s,dict(parent=parent,candidate=s['candidate']),s['revision'])
    e['match_request']=comparison_request(e,19);e['dispatch']=dict(attempted=True,body_run=None)
    return e,lambda ref:root/ref,base,candidate


class KnowledgeRouteTest(unittest.TestCase):
    def test_separate_fixed_inputs_use_exact_archived_binary_without_new_build(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);e,read,base,candidate=files_and_env(root)
            proof=materialize(e,read,root/'out','integration_smoke')
            self.assertEqual((root/'out/knowledge-A.tsv').read_bytes(),candidate)
            self.assertEqual((root/'out/knowledge-B.tsv').read_bytes(),base)
            self.assertEqual(proof['actual_binary_sha256']['A'],proof['actual_binary_sha256']['B'])
            self.assertFalse(proof['new_build_performed']);verify_materialization(root/'out',proof,e['match_request'])
            (root/'out/knowledge-B.tsv').write_bytes(candidate)
            with self.assertRaises(ValueError):verify_materialization(root/'out',proof,e['match_request'])

    def test_synthetic_wiring_cannot_become_a_normal_strength_dispatch(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);e,read,_,_=files_and_env(root)
            with self.assertRaises(ValueError):materialize(e,read,root/'out','research')

    def test_accepted_research_knowledge_is_used_by_both_sides_in_next_source(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);e,read,_,candidate=files_and_env(root);s=e['state']
            s.update(stage='collect_source',parent=s['candidate'],pending=None)
            e['parent_knowledge_publication']='prep'
            e['state']=request(s,dict(parent=s['parent']),s['revision'])
            e['match_request']=comparison_request(e,19)
            proof=materialize(e,read,root/'next','integration_smoke')
            self.assertEqual((root/'next/knowledge-A.tsv').read_bytes(),candidate)
            self.assertEqual((root/'next/knowledge-B.tsv').read_bytes(),candidate)
            self.assertEqual(proof['candidate_research_ids'],[])

    def test_changed_intent_search_source_and_staging_fail_before_execution(self):
        for kind in ('seed','evaluation','body','source','candidate'):
            with tempfile.TemporaryDirectory() as td:
                root=Path(td);e,read,_,_=files_and_env(root)
                if kind=='seed':e['match_request']['seed']+=1
                elif kind=='evaluation':
                    options=json.loads(e['match_request']['options_a']);options['EvalSafety']+=1
                    e['match_request']['options_a']=json.dumps(options)
                elif kind=='body':e['dispatch']['body_run']=123
                elif kind=='source':(root/'source/build/engine-a').write_bytes(b'changed')
                else:(root/'prep/knowledge-stage/staged/A.tsv').write_bytes(b'changed')
                with self.assertRaises(ValueError,msg=kind):materialize(e,read,root/'out','integration_smoke')

    def test_knowledge_only_preparation_never_fits_or_exposes_unused_groups(self):
        from unittest.mock import patch
        from tools.research.postgame_spiral import prepare
        from tests.test_postgame_knowledge import fixture
        from tests.test_postgame_ranker import terms
        _,params,parent,row,old,original=fixture('heldout')
        with patch('tools.research.postgame_spiral.fit',side_effect=AssertionError('knowledge-only must not fit')):
            report=prepare([row],lambda _:[original,original],lambda _:terms(),'synthetic-only',
                           registry=old['split_registry'],parent_options=params,parent_context=parent,
                           track_decisions=True,evaluation_enabled=False)
        self.assertEqual(report['learning']['trials'],0)
        self.assertEqual(report['learning']['status'],'not_requested_knowledge_only')
        self.assertFalse(any(r['heldout_consumed'] for r in report['split_registry'].values()))


class KnowledgeBackend(FakeBackend):
    """State-machine branch simulation, never live strength evidence."""
    def __init__(self,uses=1,confirm_wins=125):super().__init__(confirm_wins=confirm_wins);self.uses=uses
    def prepare(self,e):
        from tests.test_postgame_progress import measured
        parent=e['state']['parent'];p=measured('stable_research_move_candidate',context=parent)
        data=dict(preparation=p,publication=pub(len(self.saved)))
        k=dict(manifest=dict(parent=parent,purpose='research',production_match_eligible=True,formal_adoption=False,
                           candidate_positions=1,candidate_sha256=digest([parent,'knowledge-child'])),
               preflight=dict(completed=True,disabled_exact=True,regressions=0,depth_ratio=1.,targeted_corrections=1,candidate_knowledge_hits=1))
        return dict(data,knowledge_stage=k)
    def preflight(self,e):return dict(preflight=e['knowledge_candidate']['preflight'],publication=pub(len(self.saved)))
    def consume_match(self,e):
        data=super().consume_match(e);data['audit']['candidate_knowledge_uses']=self.uses;return data



class KnowledgeRuntimeTest(unittest.TestCase):
    def test_full_knowledge_comparison_and_next_generation_inheritance(self):
        p=plan(budget=604);p.update(candidate_kind='knowledge',knowledge_policy=POLICY_KNOWLEDGE,
                                  knowledge_execution_policy=POLICY_KNOWLEDGE_EXECUTION,progress_policy=POLICY_PROGRESS)
        e=initialize(p,dict(zip(OPTIONS,BASE)),'c'*64)
        b=KnowledgeBackend()
        for _ in range(12):
            e=advance(e,b)
            if e['state']['stage']=='complete':break
        self.assertEqual([r['games'] for r in b.launched],[2,100,200,2,100,200])
        self.assertNotIn('execution_route',b.launched[0])
        self.assertTrue(all(r['execution_route']=='research_knowledge' for r in b.launched[1:]))
        self.assertEqual(e['parent_options'],dict(zip(OPTIONS,BASE)))
        self.assertIsNotNone(e['parent_knowledge_publication']);self.assertFalse(e['formal_adoption'])

    def test_zero_use_or_failed_confirmation_does_not_promote_research_parent(self):
        for uses,wins in ((0,125),(1,100)):
            p=plan(budget=604);p.update(candidate_kind='knowledge',knowledge_policy=POLICY_KNOWLEDGE,
                                      knowledge_execution_policy=POLICY_KNOWLEDGE_EXECUTION,progress_policy=POLICY_PROGRESS)
            e=initialize(p,dict(zip(OPTIONS,BASE)),'c'*64);b=KnowledgeBackend(uses,wins)
            for _ in range(12):
                e=advance(e,b)
                if e['state']['stage']=='complete':break
            self.assertEqual(e['state']['parent'],p['parent']);self.assertIsNone(e['parent_knowledge_publication'])
            if uses==0:self.assertNotIn(200,[r['games'] for r in b.launched])

if __name__=='__main__':unittest.main()
