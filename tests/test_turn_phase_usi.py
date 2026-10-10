"""Production phase diagnosis is emitted and archived once per played turn."""
import sys
from pathlib import Path
import shogi
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from benchmarks.arena import Engine, compact_search_telemetry, play_game

engine=Engine(sys.argv[1],"A", options={"OpeningRandomNonLance":"true","RandomSeed":123},go_command="go depth 1")
opponent=Engine(sys.argv[1],"B", options={"OpeningRandomNonLance":"true","RandomSeed":124},go_command="go depth 1")
try:
    opening_move=engine.bestmove([])
    assert shogi.Move.from_usi(opening_move) in shogi.Board().legal_moves
    opening=compact_search_telemetry(engine.last_search,shogi.BLACK)
    assert opening["phase_maturity"] == 0,opening
    assert opening["phase_stage"] == "opening",opening
    assert opening["phase_version"] == 1,opening
    assert "phase_static_cp_black" in opening,opening
    # The initial move is random: this is NOT a searched cp score.
    assert "score_cp_stm" not in opening,opening

    engine.send("setoption name OpeningRandomNonLance value false")
    engine.send("setoption name MateAssist value false")
    engine.bestmove(["7g7f","3c3d"])
    mid=compact_search_telemetry(engine.last_search,shogi.BLACK)
    d,b,i=(mid["phase_development"],mid["phase_battle"],mid["phase_invasion"])
    expected=max(0,min(100,(4408*d+3852*b+1739*i+5000)//10000-5))
    assert mid["phase_maturity"] == expected,mid
    assert mid["phase_stage"] == ("opening" if expected<=33 else "middle" if expected<=66 else "end"),mid
    assert all(0<=mid[k]<=100 for k in (
        "phase_development","phase_battle","phase_invasion","phase_king_threat"
    )),mid
    # Both searched evaluation and root static evaluation coexist without mixing.
    assert "score_cp_stm" in mid and "phase_static_cp_black" in mid,mid

    # Common arena transport preserves a diagnosis on EVERY played turn.
    engine.send("setoption name OpeningRandomNonLance value true")
    game=play_game(engine,opponent,0,6,1234)
    assert game["plies"]>=2 and len(game["move_records"])==game["plies"],game
    for record in game["move_records"]:
        state=record["search"]
        assert state["phase_version"]==1,state
        assert state["phase_stage"] in ("opening","middle","end"),state
        assert 0<=state["phase_maturity"]<=100,state
        assert isinstance(state["phase_static_cp_black"],int),state
    print("PASS one phase/static evaluation per played turn, ordinary search, randomized opening and arena records")
finally:
    engine.close()
    opponent.close()
