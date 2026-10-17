import copy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest

from tools.research.postgame_cycle import start, request, observe_start, finish, eta, save_state


def plan(kind="evaluation", generations=1, games=300):
    return dict(cycle_id="test-only", max_generations=generations, max_new_games=games,
                candidate_kind=kind, parent=dict(engine_ref="a"*40, knowledge_sha256="b"*64,
                                                 parameters_sha256="c"*64),
                seeds=[dict(screen=1000+3*i, confirm=1001+3*i, source=1002+3*i)
                       for i in range(generations)])


def candidate(state):
    out = state["parent"].copy()
    key = "knowledge_sha256" if state["plan"]["candidate_kind"] == "knowledge" else "parameters_sha256"
    out[key] = "d"*64 if key == "knowledge_sha256" else state["expected_parameters_sha256"]
    return out


def pending(state):
    inputs = dict(parent=state["parent"])
    if state["stage"] == "prepare" and state["generation"] > 1:
        inputs["split_registry_sha256"] = state["split_registry_sha256"]
    if state["stage"] in ("preflight", "screen", "confirm"):
        inputs["candidate"] = state.get("candidate", candidate(state))
    return request(state, inputs, state["revision"])


def receipt(state, wins=None, losses=None, draws=0, uses=1):
    p = state["pending"]
    e = dict(input_sha256=p["input_sha256"], parent=state["parent"],
             publication=dict(readback_verified=True, api_digest_verified=True, bytes=99, sha256="e"*64))
    if state["stage"] == "prepare":
        e["preparation"] = dict(learning=dict(status="requires_engine_validation", options={"test_only": 1}),
                                candidate_knowledge=["test"], split_registry={})
    elif state["stage"] == "preflight":
        e.update(candidate=p["payload"]["inputs"]["candidate"],
                 preflight=dict(disabled_exact=True, regressions=0, depth_ratio=.95, heldout_improved=2,
                                targeted_corrections=2, candidate_knowledge_hits=2))
    else:
        e.update(body_run=p["body_run"], seed=p["payload"]["seed"],
                 candidate=state.get("candidate"), result=dict(wins=wins, losses=losses, draws=draws),
                 audit=dict(all_moves_legal=True, all_terminations_verified=True, conditions_verified=True,
                            binary_verified=True, knowledge_snapshot_verified=True, duplicates_checked=True,
                            games=p["payload"]["games"], candidate_knowledge_uses=uses,
                            prior_and_internal_duplicates_excluded=dict(wins=wins, losses=losses, draws=draws)))
    return e


def ready(kind="evaluation", generations=1, games=300):
    s = start(plan(kind, generations, games))
    for _ in range(2):
        s = pending(s)
        s = finish(s, s["pending"]["operation_id"], receipt(s))
    return s


def begun(s):
    s = pending(s)
    return observe_start(s, s["pending"]["operation_id"], 10, 20, 20)


class CycleTest(unittest.TestCase):
    def test_evaluation_confirmation_advances_only_research_parent(self):
        s = begun(ready(generations=2, games=600))
        s = finish(s, s["pending"]["operation_id"], receipt(s, 55, 45))
        self.assertEqual(s["stage"], "confirm")
        s = begun(s)
        child = s["candidate"]
        s = finish(s, s["pending"]["operation_id"], receipt(s, 125, 75))
        self.assertEqual(s["parent"], child)
        self.assertFalse(s["formal_adoption"])
        self.assertEqual(s["stage"], "collect_source")
        s = begun(s)
        s = finish(s, s["pending"]["operation_id"], receipt(s, 50, 50))
        self.assertEqual((s["generation"], s["stage"], s["used_games"]), (2, "prepare", 400))
        with self.assertRaisesRegex(ValueError, "registry"):
            request(s, dict(parent=s["parent"]), s["revision"])

    def test_zero_knowledge_use_does_not_spend_confirmation_games(self):
        s = begun(ready("knowledge"))
        parent = s["parent"].copy()
        s = finish(s, s["pending"]["operation_id"], receipt(s, 70, 30, uses=0))
        self.assertEqual((s["stage"], s["used_games"], s["parent"]), ("complete", 100, parent))

    def test_unproven_confirmation_retains_parent_and_stops_at_generation_cap(self):
        s = begun(ready()); parent = s["parent"].copy()
        s = finish(s, s["pending"]["operation_id"], receipt(s, 50, 50))
        s = begun(s)
        s = finish(s, s["pending"]["operation_id"], receipt(s, 100, 99, 1))
        self.assertEqual((s["stage"], s["result"], s["parent"]), ("complete", "retain_parent", parent))
        with self.assertRaises(ValueError): pending(s)

    def test_duplicate_exclusion_can_reject_a_nominal_win(self):
        s = begun(ready())
        s = finish(s, s["pending"]["operation_id"], receipt(s, 60, 40))
        s = begun(s); e = receipt(s, 125, 75)
        e["audit"]["prior_and_internal_duplicates_excluded"] = dict(wins=75, losses=75, draws=0)
        s = finish(s, s["pending"]["operation_id"], e)
        self.assertEqual(s["result"], "retain_parent")

    def test_needs_data_can_collect_bounded_new_material_without_adopting(self):
        s = pending(start(plan(generations=2, games=100)))
        e = receipt(s); e["preparation"] = dict(learning=dict(status="needs_data"), candidate_knowledge=[], split_registry={})
        s = finish(s, s["pending"]["operation_id"], e)
        self.assertEqual(s["stage"], "collect_source")
        s = begun(s); s = finish(s, s["pending"]["operation_id"], receipt(s, 50, 50))
        self.assertEqual(s["generation"], 2)
        self.assertEqual(s["used_games"], 100)

    def test_idempotent_request_and_result_but_conflicting_receipt_rejected(self):
        s = pending(start(plan()))
        self.assertEqual(pending(s), s)
        op = s["pending"]["operation_id"]; e = receipt(s)
        done = finish(s, op, e)
        self.assertEqual(finish(done, op, e), done)
        e["publication"]["bytes"] += 1
        with self.assertRaises(ValueError): finish(done, op, e)

    def test_launch_only_missing_audit_or_wrong_seed_cannot_finish(self):
        for kind in ("launch_only", "audit", "seed", "candidate", "receipt", "save"):
            s = ready(); s = pending(s) if kind == "launch_only" else begun(s)
            e = receipt(s, 60, 40)
            if kind == "audit": e["audit"]["all_terminations_verified"] = False
            elif kind == "seed": e["seed"] += 1
            elif kind == "candidate": e["candidate"] = s["parent"]
            elif kind == "receipt": e["input_sha256"] = "f"*64
            elif kind == "save": e["publication"]["readback_verified"] = False
            with self.assertRaises(ValueError, msg=kind): finish(s, s["pending"]["operation_id"], e)

    def test_no_candidate_or_policy_changes_after_freeze(self):
        s = ready(); c = candidate(s); c["parameters_sha256"] = "f"*64
        with self.assertRaises(ValueError): request(s, dict(parent=s["parent"], candidate=c), s["revision"])
        s = begun(ready()); s["plan"]["max_new_games"] += 100
        with self.assertRaises(ValueError): finish(s, s["pending"]["operation_id"], receipt(s, 60, 40))

    def test_game_cap_prevents_a_confirmation_that_cannot_fit(self):
        s = begun(ready(games=100))
        s = finish(s, s["pending"]["operation_id"], receipt(s, 60, 40))
        self.assertEqual((s["stage"], s["used_games"]), ("complete", 100))

    def test_eta_uses_slowest_lane_and_has_no_recurring_schedule(self):
        now = datetime(2026, 10, 17, 7, tzinfo=timezone.utc)
        lanes = [dict(started=True, completed=2, games=5, completed_game_seconds=60),
                 dict(started=True, completed=1, games=5, completed_game_seconds=50)]
        result = eta(lanes, now, 60)
        self.assertEqual(result["finish_at"], "2026-10-17T07:05:00+00:00")
        self.assertFalse(result["recurring"])
        lanes[1]["started"] = False
        self.assertIsNone(eta(lanes, now, 60)["finish_at"])

    def test_state_compare_and_swap_and_writer_lock(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/"state.json"; s = start(plan())
            save_state(p, s, None)
            old = hashlib.sha256(p.read_bytes()).hexdigest()
            with self.assertRaises(ValueError): save_state(p, s, None)
            p.with_suffix(".json.lock").write_text("another writer")
            with self.assertRaises(FileExistsError): save_state(p, s, old)
            p.with_suffix(".json.lock").unlink()
            save_state(p, pending(s), old)


if __name__ == "__main__": unittest.main()
