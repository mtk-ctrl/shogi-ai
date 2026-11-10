#pragma once
// Research (EvalStratExt): strategic terms the older evaluation does not look at, screened offline
// by held-out log-loss (research/eval-tuning/strategic_feature_test.py). Default OFF.
// Per side (own view): castle depth, pawns in hand, control of the enemy promotion zone,
// advancement of bishop/rook, number of distinct non-pawn hand kinds. Plus side to move.
#include "strategy/attack_map.h"
#include "strategy/material.h"
#include <algorithm>
#include <cstdlib>
namespace shogi::strategy {
inline constexpr int StratExtFeatures = 5;
// out: [0] castle2, [1] pawn_hand (<=6), [2] zone_control, [3] major_adv, [4] hand_kinds
inline void strategic_ext_features(const rules::Snapshot& s, const AttackMap& a, int side, int out[StratExtFeatures]) {
    for (int i = 0; i < StratExtFeatures; ++i) out[i] = 0;
    const int king = a.kings[side];
    out[1] = std::min(s.hands[side][0], 6);
    for (int k = 2; k <= 7; ++k) if (s.hands[side][k - 1] > 0) ++out[4];
    for (int sq = 0; sq < 81; ++sq) {
        const int ad = side == 0 ? 8 - sq % 9 : sq % 9;
        if (ad >= 6 && a.count[side][sq] > 0) ++out[2];
        const auto& p = s.board[sq];
        if (!p.kind || int(p.color) != side || p.kind == 8) continue;
        if (p.kind == 5 || p.kind == 6) out[3] += ad;
        if (king >= 0 && (p.kind == 7 || p.kind == 4 || (p.promoted && p.kind <= 4)) && a.distance(sq, king) <= 2) ++out[0];
    }
}
} // namespace shogi::strategy
