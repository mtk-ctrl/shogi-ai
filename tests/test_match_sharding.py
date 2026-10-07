"""Exercise actual workflow plans and judges without running engine matches."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
import arena
import external_match


class ResigningEngine:
    def __init__(self, label):
        self.label = label
        self.last_search = {}
        self.seeds = []

    def configure_game(self, seed):
        self.seeds.append(seed)

    new_game = configure_game

    def bestmove(self, moves):
        return "resign"


def workflow_plan(filename, games, shards, seed=2026100700):
    workflow = (ROOT / ".github/workflows" / filename).read_text()
    # Execute the workflow's own planning block, rather than a copied planner.
    block = workflow.split("python3 - <<'PY'", 1)[1].split("\n          PY", 1)[0]
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "outputs"
        env = dict(os.environ, GITHUB_OUTPUT=str(output), GAMES_INPUT=str(games),
                   SHARDS_INPUT=str(shards), MAX_PLIES_INPUT="300", SEED_INPUT=str(seed),
                   OPTIONS_A_INPUT="{}", OPTIONS_B_INPUT="{}", REF_B_INPUT="BASELINE_FILE")
        subprocess.run([sys.executable, "-c", textwrap.dedent(block)], cwd=ROOT,
                       env=env, check=True, capture_output=True, text=True)
        matrix = next(line[7:] for line in output.read_text().splitlines()
                      if line.startswith("matrix="))
    return json.loads(matrix)["include"], workflow


class MatchShardingTest(unittest.TestCase):
    def test_global_color_balance_and_even_distribution(self):
        for filename, runner, color_key in [
            ("engine-match.yml", arena.play_game, "a_black"),
            ("external-engine-benchmark.yml", external_match.play_game, "self_black"),
        ]:
            for games, shards in [(100, 20), (101, 20), (7, 3), (4, 20), (100, 1)]:
                with self.subTest(workflow=filename, games=games, shards=shards):
                    plan, workflow = workflow_plan(filename, games, shards)
                    self.assertIn('GAME_OFFSET: ${{ matrix.game_offset }}', workflow)
                    self.assertIn('--game-offset "$GAME_OFFSET"', workflow)
                    self.assertEqual(len(plan), min(games, shards))
                    counts = [row["games"] for row in plan]
                    self.assertEqual(sum(counts), games)
                    self.assertLessEqual(max(counts) - min(counts), 1)
                    colors = []
                    offset = 0
                    for row in plan:
                        self.assertEqual(row["game_offset"], offset)
                        for index in range(row["games"]):
                            first, second = ResigningEngine("A"), ResigningEngine("B")
                            result = runner(first, second, index, 1, row["seed"], row["game_offset"])
                            colors.append(result[color_key])
                        offset += row["games"]
                    self.assertEqual(colors, [index % 2 == 0 for index in range(games)])
                    self.assertEqual(sum(colors), (games + 1) // 2)

    def test_offsets_preserve_existing_random_seed_series(self):
        for runner in [arena.play_game, external_match.play_game]:
            observations = []
            for offset in [0, 5]:
                a, b = ResigningEngine("A"), ResigningEngine("B")
                runner(a, b, 2, 1, 1234, offset)
                observations.append(sorted(a.seeds + b.seeds))
            self.assertEqual(observations, [[1238, 1239], [1238, 1239]])

    def test_invalid_shard_seed_is_rejected_before_building(self):
        # Reject both an oversized base and a base which overflows in a later shard.
        for seed in [202610072235, 2147483600, -1]:
            with self.subTest(seed=seed), self.assertRaises(subprocess.CalledProcessError):
                workflow_plan("engine-match.yml", 100, 20, seed)


if __name__ == "__main__":
    unittest.main()
