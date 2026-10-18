#include "rules/position.h"
#include "strategy/selfplay_order.h"
#include "strategy/move_order.h"
#include <iostream>
#include <string>
int main(){try{
    std::string line,error;
    while(std::getline(std::cin,line)){
        if(line.empty())continue;
        shogi::rules::Position p;
        if(!p.set(line,{},error))throw std::runtime_error(error);
        const auto s=p.snapshot();
        shogi::strategy::AttackMap a(s);
        const auto moves=p.legal_moves();
        std::cout<<"{\"moves\":[";
        for(std::size_t j=0;j<moves.size();++j){
            if(j)std::cout<<',';
            auto x=shogi::strategy::selfplay_order_features(s,a,moves[j]);
            std::cout<<"{\"move\":\""<<moves[j]<<"\",\"x\":[";
            for(std::size_t i=0;i<x.size();++i){if(i)std::cout<<',';std::cout<<x[i];}
            std::cout<<"]}";
        }
        bool preserved=true;
        auto expected=moves;std::sort(expected.begin(),expected.end());
        for(int scale : {0,50,100,200})for(int tier : {0,1,2}){
            auto ordered=shogi::strategy::MoveOrder::order(s,moves,nullptr,true,tier,false,scale);
            std::sort(ordered.begin(),ordered.end());preserved &= ordered==expected;
        }
        std::cout<<"],\"all_legal_moves_preserved\":"<<(preserved ? "true" : "false")<<"}\n";
    }
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
