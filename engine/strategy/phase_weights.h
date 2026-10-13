#pragma once
// ADOPTED Q14 PHASE PROFILE - KUMOJI v2.0.12.
// The anchors and contextual bonuses reproduce the tested Q14 exactly.
#include "strategy/evaluation_params.h"
#include "research/variable_profiles.h"
#include "research/profile_select.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
namespace shogi::strategy {
inline constexpr int AdoptedPhaseProfile=34;
inline constexpr std::array<int,10> StageOpening{200,450,390,560,135,245,300,900,56,30};
inline constexpr std::array<int,10> StageMiddle{155,540,540,470,170,300,270,780,119,26};
inline constexpr std::array<int,10> StageEnd{110,740,670,380,225,180,180,570,250,22};
inline constexpr std::array<int,3> StageHandMaterial{100,145,220};
inline constexpr std::array<int,10> MWeights{100,480,380,410,150,140,210,340,60,20};
inline double phase_smoothstep(double x){ x=std::clamp(x,0.0,1.0); return x*x*(3.0-2.0*x); }
inline int phase_interpolate(int maturity,int a,int b,int c) {
    const int m=std::clamp(maturity,0,100);
    return static_cast<int>(std::lround(m<=50
        ? a+(b-a)*phase_smoothstep(m/50.0)
        : b+(c-b)*phase_smoothstep((m-50)/50.0)));
}
inline EvaluationParameters q14_turn_parameters(EvaluationParameters p,int maturity,
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

// All research profiles freeze a common, symmetric parameter vector at turn
// entry. Neither the maturity diagnosis nor the mate-budget policy is changed.
inline double research_phase_signal(const ResearchPhaseProfile& profile, int maturity,
                                    int battle, int risk, int hand_resource, int signal_override=-1) {
    const int signal=signal_override<0 ? profile.signal : signal_override;
    double x=maturity;
    if(signal==1) x=battle;
    if(signal==2) x=risk;
    if(signal==3) x=(5.0*maturity+3.0*battle+2.0*risk)/10.0;
    if(signal==4) x=hand_resource;
    x=std::clamp(x,0.0,100.0);
    if(profile.curve==2) x=100.0*std::max(0.0,x-35.0)/65.0;
    if(profile.curve==3) x=x*x/100.0;
    if(profile.curve==5) x=100.0*std::sqrt(x/100.0);
    return x;
}
inline int research_phase_interpolate(const ResearchPhaseProfile& profile, double x,
                                      int a,int b,int c) {
    if(profile.curve==4) return x<=33.0 ? a : x<=66.0 ? b : c;
    const double fraction=x<=50.0 ? x/50.0 : (x-50.0)/50.0;
    const double t=profile.curve==1 ? fraction : phase_smoothstep(fraction);
    return static_cast<int>(std::lround(x<=50.0 ? a+(b-a)*t : b+(c-b)*t));
}
inline EvaluationParameters research_turn_parameters(EvaluationParameters p,int index,
        int maturity,int battle=0,int king_threat=0,int hand_resource=0) {
    const auto& profile=ResearchProfiles.at(static_cast<std::size_t>(index));
    const auto x=research_phase_signal(profile,maturity,battle,king_threat,hand_resource);
    const int urgency=std::clamp(king_threat-20,0,80);
    const int fight=std::clamp(battle-20,0,80);
    std::array<int*,10> target{{&p.material_weight,&p.weights[0],&p.weights[1],
        &p.weights[2],&p.weights[3],&p.influence_weight,&p.potential_weight,
        &p.coordination_weight,&p.hand_potential_weight,&p.threat_weight}};
    for(std::size_t i=0;i<target.size();++i){
        const auto axis_x=profile.axis_signals[i]<0 ? x : research_phase_signal(
            profile,maturity,battle,king_threat,hand_resource,profile.axis_signals[i]);
        int w=research_phase_interpolate(profile,axis_x,profile.anchors[0][i],
                                        profile.anchors[1][i],profile.anchors[2][i]);
        if(profile.context){
            if(i==1) w+=urgency/2;
            if(i==4) w+=urgency/3;
            if(i==2) w+=fight;
            if(i==9) w+=fight/3;
        }
        *target[i]=std::clamp(static_cast<int>(std::lround(
            double(*target[i])*w/MWeights[i])),0,10000);
    }
    const auto hand_x=profile.hand_signal<0 ? x : research_phase_signal(
        profile,maturity,battle,king_threat,hand_resource,profile.hand_signal);
    p.hand_material_weight=research_phase_interpolate(profile,hand_x,
        profile.hand_material[0],profile.hand_material[1],profile.hand_material[2]);
    return p;
}
inline EvaluationParameters phase_turn_parameters(EvaluationParameters p,int maturity,
        int battle=0,int king_threat=0,int hand_resource=0,int profile_index=SelectedResearchProfile) {
    static_assert(SelectedResearchProfile>=0 && SelectedResearchProfile<
                  static_cast<int>(ResearchProfiles.size()));
    if(profile_index==0)
        return q14_turn_parameters(p,maturity,battle,king_threat);
    return research_turn_parameters(p,profile_index,maturity,battle,
                                   king_threat,hand_resource);
}
} // namespace shogi::strategy
