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
        for(int mask=0;mask<8;++mask) {
            strategy::AttackMap other(s,mask&1,mask&2,mask&4);
            std::map<int,int> again;
            strategy::structured_features(s,other,phase.maturity,[&](int i,int v){again[i]+=v;});
            for(auto it=again.begin();it!=again.end();)if(it->second==0)it=again.erase(it);else ++it;
            auto expected=sparse;
            for(auto it=expected.begin();it!=expected.end();)if(it->second==0)it=expected.erase(it);else ++it;
            if(again!=expected)throw std::runtime_error("feature extraction depends on attack-map optimization mask");
            if(strategy::structured_value(s,other,phase.maturity,100)!=strategy::structured_value(s,a,phase.maturity,100))
                throw std::runtime_error("learned value depends on attack-map optimization mask");
        }
        std::cout<<"{\"maturity\":"<<phase.maturity<<",\"base\":"<<b.total
                 <<",\"material\":"<<b.material_term<<",\"positional_raw\":"<<b.positional_unclamped
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
