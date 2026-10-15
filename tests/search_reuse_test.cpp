#include "strategy/iterative_search.h"
#include <iostream>
#include <random>
#include <tuple>
using namespace shogi;
void require(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
std::vector<int> signature(const strategy::EvaluationBreakdown& b) {
    std::vector<int> v{b.material,b.material_term,b.positional_unclamped,b.positional,
                       b.clamp_adjustment,b.total};
    for(int x:b.terms)v.push_back(x);
    for(auto& side:b.side_points)for(int x:side)v.push_back(x);
    for(auto& f:b.raw) {
        for(int x:{f.gold_guards,f.silver_guards,f.pawn_guards,f.king_attacked,
                   f.occupied_ring,f.denied_empty,f.partners,f.major_mobility,
                   f.minor_mobility,f.exposure,f.v2.influence,f.v2.potential,
                   f.v2.coordination,f.v2.hand_potential,f.v2.threat})v.push_back(x);
    }
    return v;
}
auto signature(const strategy::SearchResult& r,const strategy::IterativeSearch::Stats& s) {
    return std::make_tuple(r.move,r.score,r.depth,r.has_score,r.pv,s.nodes,s.qnodes,s.cutoffs);
}
int main(){try {
    strategy::AttackMap reference(rules::Snapshot{}),lookup(rules::Snapshot{},true,true);
    for(int a=-1;a<81;++a)for(int b=-1;b<81;++b) {
        require(lookup.distance(a,b)==strategy::v2_distance(a,b),"distance table differs from coordinate oracle");
        require(lookup.near_square(a,b)==strategy::AttackMap::near(a,b),"near table differs from coordinate oracle");
    }
    std::cout<<"PASS all square pairs and missing-king geometry\n";
    std::array<strategy::EvaluationParameters,4> parameters{
        strategy::EvaluationParameters{},strategy::EvaluationParameters::legacy_v1(),
        strategy::EvaluationParameters::material_only(),strategy::EvaluationParameters{}};
    parameters[3].material_weight=137;parameters[3].hand_material_weight=89;
    parameters[3].weights={37,117,223,411};parameters[3].v2_caps={19,23,17,31};
    parameters[3].positional_cap=73;parameters[3].danger_denominator=13;
    rules::Position p;std::string error;std::mt19937 rng(2026101592);
    int promoted=0,hands=0;
    for(int sample=0;sample<500;++sample) {
        if(sample%180==0 || p.status().result!=rules::Result::Ongoing)
            require(p.set(rules::Position::start_sfen(),{},error),"reset random game");
        const auto s=p.snapshot();
        for(auto q:s.board)promoted+=q.promoted;
        for(auto row:s.hands)for(int n:row)hands+=n;
        strategy::AttackMap base(s),indexed(s,true,true);
        require(base.count==indexed.count && base.nonking==indexed.nonking
            && base.least==indexed.least && base.targets==indexed.targets
            && base.sizes==indexed.sizes && base.escape_control==indexed.escape_control
            && base.kings==indexed.kings,"indexed map changed attacks");
        for(int side=0;side<2;++side) {
            std::vector<int> expected,actual;
            for(int sq=0;sq<81;++sq)if(s.board[sq].kind && int(s.board[sq].color)==side)expected.push_back(sq);
            for(int sq:indexed.squares(side))actual.push_back(sq);
            require(actual==expected,"occupied indexes lost ascending square order");
        }
        for(const auto& params:parameters) {
            const auto expected=signature(strategy::evaluate(s,params));
            for(unsigned mask:{2u,4u,6u})require(signature(strategy::evaluate(s,params,mask))==expected,
                "evaluation raw fields/terms/caps/rounding changed");
        }
        const auto moves=p.legal_generated_moves();
        require(p.play_generated_move(moves[rng()%moves.size()],error),"advance random game");
    }
    require(promoted>0 && hands>0,"random sample must include promoted and in-hand pieces");
    std::cout<<"PASS complete evaluation breakdown and attack/index identity: 500 legal positions, four parameter sets\n";
    const std::vector<std::pair<std::string,std::vector<std::string>>> cases{
        {"4r3k/9/9/4p4/9/9/9/4R4/K8 b - 1",{"5h5d","5h4h"}},
        {"8k/9/9/9/9/9/2P6/9/K8 b - 1",{}},
        {"8k/9/9/9/9/9/2P6/9/K8 w - 1",{}},
        {rules::Position::start_sfen(),{"7g7f","3g3f"}},
    };
    std::uint64_t hits=0,misses=0;
    for(const auto& entry:cases) {
        require(p.set(entry.first,{},error),"set search case");
        strategy::IterativeSearch baseline;baseline.set_reuse_mask(0);
        strategy::SearchControl control;
        auto result=baseline.choose(p,3,control,entry.second);
        const auto expected=signature(result,baseline.last_stats());
        for(unsigned mask=0;mask<8;++mask) {
            strategy::IterativeSearch search(5489,strategy::FeatureEvaluator({},mask));search.set_reuse_mask(mask);
            for(int repeat=0;repeat<2;++repeat) {
                const auto sf=p.sfen();const auto history=p.history_key();
                search.set_seed(5489);
                strategy::SearchControl c;auto actual=search.choose(p,3,c,entry.second);
                if(signature(actual,search.last_stats())!=expected) {
                    std::cerr<<"case "<<entry.first<<" mask "<<mask<<" repeat "<<repeat
                        <<" expected "<<result.move<<"/"<<result.score<<"/"<<baseline.last_stats().nodes
                        <<" actual "<<actual.move<<"/"<<actual.score<<"/"<<search.last_stats().nodes<<'\n';
                    throw std::runtime_error("bounded search/PV/nodes differ");
                }
                require(p.sfen()==sf && p.history_key()==history,"search changed full root/history");
                if(mask&1){hits+=search.last_stats().legal_cache_hits;misses+=search.last_stats().legal_cache_misses;}
                else require(search.last_stats().legal_cache_hits==0,"disabled cache used");
                auto replay=p.clone();for(auto m:actual.pv)require(replay.play(m,error),"PV illegal");
            }
        }
    }
    require(hits>0 && misses>2048,"test must exercise cache hits and slot replacement");
    std::cout<<"PASS all 8 masks, repeated go epochs, exact search/PV/nodes and restoration; cache hits "<<hits<<" misses "<<misses<<'\n';
    require(p.set("4k4/9/9/9/9/9/9/9/4K4 b - 1",{},error),"set repetition");
    for(int cycle=0;cycle<2;++cycle)for(auto m:{"5i6i","5a6a","6i5i","6a5a"})require(p.play(m,error),"cycle");
    for(auto m:{"5i6i","5a6a","6i5i"})require(p.play(m,error),"partial cycle");
    for(unsigned mask=0;mask<8;++mask) {
        strategy::IterativeSearch search(5489,strategy::FeatureEvaluator({},mask));search.set_reuse_mask(mask);
        strategy::SearchControl c;const auto history=p.history_key();
        auto r=search.choose(p,4,c,{"6a5a"});
        require(r.score==0 && p.history_key()==history && p.status().result==rules::Result::Ongoing,
            "cached legal tokens changed repetition/history");
    }
    require(p.play("6a5a",error) && p.status().result==rules::Result::Draw,"real fourth repetition changed");
    std::cout<<"PASS all 8 masks preserve speculative and real repetition adjudication\n";
}catch(const std::exception& e){std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}}
