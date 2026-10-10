#!/usr/bin/env python3
"""Validate an approved match request and dispatch the existing generic workflow.

Inputs:
- push/manual: .github/match-request.json (backwards compatible)
- issues.opened: a JSON issue body authored by the repository owner

The issue path is deliberately narrower: it cannot execute arbitrary commands,
select arbitrary knowledge paths, or write repository source files.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

REQUIRED = {
    "ref_a", "ref_b", "games", "shards", "go_command",
    "max_plies", "seed", "options_a", "options_b",
}
OWNER_ISSUE_PREFIX = "[KUMOJI MATCH] "
ALLOWED_ISSUE_OPTIONS = {
    "AdaptiveLongThink", "PositionKnowledge", "PositionKnowledgeFile",
    "OpeningRandomNonLance",
}
SAFE_REF = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]{0,99}$")


def read_request(event_name: str, event: dict, owner: str, request_file: Path) -> tuple[dict, bool]:
    if event_name != "issues":
        return json.loads(request_file.read_text(encoding="utf-8")), False
    issue = event.get("issue", {})
    if issue.get("user", {}).get("login") != owner:
        raise ValueError("issue author is not the repository owner")
    if not issue.get("title", "").startswith(OWNER_ISSUE_PREFIX):
        raise ValueError("issue title does not match the match-request prefix")
    body = issue.get("body") or ""
    if len(body) > 8192:
        raise ValueError("issue request is too large")
    request = json.loads(body)
    if not isinstance(request, dict):
        raise ValueError("issue body must be a JSON object")
    dry_run = request.pop("dry_run", False)
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run must be a boolean")
    return request, dry_run


def safe_ref(value: str, *, allow_baseline: bool = False) -> bool:
    if allow_baseline and value == "BASELINE_FILE":
        return True
    return bool(
        SAFE_REF.fullmatch(value)
        and ".." not in value and "//" not in value
        and not value.endswith(("/", ".", ".lock"))
    )


def validate(req: dict, *, issue_request: bool) -> dict:
    if not isinstance(req, dict):
        raise ValueError("match request must be an object")
    allowed = REQUIRED | {"request_id"}
    if set(req) - allowed:
        raise ValueError("unexpected fields: " + ", ".join(sorted(set(req) - allowed)))
    if REQUIRED - set(req):
        raise ValueError("missing fields: " + ", ".join(sorted(REQUIRED - set(req))))
    for name in ("ref_a", "ref_b", "go_command"):
        if not isinstance(req[name], str) or not req[name].strip():
            raise ValueError(name + " must be a non-empty string")
    for name in ("games", "shards", "max_plies", "seed"):
        if isinstance(req[name], bool):
            raise ValueError(name + " must be an integer")
        try:
            value = int(req[name])
        except (TypeError, ValueError) as exc:
            raise ValueError(name + " must be an integer") from exc
        if str(req[name]) != str(value):
            raise ValueError(name + " must be an integer")
        req[name] = value
    if req["games"] < 1 or not 1 <= req["shards"] <= 20 or req["max_plies"] < 1:
        raise ValueError("games/max_plies must be positive; shards must be between 1 and 20")
    req["shards"] = min(req["shards"], req["games"])
    if issue_request:
        # Restrict the lower-privilege Issue input to standard match invocations.
        if req["games"] > 10000 or req["max_plies"] > 1000:
            raise ValueError("issue match request exceeds its limit")
        for key in ("ref_a", "ref_b"):
            if not safe_ref(req[key], allow_baseline=key == "ref_b"):
                raise ValueError("unsafe engine ref: " + key)
        command = re.fullmatch(r"go movetime ([1-9][0-9]{0,5})", req["go_command"])
        if not command or int(command.group(1)) > 60000:
            raise ValueError("issue requests only support bounded 'go movetime N'")
    for name in ("options_a", "options_b"):
        if not isinstance(req[name], str):
            raise ValueError(name + " must be a JSON string")
        options = json.loads(req[name])
        if not isinstance(options, dict):
            raise ValueError(name + " must decode to a JSON object")
        if issue_request:
            if set(options) - ALLOWED_ISSUE_OPTIONS:
                raise ValueError(name + " includes unsupported USI options")
            if options.get("PositionKnowledgeFile", "build/position-knowledge-v1.tsv") != "build/position-knowledge-v1.tsv":
                raise ValueError("issue request must use the adopted knowledge path")
            if any(not isinstance(value, bool) for key, value in options.items() if key != "PositionKnowledgeFile"):
                raise ValueError(name + " has a non-boolean option")
    q, remainder = divmod(req["games"], req["shards"])
    for i in range(req["shards"]):
        games_in_shard = q + (i < remainder)
        shard_seed = req["seed"] + i * 100000
        if not 0 <= shard_seed <= 2147483647 - games_in_shard * 2:
            raise ValueError("shard seed exceeds the USI integer limit")
    return req


def dispatch_command(req: dict, repository: str) -> list[str]:
    args = ["gh", "workflow", "run", "engine-match.yml", "--repo", repository, "--ref", "main"]
    for name in (
        "ref_a", "ref_b", "games", "shards", "go_command",
        "max_plies", "seed", "options_a", "options_b",
    ):
        args.extend(["-f", name + "=" + str(req[name])])
    return args


def main() -> None:
    env = os.environ
    event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    is_issue = env["GITHUB_EVENT_NAME"] == "issues"
    req, dry_run = read_request(
        env["GITHUB_EVENT_NAME"], event,
        env["GITHUB_REPOSITORY_OWNER"],
        Path(".github/match-request.json"),
    )
    validate(req, issue_request=is_issue)
    print("validated", req.get("request_id", "unnamed"),
          "games", req["games"], "shards", req["shards"],
          "source", "owner issue" if is_issue else "repository file", flush=True)
    if dry_run:
        print("dry_run validation successful; no match dispatched", flush=True)
        return
    subprocess.run(dispatch_command(req, env["GITHUB_REPOSITORY"]), check=True)
    print("Generic Engine Match dispatched", flush=True)


if __name__ == "__main__":
    main()
