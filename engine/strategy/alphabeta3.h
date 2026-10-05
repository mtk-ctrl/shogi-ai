#pragma once
#include "strategy/material.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
#include <random>
#include <stdexcept>

namespace shogi::strategy {

// Phase 5: fixed three-ply alpha-beta search.
// Keep the material evaluation unchanged and deepen only the search:
// root move -> opponent reply -> root continuation.
class AlphaBeta3 {
public:
    static constexpr int WinScore = 100000000;

    struct Stats {
        std::uint64_t nodes = 0;          // positions actually visited after a move
        std::uint64_t cutoffs = 0;        // all alpha/beta cutoffs
        std::uint64_t min_cutoffs = 0;    // opponent-reply cutoffs
        std::uint64_t max_cutoffs = 0;    // root-continuation cutoffs
        std::uint64_t leaf_evals = 0;     // material evaluations at depth 3
        std::uint64_t terminal_nodes = 0; // terminal positions reached inside search
        std::array<std::uint64_t, 4> nodes_by_ply{};
    };

    explicit AlphaBeta3(unsigned seed = 5489u) : rng_(seed) {}
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

        // Preserve existing USI behavior after a GUI-adjudicated terminal state.
        if (position.status().result != rules::Result::Ongoing) return random_move(moves);

        const rules::Color root = position.snapshot().turn;
        int alpha = std::numeric_limits<int>::min();
        std::vector<std::string> tied;

        for (const auto& move : moves) {
            std::string error;
            if (!position.play(move, error)) throw std::logic_error(error);
            Undo root_undo{position};
            record_node(1);

            int score;
            const auto child_status = position.status();
            if (child_status.result != rules::Result::Ongoing) {
                ++stats_.terminal_nodes;
                score = terminal_score(child_status.result, root);
            } else {
                // Opponent minimizes the root side's score.
                int worst_reply = std::numeric_limits<int>::max();
                const auto replies = position.legal_moves();
                if (replies.empty()) throw std::logic_error("ongoing position has no legal reply");

                for (const auto& reply : replies) {
                    if (!position.play(reply, error)) throw std::logic_error(error);
                    Undo reply_undo{position};
                    record_node(2);

                    int reply_score;
                    const auto reply_status = position.status();
                    if (reply_status.result != rules::Result::Ongoing) {
                        ++stats_.terminal_nodes;
                        reply_score = terminal_score(reply_status.result, root);
                    } else {
                        // Root side maximizes on the third ply. Once this reply
                        // is already at least as good for root as an earlier
                        // opponent reply, the opponent would choose the earlier
                        // (lower) reply anyway, so the rest of this branch is irrelevant.
                        int best_continuation = std::numeric_limits<int>::min();
                        const auto continuations = position.legal_moves();
                        if (continuations.empty()) throw std::logic_error("ongoing position has no legal continuation");

                        for (const auto& continuation : continuations) {
                            if (!position.play(continuation, error)) throw std::logic_error(error);
                            Undo continuation_undo{position};
                            record_node(3);

                            const auto continuation_status = position.status();
                            int continuation_score;
                            if (continuation_status.result != rules::Result::Ongoing) {
                                ++stats_.terminal_nodes;
                                continuation_score = terminal_score(continuation_status.result, root);
                            } else {
                                ++stats_.leaf_evals;
                                continuation_score = material_for(position.snapshot(), root);
                            }
                            best_continuation = std::max(best_continuation, continuation_score);

                            if (worst_reply != std::numeric_limits<int>::max()
                                && best_continuation >= worst_reply) {
                                ++stats_.cutoffs;
                                ++stats_.max_cutoffs;
                                break;
                            }
                        }
                        reply_score = best_continuation;
                    }

                    worst_reply = std::min(worst_reply, reply_score);

                    // Strict inequality is important here. If worst_reply == alpha,
                    // this root move may still tie the current best. An unseen reply
                    // could make it worse, so equality cannot be cut if we want the
                    // exact same root tie set as exhaustive minimax.
                    if (worst_reply < alpha) {
                        ++stats_.cutoffs;
                        ++stats_.min_cutoffs;
                        break;
                    }
                }
                score = worst_reply;
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

    void record_node(unsigned ply) {
        ++stats_.nodes;
        if (ply < stats_.nodes_by_ply.size()) ++stats_.nodes_by_ply[ply];
    }

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
