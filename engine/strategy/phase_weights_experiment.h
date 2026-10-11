#pragma once
// RESEARCH ONLY HYBRID 13: P4 attacking anchors plus king-risk defence, separates phase profile from contextual protection
#include "strategy/evaluation_params.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
namespace shogi::strategy {
inline constexpr int ExperimentalPhaseProfile=13;
inline constexpr std::array<int,10> StageOpening{140,430,380,525,140,220,300,400,55,26};
inline constexpr std::array<int,10> StageMiddle{115,525,500,465,170,205,245,385,120,25};
inline constexpr std::array<int,10> StageEnd{75,650,620,345,210,130,155,370,220,22};
inline constexpr std::array<int,3> StageHandMaterial{100,135,190};
inline constexpr std::array<int,10> MWeights{100,480,380,410,150,140,210,340,60,20};
inline double phase_smoothstep(double x){ x=std::clamp(x,0.0,1.0); return x*x*(3.0-2.0*x); }
inline int phase_interpolate(int maturity,int a,int b,int c) {
    const int m=std::clamp(maturity,0,100);
    return static_cast<int>(std::lround(m<=50
        ? a+(b-a)*phase_smoothstep(m/50.0)
        : b+(c-b)*phase_smoothstep((m-50)/50.0)));
}
inline EvaluationParameters phase_turn_parameters(EvaluationParameters p,int maturity,
                                                   int battle=0,int king_threat=0) {
    const int urgency=std::clamp(king_threat-20,0,80);
    const int fight=std::clamp(battle-20,0,80);
    std::array<int*,10> target{{
        &p.material_weight,&p.weights[0],&p.weights[1],&p.weights[2],
        &p.weights[3],&p.influence_weight,&p.potential_weight,
        &p.coordination_weight,&p.hand_potential_weight,&p.threat_weight
    }};
    for(std::size_t i=0;i<target.size();++i){
        int w=phase_interpolate(maturity,StageOpening[i],StageMiddle[i],StageEnd[i]);
        if(i==1) w+=urgency;
        if(i==4) w+=urgency/2;
        if(i==2) w=std::max(0,w-urgency/3);
        *target[i]=std::clamp(static_cast<int>(std::lround(
            double(*target[i])*w/MWeights[i])),0,10000);
    }
    p.hand_material_weight=phase_interpolate(maturity,StageHandMaterial[0],
                                              StageHandMaterial[1],StageHandMaterial[2]);
    return p;
}
} // namespace shogi::strategy
