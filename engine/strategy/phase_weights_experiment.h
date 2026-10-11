#pragma once
// RESEARCH ONLY. Maturity-directional weights proposed on 2026-10-11.
// Do not merge into the adopted main engine without the owner's decision.
// Maturity anchors are 0 (opening), 50 (middle), and 100 (endgame).
// A separate hand-material scale prevents the early-game board-material
// premium from reducing the late-game intrinsic value of pieces in hand.
#include "strategy/evaluation_params.h"
#include <algorithm>
#include <array>
#include <cmath>

namespace shogi::strategy {
inline constexpr int ExperimentalPhaseIntensityPct = 100;

inline double phase_smoothstep(double x) {
    x=std::clamp(x,0.0,1.0);
    return x*x*(3.0-2.0*x);
}
inline int phase_interpolate(int maturity, int opening, int middle, int endgame) {
    const int m=std::clamp(maturity,0,100);
    return static_cast<int>(std::lround(m<=50
        ? opening+(middle-opening)*phase_smoothstep(m/50.0)
        : middle+(endgame-middle)*phase_smoothstep((m-50)/50.0)));
}
inline EvaluationParameters phase_turn_parameters(EvaluationParameters p,int maturity) {
    // Baseline M for explicit USI overrides. Axis order:
    // board material, safety, pressure, activity, danger, influence,
    // potential, coordination, in-hand tactical potential, fork/threat.
    constexpr std::array<int,10> M{100,480,380,410,150,140,210,340,60,20};
    constexpr std::array<int,10> O{140,440,330,460,130,180,250,380,45,25};
    constexpr std::array<int,10> C{110,575,380,410,150,140,210,350,105,23};
    constexpr std::array<int,10> E{ 80,730,440,350,180,100,150,325,190,20};
    std::array<int*,10> target{{
        &p.material_weight,&p.weights[0],&p.weights[1],&p.weights[2],
        &p.weights[3],&p.influence_weight,&p.potential_weight,
        &p.coordination_weight,&p.hand_potential_weight,&p.threat_weight
    }};
    for (std::size_t i=0;i<target.size();++i) {
        const int anchor=phase_interpolate(maturity,O[i],C[i],E[i]);
        // An explicit USI weight override scales around the original M base.
        // Disabled axes remain disabled.
        *target[i]=std::clamp(static_cast<int>(std::lround(
            double(*target[i])*anchor/M[i])),0,10000);
    }
    // Distinct from EvalHandPotential: the intrinsic material value of
    // *held* pieces rises, rather than being attenuated with board material.
    p.hand_material_weight=phase_interpolate(maturity,100,140,185);
    return p;
}
} // namespace shogi::strategy
