"""Fail if upstream strategic code leaks into the linked rules-only engine."""
import json
from pathlib import Path
import re
import subprocess
import sys

binary = Path(sys.argv[1])
command = json.loads(binary.with_name(binary.name + ".build.json").read_text())["command"]
sources = [x for x in command if x.endswith(".cpp")]
upstream = {Path(x).name for x in sources if "yaneuraou-rules" in x}
assert upstream == {"position.cpp", "bitboard.cpp", "movegen.cpp", "types.cpp"}, upstream
assert not any(x in command for x in ["-Wl,--gc-sections", "-Wl,--unresolved-symbols=ignore-all"])
symbols = subprocess.check_output(["nm", "-C", str(binary)], text=True)
for pattern in [r"YaneuraOu::Search::", r"YaneuraOu::Eval::", r"YaneuraOu::TranspositionTable::",
                r"YaneuraOu::Book", r"YaneuraOu::Mate::", r"YaneuraOu::USIEngine::",
                r"YaneuraOu::Position::(see_ge|do_null_move|undo_null_move)", r"drawValueTable"]:
    assert not re.search(pattern, symbols), pattern
print("PASS boundary: four upstream translation units; no upstream search/evaluation/TT/book/mate/USI/null-move symbols")
