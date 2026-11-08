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
inline constexpr std::array<int,10> StageOpening{100,480,469,600,168,180,300,500,60,20};
inline constexpr std::array<int,10> StageMiddle{100,480,1282,500,221,240,210,340,60,49};
inline constexpr std::array<int,10> StageEnd{100,480,2817,101,150,65,160,220,60,40};
// Research (EvalStageTable): optional override of the three anchor rows. Empty = the adopted
// profile 47 values above. Set once from the USI option before searching; never changed
// during a search. Index 0 (material) is not overridable.
struct StageTableOverride { bool active=false; std::array<int,10> rows[3]; };
inline StageTableOverride& stage_table_override(){ static StageTableOverride o; return o; }
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
    // Research (EvalKingExt): the king-exposure term fades in with maturity (0 at <=20, full at >=60).
    p.king_ext_scale=static_cast<int>(std::lround(p.king_ext_scale*std::clamp((maturity-20)/40.0,0.0,1.0)));
    for(std::size_t i=0;i<target.size();++i){
        const auto& ov=stage_table_override();
        int w=ov.active ? phase_interpolate(maturity,ov.rows[0][i],ov.rows[1][i],ov.rows[2][i])
                        : phase_interpolate(maturity,StageOpening[i],StageMiddle[i],StageEnd[i]);
        *target[i]=std::clamp(static_cast<int>(std::lround(
            double(*target[i])*w/MWeights[i])),0,10000);
    }
    p.hand_material_weight=phase_interpolate(maturity,StageHandMaterial[0],
                                              StageHandMaterial[1],StageHandMaterial[2]);
    return p;
}
} // namespace shogi::strategy
