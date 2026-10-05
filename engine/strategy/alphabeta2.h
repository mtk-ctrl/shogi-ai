#pragma once
#include "strategy/material.h"
#include <algorithm>
#include <cstdint>
#include <limits>
#include <random>
#include <stdexcept>

namespace shogi::strategy {

// Phase 4: fixed two-ply alpha-beta search.
// The evaluation and depth are intentionally identical to Minimax2.
// Only branches that cannot equal or beat the current root best are pruned.
class AlphaBeta2 {
public:
    static constexpr int WinScore = 100000000;

    struct Stats {
        std::uint64_t nodes = 0;       // positions actually visited after a move
        std::uint64_t full_nodes = 0;  // nodes Minimax2 would visit at this fixed depth
        std::uint64_t cutoffs = 0;
    };

    explicit AlphaBeta2(unsigned seed = 5489u) : rng_(seed) {}
    void set_seed(unsigned seed) { rng_.seed(seed); }
    const Stats& last_stats() const { return stats_; }

    std::string choose(rules::Position& position,
                       const std::vector<std::string>& allowed = {}) {
        stats_ = {};
        auto moves = position.legal_moves();
        if (!allowed.empty()) {
            moves.erase(std::remove_if(moves.begin(), moves.end(), [&](const auto& move) {
                return std::find(allowed.begin(), allowed.end(), move) == allowed.end();
            }), moves.end());
        }
        if (moves.empty()) return "resign";

        // Preserve the existing USI behavior after a GUI-adjudicated terminal state.
        if (position.status().result != rules::Result::Ongoing) return random_move(moves);

        const rules::Color root = position.snapshot().turn;
        int alpha = std::numeric_limits<int>::min();
        std::vector<std::string> tied;

        for (const auto& move : moves) {
            std::string error;
            if (!position.play(move, error)) throw std::logic_error(error);
            Undo root_undo{position};
            ++stats_.nodes;
            ++stats_.full_nodes;

            int score;
            const auto child_status = position.status();
            if (child_status.result != rules::Result::Ongoing) {
                score = terminal_score(child_status.result, root);
            } else {
                // Opponent is the minimizing side. beta is its best (lowest)
                // reply found so far. Once beta is strictly below alpha, this
                // root move cannot even tie the current best, so remaining
                // replies cannot affect the selected-move set.
                int beta = std::numeric_limits<int>::max();
                const auto replies = position.legal_moves();
                if (replies.empty()) throw std::logic_error("ongoing position has no legal reply");
                stats_.full_nodes += replies.size();

                for (const auto& reply : replies) {
                    if (!position.play(reply, error)) throw std::logic_error(error);
                    Undo reply_undo{position};
                    ++stats_.nodes;
                    const auto reply_status = position.status();
                    const int reply_score = reply_status.result == rules::Result::Ongoing
                        ? material_for(position.snapshot(), root)
                        : terminal_score(reply_status.result, root);
                    beta = std::min(beta, reply_score);

                    // Strict inequality deliberately preserves root ties so
                    // the same RandomSeed chooses the same move as Minimax2.
                    if (beta < alpha) {
                        ++stats_.cutoffs;
                        break;
                    }
                }
                score = beta;
            }

            if (score > alpha) {
                alpha = score;
                tied.clear();
            }
            if (score == alpha) tied.push_back(move);
        }
        return random_move(tied);
    }

    static int terminal_score(rules::Result result, rules::Color root) {
        if (result == rules::Result::Draw || result == rules::Result::Ongoing) return 0;
        const bool black_wins = result == rules::Result::BlackWin;
        const bool root_wins = (root == rules::Color::Black) == black_wins;
        return root_wins ? WinScore : -WinScore;
    }

private:
    struct Undo {
        rules::Position& position;
        ~Undo() { position.undo(); }
    };

    static int material_for(const rules::Snapshot& snapshot, rules::Color root) {
        const int sign = root == rules::Color::Black ? 1 : -1;
        return sign * material_black(snapshot);
    }

    std::string random_move(const std::vector<std::string>& moves) {
        return moves[std::uniform_int_distribution<std::size_t>(0, moves.size() - 1)(rng_)];
    }

    std::mt19937 rng_;
    Stats stats_{};
};
} // namespace shogi::strategy
