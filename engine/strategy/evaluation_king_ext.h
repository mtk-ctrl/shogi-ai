#pragma once
// Research (EvalKingExt): extra king-exposure features. For the king of `side` (attacked by the
// other colour). Used by both the engine evaluation and the offline probe so they are identical.
#include "strategy/attack_map.h"
#include "strategy/material.h"
#include <algorithm>
namespace shogi::strategy {
inline constexpr int KingExtFeatures = 12;
inline void king_ext_features(const rules::Snapshot& s, const AttackMap& a, int side, int out[KingExtFeatures]) {
    for (int i = 0; i < KingExtFeatures; ++i) out[i] = 0;
    const int king = a.kings[side];
    if (king < 0) return;
    const int enemy = 1 - side;
    const int kf = king / 9, kr = king % 9;
    for (int sq = 0; sq < 81; ++sq) {
        const int d = a.distance(sq, king);
        const auto& piece = s.board[sq];
        if (sq != king && d <= 1) {
            const bool own = piece.kind && int(piece.color) == side;
            const bool empty = !piece.kind;
            if (empty && !a.escape_control[enemy][sq]) ++out[0];
            out[1] += a.count[enemy][sq];
            out[2] += (own || empty) ? std::min(a.nonking[side][sq], 3) : 0;
            if ((own || empty) && a.count[enemy][sq] > a.nonking[side][sq]) ++out[3];
            if (empty && a.count[enemy][sq] && !a.nonking[side][sq]) ++out[8];
        }
        if (sq != king && d <= 2 && piece.kind && int(piece.color) == side && piece.kind != 8) ++out[5];
        if (piece.kind && int(piece.color) == enemy && piece.kind != 8 && d <= 3) ++out[9];
    }
    int hand_attackers = 0, hand_value = 0;
    for (int k = 2; k <= 7; ++k) { hand_attackers += s.hands[enemy][k - 1]; hand_value += s.hands[enemy][k - 1] * hand_piece_value(k); }
    out[4] = hand_attackers;
    out[6] = side == 0 ? 8 - kr : kr;
    out[7] = std::min(hand_value, 6000) / 100;
    out[10] = out[3] * std::min(hand_attackers, 4);
    int open = 0;
    const int dirs[4][2] = {{1,0},{-1,0},{0,1},{0,-1}};
    for (auto& dd : dirs) { int f = kf + dd[0], r = kr + dd[1];
        while (f >= 0 && f < 9 && r >= 0 && r < 9 && !s.board[f * 9 + r].kind) { ++open; f += dd[0]; r += dd[1]; } }
    out[11] = open;
}
// Selected feature indices (king_ext coefficients are given for these, in this order):
// ring_enemy_attacks(1), ring_own_defence(2), weak_ring(3), enemy_hand_value(7),
// undefended_attacked_ring(8), enemy_near_king(9), weak_ring_x_hand(10).
inline constexpr int KingExtSelected[7] = {1, 2, 3, 7, 8, 9, 10};
} // namespace shogi::strategy
