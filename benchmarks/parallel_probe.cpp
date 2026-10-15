#include "strategy/iterative_search.h"
#include "strategy/phase_weights.h"
#include "strategy/turn_phase.h"
#include <thread>
#include <iostream>
#include <memory>
using namespace shogi;
// Diagnostic prototype only. Independent per-lane state; no upstream search,
// shared transposition table or product time-control change.
int main() {try {
    std::array<std::unique_ptr<strategy::IterativeSearch>,3> engines;
    for(auto& e:engines) {
        e=std::make_unique<strategy::IterativeSearch>();
        if(!e->load_position_knowledge("position-knowledge-v1.tsv"))
            throw std::runtime_error("adopted knowledge unavailable");
    }
    std::string line,error;int index=0;
    while(std::getline(std::cin,line)) {
        rules::Position p;
        if(!p.set_usi(line,error))throw std::runtime_error(error);
        const auto snapshot=p.snapshot();
        const auto phase=strategy::classify_turn_phase(snapshot);
        const auto params=strategy::phase_turn_parameters(strategy::EvaluationParameters{},
            phase.maturity,phase.components.battle,phase.components.king_threat);
        std::array<std::vector<std::string>,2> groups;
        const auto moves=p.legal_moves();
        if(moves.size()<2)continue;
        for(std::size_t i=0;i<moves.size();++i)groups[i%2].push_back(moves[i]);
        for(int rep=0;rep<3;++rep) {
            strategy::SearchResult single;
            std::array<strategy::SearchResult,2> parallel;
            double one_ms=0,two_ms=0;
            std::uint64_t one_nodes=0,two_nodes=0;
            for(int order=0;order<2;++order) {
                const bool two=(order+rep+index)%2;
                for(auto& e:engines) { e->set_seed(5489);e->set_evaluator(strategy::FeatureEvaluator(params)); }
                if(two) {
                    const auto begin=strategy::SearchControl::now_ns();
                    auto p0=p.clone(),p1=p.clone();
                    strategy::SearchControl c0,c1;
                    std::exception_ptr worker_error;
                    std::thread worker([&]{try{parallel[1]=engines[2]->choose(p1,2,c1,groups[1]);}
                        catch(...){worker_error=std::current_exception();}});
                    try{parallel[0]=engines[1]->choose(p0,2,c0,groups[0]);}
                    catch(...){worker.join();throw;}
                    worker.join();if(worker_error)std::rethrow_exception(worker_error);
                    two_ms=(strategy::SearchControl::now_ns()-begin)/1e6;
                    two_nodes=engines[1]->last_stats().nodes+engines[2]->last_stats().nodes;
                } else {
                    strategy::SearchControl control;
                    const auto begin=strategy::SearchControl::now_ns();
                    single=engines[0]->choose(p,2,control);
                    one_ms=(strategy::SearchControl::now_ns()-begin)/1e6;
                    one_nodes=engines[0]->last_stats().nodes;
                }
            }
            if(single.score!=std::max(parallel[0].score,parallel[1].score))
                throw std::runtime_error("split-root fixed-depth score differs");
            std::cout<<index<<'\t'<<rep<<'\t'<<one_ms<<'\t'<<two_ms<<'\t'
                <<one_nodes<<'\t'<<two_nodes<<'\t'<<single.score<<'\n'<<std::flush;
        }
        ++index;
    }
}catch(const std::exception& e){std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}}
