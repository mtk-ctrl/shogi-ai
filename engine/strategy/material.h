#pragma once
#include "rules/position.h"
#include <algorithm>
#include <limits>
#include <random>
#include <stdexcept>

namespace shogi::strategy {
// Our values, independent of the upstream engine. One pawn = 100.
inline int piece_value(int kind, bool promoted = false) {
    constexpr int base[] = {0, 100, 300, 300, 500, 800, 1000, 600, 0};
    if (kind < 0 || kind > 8) throw std::logic_error("unknown piece kind");
    if (promoted && kind >= 1 && kind <= 4) return 600;
    if (promoted && (kind == 5 || kind == 6)) return base[kind] + 200;
    return base[kind];
}

// Always Black minus White; independent of whose turn the snapshot has.
inline int material_black(const rules::Snapshot& snapshot) {
    int score = 0;
    for (const auto& piece : snapshot.board)
        score += (piece.color == rules::Color::Black ? 1 : -1)
                 * piece_value(piece.kind, piece.promoted);
    for (int color = 0; color < 2; ++color)
        for (int kind = 1; kind <= 7; ++kind)
            score += (color == 0 ? 1 : -1) * snapshot.hands[color][kind - 1]
                     * piece_value(kind);
    return score;
}

// Phase 2: evaluate the board immediately AFTER each of our legal moves.
// No opponent replies, mate search, positional bonuses or learned values.
class Material {
public:
    explicit Material(unsigned seed = 5489u) : rng_(seed) {}
    void set_seed(unsigned seed) { rng_.seed(seed); }

    std::string choose(rules::Position& position,
                       const std::vector<std::string>& allowed = {}) {
        auto moves = position.legal_moves();
        if (!allowed.empty()) {
            moves.erase(std::remove_if(moves.begin(), moves.end(), [&](const auto& move) {
                return std::find(allowed.begin(), allowed.end(), move) == allowed.end();
            }), moves.end());
        }
        if (moves.empty()) return "resign";
        // Preserve v0.0.2's USI behavior after repetition: the GUI adjudicates.
        // Position::play correctly refuses to extend a terminal game.
        if (position.status().result != rules::Result::Ongoing) return random_move(moves);

        const int sign = position.snapshot().turn == rules::Color::Black ? 1 : -1;
        int best = std::numeric_limits<int>::min();
        std::vector<std::string> tied;
        for (const auto& move : moves) {
            std::string error;
            if (!position.play(move, error)) throw std::logic_error(error);
            // Roll back even if an exception is raised while reading the child.
            struct Undo {
                rules::Position& position;
                ~Undo() { position.undo(); }
            } undo{position};
            const int score = sign * material_black(position.snapshot());
            if (score > best) { best = score; tied.clear(); }
            if (score == best) tied.push_back(move);
        }
        return random_move(tied);
    }

private:
    std::string random_move(const std::vector<std::string>& moves) {
        return moves[std::uniform_int_distribution<std::size_t>(0, moves.size()-1)(rng_)];
    }
    std::mt19937 rng_;
};
} // namespace shogi::strategy
