#pragma once
#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>
namespace shogi::strategy {
class MoveHintCache {
public:
    struct Entry { std::uint64_t key=0; std::uint32_t generation=0; std::int8_t depth=-1; std::array<char,6> best_move{}; };
    static constexpr std::size_t Capacity=1u<<17;
    MoveHintCache(): entries_(Capacity) {}
    void new_search(){ ++generation_; if(generation_==0){ clear(); generation_=1; } }
    const Entry* probe(std::uint64_t key) const { const auto& e=entries_[index(key)]; return e.generation!=0 && e.generation!=generation_ && e.key==key ? &e : nullptr; }
    bool store(std::uint64_t key,int depth,const std::string& move){ if(move.empty())return false; auto& e=entries_[index(key)]; const bool live=e.generation!=0; const bool same=live&&e.key==key; if(same&&depth<e.depth)return false; if(live&&!same&&depth<e.depth)return false; const bool replaced=live&&!same; e.key=key; e.depth=static_cast<std::int8_t>(depth); e.generation=generation_; e.best_move.fill('\0'); const auto n=std::min(move.size(),e.best_move.size()-1); std::copy_n(move.data(),n,e.best_move.data()); return replaced; }
    void clear(){ for(auto& e:entries_) e.generation=0; }
    static std::string best_move(const Entry& e){ return std::string(e.best_move.data()); }
private:
    static constexpr std::size_t Mask=Capacity-1;
    static std::size_t index(std::uint64_t key){ key^=key>>30; key*=0xbf58476d1ce4e5b9ULL; key^=key>>27; key*=0x94d049bb133111ebULL; key^=key>>31; return static_cast<std::size_t>(key&Mask); }
    std::vector<Entry> entries_; std::uint32_t generation_=1;
};
} // namespace shogi::strategy
