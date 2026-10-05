#pragma once
#include "strategy/material.h"
#include <algorithm>
#include <limits>
#include <random>
#include <stdexcept>

namespace shogi::strategy {

// Phase 3: fixed two-ply minimax.
// Keep v0.0.3's material values unchanged; only add one opponent reply.
class Minimax2 {
public:
    static constexpr int WinScore = 100000000;

    explicit Minimax2(unsigned seed = 5489u) : rng_(seed) {}
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

        // Preserve the existing USI behavior after a GUI-adjudicated terminal state.
        if (position.status().result != rules::Result::Ongoing) return random_move(moves);

        const rules::Color root = position.snapshot().turn;
        int best = std::numeric_limits<int>::min();
        std::vector<std::string> tied;

        for (const auto& move : moves) {
            std::string error;
            if (!position.play(move, error)) throw std::logic_error(error);
            Undo root_undo{position};

            int score;
            const auto child_status = position.status();
            if (child_status.result != rules::Result::Ongoing) {
                score = terminal_score(child_status.result, root);
            } else {
                // The opponent chooses the reply that is worst for the root side.
                int worst_reply = std::numeric_limits<int>::max();
                const auto replies = position.legal_moves();
                for (const auto& reply : replies) {
                    if (!position.play(reply, error)) throw std::logic_error(error);
                    Undo reply_undo{position};
                    const auto reply_status = position.status();
                    const int reply_score = reply_status.result == rules::Result::Ongoing
                        ? material_for(position.snapshot(), root)
                        : terminal_score(reply_status.result, root);
                    worst_reply = std::min(worst_reply, reply_score);
                }
                if (replies.empty()) throw std::logic_error("ongoing position has no legal reply");
                score = worst_reply;
            }

            if (score > best) {
                best = score;
                tied.clear();
            }
            if (score == best) tied.push_back(move);
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
};
} // namespace shogi::strategy
