#pragma once
#include "rules/position.h"
#include <random>

namespace shogi::strategy {
// Only a connection baseline. Replace this layer to develop your own thinking.
class Random {
public:
    explicit Random(unsigned seed = 5489u) : rng_(seed) {}
    void set_seed(unsigned seed) { rng_.seed(seed); }
    std::string choose(const rules::Position& position,
                       const std::vector<std::string>& allowed = {}) {
        auto moves = position.legal_moves();
        if (!allowed.empty()) {
            std::vector<std::string> filtered;
            for (const auto& move : moves)
                for (const auto& a : allowed) if (move == a) { filtered.push_back(move); break; }
            moves = std::move(filtered);
        }
        if (moves.empty()) return "resign";
        return moves[std::uniform_int_distribution<std::size_t>(0, moves.size()-1)(rng_)];
    }
private:
    std::mt19937 rng_;
};
}
