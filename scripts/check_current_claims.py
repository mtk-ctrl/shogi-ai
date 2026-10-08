#!/usr/bin/env python3
"""Check behavioral contracts strictly and prose summaries non-blockingly."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def plain(text: str) -> str:
    # Markdown emphasis, inline-code delimiters and spacing are not policy.
    return re.sub(r"\s+", " ", re.sub(r"[\x60*_]", "", text))

def check(root: Path = ROOT) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    def read(path: str) -> str:
        return (root / path).read_text(encoding="utf-8")

    engine = re.search(r"id name KUMOJI v(\d+\.\d+\.\d+)", read("engine/main.cpp"))
    if engine is None:
        errors.append("engine/main.cpp: USIの正式エンジン版を読み取れない")
    else:
        version = engine.group(1)
        for path in ("README.md", "docs/rules/R70_記録・Journal・バージョン.md", "docs/33_Floodgate接続基盤.md"):
            content = plain(read(path))
            if not re.search(rf"KUMOJI\s+v{re.escape(version)}\b", content):
                errors.append(f"{path}: エンジン実装と同じ正式版 KUMOJI v{version} の記載がない")
            # Actual conflicting current-version statements remain blocking.
            current = re.findall(r"現在[^。\n]{0,140}?KUMOJI\s+v(\d+\.\d+\.\d+)", content)
            if current and current[0] != version:
                errors.append(f"{path}: 現行版の説明 {current} が実装 v{version} と異なる")

    match = read(".github/workflows/engine-match.yml")
    option_defaults = []
    for raw in re.findall(r"default:\s*'(\{[^\n]*\})'", match):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if "PositionKnowledge" in value or "AdaptiveLongThink" in value:
            option_defaults.append(value)
    if len(option_defaults) < 2:
        errors.append("engine-match.yml: A/B両者の標準対局設定を読み取れない")
    else:
        for side, options in zip(("A", "B"), option_defaults[:2]):
            if options.get("PositionKnowledge") is not True:
                errors.append(f"engine-match.yml: {side}側で採用済み局面知識が標準ONでない")
            if options.get("AdaptiveLongThink") is not True:
                errors.append(f"engine-match.yml: {side}側で長考設定が標準ONでない")

    for path in ("engine/main.cpp", ".github/workflows/engine-match.yml", ".github/workflows/external-engine-benchmark.yml"):
        for removed in ("OpeningBook", "ExperienceCache"):
            if removed in read(path):
                errors.append(f"{path}: 廃止された実行オプション {removed} が残っている")

    r20 = plain(read("docs/rules/R20_対局・比較・統計.md"))
    if not re.search(r"局面知識.{0,90}(?:毎回|常時|すべて|全て)", r20):
        errors.append("R20: 採用済み局面知識を毎対局利用する正式規定が見つからない")

    # The following are useful documentation reminders, not exact-string gates.
    readme = read("README.md")
    if "docs/35_局面知識の統合設計と即活用.md" not in readme:
        warnings.append("README.md: 局面知識の設計資料へのリンクを確認")
    if not re.search(r"APK", readme) or "Android" not in readme:
        warnings.append("README.md: Android配布状況の説明を確認")
    if "docs/rules/R25_着手記録の保存.md" not in read("docs/26_対局データ収集・分析・学習設計.md"):
        warnings.append("docs/26: 着手記録の正本R25へのリンクを確認")
    if "日本語" not in read("docs/rules/R00_基本原則.md"):
        warnings.append("R00: 利用者向け日本語優先の説明を確認")

    legacy = (
        ("README.md", "現在の完成版は **v1.0.1**"),
        ("docs/04_強化ロードマップ.md", "戦略変更の比較は原則50ms"),
        ("docs/DAYTIME_RESEARCH_BACKLOG.md", "50msを開発基準にしつつ"),
    )
    for path, phrase in legacy:
        if phrase in read(path):
            warnings.append(f"{path}: 過去の表現が現行説明に残っていないか確認")
    return errors, warnings

def main() -> int:
    errors, warnings = check()
    for message in warnings:
        print("WARNING:", message)
    for message in errors:
        print("ERROR:", message)
    if errors:
        print(f"Current-claim consistency FAILED: {len(errors)} error(s)")
        return 1
    print(f"Current-claim consistency OK ({len(warnings)} advisory warning(s))")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
