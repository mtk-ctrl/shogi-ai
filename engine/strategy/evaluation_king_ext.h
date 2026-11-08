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
// Research (EvalKingExt2): second round of king features, for the king of `side`.
// out: supported drop spots within radius 2, gold/silver next to the king, value (/100) of
// enemy pieces within 3 squares, free squares on the second ring, gold+silver in enemy hand.
inline constexpr int KingExt2Features = 5;
inline void king_ext2_features(const rules::Snapshot& s, const AttackMap& a, int side, int out[KingExt2Features]) {
    for (int i = 0; i < KingExt2Features; ++i) out[i] = 0;
    const int king = a.kings[side];
    if (king < 0) return;
    const int enemy = 1 - side;
    bool strong_drop = false;
    for (int k = 2; k <= 7; ++k) if (s.hands[enemy][k - 1]) strong_drop = true;
    for (int sq = 0; sq < 81; ++sq) {
        const int d = a.distance(sq, king);
        const auto& p = s.board[sq];
        const bool own = p.kind && int(p.color) == side && p.kind != 8;
        if (sq != king && d <= 2 && !p.kind && strong_drop && a.count[enemy][sq] && !a.nonking[side][sq]) ++out[0];
        if (own && d <= 1 && (p.kind == 7 || p.kind == 4)) ++out[1];
        if (p.kind && p.kind != 8 && int(p.color) == enemy && d <= 3) out[2] += piece_value(p.kind, p.promoted) / 100;
        if (sq != king && d == 2 && !p.kind && !a.escape_control[enemy][sq]) ++out[3];
    }
    out[4] = s.hands[enemy][6] + s.hands[enemy][3];
}
// Selected feature indices (king_ext coefficients are given for these, in this order):
// ring_enemy_attacks(1), ring_own_defence(2), weak_ring(3), enemy_hand_value(7),
// undefended_attacked_ring(8), enemy_near_king(9), weak_ring_x_hand(10).
inline constexpr int KingExtSelected[7] = {1, 2, 3, 7, 8, 9, 10};
} // namespace shogi::strategy
