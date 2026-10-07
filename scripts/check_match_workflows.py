#!/usr/bin/env python3
"""Static preflight for ACTIVE match/research GitHub Actions workflows."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
USI_INT_MAX = 2_147_483_647

ARENA_COMMAND = re.compile(
    r"python3\s+[^\n]*(?:benchmarks/(?:arena|position_arena)\.py)"
)


def check_workflow_text(path: Path, text: str, *, root_has_cmake: bool | None = None) -> list[str]:
    errors: list[str] = []
    label = path.as_posix()

    if "\\${{" in text:
        errors.append(f"{label}: escaped GitHub Actions expression \\${{ ... }} is forbidden")

    has_arena_command = bool(ARENA_COMMAND.search(text))
    if has_arena_command and "python-shogi==1.1.1" not in text:
        errors.append(f"{label}: arena execution requires python-shogi==1.1.1 installation")
    if has_arena_command and path.name != "engine-match.yml":
        if "scripts/check_match_workflows.py" not in text:
            errors.append(f"{label}: dedicated arena workflow must run match-workflow preflight")
        if "workflow_dispatch" not in text:
            errors.append(f"{label}: dedicated arena workflow must expose workflow_dispatch")

    if root_has_cmake is None:
        root_has_cmake = (ROOT / "CMakeLists.txt").exists()
    if "cmake -S . " in text and not root_has_cmake:
        errors.append(f"{label}: uses 'cmake -S .' but repository root has no CMakeLists.txt")

    for lineno, line in enumerate(text.splitlines(), 1):
        if "seed" not in line.lower():
            continue
        for raw in re.findall(r"(?<![A-Za-z0-9_])(\d{10,})(?![A-Za-z0-9_])", line):
            value = int(raw)
            if value > USI_INT_MAX:
                errors.append(
                    f"{label}:{lineno}: seed-related literal {value} exceeds USI signed-int range"
                )

    if path.name == "engine-match.yml":
        required = {
            "python3 scripts/build.py": "must build both revisions through scripts/build.py",
            "python-shogi==1.1.1": "must install the arena dependency",
            "2147483647": "must validate shard seeds before build",
            "game_offset": "must preserve global color alternation across shards",
        }
        for needle, why in required.items():
            if needle not in text:
                errors.append(f"{label}: {why}")

    return errors


def active_workflows() -> list[Path]:
    return sorted(
        p for p in WORKFLOW_DIR.iterdir()
        if p.is_file() and p.suffix in {".yml", ".yaml"}
    )


def check_policy_links() -> list[str]:
    errors: list[str] = []
    router = (ROOT / "docs" / "00_開発ルーター.md").read_text(encoding="utf-8")
    r15 = (ROOT / "docs" / "rules" / "R15_Workflow運用.md").read_text(encoding="utf-8")

    match_row = next(
        (line for line in router.splitlines() if "GitHub Actionsで対局を起動・分割・監視" in line),
        "",
    )
    for rule in ("R15_Workflow運用.md", "R20_対局・比較・統計.md", "R21_Actionsランナー運用.md"):
        if rule not in match_row:
            errors.append(f"docs/00_開発ルーター.md: Actions match route must include {rule}")

    if ".github/workflows/engine-match.yml" not in r15:
        errors.append("docs/rules/R15_Workflow運用.md: standard internal match workflow is not named")
    if "scripts/check_match_workflows.py" not in r15:
        errors.append("docs/rules/R15_Workflow運用.md: match preflight checker is not required")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workflow",
        action="append",
        default=[],
        help="Repository-relative workflow path to check; omit to check every ACTIVE workflow.",
    )
    args = parser.parse_args()

    if args.workflow:
        files = [(ROOT / p).resolve() for p in args.workflow]
        for p in files:
            if WORKFLOW_DIR.resolve() not in p.parents:
                raise SystemExit(f"workflow must be under .github/workflows: {p}")
    else:
        files = active_workflows()

    errors = check_policy_links()
    for path in files:
        if not path.exists():
            errors.append(f"{path.relative_to(ROOT)}: workflow file does not exist")
            continue
        errors.extend(check_workflow_text(path.relative_to(ROOT), path.read_text(encoding="utf-8")))

    if errors:
        print("Match workflow preflight FAILED")
        for error in errors:
            print("- " + error)
        return 1

    print(f"Match workflow preflight OK: {len(files)} workflow(s) checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
