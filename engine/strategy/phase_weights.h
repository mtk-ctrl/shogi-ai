#pragma once
// ADOPTED MOB_smooth_0 (research profile 47) - KUMOJI v2.0.13.
// Matches frozen candidate e7440354 without the research profile selector.
#include "strategy/evaluation_params.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
namespace shogi::strategy {
inline constexpr int AdoptedPhaseProfile=47;
inline constexpr std::array<int,10> StageOpening{100,480,450,600,150,180,300,500,60,20};
inline constexpr std::array<int,10> StageMiddle{100,480,750,500,150,240,210,340,60,20};
inline constexpr std::array<int,10> StageEnd{100,480,1050,300,150,120,160,220,60,20};
inline constexpr std::array<int,3> StageHandMaterial{100,100,100};
inline constexpr std::array<int,10> MWeights{100,480,380,410,150,140,210,340,60,20};
inline double phase_smoothstep(double x){ x=std::clamp(x,0.0,1.0); return x*x*(3.0-2.0*x); }
inline int phase_interpolate(int maturity,int a,int b,int c) {
    const int m=std::clamp(maturity,0,100);
    return static_cast<int>(std::lround(m<=50
        ? a+(b-a)*phase_smoothstep(m/50.0)
        : b+(c-b)*phase_smoothstep((m-50)/50.0)));
}
inline EvaluationParameters phase_turn_parameters(EvaluationParameters p,int maturity,
                                                   int /*battle*/=0,int /*king_threat*/=0) {
    std::array<int*,10> target{{
        &p.material_weight,&p.weights[0],&p.weights[1],&p.weights[2],
        &p.weights[3],&p.influence_weight,&p.potential_weight,
        &p.coordination_weight,&p.hand_potential_weight,&p.threat_weight
    }};
    for(std::size_t i=0;i<target.size();++i){
        int w=phase_interpolate(maturity,StageOpening[i],StageMiddle[i],StageEnd[i]);
        *target[i]=std::clamp(static_cast<int>(std::lround(
            double(*target[i])*w/MWeights[i])),0,10000);
    }
    p.hand_material_weight=phase_interpolate(maturity,StageHandMaterial[0],
                                              StageHandMaterial[1],StageHandMaterial[2]);
    return p;
}
} // namespace shogi::strategy
