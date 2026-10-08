#pragma once
#include "rules/position.h"
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

namespace shogi::strategy {

// An adopted research PV from a fixed position. Both sides' moves are recorded.
// This is not an opening book; it is a continuation of one separately archived analysis.
struct ResearchLine {
    std::string research_id;
    std::vector<std::string> pv;
};

class ResearchLines {
public:
    bool load(const std::string& path) {
        std::ifstream in(path);
        if (!in) { lines_.clear(); return false; }
        std::unordered_map<std::string,ResearchLine> next;
        std::string line;
        while (std::getline(in,line)) {
            if (line.empty() || line[0]=='#') continue;
            const auto t1=line.find('\t'),t2=t1==std::string::npos?std::string::npos:line.find('\t',t1+1);
            if(t2==std::string::npos || line.find('\t',t2+1)!=std::string::npos) {lines_.clear();return false;}
            const std::string key=line.substr(0,t1);
            const std::string source=line.substr(t2+1);
            std::istringstream is(line.substr(t1+1,t2-t1-1));
            ResearchLine entry{source,{}};
            std::string move;
            while (is>>move) entry.pv.push_back(move);
            if(key.empty()||source.empty()||entry.pv.empty()||entry.pv.size()>64) {lines_.clear();return false;}
            if(!next.emplace(key,std::move(entry)).second) {lines_.clear();return false;}
        }
        if(next.empty()) {lines_.clear();return false;}
        lines_.swap(next);
        return true;
    }
    const ResearchLine* probe(const rules::Position& p) const {
        std::istringstream is(p.sfen());
        std::string board,side,hands;
        if(!(is>>board>>side>>hands)) return nullptr;
        auto it=lines_.find(board+" "+side+" "+hands);
        return it==lines_.end()?nullptr:&it->second;
    }
    std::size_t size() const {return lines_.size();}
private:
    std::unordered_map<std::string,ResearchLine> lines_;
};
} // namespace shogi::strategy
