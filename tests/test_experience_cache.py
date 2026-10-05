"""Experience Cache V1: cross-game and cross-process persistence without score reuse."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.arena import Engine


binary = sys.argv[1]
with tempfile.TemporaryDirectory() as tmp:
    cache_file = str(Path(tmp) / "experience.bin")
    options = {
        "ExperienceFile": cache_file,
        "ExperienceCache": "true",
        "RandomSeed": 24680,
    }

    engine = Engine(binary, "experience", options)
    try:
        # Cold search: empty long-lived cache.
        engine.configure_game(24680)
        first = engine.bestmove([])
        cold = engine.search_stats[-1]
        assert cold.get("experience_hits", 0) == 0, cold
        assert cold.get("experience_stores", 0) > 0, cold

        # usinewgame must not clear Experience Cache. The identical root and many
        # internal positions should now produce legal ordering hints, while the
        # deterministic best move must remain unchanged.
        engine.configure_game(24680)
        second = engine.bestmove([])
        warm = engine.search_stats[-1]
        assert second == first, (first, second, cold, warm)
        assert warm.get("experience_hits", 0) > 0, warm
        assert warm.get("experience_move_first", 0) > 0, warm
    finally:
        # quit persists dirty experience to the configured file.
        engine.close()

    path = Path(cache_file)
    assert path.exists() and path.stat().st_size > 24, path

    # A fresh engine process must load the file at isready and immediately reuse
    # it on its first search. This is the actual "next game after restart" case.
    restarted = Engine(binary, "restarted", options)
    try:
        restarted.configure_game(24680)
        move = restarted.bestmove([])
        stats = restarted.search_stats[-1]
        assert move == first, (first, move, stats)
        assert stats.get("experience_hits", 0) > 0, stats
        assert stats.get("experience_move_first", 0) > 0, stats
    finally:
        restarted.close()

    # A different evaluation configuration must reject the old file signature.
    incompatible = Engine(binary, "incompatible", {
        "ExperienceFile": cache_file,
        "ExperienceCache": "true",
        "EvalDanger": 150,
        "RandomSeed": 24680,
    })
    try:
        incompatible.configure_game(24680)
        incompatible.bestmove([])
        incompatible_stats = incompatible.search_stats[-1]
        assert incompatible_stats.get("experience_hits", 0) == 0, incompatible_stats
    finally:
        incompatible.close()

    # Disabling the feature must make the cache logically invisible.
    disabled = Engine(binary, "disabled", {
        "ExperienceFile": cache_file,
        "ExperienceCache": "false",
        "RandomSeed": 24680,
    })
    try:
        disabled.configure_game(24680)
        disabled_move = disabled.bestmove([])
        disabled_stats = disabled.search_stats[-1]
        assert disabled_move == first, (first, disabled_move)
        assert disabled_stats.get("experience_probes", 0) == 0, disabled_stats
        assert disabled_stats.get("experience_hits", 0) == 0, disabled_stats
    finally:
        disabled.close()

    print(
        "PASS Experience Cache survives usinewgame and engine restart, rejects incompatible settings, "
        f"warm hits={warm.get('experience_hits', 0)} restart hits={stats.get('experience_hits', 0)}"
    )
