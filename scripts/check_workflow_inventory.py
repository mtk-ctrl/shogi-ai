#!/usr/bin/env python3
"""Match executable workflows to the human-maintained index."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def check(root: Path = ROOT, strict: bool = False) -> tuple[list[str], list[str], list[str]]:
    folder = root / ".github" / "workflows"
    active = sorted(p.relative_to(root).as_posix() for p in folder.iterdir()
                    if p.is_file() and p.suffix in (".yml", ".yaml"))
    readme = (folder / "README.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"(\.github/workflows/[A-Za-z0-9._/-]+\.ya?ml)", readme))
    missing = sorted(set(active) - listed)
    stale = sorted(listed - set(active))
    errors: list[str] = []
    warnings: list[str] = []
    if missing:
        message = "README未登録の実行可能workflow: " + ", ".join(missing)
        (errors if strict else warnings).append(message + "（同じ変更で一覧へ登録すること）")
    if stale:
        warnings.append("READMEにのみ残るworkflow: " + ", ".join(stale) + "（移動・廃止状態を確認）")
    if "docs/rules/R15_Workflow運用.md" not in readme:
        errors.append("workflow README: 運用ルールR15への参照がない")
    return errors, warnings, active

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true",
                        help="一覧への登録漏れもエラーにする（手動の出荷前確認向け）")
    args = parser.parse_args()
    errors, warnings, active = check(strict=args.strict)
    for message in warnings:
        print("WARNING:", message)
    for message in errors:
        print("ERROR:", message)
    if errors:
        print(f"Workflow inventory check FAILED ({len(errors)} error(s))")
        return 1
    print(f"Workflow inventory check OK: {len(active)} ACTIVE workflows, {len(warnings)} warning(s)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
