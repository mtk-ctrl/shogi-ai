#include "strategy/iterative_search.h"
#include <iostream>
#include <random>
#include <tuple>
using namespace shogi;
void require(bool value,const char* why){if(!value)throw std::runtime_error(why);}
auto sig(const strategy::SearchResult& r,const strategy::IterativeSearch::Stats& s) {
    return std::make_tuple(r.move,r.score,r.depth,r.has_score,r.pv,s.nodes,s.qnodes,s.cutoffs);
}
int main(){try {
    strategy::IncrementalAttackMap incremental;
    strategy::IncrementalMaterial material;
    std::array<strategy::EvaluationParameters,4> params{
        strategy::EvaluationParameters{},strategy::EvaluationParameters::legacy_v1(),
        strategy::EvaluationParameters::material_only(),strategy::EvaluationParameters{}};
    params[3].material_weight=137;params[3].hand_material_weight=89;
    params[3].weights={37,117,223,411};params[3].positional_cap=73;
    rules::Position p;std::string error;std::mt19937 rng(2026101571);
    std::vector<rules::Snapshot> saved;
    int promoted=0,in_hand=0;
    auto check=[&](const rules::Snapshot& s) {
        const auto& a=incremental.update(s,6);strategy::AttackMap b(s,true,true);
        require(a.count==b.count && a.nonking==b.nonking && a.least==b.least
            && a.targets==b.targets && a.sizes==b.sizes
            && a.escape_control==b.escape_control && a.kings==b.kings
            && a.occupied==b.occupied && a.occupied_sizes==b.occupied_sizes,"attack map mismatch");
        const auto& m=material.update(s);
        require(m.board+m.hand==strategy::material_black(s),"material mismatch");
        for(const auto& param:params) {
            const auto ref=strategy::evaluate(s,param,6);
            const auto actual=strategy::evaluate(s,param,6,&a,&m);
            require(ref.total==actual.total && ref.material==actual.material
                && ref.material_term==actual.material_term && ref.terms==actual.terms
                && ref.side_points==actual.side_points
                && ref.positional_unclamped==actual.positional_unclamped
                && ref.clamp_adjustment==actual.clamp_adjustment,"evaluation breakdown mismatch");
        }
    };
    for(int i=0;i<2500;++i) {
        if(i%160==0 || p.status().result!=rules::Result::Ongoing)
            require(p.set(rules::Position::start_sfen(),{},error),"reset");
        auto s=p.snapshot();check(s);saved.push_back(s);
        for(auto q:s.board)promoted+=q.promoted;
        for(auto side:s.hands)for(int n:side)in_hand+=n;
        // Test arbitrary evaluation order, not just contiguous forward moves.
        if(i%7==0) {check(saved[rng()%saved.size()]);check(s);}
        auto moves=p.legal_generated_moves();
        require(p.play_generated_move(moves[rng()%moves.size()],error),"random move");
        if(i%11==0){check(p.snapshot());require(p.undo(),"undo");check(p.snapshot());}
    }
    require(promoted && in_hand,"must cover promotions and hands");
    for(auto sfen:{"4r3k/9/9/4p4/9/9/9/4R4/K8 b - 1",
                   "4k4/9/9/9/4R4/9/9/9/4K4 w - 1",
                   "4k4/9/9/9/9/9/9/9/4K4 b 2P2p 1"}) {
        require(p.set(sfen,{},error),"set custom");check(p.snapshot());
        for(auto m:p.legal_generated_moves()) {
            require(p.play_generated_move(m,error),"custom move");check(p.snapshot());
            require(p.undo(),"custom undo");check(p.snapshot());
        }
    }
    std::cout<<"PASS 2500 legal positions plus unrelated positions, undo, x-rays, drops; full attack maps and evaluation components\n";
    for(auto sfen:{rules::Position::start_sfen(),std::string("4r3k/9/9/4p4/9/9/9/4R4/K8 b - 1"),
                   std::string("8k/9/9/9/9/9/2P6/9/K8 b - 1")}) {
        require(p.set(sfen,{},error),"set search root");
        strategy::IterativeSearch ref;strategy::SearchControl c;
        auto expected=ref.choose(p,2,c);const auto signature=sig(expected,ref.last_stats());
        for(unsigned mask=0;mask<4;++mask) {
            strategy::IterativeSearch search;search.set_eval_update_mask(mask);
            for(int rep=0;rep<2;++rep) {
                search.set_seed(5489);strategy::SearchControl control;
                auto actual=search.choose(p,2,control);
                require(sig(actual,search.last_stats())==signature,"search score/move/PV/nodes mismatch");
            }
        }
    }
    std::cout<<"PASS all four masks: exact search scores, moves, PV, nodes and repeated searches\n";
}catch(const std::exception& e){std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}}
