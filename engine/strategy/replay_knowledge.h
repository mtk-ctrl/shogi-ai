#pragma once
#include "replay_knowledge_data.h"
#include "position_knowledge.h"
#include <sstream>
#include <stdexcept>
#include <unordered_map>

namespace shogi::strategy {
// Fixed own-play knowledge. No past score is added to an evaluation or cutoff.
class ReplayKnowledge {
public:
    struct Entry { std::string order, research; bool time_need=false; };
    static const ReplayKnowledge& instance() { static const ReplayKnowledge data; return data; }
    const Entry* probe(const rules::Position& position) const {
        if (position.has_repeated_history()) return nullptr;
        auto it=rows_.find(PositionKnowledge::canonical_key(position));
        return it==rows_.end()?nullptr:&it->second;
    }
    std::size_t size() const { return rows_.size(); }
private:
    ReplayKnowledge() {
        std::istringstream stream{std::string(detail::ReplayKnowledgeText)};
        std::string line;
        while(std::getline(stream,line)) {
            std::vector<std::string> fields;std::size_t start=0;
            for(;;) { auto end=line.find('\t',start);fields.push_back(line.substr(start,end==std::string::npos?end:end-start));
                if(end==std::string::npos)break;start=end+1; }
            if(fields.size()!=4 || (fields[3]!="0" && fields[3]!="1"))
                throw std::runtime_error("invalid compiled replay knowledge");
            if(!rows_.emplace(fields[0],Entry{fields[1]=="-"?"":fields[1],fields[2]=="-"?"":fields[2],fields[3]=="1"}).second)
                throw std::runtime_error("conflicting compiled replay knowledge");
        }
    }
    std::unordered_map<std::string,Entry> rows_;
};
} // namespace shogi::strategy
