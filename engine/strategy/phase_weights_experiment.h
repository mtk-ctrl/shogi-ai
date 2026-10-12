#pragma once
// RESEARCH ONLY EXPERIMENT Q15: piece danger +20% from Q5; one-axis test vs Q5, not adopted.
#include "strategy/evaluation_params.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
namespace shogi::strategy {
inline constexpr int ExperimentalPhaseProfile=35;
inline constexpr std::array<int,10> StageOpening{200,450,390,560,162,245,300,900,45,30};
inline constexpr std::array<int,10> StageMiddle{155,540,540,470,204,300,270,780,95,26};
inline constexpr std::array<int,10> StageEnd{110,740,670,380,270,180,180,570,200,22};
inline constexpr std::array<int,3> StageHandMaterial{100,145,220};
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
        if(i==1) w+=urgency/2;
        if(i==4) w+=urgency/3;
        if(i==2) w+=fight;
        if(i==9) w+=fight/3;
        *target[i]=std::clamp(static_cast<int>(std::lround(
            double(*target[i])*w/MWeights[i])),0,10000);
    }
    p.hand_material_weight=phase_interpolate(maturity,StageHandMaterial[0],
                                              StageHandMaterial[1],StageHandMaterial[2]);
    return p;
}
} // namespace shogi::strategy
