"""Import a verified generic source run, analyze it, and preserve the handoff."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.research.postgame_bridge import analyze_source, dump
from tools.research.postgame_ranker import BASE, OPTIONS, digest, require
from tools.research.postgame_cases import sha256
from tools.research.postgame_cycle import start, request as intend, observe_start, finish


def gh(*args):
    return subprocess.check_output(["gh", *map(str, args)], text=True)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def publish(files, output, repo, run_id):
    month = datetime.now(timezone(timedelta(hours=9))).strftime("records-%Y-%m-01")
    name = f"postgame-source-bridge-{run_id}-a{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}.tgz"
    package = output/name
    inspector = module("postgame_package_inspector", ROOT/".github/scripts/publish_postgame.py")
    with tarfile.open(package, "w:gz") as tar:
        for destination, path in files.items():
            if path.suffix == ".json": inspector.no_pv(json.loads(path.read_bytes()))
            tar.add(path, arcname=destination, recursive=False)
    require(package.stat().st_size < 256*1024*1024, "split required before publication")
    release = json.loads(gh("api", f"repos/{repo}/releases/tags/{month}"))
    require(len(release["assets"]) < 800, "monthly release rollover required")
    existing = [x for x in release["assets"] if x["name"] == name]
    expected = sha256(package.read_bytes())
    if existing:
        require(len(existing) == 1 and existing[0]["size"] == package.stat().st_size
                and existing[0].get("digest") == "sha256:"+expected, "do not overwrite a different asset")
    else:
        gh("release", "upload", month, package, "--repo", repo)
    readback = output/"release-readback"; readback.mkdir()
    gh("release", "download", month, "--repo", repo, "--pattern", name, "--dir", readback)
    require(sha256((readback/name).read_bytes()) == expected, "source bridge readback mismatch")
    fresh = json.loads(gh("api", f"repos/{repo}/releases/tags/{month}"))
    asset = next(a for a in fresh["assets"] if a["name"] == name)
    require(asset["size"] == package.stat().st_size and asset.get("digest") == "sha256:"+expected,
            "Release API digest/bytes mismatch")
    return dict(release=month, name=name, sha256=expected, bytes=package.stat().st_size,
                readback_verified=True, api_digest_verified=True, url=asset["browser_download_url"],
                release_asset_count=len(fresh["assets"]), release_total_bytes=sum(a["size"] for a in fresh["assets"]))


def run(source, output, match_run, parent_ref, repo):
    source, output = Path(source), Path(output); output.mkdir(parents=True)
    frozen = json.loads((ROOT/"research/postgame-spiral-core-20261017/bridge-request.json").read_bytes())
    req, launcher = frozen["match_request"], frozen["launcher_run"]
    require(frozen["match_run"] == match_run and req["ref_a"] == req["ref_b"] == parent_ref,
            "frozen bridge input mismatch")
    require(1 <= req["games"] <= 100 and 1 <= req["shards"] <= min(20, req["games"]), "bounded source request")
    info = json.loads(gh("api", f"repos/{repo}/actions/runs/{match_run}"))
    require(info["status"] == "completed" and info["conclusion"] == "success"
            and info["event"] == "workflow_dispatch" and info["path"] == ".github/workflows/engine-match.yml",
            "not a successful generic source run")
    launched = json.loads(gh("api", f"repos/{repo}/actions/runs/{launcher}"))
    require(launched["status"] == "completed" and launched["conclusion"] == "success", "launcher not successful")
    if frozen.get("issue_number"):
        issue = json.loads(gh("api", f'repos/{repo}/issues/{frozen["issue_number"]}'))
        require(issue["user"]["login"] == repo.split("/")[0]
                and issue["title"].startswith("[KUMOJI MATCH] ")
                and json.loads(issue["body"]) == req and launched["event"] == "issues",
                "owner source intent does not match launcher/request")
    else:
        import base64
        original = json.loads(gh("api", f'repos/{repo}/contents/.github/match-request.json?ref={frozen["request_commit"]}'))
        require(json.loads(base64.b64decode(original["content"])) == req
                and launched["event"] == "push" and launched["head_sha"] == frozen["request_commit"],
                "existing request-file intent/launcher mismatch")
    jobs = json.loads(gh("api", f"repos/{repo}/actions/runs/{match_run}/jobs?per_page=100"))["jobs"]
    build = [j for j in jobs if j["name"] == "build" and j["conclusion"] == "success"]
    lanes = [j for j in jobs if j["name"].startswith("match (") and j["conclusion"] == "success"]
    require(len(build) == 1 and len(lanes) == req["shards"]
            and all(any(s["name"] == "Run shard" and s["conclusion"] == "success" for s in j["steps"]) for j in lanes),
            "build/actual source lane proof missing")
    logger = module("postgame_safe_logs", ROOT/".github/scripts/audit_postgame_pilot.py")
    log = logger.sanitized_job_log(repo, build[0]["id"])
    params = frozen["parent_options"]
    checked = analyze_source(source, req, params, log, output, frozen["knowledge_sha256"])
    parent = dict(engine_ref=parent_ref, knowledge_sha256=checked["audit"]["knowledge_sha256"],
                  parameters_sha256=digest(params))
    plan = dict(cycle_id=frozen["operation_id"], purpose="integration_smoke", source_games=req["games"],
                generate_initial_source=True, max_generations=1, max_new_games=req["games"], candidate_kind="evaluation",
                parent=parent, seeds=[dict(source=req["seed"], screen=req["seed"]+1000, confirm=req["seed"]+2000)])
    dump(output/"cycle-plan.json", plan)
    dump(output/"bridge-request.json", frozen)
    provenance = dict(match_run=match_run, launcher_run=launcher, build_job=build[0]["id"],
                      match_workflow_ref=info["head_sha"], parent_ref=parent_ref,
                      binary_sha256=checked["audit"]["binary_sha256"],
                      build_log_sha256=sha256(log.encode()), verification_ref=os.environ.get("GITHUB_SHA"),
                      adapter_code_sha256=sha256(Path(__file__).read_bytes()),
                      input_intent_record="BRIDGE_PLAN committed before source Issue; imported into the cycle ledger here.")
    dump(output/"build-provenance.json", provenance)
    build_path = source/"binaries/build"
    files = {"source-audit.json": output/"source-audit.json", "preparation.json": output/"preparation.json",
             "build-provenance.json": output/"build-provenance.json", "cycle-plan.json": output/"cycle-plan.json",
             "bridge-request.json": output/"bridge-request.json", "build/engine-a": build_path/"engine-a",
             "build/position-knowledge-v1.tsv": build_path/"position-knowledge-v1.tsv",
             "build/position-knowledge-v1.manifest.json": build_path/"position-knowledge-v1.manifest.json"}
    for name in ("manifest.json", "played-games.jsonl.gz"):
        files["played-archive/"+name] = source/"verified-archive"/name
    for name in ("selected-cases.json", "diagnosis.json", "summary.json"):
        files["analysis/"+name] = output/"analysis"/name
    publication = publish(files, output, repo, os.environ["GITHUB_RUN_ID"])
    dump(output/"publication.json", publication)
    state = start(plan)
    state = intend(state, dict(parent=parent, match_request_sha256=digest(req)), state["revision"])
    op = state["pending"]["operation_id"]
    state = observe_start(state, op, launcher, match_run, len(lanes))
    evidence = dict(input_sha256=state["pending"]["input_sha256"], parent=parent, publication=publication,
                    body_run=match_run, seed=req["seed"], result=checked["result"], audit=checked["audit"])
    state = finish(state, op, evidence)
    state = intend(state, dict(parent=parent, source_archive_sha256=sha256((source/"verified-archive/played-games.jsonl.gz").read_bytes())), state["revision"])
    state = finish(state, state["pending"]["operation_id"], dict(input_sha256=state["pending"]["input_sha256"],
                    parent=parent, publication=publication, preparation=checked["preparation"]))
    dump(output/"cycle-state.json", state)
    result = dict(mode="postgame-bridge", source_match_run=match_run, source_games=checked["audit"]["games"],
                  source_plies=checked["audit"]["plies"], selected_cases=checked["analysis"]["selected_cases"],
                  routes=checked["analysis"]["routes"], preparation_status=checked["preparation"]["learning"]["status"],
                  parameter_updates=checked["preparation"]["learning"]["parameter_updates"],
                  cycle_stage=state["stage"], cycle_result=state["result"], used_games=state["used_games"],
                  publication=publication, formal_adoption=False,
                  limitation="Verified one source-to-preparation handoff, not autonomous multi-generation strength improvement.")
    dump(output/"report.json", result)
    print("POSTGAME_BRIDGE_RESULT "+json.dumps(result, ensure_ascii=False), flush=True)
    return result


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    p.add_argument("--match-run", type=int, required=True); p.add_argument("--parent-ref", required=True)
    a = p.parse_args()
    run(a.source, a.output, a.match_run, a.parent_ref, os.environ["GITHUB_REPOSITORY"])
