#include "strategy/replay_knowledge.h"
#include <cassert>
#include <algorithm>
#include <iostream>

int main() {
    using namespace shogi::strategy;
    std::istringstream input{std::string(detail::ReplayKnowledgeText)};
    std::string line,error;std::size_t checked=0;
    while(std::getline(input,line)) {
        const auto tab=line.find('\t');const auto sfen=line.substr(0,tab)+" 1";
        shogi::rules::Position p;
        assert(p.set(sfen,{},error));const auto* e=ReplayKnowledge::instance().probe(p);assert(e);
        const auto legal=p.legal_moves();
        for(const auto& move:{e->order,e->research})
            assert(move.empty() || std::find(legal.begin(),legal.end(),move)!=legal.end());
        ++checked;
    }
    assert(checked==ReplayKnowledge::instance().size());
    // Same board reached repeatedly must not use history-insensitive memory.
    shogi::rules::Position repeated;
    assert(repeated.set(shogi::rules::Position::start_sfen(),{"5i5h","5a5b","5h5i","5b5a"},error));
    assert(repeated.has_repeated_history());assert(!ReplayKnowledge::instance().probe(repeated));
    std::cout<<"replay knowledge legal entries "<<checked<<"; repetition disabled\n";
}
