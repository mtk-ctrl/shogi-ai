#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
README = WORKFLOW_DIR / "README.md"


def main() -> int:
    errors: list[str] = []
    active = sorted(
        p.relative_to(ROOT).as_posix()
        for p in WORKFLOW_DIR.iterdir()
        if p.is_file() and p.suffix in {".yml", ".yaml"}
    )
    readme = README.read_text(encoding="utf-8")
    listed = sorted(set(re.findall(r"(\.github/workflows/[A-Za-z0-9._/-]+\.ya?ml)", readme)))

    missing = sorted(set(active) - set(listed))
    stale = sorted(set(listed) - set(active))

    if missing:
        errors.append("ACTIVE workflow not listed in README: " + ", ".join(missing))
    if stale:
        errors.append("README lists workflow that is not ACTIVE: " + ", ".join(stale))

    if "docs/rules/R15_Workflow運用.md" not in readme:
        errors.append("workflow README must point to R15")

    if errors:
        print("Workflow inventory check FAILED")
        for error in errors:
            print("- " + error)
        return 1

    print(f"Workflow inventory check OK: {len(active)} ACTIVE workflows")
    for path in active:
        print("- " + path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
