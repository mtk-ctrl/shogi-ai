import copy
import unittest

import shogi
from tools.research.postgame_spiral import group_rows, parent_effect, prepare, actor_terms
from tools.research.postgame_cases import position_command, sha256
from tests.test_postgame_ranker import terms
from tests.test_postgame_ranker import dataset
from tools.research.postgame_ranker import BASE, OPTIONS, digest


def diagnosis():
    board = shogi.Board()
    def frame(history, move, value, depth):
        command = position_command(board.sfen(), tuple(history))
        return dict(status="recorded", kind="cp", bound="exact", depth=depth,
                    pv_head_matches=True, bestmove=move, value_stm=value,
                    history_key=sha256(command.encode()), position_command=command)
    root = frame([], "2g2f", 0, 3)
    return dict(route="stable_research_move_candidate", research_move="2g2f",
                root_short=root, root_deep=copy.deepcopy(root),
                followup=dict(requested_depth=3, actual=frame(["7g7f"], "3c3d", 200, 3),
                              research=frame(["2g2f"], "3c3d", 0, 3),
                              comparison=dict(status="comparable", improvement_cp=200, actual_depth=3, improved_depth=3)),
                case=dict(case_id="a"*64, start_sfen=board.sfen(), history_moves=[],
                          history_key=root["history_key"], position_key=" ".join(board.sfen().split()[:3]),
                          actual_move="7g7f", source=dict(run_id=1, game_id="g", ply=1),
                          actor="A", outcome=dict(status="unresolved", terminal_reward_stm=None,
                                                   winner=None, reason="move_limit")))


class SpiralTest(unittest.TestCase):
    def test_parent_already_correct_does_not_spawn_useless_candidate(self):
        row = diagnosis()
        report = prepare([row], lambda c: [row["root_deep"]]*2,
                         lambda s: self.fail("no static training for solved example"), "fixed")
        self.assertEqual(report["rejected"], {"already_correct": 1})
        self.assertEqual(report["candidate_knowledge"], [])
        self.assertEqual(report["learning"]["status"], "needs_data")

    def test_unstable_parent_is_held_not_trained(self):
        self.assertEqual(parent_effect(["7g7f", "2g2f"], "2g2f"), "unstable_parent")

    def test_white_feature_sign_and_reward_are_separate(self):
        white = actor_terms(terms(safety=90, material_term=-100), -1)
        self.assertEqual(white["total"], 10)
        self.assertEqual(white["safety"], -90)

    def test_unresolved_game_cannot_be_a_draw_teacher(self):
        row = diagnosis(); row["case"]["outcome"]["terminal_reward_stm"] = 0
        with self.assertRaisesRegex(ValueError, "unresolved"):
            prepare([row], lambda c: [], lambda s: terms(), "fixed")

    def test_comparison_and_history_tamper_is_rejected(self):
        for key in ("comparison", "history"):
            row = diagnosis()
            if key == "comparison": row["followup"]["actual"]["value_stm"] = 100
            else: row["followup"]["actual"]["position_command"] = "position startpos"
            with self.assertRaises(ValueError): prepare([row], lambda c: [], lambda s: terms(), "fixed")

    def test_transitive_grouping_prevents_game_and_near_position_leakage(self):
        rows = [dict(case_id=str(i), game=g, leakage_keys=k) for i, (g, k) in enumerate([
            ("g1", ["position:a"]), ("g1", ["formation:b"]),
            ("g2", ["formation:b"]), ("g3", ["position:z"])])]
        group_rows(rows, "fixed")
        self.assertEqual(len({r["group"] for r in rows[:3]}), 1)
        self.assertNotEqual(rows[0]["group"], rows[3]["group"])
        # Input order cannot move a connected component between train/test.
        before = {r["case_id"]: (r["group"], r["split"]) for r in rows}
        rows.reverse(); group_rows(rows, "fixed")
        self.assertEqual(before, {r["case_id"]: (r["group"], r["split"]) for r in rows})

    def test_prior_heldout_never_becomes_training_when_new_cases_arrive(self):
        registry = {"position:old": dict(group="previous", split="heldout")}
        rows = [dict(case_id="new", game="new-game", leakage_keys=["position:old", "position:new"])]
        group_rows(rows, "different-generation-seed", registry)
        self.assertEqual(rows[0]["split"], "heldout")
        self.assertEqual(registry["position:new"]["split"], "heldout")

    def test_new_bridge_between_previous_train_and_test_quarantines_both(self):
        registry = {"position:a": dict(group="old-train", split="train"),
                    "position:b": dict(group="old-heldout", split="heldout"),
                    "unseen-old-alias": dict(group="old-heldout", split="heldout")}
        rows = [dict(case_id="bridge", game="g", leakage_keys=["position:a", "position:b"])]
        group_rows(rows, "fixed", registry)
        self.assertEqual(rows[0]["split"], "quarantine")
        self.assertEqual({v["split"] for v in registry.values()}, {"quarantine"})

    def test_examined_holdout_cannot_be_called_unused_again(self):
        registry = {"position:old": dict(group="previous", split="heldout", heldout_consumed=True)}
        rows = [dict(case_id="new", game="new-game", leakage_keys=["position:old"])]
        group_rows(rows, "fixed", registry)
        self.assertEqual(rows[0]["split"], "quarantine")

    def bank(self):
        rows=dataset()
        registry={}
        for r in rows:
            r['leakage_keys']=['position:'+r['case_id']]
            for key in ['game:'+r['game'],*r['leakage_keys']]:
                registry[key]=dict(group=r['group'],split=r['split'])
        context=dict(engine_ref='a'*40,knowledge_sha256='b'*64,parameters_sha256=digest(dict(zip(OPTIONS,BASE))))
        bank=dict(schema='postgame-example-bank-v1',parent_context=context,examples=rows)
        return bank,registry

    def test_eligible_examples_survive_batches_and_can_reach_learning_gate(self):
        bank,registry=self.bank()
        result=prepare([],lambda c: [],lambda s: {},'fixed',registry=registry,
                       example_bank=bank,parent_context=bank['parent_context'])
        self.assertEqual(result['bank_pairs_reused'],32)
        self.assertEqual(result['learning']['status'],'requires_engine_validation')
        # Next generation cannot reuse the heldout score it just examined.
        following=prepare([],lambda c: [],lambda s: {},'fixed',registry=result['split_registry'],
                          example_bank=result['example_bank'],parent_context=bank['parent_context'])
        self.assertEqual(following['learning']['status'],'needs_data')
        self.assertEqual(following['learning']['split_groups']['heldout'],0)

    def test_new_parent_cannot_learn_stale_static_features(self):
        bank,registry=self.bank()
        with self.assertRaisesRegex(ValueError,'different research parent'):
            prepare([],lambda c: [],lambda s: {},'fixed',registry=registry,
                    example_bank=bank,parent_context=dict(bank['parent_context'],engine_ref='c'*40))

    def test_time_only_pair_is_deferred_instead_of_aborting_the_cycle(self):
        r=diagnosis();r['followup']=None
        result=prepare([r],lambda c: self.fail('do not probe unconfirmed pair'),lambda s: {},'fixed')
        self.assertEqual(result['rejected']['needs_fixed_depth_verification'],1)


if __name__ == "__main__": unittest.main()
