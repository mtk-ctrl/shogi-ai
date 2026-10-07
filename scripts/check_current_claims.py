#!/usr/bin/env python3
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")

errors = []

def require(path: str, needle: str, why: str) -> None:
    if needle not in read(path):
        errors.append(f"{path}: missing {why}")

def forbid(path: str, needle: str, why: str) -> None:
    if needle in read(path):
        errors.append(f"{path}: stale claim remains ({why})")

# Compare current summaries with the adopted engine name. Do not freeze the
# checker at v2.0.0 when a later version is formally adopted.
version_match = re.search(r"id name KUMOJI v(\d+\.\d+\.\d+)", read("engine/main.cpp"))
engine_version = version_match.group(1) if version_match else "UNKNOWN"
if version_match is None:
    errors.append("engine/main.cpp: adopted engine version is missing")
require("README.md", f"現在の正式Engine世代は **KUMOJI v{engine_version}**", "current engine generation")
require("README.md", "最後にAndroidへ配布するために作ったAPKは **v1.0.1**", "last generated APK")
require("README.md", "Androidへダウンロードする必要がなくAPKを新たに作っていない", "user-confirmed reason for older APK")
forbid("README.md", "Engine世代とAndroid/OEX release番号は分けて管理する", "independent engine/release policy was not the user's intent")
forbid("README.md", "現在の完成版は **v1.0.1**", "release label presented as current engine")

forbid("docs/hold/H10_Book・Experience方針保留.md", "現行 `.github/workflows/nightly-book-learning.yml`", "workflow already moved to HOLD")
require("docs/33_Floodgate接続基盤.md", "正式方針ではない", "H10 boundary for legacy Floodgate Experience behavior")
forbid("docs/33_Floodgate接続基盤.md", "既定の検証対象は `research/evaluation-v2-challenger`", "archived generation workflow default")
require("docs/33_Floodgate接続基盤.md", f"現在の正式Engine世代は `KUMOJI v{engine_version}`", "current Floodgate engine generation")

require("docs/rules/R70_記録・Journal・バージョン.md", f"現在の正式Engine世代は **KUMOJI v{engine_version}**", "engine generation rule")
forbid("docs/04_強化ロードマップ.md", "通常のpushでは短いsmoke対局", "old CI policy")
forbid("docs/04_強化ロードマップ.md", "戦略変更の比較は原則50ms", "old general comparison condition")
forbid("docs/DAYTIME_RESEARCH_BACKLOG.md", "50msを開発基準にしつつ", "old timing standard")
require("docs/26_対局データ収集・分析・学習設計.md", "長期蓄積する基盤データの範囲は `docs/rules/R25_着手記録の保存.md`", "R25 precedence")
require("docs/26_対局データ収集・分析・学習設計.md", "Book / Experienceの採用・更新・credit方針はH10の保留を優先する", "H10 precedence")

wf = read(".github/workflows/engine-match.yml")
if wf.count('"AdaptiveLongThink":true') < 2:
    errors.append(".github/workflows/engine-match.yml: formal default must explicitly enable AdaptiveLongThink for A/B")
if wf.count('"PositionKnowledge":true') < 2:
    errors.append(".github/workflows/engine-match.yml: normal A/B defaults must use adopted position knowledge")
require("README.md", "通常対局で毎回ON", "adopted position knowledge default-use summary")
require("docs/rules/R20_対局・比較・統計.md", "雲路が対局する場合は採用済みの局面知識snapshotを毎回使用する", "position knowledge every-match rule")

if errors:
    print("Current-claim consistency FAILED")
    for e in errors:
        print("- " + e)
    raise SystemExit(1)

print("Current-claim consistency OK")
