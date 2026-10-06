#pragma once

#include "strategy/attack_map.h"
#include <algorithm>
#include <array>
#include <cstdlib>

namespace shogi::strategy {

// Experimental, mechanically-derived king-defence network.
//
// The king zone is split into:
//   distance 1: the ordinary 8-neighbour ring
//   distance 2: the surrounding outer ring (up to 16 squares on-board)
//
// Defence is not rewarded uniformly around the king.  The board is divided
// into eight directions from the king, and a sector is scored only when enemy
// non-king attacks actually reach that sector.  Friendly non-king control and
// supported friendly pieces in that same sector then count as useful defence.
// This deliberately avoids hard-coding castle names such as Yagura.
struct KingDefenseFeatures {
    std::array<int, 8> inner_threat{};
    std::array<int, 8> outer_threat{};
    std::array<int, 8> inner_control{};
    std::array<int, 8> outer_control{};
    std::array<int, 8> support{};
    int inner_threat_total = 0;
    int outer_threat_total = 0;
    int inner_control_total = 0;
    int outer_control_total = 0;
    int supported_inner_pieces = 0;
    int supported_outer_pieces = 0;
    int active_sectors = 0;
    int raw_score = 0;
};

inline int king_sector(int df, int dr) {
    const int x = (df > 0) - (df < 0);
    const int y = (dr > 0) - (dr < 0);
    // Clockwise-ish stable mapping.  Absolute labels do not matter because
    // sectors share identical weights; only "same direction" matters.
    if (x == 0 && y < 0) return 0;
    if (x > 0 && y < 0) return 1;
    if (x > 0 && y == 0) return 2;
    if (x > 0 && y > 0) return 3;
    if (x == 0 && y > 0) return 4;
    if (x < 0 && y > 0) return 5;
    if (x < 0 && y == 0) return 6;
    return 7;
}

inline KingDefenseFeatures king_defense_features(const rules::Snapshot& s,
                                                 const AttackMap& a,
                                                 int side) {
    KingDefenseFeatures out;
    const int king = a.kings[side];
    if (king < 0) return out;
    const int enemy = 1 - side;
    const int kf = king / 9, kr = king % 9;

    // First pass: where does enemy pressure reach, and where is non-king
    // friendly control already present?  Inner squares count twice as much
    // when aggregating raw pressure/control because they are one tempo closer.
    for (int sq = 0; sq < 81; ++sq) {
        if (sq == king) continue;
        const int df = sq / 9 - kf;
        const int dr = sq % 9 - kr;
        const int dist = std::max(std::abs(df), std::abs(dr));
        if (dist < 1 || dist > 2) continue;
        const int sector = king_sector(df, dr);
        const int enemy_attacks = std::min(2, a.nonking[enemy][sq]);
        const int own_control = std::min(2, a.nonking[side][sq]);
        if (dist == 1) {
            out.inner_threat[sector] += 2 * enemy_attacks;
            out.inner_control[sector] += 2 * own_control;
            out.inner_threat_total += 2 * enemy_attacks;
            out.inner_control_total += 2 * own_control;
        } else {
            out.outer_threat[sector] += enemy_attacks;
            out.outer_control[sector] += own_control;
            out.outer_threat_total += enemy_attacks;
            out.outer_control_total += own_control;
        }
    }

    // Second pass: count actual friendly guard pieces that are themselves
    // supported by another non-king friendly piece.  A king merely standing
    // next to a guard does not create a "coordination" edge here.
    for (int sq = 0; sq < 81; ++sq) {
        const auto& piece = s.board[sq];
        if (!piece.kind || piece.kind == 8 || int(piece.color) != side) continue;
        const int df = sq / 9 - kf;
        const int dr = sq % 9 - kr;
        const int dist = std::max(std::abs(df), std::abs(dr));
        if (dist < 1 || dist > 2) continue;
        const int supporters = std::min(2, a.nonking[side][sq]);
        if (!supporters) continue;
        const int sector = king_sector(df, dr);
        const int weight = dist == 1 ? 2 : 1;
        out.support[sector] += weight * supporters;
        if (dist == 1) ++out.supported_inner_pieces;
        else ++out.supported_outer_pieces;
    }

    // Threat-gated coordination:
    // - a quiet/closed sector contributes nothing, so "missing guards" there
    //   are not mechanically punished;
    // - a sector under attack rewards control that meets the pressure and
    //   supported guard pieces in that same direction;
    // - inner-ring contact is intentionally more important than outer-only
    //   contact, while the outer ring still matters as an early warning layer.
    for (int sector = 0; sector < 8; ++sector) {
        const int inner_t = out.inner_threat[sector];
        const int outer_t = out.outer_threat[sector];
        const int threat = inner_t + outer_t;
        if (!threat) continue;
        ++out.active_sectors;

        const int control = out.inner_control[sector] + out.outer_control[sector];
        const int covered = std::min(threat, control);
        const int supported = std::min(threat, out.support[sector]);

        const bool inner_contact = inner_t > 0;
        const int coverage_max = inner_contact ? 10 : 6;
        const int support_max = inner_contact ? 5 : 3;
        out.raw_score += coverage_max * covered / threat;
        out.raw_score += support_max * supported / threat;
    }
    return out;
}

} // namespace shogi::strategy
