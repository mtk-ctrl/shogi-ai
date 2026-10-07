#!/usr/bin/env python3
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_match_workflows as guard


class MatchWorkflowGuardTest(unittest.TestCase):
    def test_rejects_escaped_actions_expression(self):
        errors = guard.check_workflow_text(
            Path(".github/workflows/x.yml"),
            r"name: x\nartifact: \\${{ github.run_id }}\n",
            root_has_cmake=False,
        )
        self.assertTrue(any("escaped GitHub Actions expression" in e for e in errors), errors)

    def test_rejects_oversized_seed_literal(self):
        errors = guard.check_workflow_text(
            Path(".github/workflows/x.yml"),
            "run: SHARD_SEED=$((202610072235 + SHARD_ID * 100000))\n",
            root_has_cmake=False,
        )
        self.assertTrue(any("exceeds USI signed-int range" in e for e in errors), errors)

    def test_arena_requires_python_shogi(self):
        errors = guard.check_workflow_text(
            Path(".github/workflows/x.yml"),
            "run: python3 benchmarks/arena.py --engine-a a --engine-b b\n",
            root_has_cmake=False,
        )
        self.assertTrue(any("python-shogi==1.1.1" in e for e in errors), errors)

    def test_rejects_missing_root_cmake_entrypoint(self):
        errors = guard.check_workflow_text(
            Path(".github/workflows/x.yml"),
            "run: cmake -S . -B build\n",
            root_has_cmake=False,
        )
        self.assertTrue(any("root has no CMakeLists.txt" in e for e in errors), errors)

    def test_current_engine_match_contract(self):
        path = Path(".github/workflows/engine-match.yml")
        text = (ROOT / path).read_text(encoding="utf-8")
        self.assertEqual(guard.check_workflow_text(path, text), [])


if __name__ == "__main__":
    unittest.main()
