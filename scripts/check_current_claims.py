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

    # Version-independent current specification: verify facts, not phrasing.
    spec_path = "docs/現行エンジン仕様.md"
    spec = read(spec_path)
    spec_flat = plain(spec)
    engine = re.search(r"id name KUMOJI v(\d+\.\d+\.\d+)", read("engine/main.cpp"))
    version = re.search(r"現在の正式エンジン\s*[:：]\s*KUMOJI v(\d+\.\d+\.\d+)", spec_flat)
    if engine is None:
        errors.append("engine/main.cpp: USIの正式エンジン版を読み取れない")
    if version is None:
        errors.append(f"{spec_path}: 正式エンジンの版番号を読み取れない")
    if engine and version and engine.group(1) != version.group(1):
        errors.append(f"{spec_path}: 現行版 {version.group(1)} と実装 {engine.group(1)} が異なる")

    material = read("engine/strategy/material.h")
    piece_arrays = {}
    for name in ("base", "promoted_values", "hand_values"):
        match_array = re.search(rf"constexpr int {name}\[\]\s*=\s*\{{([^}}]+)\}}", material)
        if match_array:
            piece_arrays[name] = [int(x) for x in re.findall(r"\d+", match_array.group(1))]
        else:
            errors.append(f"material.h: {name} の値を読み取れない")
    if len(piece_arrays) == 3:
        for index, piece in enumerate(("歩", "香", "桂", "銀", "角", "飛", "金"), 1):
            row = re.search(rf"^\|\s*{piece}\s*\|\s*(\d+)\s*\|\s*([0-9]+|—)\s*\|\s*(\d+)\s*\|", spec, re.M)
            if row is None:
                errors.append(f"{spec_path}: {piece} の駒価値行がない")
                continue
            reported = (int(row.group(1)), None if row.group(2) == "—" else int(row.group(2)), int(row.group(3)))
            actual = (piece_arrays["base"][index],
                      piece_arrays["promoted_values"][index] if index <= 6 else None,
                      piece_arrays["hand_values"][index])
            if reported != actual:
                errors.append(f"{spec_path}: {piece} の駒価値 {reported} が実装 {actual} と異なる")

    params = read("engine/strategy/evaluation_params.h")
    weights_array = re.search(r"std::array<int, 4> weights\{([^}]+)\}", params)
    actual_weights = {}
    if not weights_array:
        errors.append("evaluation_params.h: M型重みの配列を読み取れない")
    else:
        vals = [int(x) for x in re.findall(r"\d+", weights_array.group(1))]
        if len(vals) == 4:
            actual_weights.update(zip(("EvalSafety", "EvalPressure", "EvalActivity", "EvalDanger"), vals))
        else:
            errors.append("evaluation_params.h: M型重みの項目数が不正")
    names = {
        "EvalMaterialWeight": "material_weight",
        "EvalInfluence": "influence_weight",
        "EvalPotential": "potential_weight",
        "EvalCoordination": "coordination_weight",
        "EvalHandPotential": "hand_potential_weight",
        "EvalThreat": "threat_weight",
        "EvalPositionalCap": "positional_cap",
    }
    for option, field in names.items():
        match_value = re.search(rf"int {field}\s*=\s*(\d+)", params)
        if match_value:
            actual_weights[option] = int(match_value.group(1))
        else:
            errors.append(f"evaluation_params.h: {field} を読み取れない")
    reported_weights = {name: int(value) for name, value in re.findall(
        r"^\|[^|\n]+\|\s*(Eval[A-Za-z]+)\s*\|\s*(\d+)\s*\|", spec, re.M)}
    for option, actual in actual_weights.items():
        if option not in reported_weights:
            errors.append(f"{spec_path}: 評価重み {option} が未記載")
        elif reported_weights[option] != actual:
            errors.append(f"{spec_path}: {option} の重み {reported_weights[option]} が実装 {actual} と異なる")
    if not re.search(r"bool v2_enabled\s*=\s*true", params) or "EvalV2=true" not in spec:
        errors.append(f"{spec_path}: 評価関数v2の既定値が実装と一致しない")

    phase = read("engine/strategy/turn_phase.h")
    for label, field in (("配置展開", "development"), ("戦闘", "battle"), ("敵陣進出", "invasion")):
        actual = re.search(rf"(\d+)\s*\*\s*out\.components\.{field}", phase)
        described = re.search(rf"{label}係数\s*(\d+)", spec_flat)
        if not actual or not described or actual.group(1) != described.group(1):
            errors.append(f"{spec_path}: 成熟度{label}係数と実装が一致しない")
    offset = re.search(r"/10000\s*-\s*(\d+)", phase)
    offset_in_doc = re.search(r"加重平均から\s*(\d+)\s*を減じ", spec_flat)
    if not offset or not offset_in_doc or offset.group(1) != offset_in_doc.group(1):
        errors.append(f"{spec_path}: 成熟度の減点値と実装が一致しない")

    manifest_count = int(json.loads(read("position-knowledge-v1.manifest.json"))["adopted_positions"])
    described_count = re.search(r"採用済み局面数\s*[:：]\s*(\d+)", spec_flat)
    if not described_count or int(described_count.group(1)) != manifest_count:
        errors.append(f"{spec_path}: 採用知識数とmanifest ({manifest_count}) が一致しない")

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
