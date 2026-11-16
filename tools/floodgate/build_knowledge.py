"""Floodgate専用の局面知識ファイルを作る（2026-11-16）。

正式採用の `position-knowledge-v1.tsv`（163局面）は変えず、Floodgate用の追加分
`tools/floodgate/knowledge-additions.tsv` を足した一時ファイルを書き出す。追加分は
今のエンジンで長く読んだ序盤の手で、自己対局・比較対局・梯子には使わない。

各追加行は、`source_moves`（開始局面からの手順）を python-shogi で再生した局面と
`position_key` が一致することを確認する。基礎と同じ局面があるときは追加分を採る。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def read_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    header, rows = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            header.append(line)
        elif line.strip():
            rows.append(line.split("\t"))
    return header, rows


def key_after(moves: list[str]) -> str:
    import shogi
    board = shogi.Board()
    for move in moves:
        board.push_usi(move)
    return " ".join(board.sfen().split()[:3])


def check_additions(rows: list[list[str]]) -> None:
    import shogi
    for row in rows:
        if len(row) < 14:
            raise SystemExit(f"追加行の列が足りない: {row[:2]}")
        moves = row[13].split()
        if key_after(moves) != row[0]:
            raise SystemExit(f"局面キーが手順と一致しない: {row[11]}")
        board = shogi.Board()
        for move in moves:
            board.push_usi(move)
        if shogi.Move.from_usi(row[1]) not in board.legal_moves:
            raise SystemExit(f"選んだ手が合法でない: {row[11]} {row[1]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="position-knowledge-v1.tsv")
    ap.add_argument("--additions", default="tools/floodgate/knowledge-additions.tsv")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    header, base = read_rows(Path(args.base))
    _, add = read_rows(Path(args.additions))
    check_additions(add)
    merged = {row[0]: row for row in base}
    replaced = sum(1 for row in add if row[0] in merged)
    for row in add:
        merged[row[0]] = row
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = header + ["# floodgate-additions=%d replaced=%d" % (len(add), replaced)]
    lines += ["\t".join(row) for row in merged.values()]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"FLOODGATE_KNOWLEDGE base={len(base)} additions={len(add)} replaced={replaced} total={len(merged)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
