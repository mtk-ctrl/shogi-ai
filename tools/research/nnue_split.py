"""Frozen original-game splits and position identity for selfplay NNUE.

Only the original game determines membership; all future reanalysis and child
variations inherit that root.  The SFEN move counter is deliberately excluded
from position identity because the NNUE features do not encode it.
"""
import hashlib


def allocate_roots(root_ids, seed=20261021):
    roots = sorted(set(root_ids), key=lambda root:
                   (hashlib.sha256(f"{seed}:{root}".encode()).digest(), root))
    if len(roots) < 3:
        raise ValueError("need at least three distinct original games")
    n = len(roots)
    n_test = max(1, n // 10)
    n_validation = max(1, n // 10)
    return {
        "train": set(roots[n_test + n_validation:]),
        "validation": set(roots[n_test:n_test + n_validation]),
        "test": set(roots[:n_test]),
    }


def position_identity(sfen):
    fields = sfen.split()
    if len(fields) != 4:
        raise ValueError("invalid SFEN, expected four fields")
    # Exactly the board, hands and side represented by the NNUE.
    return " ".join(fields[:3])
