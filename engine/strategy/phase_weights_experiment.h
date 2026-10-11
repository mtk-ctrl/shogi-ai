#pragma once
// RESEARCH ONLY: contextual phase-weight experiments, not adopted in main.
// Keep all feature definitions, mate search, time control and knowledge identical
// to the pinned N-profile opponent. Change only evaluation integration.
#include "strategy/evaluation_params.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>

namespace shogi::strategy {

// Independent research branches each pin a single ID for reproducibility.
// 1 king-risk defence; 2 material preservation; 3 influence/coordination;
// 4 tactical battle gate; 5 restrained transition; 6 combined response.
inline constexpr int ExperimentalPhaseProfile = 3;
inline constexpr int ExperimentalPhaseIntensityPct = 100;
using WeightVector = std::array<int,10>;
struct ProfileAnchors {
    WeightVector opening;
    WeightVector middle;
    WeightVector endgame;
};
inline constexpr WeightVector PhaseM{100,480,380,410,150,140,210,340,60,20};

inline ProfileAnchors anchors_for_profile() {
    if constexpr (ExperimentalPhaseProfile == 1) {
        return {{100,500,340,455,140,175,260,400,50,20},
                {110,495,400,415,185,160,215,360,75,40},
                {115,510,465,370,215,120,170,300,105,60}};
    } else if constexpr (ExperimentalPhaseProfile == 2) {
        return {{125,500,340,445,175,160,225,385,55,20},
                {145,480,400,410,215,140,205,330,75,35},
                {150,500,470,355,235,110,165,265,95,65}};
    } else if constexpr (ExperimentalPhaseProfile == 3) {
        return {{100,460,320,480,140,280,350,480,45,15},
                {105,465,385,440,170,240,290,440,70,30},
                {110,510,460,380,210,160,210,345,100,55}};
    } else if constexpr (ExperimentalPhaseProfile == 4) {
        return {{105,500,345,455,150,180,255,385,50,20},
                {110,490,410,425,175,165,215,355,70,35},
                {115,485,490,375,205,110,165,285,110,65}};
    } else if constexpr (ExperimentalPhaseProfile == 5) {
        return {{100,490,360,445,145,160,235,365,55,20},
                {105,480,395,420,160,145,220,350,70,30},
                {112,505,460,380,195,125,185,320,90,45}};
    } else {
        static_assert(ExperimentalPhaseProfile == 6, "unsupported experimental phase profile");
        return {{110,510,350,470,150,175,240,400,50,20},
                {125,485,415,420,185,160,215,355,80,45},
                {130,505,495,370,225,120,175,300,125,85}};
    }
}

inline double phase_smoothstep(double x) {
    x=std::clamp(x,0.0,1.0);
    return x*x*(3.0-2.0*x);
}
inline int phase_interpolate(int maturity,int opening,int middle,int endgame) {
    const int m=std::clamp(maturity,0,100);
    return static_cast<int>(std::lround(m<=50
        ? opening+(middle-opening)*phase_smoothstep(m/50.0)
        : middle+(endgame-middle)*phase_smoothstep((m-50)/50.0)));
}
inline EvaluationParameters phase_turn_parameters(
    EvaluationParameters p, int maturity, int battle, int king_threat) {
    const auto anchors=anchors_for_profile();
    const int fight=std::clamp(battle-20,0,80);
    const int urgency=std::clamp(king_threat-20,0,80);
    WeightVector desired{};
    for (std::size_t i=0; i<desired.size(); ++i)
        desired[i]=phase_interpolate(maturity,anchors.opening[i],
                                    anchors.middle[i],anchors.endgame[i]);
    // The risk diagnostic is symmetric across kings; adjust relative importance,
    // never pretend it identifies which side is under threat.
    if constexpr (ExperimentalPhaseProfile == 1) {
        desired[1]+=urgency;                   // secure king on tactical contact
        desired[4]+=urgency/2;                 // reduce hanging pieces
        desired[2]-=urgency/3;                 // do not overvalue a speculative rush
    } else if constexpr (ExperimentalPhaseProfile == 4) {
        desired[2]+=2*fight;                   // attack only once fighting starts
        desired[9]+=fight/2;                   // concrete threats matter then
        desired[3]-=fight/4;                   // raw activity is not the goal
    } else if constexpr (ExperimentalPhaseProfile == 6) {
        desired[1]+=urgency/2;
        desired[4]+=urgency/3;
        desired[2]+=fight;
        desired[9]+=fight/3;
    }
    std::array<int*,10> weights{{
      &p.material_weight,&p.weights[0],&p.weights[1],
      &p.weights[2],&p.weights[3],&p.influence_weight,
      &p.potential_weight,&p.coordination_weight,
      &p.hand_potential_weight,&p.threat_weight
    }};
    for (std::size_t i=0; i<weights.size(); ++i) {
        // A zero explicitly set by a USI feature override remains zero.
        desired[i]=std::clamp(desired[i],0,10000);
        *weights[i]=std::clamp(static_cast<int>(std::lround(
            double(*weights[i])*desired[i]/PhaseM[i])),0,10000);
    }
    return p;
}
} // namespace shogi::strategy
