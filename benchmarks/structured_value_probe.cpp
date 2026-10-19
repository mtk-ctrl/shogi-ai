#include "strategy/evaluation.h"
#include "strategy/phase_weights.h"
#include "strategy/turn_phase.h"
#include <iostream>
#include <map>
#include <string>
using namespace shogi;
int main(){try{
    std::string line,error;
    while(std::getline(std::cin,line)) {
        if(line.empty())continue;
        rules::Position p;
        if(!p.set(line,{},error))throw std::runtime_error(error);
        const auto s=p.snapshot();
        const auto phase=strategy::classify_turn_phase(s);
        strategy::EvaluationParameters base;
        base.weights={540,391,422,157};base.influence_weight=143;
        base.potential_weight=190;base.coordination_weight=343;
        base.hand_potential_weight=59;base.threat_weight=22;
        base=strategy::phase_turn_parameters(base,phase.maturity);
        const auto b=strategy::evaluate(s,base,6);
        strategy::AttackMap a(s,true,true);
        std::map<int,int> sparse;
        strategy::structured_features(s,a,phase.maturity,[&](int i,int v){sparse[i]+=v;});
        std::cout<<"{\"maturity\":"<<phase.maturity<<",\"base\":"<<b.total
                 <<",\"clamp\":"<<b.clamp_adjustment
                 <<",\"learned50\":"<<strategy::structured_value(s,a,phase.maturity,50)
                 <<",\"learned100\":"<<strategy::structured_value(s,a,phase.maturity,100)
                 <<",\"learned150\":"<<strategy::structured_value(s,a,phase.maturity,150)
                 <<",\"features\":[";
        bool first=true;
        for(const auto& [i,v]:sparse)if(v){if(!first)std::cout<<',';first=false;std::cout<<'['<<i<<','<<v<<']';}
        std::cout<<"]}\n";
    }
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
