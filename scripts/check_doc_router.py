#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "docs" / "00_開発ルーター.md"
RULES_DIR = ROOT / "docs" / "rules"

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)
FIELD_RE = re.compile(r"^([A-Za-z0-9_]+):\s*(.+?)\s*$", re.M)
DOC_PATH_RE = re.compile(r"`((?:docs|journal)/[^\`]+(?:\.md|/))`")


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    return {k: v.strip() for k, v in FIELD_RE.findall(match.group(1))}


def main() -> int:
    errors: list[str] = []
    router_text = ROUTER.read_text(encoding="utf-8")

    active_rules: list[Path] = []
    ids: dict[str, Path] = {}

    for path in sorted(RULES_DIR.glob("*.md")):
        meta = frontmatter(path)
        if meta.get("status") != "active":
            continue
        active_rules.append(path)
        rule_id = meta.get("rule_id")
        if not rule_id:
            errors.append(f"{path.relative_to(ROOT)}: active rule has no rule_id")
            continue
        if rule_id in ids:
            errors.append(
                f"duplicate rule_id {rule_id}: "
                f"{ids[rule_id].relative_to(ROOT)} and {path.relative_to(ROOT)}"
            )
        ids[rule_id] = path

    for path in active_rules:
        rel = path.relative_to(ROOT).as_posix()
        if f"`{rel}`" not in router_text:
            errors.append(f"active rule is not routed: {rel}")

    for raw in DOC_PATH_RE.findall(router_text):
        rel = raw.rstrip("/")
        target = ROOT / rel
        if raw.endswith("/"):
            if not target.is_dir():
                errors.append(f"router points to missing directory: {raw}")
        elif not target.is_file():
            errors.append(f"router points to missing file: {raw}")

    if "この文書にはルール本文を書かない" not in router_text:
        errors.append("router must declare that rule bodies do not live in the router")

    if errors:
        print("Document router consistency check FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        f"Document router consistency check OK: "
        f"{len(active_rules)} active rules, {len(ids)} unique rule_ids"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
