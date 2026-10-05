#!/usr/bin/env python3
"""Stable 100-level node scale for the YaneuraOu material benchmark."""

from __future__ import annotations

import argparse
import math

MIN_LEVEL = 1
MAX_LEVEL = 100
MIN_NODES = 10
MAX_NODES = 1_000_000


def nodes_for_level(level: int) -> int:
    if not MIN_LEVEL <= level <= MAX_LEVEL:
        raise ValueError(f"level must be {MIN_LEVEL}..{MAX_LEVEL}")
    if level == MIN_LEVEL:
        return MIN_NODES
    if level == MAX_LEVEL:
        return MAX_NODES
    fraction = (level - MIN_LEVEL) / (MAX_LEVEL - MIN_LEVEL)
    value = MIN_NODES * ((MAX_NODES / MIN_NODES) ** fraction)
    return int(round(value))


def nearest_level_for_nodes(nodes: int) -> int:
    if nodes <= 0:
        raise ValueError("nodes must be positive")
    return min(range(MIN_LEVEL, MAX_LEVEL + 1), key=lambda level: abs(math.log(nodes_for_level(level)) - math.log(nodes)))


def level_table() -> list[dict[str, int]]:
    return [{"level": level, "nodes": nodes_for_level(level)} for level in range(MIN_LEVEL, MAX_LEVEL + 1)]


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--level", type=int)
    group.add_argument("--nodes", type=int)
    parser.add_argument("--nodes-only", action="store_true")
    args = parser.parse_args()

    try:
        if args.level is not None:
            nodes = nodes_for_level(args.level)
            if args.nodes_only:
                print(nodes)
            else:
                print(f"level={args.level} nodes={nodes}")
        else:
            level = nearest_level_for_nodes(args.nodes)
            if args.nodes_only:
                print(nodes_for_level(level))
            else:
                print(f"nodes={args.nodes} nearest_level={level} level_nodes={nodes_for_level(level)}")
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
