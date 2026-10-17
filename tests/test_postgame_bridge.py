import copy
import json
import unittest
from unittest.mock import patch

from tools.research.postgame_bridge import match_request, validate_shard
from tools.research.postgame_ranker import BASE, OPTIONS, digest
from tools.research.postgame_cycle import start, request, observe_start, finish
from tools.research.postgame_spiral import prepare
from tools.research.postgame_analyze import search
from tests.test_postgame_cycle import plan, receipt


def initial():
    p = plan(games=2)
    params = dict(zip(OPTIONS, BASE))
    p.update(generate_initial_source=True, purpose="integration_smoke", source_games=2)
    p["parent"]["parameters_sha256"] = digest(params)
    s = start(p)
    return request(s, dict(parent=s["parent"]), s["revision"]), params


def row():
    req = dict(games=2, shards=2, seed=1000, go_command="go movetime 200", max_plies=300,
               options_a='{"PositionKnowledge":true}', options_b='{"PositionKnowledge":true}')
    data = dict(games=1, game_offset=0, seed=1000, go_command=req["go_command"], max_plies=300,
                illegal_games=0, sha256_a="a"*64, sha256_b="a"*64,
                options_a=dict(PositionKnowledge=True,PositionKnowledgeFile='position-knowledge-v1.tsv',RiskVerify=True,USI_Ponder=True),
                options_b=dict(PositionKnowledge=True,PositionKnowledgeFile='position-knowledge-v1.tsv',RiskVerify=True,USI_Ponder=True),
                position_knowledge={side:dict(enabled=True,available=True,sha256="b"*64,positions=163) for side in ('A','B')},
                details=[dict(a_black=True,moves=['7g7f'],move_records=[dict(move='7g7f',engine='A',search=dict(phase_maturity=0))])])
    return req, data


class BridgeTest(unittest.TestCase):
    def test_source_generation_uses_existing_entry_and_available_lanes(self):
        s, params = initial()
        req = match_request(s, params, 20)
        self.assertEqual((req["games"], req["shards"], req["entry"]), (2,2,"owner_issue"))
        self.assertEqual(req["options_a"],req["options_b"])
        with self.assertRaises(ValueError): match_request(s,params,0)

    def test_changed_research_parameters_use_authorized_existing_file_input(self):
        s, params = initial(); params["EvalSafety"] += 1
        s["parent"]["parameters_sha256"] = digest(params)
        req = match_request(s,params,2)
        self.assertEqual(req["entry"],"existing_request_file")
        self.assertEqual(json.loads(req["options_a"])["EvalSafety"],481)

    def test_initial_source_then_prepare_counts_the_actual_budget(self):
        s, _ = initial(); op=s["pending"]["operation_id"]
        s=observe_start(s,op,1,2,2)
        e=receipt(s,1,1)
        s=finish(s,op,e)
        self.assertEqual((s["stage"],s["used_games"],s["generation"]),("prepare",2,1))
        s=request(s,dict(parent=s["parent"]),s["revision"])
        e=receipt(s);e["preparation"]=dict(learning=dict(status="needs_data"),candidate_knowledge=[],split_registry={})
        s=finish(s,s["pending"]["operation_id"],e)
        self.assertEqual(s["stage"],"complete")
        self.assertEqual(s["used_games"],2)

    def test_small_batch_requires_explicit_smoke_purpose(self):
        p=plan();p["source_games"]=2
        with self.assertRaises(ValueError):start(p)

    def test_source_conditions_and_colors_are_not_just_inferred_from_score(self):
        req,data=row();validate_shard(data,0,req,"a"*64,"b"*64)
        for kind in ('seed','color','knowledge','options','binary'):
            bad=copy.deepcopy(data)
            if kind=='seed':bad['seed']+=1
            elif kind=='color':bad['details'][0]['a_black']=False
            elif kind=='knowledge':bad['position_knowledge']['A']['available']=False
            elif kind=='options':bad['options_a']['PositionKnowledge']=False
            else:bad['sha256_b']='c'*64
            with self.assertRaises(ValueError,msg=kind):validate_shard(bad,0,req,"a"*64,"b"*64)

    def test_parent_parameters_reach_real_analyzer_constructor(self):
        params=dict(zip(OPTIONS,BASE));params['EvalSafety']=490
        with patch('tools.research.postgame_analyze.Analyzer') as cls:
            search('binary','knowledge',dict(start_sfen='sfen'),('7g7f',),50,evaluation_options=params)
            self.assertEqual(cls.call_args.kwargs['evaluation_options'],params)
            cls.return_value.search.assert_called_once_with('sfen',('7g7f',),50,None)

    def test_separate_build_paths_preserve_and_check_both_binary_hashes(self):
        req,data=row();data['sha256_b']='c'*64
        validate_shard(data,0,req,dict(A='a'*64,B='c'*64),'b'*64)
        with self.assertRaises(ValueError):validate_shard(data,0,req,dict(A='a'*64,B='a'*64),'b'*64)

    def test_early_terminal_batch_with_no_selected_cases_is_material_shortage(self):
        result=prepare([],lambda c: [],lambda s: {},'fixed')
        self.assertEqual(result['learning']['status'],'needs_data')
        self.assertIsNone(result['learning']['options'])


if __name__=='__main__':unittest.main()
