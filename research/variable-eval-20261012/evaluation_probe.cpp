// Post-game diagnosis only; it never changes or labels the observed moves.
#include "strategy/evaluation.h"
#include "strategy/turn_phase.h"
#include "strategy/phase_weights.h"
#include <iostream>
#include <string>
int main(){try{
    std::string line,error;
    while(std::getline(std::cin,line)){
        if(line.empty())continue;
        shogi::rules::Position p;
        if(!p.set(line,{},error))throw std::runtime_error(error);
        const auto s=p.snapshot();
        const auto phase=shogi::strategy::classify_turn_phase(s);
        int hand=0;constexpr int hw[7]={1,2,2,3,6,6,3};
        for(const auto& side:s.hands)for(int k=0;k<7;++k)hand+=side[k]*hw[k];
        hand=std::min(100,hand*4);
        std::cout<<"{\"maturity\":"<<phase.maturity<<",\"battle\":"<<phase.components.battle
                 <<",\"risk\":"<<phase.components.king_threat<<",\"hand\":"<<hand<<",\"profiles\":[";
        for(int i=0;i<static_cast<int>(shogi::strategy::ResearchProfiles.size());++i){
            auto params=shogi::strategy::research_turn_parameters({},i,phase.maturity,
                            phase.components.battle,phase.components.king_threat,hand);
            const auto b=shogi::strategy::evaluate(s,params);
            if(i)std::cout<<',';
            std::cout<<"{\"index\":"<<i<<",\"total\":"<<b.total<<",\"board_weight\":"<<params.material_weight
                <<",\"hand_weight\":"<<params.hand_material_weight<<",\"material_term\":"<<b.material_term
                <<",\"positional_raw\":"<<b.positional_unclamped<<",\"clamp\":"<<b.clamp_adjustment
                <<",\"terms\":[";
            for(int axis=0;axis<9;++axis){if(axis)std::cout<<',';std::cout<<b.terms[axis];}
            std::cout<<"]}";
        }
        std::cout<<"]}\n";
    }
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
