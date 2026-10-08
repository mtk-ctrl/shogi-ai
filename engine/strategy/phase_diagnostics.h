#pragma once
// Experimental position-stage diagnostics. This header is not called by the
// production search or evaluator; its coefficients are NOT adopted weights.
#include "rules/position.h"
#include "strategy/attack_map.h"
#include <algorithm>
#include <array>
#include <cstdlib>
#include <limits>
#include <vector>

namespace shogi::strategy {
struct PhaseDiagnostics {
    int development = 0;
    int battle = 0;
    int invasion = 0;
    int king_threat = 0;
    int provisional_progress = 0;
};
namespace phase_detail {
inline int square(int file, int rank) { return (file - 1) * 9 + rank; }
inline int weight(int kind) {
    constexpr int w[9] = {0, 1, 2, 3, 3, 5, 5, 3, 2};
    return w[kind];
}
inline std::vector<int> original(int side, int kind) {
    const int back = side == 0 ? 8 : 0;
    const int second = side == 0 ? 7 : 1;
    const int pawn = side == 0 ? 6 : 2;
    std::vector<int> squares;
    auto add = [&](int file, int rank) { squares.push_back(square(file, rank)); };
    switch (kind) {
        case 1: for (int file=1;file<=9;++file) add(file,pawn); break;
        case 2: add(1,back); add(9,back); break;
        case 3: add(2,back); add(8,back); break;
        case 4: add(3,back); add(7,back); break;
        case 5: add(side==0?8:2,second); break;
        case 6: add(side==0?2:8,second); break;
        case 7: add(4,back); add(6,back); break;
        case 8: add(5,back); break;
    }
    return squares;
}
inline int distance(int a, int b) {
    return std::abs(a/9-b/9) + std::abs(a%9-b%9);
}
// One-to-one minimum-distance matching. Same-kind pawns/golds/silvers
// are indistinguishable; assign them globally, never by greedy first match.
// Captured-and-redeployed excess pieces get the capped displacement cost.
inline int placement_cost(const std::vector<int>& current,
                          const std::vector<int>& initial, int piece_weight) {
    const int slots = static_cast<int>(initial.size());
    const int masks = 1 << slots;
    const int INF = std::numeric_limits<int>::max()/4;
    std::vector<int> dp(masks, INF), next(masks, INF);
    dp[0] = 0;
    for (int square : current) {
        std::fill(next.begin(), next.end(), INF);
        for (int mask=0;mask<masks;++mask) {
            if (dp[mask] == INF) continue;
            // An additional captured piece may have no unique original slot.
            next[mask] = std::min(next[mask], dp[mask] + piece_weight * 5);
            for(int i=0;i<slots;++i) {
                if (mask & (1<<i)) continue;
                const int cost = piece_weight * std::min(5, distance(square,initial[i]));
                next[mask | (1<<i)] = std::min(next[mask | (1<<i)], dp[mask]+cost);
            }
        }
        dp.swap(next);
    }
    return *std::min_element(dp.begin(),dp.end());
}
inline int bound100(int v) { return std::clamp(v,0,100); }
} // namespace phase_detail

inline PhaseDiagnostics diagnose_phase(const rules::Snapshot& s) {
    using namespace phase_detail;
    PhaseDiagnostics out;
    int weighted_displacement = 0;
    for(int side=0;side<2;++side) for(int kind=1;kind<=8;++kind) {
        std::vector<int> current;
        for(int sq=0;sq<81;++sq) {
            const auto& p=s.board[sq];
            if (p.kind==kind && static_cast<int>(p.color)==side)
                current.push_back(sq);
        }
        weighted_displacement += placement_cost(current,original(side,kind),weight(kind));
    }
    // Saturates at 210 weighted squares; this scale is a starting hypothesis.
    out.development = bound100((weighted_displacement*100+105)/210);

    const AttackMap attacks(s);
    int hand_pressure=0, occupied_under_attack=0, contested=0;
    int promoted=0, enemy_camp=0, deep_advance=0;
    for(int side=0;side<2;++side) for(int kind=1;kind<=7;++kind) {
        constexpr int hand_weights[8]={0,1,2,2,3,6,6,3};
        hand_pressure += s.hands[side][kind-1]*hand_weights[kind];
    }
    for(int sq=0;sq<81;++sq) {
        const auto& p=s.board[sq];
        if (p.kind && p.kind!=8) {
            const int side=static_cast<int>(p.color);
            if (attacks.nonking[1-side][sq]) ++occupied_under_attack;
            if (p.promoted) ++promoted;
            const int rank=sq%9;
            const int forward= side==0 ? 8-rank : rank;
            if (forward>=6) ++enemy_camp;
            else if (forward>=4) ++deep_advance;
        }
        if (attacks.nonking[0][sq] && attacks.nonking[1][sq]) ++contested;
    }
    // The first 96-game sample saturated battle by move 40 (median 100).
    // Reduced coefficients keep bishop trades from overwhelming this scale;
    // these are still unadopted diagnostic hypotheses.
    out.battle=bound100(4*hand_pressure+3*occupied_under_attack+contested);
    out.invasion=bound100(16*promoted+9*enemy_camp+2*deep_advance);

    int king_risk=0;
    for(int side=0;side<2;++side) {
        const int king=attacks.kings[side];
        if(king<0) continue;
        int zone=0, close_enemy=0;
        for(int sq=0;sq<81;++sq) {
            if(std::max(std::abs(sq/9-king/9),std::abs(sq%9-king%9))<=1
               && attacks.nonking[1-side][sq]) ++zone;
            const auto& p=s.board[sq];
            if(p.kind && p.kind!=8 && static_cast<int>(p.color)!=side
               && std::max(std::abs(sq/9-king/9),std::abs(sq%9-king%9))<=2)
                ++close_enemy;
        }
        const int risk=30*(attacks.nonking[1-side][king]>0)
                       +5*zone+11*close_enemy;
        king_risk=std::max(king_risk,risk);
    }
    out.king_threat=bound100(king_risk);

    // Provisional, not a trained stage classification. King urgency is reported
    // separately so an early king attack does not falsely mean "late game".
    out.provisional_progress=bound100(
        (20*out.development+40*out.battle+30*out.invasion
         +10*out.king_threat+50)/100);
    return out;
}
} // namespace shogi::strategy
