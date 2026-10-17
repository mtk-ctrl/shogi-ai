#!/usr/bin/env python3
"""Bounded research parameter proposals. No engine edits or strength claims.

Inputs are actor-oriented, selected own-engine static breakdowns. They are a
surrogate for proposal generation, NOT a replacement for live-engine validation.
Terminal reward belongs only to the observed root, never a hypothetical child.
"""
from __future__ import annotations

import collections
import hashlib
import json
import math

AXES = ("safety", "pressure", "activity", "danger", "influence", "potential",
        "coordination", "hand_potential", "threat")
OPTIONS = ("EvalSafety", "EvalPressure", "EvalActivity", "EvalDanger", "EvalInfluence",
           "EvalPotential", "EvalCoordination", "EvalHandPotential", "EvalThreat")
BASE = (480, 380, 410, 150, 140, 210, 340, 60, 20)
POLICY = dict(epochs=100, learning_rate=.02, max_fraction=.05, pair_temperature=150.,
              reward_temperature=600., reward_weight=.1, regularization=.1,
              min_groups=[8, 4, 4], min_pairs=32)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def validate_terms(terms):
    require(set(terms) == set(AXES) | {"material_term", "total", "clamp"},
            "incomplete or unexpected static terms")
    require(all(type(v) is int and abs(v) <= 1000000 for v in terms.values()),
            "noninteger or invalid static terms")
    require(terms["clamp"] == 0 and abs(terms["total"]) < 20000,
            "clamped/terminal-scale static terms are ineligible")
    require(terms["total"] == terms["material_term"] + sum(terms[k] for k in AXES),
            "static terms do not sum to total")


def validate_rows(rows):
    seen = set()
    for row in rows:
        require(row["case_id"] not in seen, "duplicate learning example")
        seen.add(row["case_id"])
        require(row["split"] in ("train", "validation", "heldout"), "unknown split")
        require(isinstance(row["group"], str) and row["group"], "missing group")
        require(isinstance(row["game"], str) and row["game"], "missing game")
        require(row["reward"] is None or type(row["reward"]) is int and row["reward"] in (-1, 0, 1),
                "invalid root reward")
        for key in ("root", "actual", "research"):
            validate_terms(row[key])
    # A group or game may never leak even when callers supply their own rows.
    for key in ("group", "game"):
        assigned = {}
        for row in rows:
            require(assigned.setdefault(row[key], row["split"]) == row["split"],
                    key + " leaks between splits")


def score(terms, delta):
    return terms["total"] + sum(terms[k] * d for k, d in zip(AXES, delta))


def loss_gradient(rows, delta):
    """Equal total mass per actual game; actor view on both branches and root."""
    require(rows, "empty learning split")
    counts = collections.Counter(r["game"] for r in rows)
    games = len(counts)
    total, gradient = 0., [0.] * len(AXES)
    for r in rows:
        weight = 1. / (games * counts[r["game"]])
        gap = (score(r["research"], delta) - score(r["actual"], delta)) / POLICY["pair_temperature"]
        # Stable softplus(-gap), with no demand to reproduce a deep cp value.
        pair_loss = max(-gap, 0.) + math.log1p(math.exp(-abs(gap)))
        slope = -1. / (1. + math.exp(max(-60., min(60., gap))))
        total += weight * pair_loss
        for j, k in enumerate(AXES):
            gradient[j] += weight * slope * (r["research"][k] - r["actual"][k]) / POLICY["pair_temperature"]
        if r["reward"] is not None:
            prediction = math.tanh(score(r["root"], delta) / POLICY["reward_temperature"])
            error = prediction - r["reward"]
            total += weight * POLICY["reward_weight"] * error * error
            slope = 2 * POLICY["reward_weight"] * error * (1 - prediction * prediction)
            for j, k in enumerate(AXES):
                gradient[j] += weight * slope * r["root"][k] / POLICY["reward_temperature"]
    total += POLICY["regularization"] * sum(d*d for d in delta)
    return total, [g + 2*POLICY["regularization"]*d for g, d in zip(gradient, delta)]


def diagnostics(rows, delta):
    loss, _ = loss_gradient(rows, delta)
    gaps = [score(r["research"], delta) - score(r["actual"], delta) for r in rows]
    return dict(loss=loss, pairs=len(rows), groups=len({r["group"] for r in rows}),
                preferred=sum(g > 0 for g in gaps), reward_known=sum(r["reward"] is not None for r in rows))


def parent_values(options=None):
    options = dict(zip(OPTIONS, BASE)) if options is None else options
    require(set(options) == set(OPTIONS) and all(type(v) is int and 1 <= v <= 10000 for v in options.values()),
            "complete positive parent evaluation options required")
    return tuple(options[k] for k in OPTIONS)


def fit(rows, parent_options=None):
    validate_rows(rows)
    base = parent_values(parent_options)
    subsets = {name: [r for r in rows if r["split"] == name]
               for name in ("train", "validation", "heldout")}
    counts = {name: len({r["group"] for r in subset}) for name, subset in subsets.items()}
    report = dict(schema="postgame-ranker-v1", policy=POLICY, dataset_sha256=digest(rows),
                  split_groups=counts, formal_adoption=False, trials=1,
                  parent_options=dict(zip(OPTIONS, base)))
    if len(rows) < POLICY["min_pairs"] or any(counts[n] < minimum for n, minimum in zip(subsets, POLICY["min_groups"])):
        return dict(report, status="needs_data", reason="Insufficient independent game/position groups.",
                    options=None, parameter_updates=0)
    delta = [0.] * len(AXES)
    # One frozen trial. Validation never selects an epoch or changes coefficients.
    for _ in range(POLICY["epochs"]):
        _, gradient = loss_gradient(subsets["train"], delta)
        delta = [max(-POLICY["max_fraction"], min(POLICY["max_fraction"],
                 d - POLICY["learning_rate"]*g)) for d, g in zip(delta, gradient)]
    # Quantize to a representable USI candidate before assessing the surrogate.
    options = {k: max(math.ceil(b*.95), min(10000, math.floor(b*1.05), int(b*(1+d)+.5)))
               for k, b, d in zip(OPTIONS, base, delta)}
    delta = [options[k]/b - 1 for k, b in zip(OPTIONS, base)]
    for name, subset in subsets.items():
        report[name] = dict(parent=diagnostics(subset, [0.]*len(AXES)),
                            candidate=diagnostics(subset, delta))
    validation_ok = report["validation"]["candidate"]["loss"] < report["validation"]["parent"]["loss"] - 1e-9
    # Heldout is examined once, after the fixed candidate, solely to reject it.
    heldout_ok = report["heldout"]["candidate"]["loss"] <= report["heldout"]["parent"]["loss"]
    changed = any(options[k] != b for k, b in zip(OPTIONS, base))
    return dict(report, status="requires_engine_validation" if changed and validation_ok and heldout_ok else "retain_parent",
                options=options, delta=delta, parameter_updates=int(changed),
                limitation="Static-term linearization only. Live-engine heldout, regressions, speed and matches remain required.")
