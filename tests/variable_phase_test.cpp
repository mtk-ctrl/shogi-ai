#include "strategy/phase_weights.h"
#include <cassert>
#include <iostream>
using namespace shogi::strategy;
std::array<int,11> values(const EvaluationParameters& p) {
    return {p.material_weight,p.weights[0],p.weights[1],p.weights[2],p.weights[3],
        p.influence_weight,p.potential_weight,p.coordination_weight,
        p.hand_potential_weight,p.threat_weight,p.hand_material_weight};
}
int main() {
    for(int m=-1;m<=101;++m) for(int b:{0,20,50,100}) for(int r:{0,20,50,100}) {
        auto original=EvaluationParameters{};
        original.weights[0]=977; original.coordination_weight=0;
        assert(values(q14_turn_parameters(original,m,b,r))==
               values(research_turn_parameters(original,0,m,b,r)));
        for(int profile=0;profile<static_cast<int>(ResearchProfiles.size());++profile)
            for(int hand:{0,50,100}){
                auto p=research_turn_parameters(EvaluationParameters{},profile,m,b,r,hand);
                p.validate();
                if(profile==1) assert(values(p)==values(EvaluationParameters{}));
                assert(p.positional_cap==5000);
                assert(p.v2_enabled);
            }
    }
    // Independently specified anchors, curves, gates and single-axis controls.
    auto board0=research_turn_parameters({},12,0),board100=research_turn_parameters({},12,100);
    assert(board0.material_weight==200 && board100.material_weight==75);
    assert(board100.weights==EvaluationParameters{}.weights);
    assert(research_turn_parameters({},14,100).hand_material_weight==400);
    assert(research_turn_parameters({},15,100).hand_potential_weight==480);
    assert(values(research_turn_parameters({},5,0))==values(research_turn_parameters({},5,35)));
    assert(values(research_turn_parameters({},6,50))==values(research_turn_parameters({},3,25)));
    assert(values(research_turn_parameters({},7,33))==values(research_turn_parameters({},3,0)));
    assert(values(research_turn_parameters({},7,34))==values(research_turn_parameters({},3,50)));
    assert(values(research_turn_parameters({},22,0,0,100))==
           values(research_turn_parameters({},22,100,100,100)));
    assert(values(research_turn_parameters({},24,0,0,0,100))==
           values(research_turn_parameters({},24,100,100,100,100)));
    assert(research_turn_parameters({},25,100).hand_material_weight==110);
    assert(research_turn_parameters({},26,100).material_weight==100);
    assert(research_turn_parameters({},26,100).hand_material_weight==100);
    std::cout<<"PASS exact Q14 across 1648 contexts, M invariant, all 28 bounded profiles, curves, independent gates and hand/board balance\n";
}
