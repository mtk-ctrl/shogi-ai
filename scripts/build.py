"""Host/Android build with one explicit upstream source allowlist."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from prepare_rules import prepare, ROOT

parser = argparse.ArgumentParser()
parser.add_argument("--source", help="Existing pinned upstream checkout (optional)")
parser.add_argument("--cxx", default=os.environ.get("CXX", "g++"))
parser.add_argument("--output", default="build/shogi-ai")
tests = parser.add_mutually_exclusive_group()
tests.add_argument("--test", action="store_true")
tests.add_argument("--strategy-test", action="store_true")
tests.add_argument("--search-test", action="store_true")
tests.add_argument("--mate-search-test", action="store_true")
tests.add_argument("--mate-assist-test", action="store_true")
tests.add_argument("--generated-move-test", action="store_true")
tests.add_argument("--quiescence-test", action="store_true")
tests.add_argument("--ordering-test", action="store_true")
tests.add_argument("--contact-ordering-test", action="store_true")
tests.add_argument("--evaluation-test", action="store_true")
tests.add_argument("--opening-book-test", action="store_true")
tests.add_argument("--evaluation-probe", action="store_true")
tests.add_argument("--kifu-validator", action="store_true")
parser.add_argument("--sanitize", action="store_true")
parser.add_argument("--android", action="store_true")
args = parser.parse_args()
source = prepare(args.source)
out = (ROOT / args.output).resolve()
out.parent.mkdir(parents=True, exist_ok=True)

# The default opening book must travel with a standalone engine binary. Android
# OEX hosts typically copy only the executable, so generate a tiny header from
# the repository's current self-play book and compile it as a fallback. Host
# builds still prefer an external shogi-ai-book.tsv when it is present, which
# keeps book experiments editable without recompiling.
generated = ROOT / "build/generated"
generated.mkdir(parents=True, exist_ok=True)
book_path = ROOT / "shogi-ai-book.tsv"
book_text = book_path.read_text(encoding="utf-8")
delimiter = "KUMOJIBOOK"
if f'){delimiter}\"' in book_text:
    raise SystemExit("opening book contains the generated raw-string delimiter")
(generated / "embedded_opening_book.h").write_text(
    "#pragma once\n"
    "#include <string_view>\n"
    "namespace shogi::strategy::detail {\n"
    f'inline constexpr std::string_view kEmbeddedOpeningBook = R"{delimiter}({book_text}){delimiter}";\n'
    "} // namespace shogi::strategy::detail\n",
    encoding="utf-8",
)

flags = ["-std=c++17", "-O1" if args.sanitize else "-O2", "-g", "-pthread",
         "-DSHOGI_RULES_ONLY", "-DUSER_ENGINE", "-DNO_SSE", "-DASSERT_LV=3",
         "-I" + str(generated), "-I" + str(ROOT / "engine"), "-I" + str(source)]
if args.sanitize: flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
if args.android: flags += ["-fPIE", "-pie", "-static-libstdc++"]
upstream = [source / n for n in ["bitboard.cpp", "position.cpp", "movegen.cpp", "types.cpp"]]
test_source = ("tests/rules_test.cpp" if args.test else
               "tests/strategy_test.cpp" if args.strategy_test else
               "tests/search_test.cpp" if args.search_test else
               "tests/mate_search_test.cpp" if args.mate_search_test else
               "tests/mate_assist_test.cpp" if args.mate_assist_test else
               "tests/generated_move_test.cpp" if args.generated_move_test else
               "tests/quiescence_test.cpp" if args.quiescence_test else
               "tests/ordering_test.cpp" if args.ordering_test else
               "tests/contact_ordering_test.cpp" if args.contact_ordering_test else
               "tests/evaluation_test.cpp" if args.evaluation_test else
               "tests/opening_book_test.cpp" if args.opening_book_test else
               "benchmarks/evaluation_probe.cpp" if args.evaluation_probe else
               "tools/kifu/validate_games.cpp" if args.kifu_validator else
               "engine/main.cpp")
own = [ROOT / "engine/rules/upstream_support.cpp", ROOT / "engine/rules/position.cpp", ROOT / test_source]
command = [args.cxx, *flags, *map(str, upstream + own), "-o", str(out)]
# No dead-code removal, unresolved-symbol bypass, search.cpp, evaluate.cpp, tt.cpp,
# book, neural network, upstream mate solver or upstream USI runtime is needed to link.
subprocess.run(command, check=True)
(out.parent / (out.name + ".build.json")).write_text(json.dumps({"command": command}, indent=2))
print(out)
