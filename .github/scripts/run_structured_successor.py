"""Freeze a verified successor of the learned contextual evaluator and launch one bounded cycle.

Runs only after a deliberately enabled research-branch request. The historical
model and official main are not changed. No retries after ambiguous dispatch.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).parent)]
from run_postgame_spiral import Backend, api
from prepare_structured_successor import prepare
from tools.research.train_structured_value import PARENT
import selfplay_trial_transport as transport

BRANCH = "research/structured-successor-20261020"
CYCLE = "structured-value-20261020-g2"
PREVIOUS = dict(
    release="records-2026-10-01",
    name="structured-value-result-39195782210.tgz",
    sha256="8389922d4dccb84e90b169e6a4cee5994699e40d162eb3efd890e6f78c729c20",
    bytes=805487,
)
STUDY = ROOT / "research/structured-successor-20261020"
REQUEST = ROOT / ".github/structured-successor-request.json"
CONTROL = ROOT / ".github/structured-value-control.json"

def run(*args, cwd=ROOT):
    subprocess.run(list(map(str, args)), cwd=cwd, check=True)

def json_file(path):
    return json.loads(Path(path).read_text())

def stop_requested():
    state = json_file(CONTROL)
    if state != {"stop_requested": False}:
        raise ValueError("research stop control is not false")
    return False

def launcher():
    request = json_file(REQUEST)
    if request == {"enabled": False}:
        print("SUCCESSOR_REQUEST_DISABLED", flush=True)
        return
    if request != {"enabled": True, "cycle_id": CYCLE}:
        raise ValueError("unexpected or non-frozen successor request")
    if os.environ.get("GITHUB_REF_NAME") != BRANCH:
        raise ValueError("wrong branch for successor research")
    from run_postgame_spiral import api
    runs = api("repos/mtk-ctrl/shogi-ai/actions/workflows/postgame-spiral.yml/runs?event=workflow_dispatch&per_page=100")["workflow_runs"]
    if any(r["display_title"] == "Spiral " + CYCLE for r in runs):
        raise ValueError("cycle already dispatched; reconcile without retry")
    ref = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    response = api("repos/mtk-ctrl/shogi-ai/actions/workflows/postgame-spiral.yml/dispatches", {
        "ref": BRANCH, "return_run_details": True,
        "inputs": {"cycle_id": CYCLE, "plan_ref": ref, "successor_only": "true"},
    })
    if type(response.get("workflow_run_id")) is not int:
        raise ValueError("ambiguous successor dispatch; inspect before retry")
    print("SUCCESSOR_PREPARATION_RUN " + json.dumps(response), flush=True)

def prepare_and_launch():
    if (os.environ.get("GITHUB_REF_NAME") != BRANCH
            or os.environ.get("GITHUB_REPOSITORY") != "mtk-ctrl/shogi-ai"
            or os.environ.get("GITHUB_RUN_ATTEMPT", "1") != "1"):
        raise ValueError("unexpected repository, branch, or attempt")
    ref = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if ref != os.environ["PLAN_REF"] or json_file(REQUEST) != {"enabled": True, "cycle_id": CYCLE}:
        raise ValueError("the preparation request/ref is no longer frozen")
    stop_requested()
    backend = Backend("mtk-ctrl/shogi-ai", ROOT / "build/successor-transport")
    package = backend.unpack(PREVIOUS)
    previous = json_file(package / "result.json")
    if (previous.get("status") != "research_parent_improved"
            or previous.get("formal_adoption") is not False
            or previous.get("model_sha256") != "8c174f7adac2d45cc0ab2633986ab89db3f24906bd655f5e18e81538eb7fdb1c"):
        raise ValueError("saved predecessor is not the confirmed learned parent")
    old = json_file(ROOT / "research/structured-eval-20261019/EXECUTION.json")
    # The separate 2026-10-19 route experiments used these seeds after this
    # execution was recorded. Preserve their exclusion from this new cycle.
    old["used_seed_bases"] = sorted(set(old["used_seed_bases"] + [
        2106101901, 2108101901, 2110101901, 2113101901
    ]))
    priors = json_file(ROOT / "research/structured-eval-20261019/prior-publications.json")
    dest = ROOT / "build/successor-freeze"
    execution, model = prepare(package, old, priors, CYCLE, 2120101901,
                               dest, transport.BASE, PARENT)
    if not model.get("eligible"):
        raise ValueError("candidate failed its own learning suitability gate")
    STUDY.mkdir(parents=True, exist_ok=False)
    for name in ("model.json", "EXECUTION.json", "parent-options.json",
                 "prior-publications.json"):
        shutil.copyfile(dest / name, STUDY / name)
    shutil.copyfile(dest / "structured_value_weights.h",
                    ROOT / "engine/strategy/structured_value_weights.h")
    positions = package / "next-model/actual-positions.jsonl"
    if not positions.exists():
        raise ValueError("the source package lacks actual training positions")
    # The parent binary is built from the immutable accepted predecessor, not
    # from the new candidate whose weights are about to be tested.
    parent_dir = ROOT / "build/successor-parent-worktree"
    run("git", "worktree", "add", "--detach", parent_dir,
        previous["research_parent"]["engine_ref"])
    run(sys.executable, "scripts/build.py", "--output",
        "build/successor-parent-engine", cwd=parent_dir)
    parent_binary = parent_dir / "build/successor-parent-engine"
    run(sys.executable, "scripts/build.py", "--output", "build/successor-candidate-engine")
    run(sys.executable, "scripts/build.py", "--structured-value-probe",
        "--output", "build/successor-feature-probe")
    run(sys.executable, "research/structured-eval-20261019/preflight.py",
        "--binary", ROOT / "build/successor-candidate-engine",
        "--parent", parent_binary,
        "--probe", ROOT / "build/successor-feature-probe",
        "--positions", positions, "--model", STUDY / "model.json",
        "--parent-options", STUDY / "parent-options.json",
        "--output", STUDY / "preflight.json")
    checks = json_file(STUDY / "preflight.json")
    if (not checks.get("disabled_exact") or not checks.get("integer_evaluation_exact")
            or not any(checks["candidates_passed"])):
        raise ValueError("the next learned candidate did not pass actual binary preflight")
    stop_requested()
    # Freeze only research inputs and the candidate header, never main/defaults.
    REQUEST.write_text('{"enabled": false}\n')
    run("git", "config", "user.name", "github-actions[bot]")
    run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    run("git", "add", str(STUDY.relative_to(ROOT)),
        "engine/strategy/structured_value_weights.h",
        ".github/structured-successor-request.json")
    run("git", "commit", "-m", "research: freeze learned evaluation G2 and verified parent-aware preflight")
    frozen_ref = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    run("git", "push", "origin", "HEAD:refs/heads/" + BRANCH)
    response = api("repos/mtk-ctrl/shogi-ai/actions/workflows/postgame-spiral.yml/dispatches", {
        "ref": BRANCH, "return_run_details": True,
        "inputs": {"cycle_id": CYCLE, "plan_ref": frozen_ref,
                   "order_only": "true", "structured_only": "true"},
    })
    if type(response.get("workflow_run_id")) is not int:
        raise ValueError("candidate frozen, but comparison dispatch is ambiguous; inspect, do not retry")
    receipt = {"cycle_id": CYCLE, "plan_ref": frozen_ref, "comparison_run_id": response["workflow_run_id"],
               "parent_model_sha256": model["parent_model_sha256"],
               "new_model_sha256": hashlib.sha256((STUDY/"model.json").read_bytes()).hexdigest(),
               "candidate_scales_passed": checks["candidates_passed"], "formal_adoption": False}
    print("SUCCESSOR_COMPARISON_DISPATCHED " + json.dumps(receipt), flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--launch", action="store_true")
    args = parser.parse_args()
    launcher() if args.launch else prepare_and_launch()
