#pragma once
#include "rules/position.h"
#include "strategy/attack_map.h"
#include <algorithm>
#include <cmath>
#include <string>
#include <vector>

namespace shogi::strategy {

// Diagnostic-only three-axis stage estimate. It must not alter evaluation
// or move choice until independent controlled comparisons have been completed.
struct GameStage {
    int progress = 0;   // opening(0) -> endgame(100); may move both directions.
    int urgency = 0;    // concrete near-king attacks/checks, independent of progress.
    int complexity = 0; // number of legal options and drops at the root.
    const char* phase_name() const {
        return progress < 25 ? "opening" : (progress < 70 ? "middlegame" : "endgame");
    }
    bool quiet_opening() const { return progress < 25 && urgency < 20; }
};

inline GameStage estimate_game_stage(const rules::Snapshot& s,
                                     const std::vector<std::string>& legal,
                                     bool in_check) {
    GameStage out;
    int promoted = 0, invading = 0, hand_minor = 0, hand_major = 0, drops = 0;
    for (int sq=0; sq<81; ++sq) {
        const auto& pc = s.board[sq];
        if (!pc.kind || pc.kind==8) continue;
        if (pc.promoted) ++promoted;
        const int rank = sq % 9;
        if ((pc.color==rules::Color::Black && rank<3)
            || (pc.color==rules::Color::White && rank>5)) ++invading;
    }
    for (int color=0; color<2; ++color)
        for (int kind=1; kind<=7; ++kind) {
            int n=s.hands[color][kind-1];
            if (kind==5 || kind==6) hand_major += n;
            else hand_minor += n;
        }
    for (const auto& m:legal)
        if (m.size()==4 && m[1]=='*') ++drops;

    AttackMap attacks(s);
    int king_rim_attacks=0, contact=0;
    for (int c=0; c<2; ++c) {
        const int king=attacks.kings[c];
        if (king<0) continue;
        for (int sq=0; sq<81; ++sq) {
            int d=std::max(std::abs(sq/9-king/9),std::abs(sq%9-king%9));
            if (d<=1 && attacks.nonking[1-c][sq]) ++king_rim_attacks;
            const auto& p=s.board[sq];
            if (d<=2 && p.kind && p.kind!=8 && int(p.color)==1-c) ++contact;
        }
    }
    out.progress=std::clamp(std::min(35,3*hand_minor+7*hand_major)
          +std::min(25,6*promoted)+std::min(20,3*invading)
          +std::min(20,5*contact),0,100);
    out.urgency=in_check?100:std::clamp(8*king_rim_attacks+8*contact,0,100);
    out.complexity=std::clamp(static_cast<int>(legal.size()/2)
                    +2*drops + 4*hand_major,0,100);
    return out;
}
} // namespace shogi::strategy
