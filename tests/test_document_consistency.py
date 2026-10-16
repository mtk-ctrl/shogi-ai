#!/usr/bin/env python3
"""Regression tests: wording changes must not be mistaken for broken policy."""
from __future__ import annotations

import re
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_current_claims as claims
import check_workflow_inventory as inventory
import check_match_workflows as match_workflows

NEEDED = (
    "README.md", "engine/main.cpp", "docs/現行エンジン仕様.md",
    "engine/strategy/material.h", "engine/strategy/evaluation_params.h",
    "engine/strategy/phase_weights.h",
    "engine/strategy/turn_phase.h", "position-knowledge-v1.manifest.json",
    "engine/strategy/search_research.h",
    "docs/rules/R00_基本原則.md", "docs/rules/R20_対局・比較・統計.md",
    "docs/rules/R70_記録・Journal・バージョン.md",
    "docs/33_Floodgate接続基盤.md",
    "docs/26_対局データ収集・分析・学習設計.md",
    "docs/04_強化ロードマップ.md", "docs/DAYTIME_RESEARCH_BACKLOG.md",
    ".github/workflows/engine-match.yml",
    ".github/workflows/external-engine-benchmark.yml",
)

class ClaimChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for rel in NEEDED:
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / rel, target)

    def change(self, path, before, after):
        p = self.root / path
        content = p.read_text(encoding="utf-8")
        self.assertIn(before, content)
        p.write_text(content.replace(before, after, 1), encoding="utf-8")

    def test_current_repository_passes(self):
        errors, _ = claims.check(self.root)
        self.assertEqual(errors, [])

    def test_natural_rephrasing_does_not_fail(self):
        self.change("docs/現行エンジン仕様.md", "過去版の研究値と採用理由", "旧版の研究値と採用理由")
        errors, _ = claims.check(self.root)
        self.assertEqual(errors, [])

    def test_missing_default_knowledge_still_fails(self):
        self.change(".github/workflows/engine-match.yml",
                    '"PositionKnowledge":true', '"PositionKnowledge":false')
        errors, _ = claims.check(self.root)
        self.assertTrue(any("局面知識が標準ONでない" in e for e in errors), errors)

    def test_wrong_current_engine_version_still_fails(self):
        engine = (self.root / "engine/main.cpp").read_text(encoding="utf-8")
        version = re.search(r"id name KUMOJI v(\d+\.\d+\.\d+)", engine).group(1)
        self.change("docs/現行エンジン仕様.md", f"現在の正式エンジン：KUMOJI v{version}",
                    "現在の正式エンジン：KUMOJI v0.0.0")
        errors, _ = claims.check(self.root)
        self.assertTrue(any("現行版" in e for e in errors), errors)

    def test_wrong_g_piece_value_fails(self):
        self.change("docs/現行エンジン仕様.md", "| 歩 | 120 | 760 | 180 |",
                    "| 歩 | 121 | 760 | 180 |")
        errors, _ = claims.check(self.root)
        self.assertTrue(any("駒価値" in e for e in errors), errors)

    def test_wrong_documented_efficiency_default_fails(self):
        self.change("docs/現行エンジン仕様.md", "| SearchEfficiencyMask | 8 |",
                    "| SearchEfficiencyMask | 15 |")
        errors, _ = claims.check(self.root)
        self.assertTrue(any("SearchEfficiencyMask" in e for e in errors), errors)

    def test_wrong_documented_thread_default_fails(self):
        self.change("docs/現行エンジン仕様.md", "| SearchThreads | 2 |",
                    "| SearchThreads | 1 |")
        errors, _ = claims.check(self.root)
        self.assertTrue(any("SearchThreads" in e for e in errors), errors)

    def test_wrong_documented_probe_default_fails(self):
        header = (self.root / "engine/strategy/search_research.h").read_text(encoding="utf-8")
        value = int(re.search(r"DefaultSearchProbeMask\s*=\s*(\d+)", header).group(1))
        self.change("docs/現行エンジン仕様.md", f"| SearchProbeMask | {value} |",
                    f"| SearchProbeMask | {value ^ 1} |")
        errors, _ = claims.check(self.root)
        self.assertTrue(any("SearchProbeMask" in e for e in errors), errors)

    def test_wrong_actual_search_default_fails(self):
        self.change("engine/strategy/search_research.h", "DefaultSearchResearchMask = 23",
                    "DefaultSearchResearchMask = 31")
        errors, _ = claims.check(self.root)
        self.assertTrue(any("SearchResearchMask" in e for e in errors), errors)

    def test_wrong_m_weight_fails(self):
        self.change("docs/現行エンジン仕様.md", "| EvalThreat | 20 |", "| EvalThreat | 21 |")
        errors, _ = claims.check(self.root)
        self.assertTrue(any("EvalThreat" in e for e in errors), errors)

    def test_wrong_phase_coefficient_fails(self):
        self.change("docs/現行エンジン仕様.md", "配置展開係数 **4408**", "配置展開係数 **4407**")
        errors, _ = claims.check(self.root)
        self.assertTrue(any("成熟度配置展開係数" in e for e in errors), errors)

    def test_wrong_adopted_dynamic_weight_fails(self):
        self.change("docs/現行エンジン仕様.md",
                    "| 駒の活動 | 600 | 500 | 300 |",
                    "| 駒の活動 | 600 | 500 | 301 |")
        errors, _ = claims.check(self.root)
        self.assertTrue(any("採用評価" in e and "駒の活動" in e for e in errors), errors)

    def test_wrong_knowledge_count_fails(self):
        manifest = json.loads((self.root / "position-knowledge-v1.manifest.json").read_text(encoding="utf-8"))
        count = int(manifest["adopted_positions"])
        self.change("docs/現行エンジン仕様.md",
                    f"採用済み局面数：{count}", f"採用済み局面数：{count + 1}")
        errors, _ = claims.check(self.root)
        self.assertTrue(any("採用知識数" in e for e in errors), errors)


class FormalMaterialLadderChecks(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / ".github/workflows/yaneuraou-ladder.yml").read_text(encoding="utf-8")
        self.path = Path(".github/workflows/yaneuraou-ladder.yml")

    def test_formal_ladder_settings_pass(self):
        self.assertEqual(match_workflows.check_workflow_text(self.path, self.workflow), [])

    def test_wrong_time_fails(self):
        broken=self.workflow.replace('--self-go "go movetime 200"', '--self-go "go movetime 50"', 1)
        failures=match_workflows.check_workflow_text(self.path, broken)
        self.assertTrue(any("200ms" in x for x in failures), failures)

    def test_disabled_long_think_fails(self):
        broken=self.workflow.replace('"AdaptiveLongThink":true','"AdaptiveLongThink":false',1)
        failures=match_workflows.check_workflow_text(self.path, broken)
        self.assertTrue(any("long think" in x for x in failures), failures)

    def test_disabled_knowledge_fails(self):
        broken=self.workflow.replace('"PositionKnowledge":true','"PositionKnowledge":false',1)
        failures=match_workflows.check_workflow_text(self.path, broken)
        self.assertTrue(any("knowledge" in x for x in failures), failures)


class WorkflowIndexChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        folder = self.root / ".github/workflows"
        folder.mkdir(parents=True)
        (folder / "README.md").write_text(
            "# workflow\n`docs/rules/R15_Workflow運用.md`\n"
            "| .github/workflows/existing.yml | 用途 |\n", encoding="utf-8")
        (folder / "existing.yml").write_text("name: Existing\n", encoding="utf-8")
        (folder / "new.yml").write_text("name: New\n", encoding="utf-8")

    def test_unlisted_new_workflow_is_warning_not_ci_failure(self):
        errors, warnings, active = inventory.check(self.root)
        self.assertEqual(errors, [])
        self.assertEqual(len(active), 2)
        self.assertTrue(any("new.yml" in w for w in warnings), warnings)

    def test_manual_strict_mode_catches_unlisted_workflow(self):
        errors, _, _ = inventory.check(self.root, strict=True)
        self.assertTrue(any("new.yml" in e for e in errors), errors)

if __name__ == "__main__":
    unittest.main()
