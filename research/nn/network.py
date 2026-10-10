"""Standalone NumPy neural position evaluator. Never called by the playing engine."""
from __future__ import annotations

from pathlib import Path
import numpy as np

PIECES = "PLNSGBRK"
HAND_PIECES = "PLNSGBR"
PLANES = 28  # black/white x (8 original + 6 promoted)
INPUT_SIZE = 81 * PLANES + 2 * len(HAND_PIECES) + 1
PROMOTABLE = "PLNSBR"


def encode_sfen(sfen: str) -> np.ndarray:
    """Encode a position using fixed Black/White coordinates; output predicts Black win."""
    fields = sfen.split()
    if len(fields) < 3 or fields[1] not in ("b", "w"):
        raise ValueError("invalid SFEN: board, turn and hands are required")
    board, turn, hands = fields[:3]
    rows = board.split("/")
    if len(rows) != 9:
        raise ValueError("SFEN board must contain nine ranks")
    x = np.zeros(INPUT_SIZE, dtype=np.float32)
    for rank, row in enumerate(rows):
        file_index, index = 0, 0
        while index < len(row):
            ch = row[index]
            if ch.isdigit():
                step = int(ch)
                if step < 1 or file_index + step > 9:
                    raise ValueError("invalid SFEN blank count")
                file_index += step
                index += 1
                continue
            promoted = ch == "+"
            if promoted:
                index += 1
                if index >= len(row):
                    raise ValueError("dangling promotion marker")
                ch = row[index]
            kind = ch.upper()
            if kind not in PIECES or (promoted and kind not in PROMOTABLE):
                raise ValueError("unknown or invalid SFEN piece")
            if file_index >= 9:
                raise ValueError("SFEN rank exceeds nine files")
            color = 0 if ch.isupper() else 1
            plane = PIECES.index(kind)
            if promoted:
                plane = 8 + PROMOTABLE.index(kind)
            x[(rank * 9 + file_index) * PLANES + color * 14 + plane] = 1
            file_index += 1
            index += 1
        if file_index != 9:
            raise ValueError("SFEN rank does not have nine squares")
    if hands != "-":
        i = 0
        while i < len(hands):
            j = i
            while j < len(hands) and hands[j].isdigit():
                j += 1
            count = int(hands[i:j]) if j > i else 1
            if j == len(hands) or hands[j].upper() not in HAND_PIECES or count < 1:
                raise ValueError("invalid SFEN hands")
            ch = hands[j]
            color = 0 if ch.isupper() else 1
            idx = 81 * PLANES + color * 7 + HAND_PIECES.index(ch.upper())
            x[idx] += count / 4.0
            i = j + 1
    x[-1] = 1.0 if turn == "b" else -1.0
    return x


def sigmoid(a: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(a, -40.0, 40.0)))


class PositionNet:
    """One-hidden-layer MLP, trained with cross-entropy and Adam on CPU."""
    def __init__(self, hidden: int = 32, seed: int = 20261011):
        if hidden < 1:
            raise ValueError("hidden must be positive")
        rng = np.random.default_rng(seed)
        self.w1 = (rng.standard_normal((INPUT_SIZE, hidden)) *
                   np.sqrt(2.0 / INPUT_SIZE)).astype(np.float32)
        self.b1 = np.zeros(hidden, dtype=np.float32)
        self.w2 = (rng.standard_normal((hidden, 1)) *
                   np.sqrt(1.0 / hidden)).astype(np.float32)
        self.b2 = np.zeros(1, dtype=np.float32)

    def predict(self, x: np.ndarray) -> np.ndarray:
        h = np.tanh(x @ self.w1 + self.b1)
        return sigmoid(h @ self.w2 + self.b2).reshape(-1)

    def fit(self, x: np.ndarray, y: np.ndarray, *, epochs: int = 15,
            batch_size: int = 128, lr: float = 0.003, seed: int = 20261011):
        if x.ndim != 2 or x.shape[1] != INPUT_SIZE or y.shape != (len(x),):
            raise ValueError("wrong training array shapes")
        if len(x) == 0 or epochs < 1 or batch_size < 1 or lr <= 0:
            raise ValueError("invalid training parameters")
        if not np.isfinite(x).all() or not np.isfinite(y).all() or ((y < 0) | (y > 1)).any():
            raise ValueError("nonfinite features or invalid target")
        rng = np.random.default_rng(seed)
        params = [self.w1, self.b1, self.w2, self.b2]
        m = [np.zeros_like(p) for p in params]
        v = [np.zeros_like(p) for p in params]
        t = 0
        for _ in range(epochs):
            for indices in np.array_split(rng.permutation(len(x)),
                                          max(1, (len(x) + batch_size - 1) // batch_size)):
                xb, yb = x[indices], y[indices, None]
                hidden = np.tanh(xb @ self.w1 + self.b1)
                probability = sigmoid(hidden @ self.w2 + self.b2)
                dlogits = (probability - yb) / len(xb)
                d_w2 = hidden.T @ dlogits + 0.00001 * self.w2
                d_b2 = dlogits.sum(axis=0)
                d_hidden = (dlogits @ self.w2.T) * (1.0 - hidden * hidden)
                d_w1 = xb.T @ d_hidden + 0.00001 * self.w1
                d_b1 = d_hidden.sum(axis=0)
                gradients = [d_w1, d_b1, d_w2, d_b2]
                t += 1
                for p, g, mm, vv in zip(params, gradients, m, v):
                    np.clip(g, -2.0, 2.0, out=g)
                    mm *= 0.9
                    mm += 0.1 * g
                    vv *= 0.999
                    vv += 0.001 * (g * g)
                    p -= lr * (mm / (1 - 0.9 ** t)) / (
                        np.sqrt(vv / (1 - 0.999 ** t)) + 1e-8)

    def save(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, version=np.array(1), w1=self.w1, b1=self.b1,
                            w2=self.w2, b2=self.b2)

    @classmethod
    def load(cls, path: Path) -> "PositionNet":
        with np.load(path, allow_pickle=False) as data:
            if int(data["version"]) != 1 or data["w1"].shape[0] != INPUT_SIZE:
                raise ValueError("unsupported model version or features")
            model = cls(hidden=data["w1"].shape[1])
            for name in ("w1", "b1", "w2", "b2"):
                value = data[name]
                if value.shape != getattr(model, name).shape or not np.isfinite(value).all():
                    raise ValueError("invalid model weight: " + name)
                getattr(model, name)[:] = value
        return model
