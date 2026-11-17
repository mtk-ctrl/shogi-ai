#pragma once

// Opening book in the de-facto standard YaneuraOu text format
// ("#YANEURAOU-DB2016 1.00"). Self-authored reader; no upstream book code.
//
//   #YANEURAOU-DB2016 1.00
//   sfen <board> <turn> <hand> <ply>
//   <move> <ponder|none> <eval> <depth> <count>
//   ...
//
// Positions are matched by board, side to move and hands only (the ply is
// ignored, like YaneuraOu's IgnoreBookPly=true), so transpositions hit.
// SFEN keys are normalized through the rules layer on load, which makes
// the hand order of the producing tool irrelevant.

#include "rules/position.h"
#include <algorithm>
#include <cstdint>
#include <fstream>
#include <random>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

namespace shogi::strategy {

class BookDatabase {
public:
    struct Move {
        std::string move;
        std::string ponder;   // empty when "none"
        int eval = 0;
        int depth = 0;
        std::uint64_t count = 0;
    };

    // Returns false (and keeps an empty book) on missing file or format error.
    bool load(const std::string& path, std::string& error) {
        clear();
        std::ifstream in(path);
        if (!in) { error = "cannot open"; return false; }
        std::unordered_map<std::string, std::vector<Move>> loaded;
        std::string line, key;
        bool header = false;
        int line_no = 0;
        while (std::getline(in, line)) {
            ++line_no;
            if (!line.empty() && line.back() == '\r') line.pop_back();
            if (line.empty()) continue;
            if (line.rfind("#YANEURAOU-DB2016", 0) == 0) { header = true; continue; }
            if (line[0] == '#' || line.rfind("//", 0) == 0) continue;
            std::istringstream fields(line);
            if (line.rfind("sfen ", 0) == 0) {
                std::string tag, board, turn, hand;
                fields >> tag >> board >> turn >> hand;
                rules::Position p;
                std::string why;
                if (!p.set(board + " " + turn + " " + hand + " 1", {}, why)) {
                    error = "bad sfen at line " + std::to_string(line_no); return false;
                }
                key = canonical_key(p);
                continue;
            }
            if (key.empty()) { error = "move before sfen at line " + std::to_string(line_no); return false; }
            Move m;
            std::string ponder;
            if (!(fields >> m.move)) continue;
            fields >> ponder >> m.eval >> m.depth >> m.count;
            if (ponder != "none" && ponder != "None") m.ponder = ponder;
            if (m.count == 0) m.count = 1;
            auto& list = loaded[key];
            auto it = std::find_if(list.begin(), list.end(), [&](const Move& x) { return x.move == m.move; });
            if (it == list.end()) list.push_back(m);
            else it->count += m.count;
        }
        if (!header) { error = "missing #YANEURAOU-DB2016 header"; return false; }
        if (loaded.empty()) { error = "no positions"; return false; }
        book_.swap(loaded);
        return true;
    }

    void clear() { book_.clear(); }
    std::size_t size() const { return book_.size(); }

    const std::vector<Move>* probe(const rules::Position& position) const {
        const auto it = book_.find(canonical_key(position));
        return it == book_.end() ? nullptr : &it->second;
    }

    // Picks a move among the book moves that are also in `legal`.
    // weighted=true: probability proportional to count (YaneuraOu's
    // ConsiderBookMoveCount). weighted=false: highest count, then eval.
    const Move* choose(const rules::Position& position, const std::vector<std::string>& legal,
                       bool weighted, unsigned seed) const {
        const auto* moves = probe(position);
        if (!moves) return nullptr;
        std::vector<const Move*> usable;
        for (const auto& m : *moves)
            if (std::find(legal.begin(), legal.end(), m.move) != legal.end()) usable.push_back(&m);
        if (usable.empty()) return nullptr;
        if (!weighted) {
            return *std::max_element(usable.begin(), usable.end(), [](const Move* a, const Move* b) {
                return a->count != b->count ? a->count < b->count : a->eval < b->eval;
            });
        }
        std::uint64_t total = 0;
        for (const auto* m : usable) total += m->count;
        std::mt19937_64 rng(seed);
        auto pick = std::uniform_int_distribution<std::uint64_t>(0, total - 1)(rng);
        for (const auto* m : usable) {
            if (pick < m->count) return m;
            pick -= m->count;
        }
        return usable.back();
    }

    static std::string canonical_key(const rules::Position& position) {
        std::istringstream in(position.sfen());
        std::string board, turn, hand;
        if (!(in >> board >> turn >> hand)) return {};
        return board + " " + turn + " " + hand;
    }

private:
    std::unordered_map<std::string, std::vector<Move>> book_;
};

} // namespace shogi::strategy
