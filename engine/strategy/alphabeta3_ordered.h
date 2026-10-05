#pragma once

#include "strategy/alphabeta3.h"
#include "strategy/move_order.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
#include <random>
#include <stdexcept>
#include <utility>
#include <vector>

namespace shogi::strategy {

// v0.0.7: same fixed 3-ply alpha-beta and material evaluation as v0.0.6,
// but tactical move ordering tries forcing/promising moves first so alpha-beta
// can cut more branches. Search order must not change the final minimax result.
class AlphaBeta3Ordered {
public:
    static constexpr int WinScore = AlphaBeta3::WinScore;

    struct Stats {
        std::uint64_t nodes = 0;
        std::uint64_t cutoffs = 0;
        std::uint64_t min_cutoffs = 0;
        std::uint64_t max_cutoffs = 0;
        std::uint64_t leaf_evals = 0;
        std::uint64_t terminal_nodes = 0;
        std::uint64_t order_calls = 0;
        std::uint64_t ordered_moves = 0;
        std::array<std::uint64_t, 4> nodes_by_ply{};
    };

    explicit AlphaBeta3Ordered(unsigned seed = 5489u) : rng_(seed) {}
    void set_seed(unsigned seed) { rng_.seed(seed); }
    const Stats& last_stats() const { return stats_; }

    std::string choose(rules::Position& position,
                       const std::vector<std::string>& allowed = {}) {
        stats_ = {};
        auto original_moves = position.legal_moves();
        if (!allowed.empty()) {
            original_moves.erase(std::remove_if(original_moves.begin(), original_moves.end(), [&](const auto& move) {
                return std::find(allowed.begin(), allowed.end(), move) == allowed.end();
            }), original_moves.end());
        }
        if (original_moves.empty()) return "resign";
        if (position.status().result != rules::Result::Ongoing) return random_move(original_moves);

        const rules::Color root = position.snapshot().turn;
        const auto moves = ordered(position, original_moves);
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
                int worst_reply = std::numeric_limits<int>::max();
                const auto replies = ordered(position, position.legal_moves());
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
                        int best_continuation = std::numeric_limits<int>::min();
                        const auto continuations = ordered(position, position.legal_moves());
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

        // Root search order is different from v0.0.6. Restore the original legal-move
        // order before seeded tie-breaking so identical minimax ties choose identically.
        std::stable_sort(tied.begin(), tied.end(), [&](const auto& a, const auto& b) {
            return original_index(original_moves, a) < original_index(original_moves, b);
        });
        return random_move(tied);
    }

    static int terminal_score(rules::Result result, rules::Color root) {
        return AlphaBeta3::terminal_score(result, root);
    }

private:
    struct Undo {
        rules::Position& position;
        ~Undo() { position.undo(); }
    };

    std::vector<std::string> ordered(const rules::Position& position,
                                     const std::vector<std::string>& moves) {
        ++stats_.order_calls;
        stats_.ordered_moves += moves.size();
        return MoveOrder::order(position.snapshot(), moves);
    }

    static std::size_t original_index(const std::vector<std::string>& moves,
                                      const std::string& move) {
        const auto it = std::find(moves.begin(), moves.end(), move);
        return it == moves.end() ? moves.size() : static_cast<std::size_t>(it - moves.begin());
    }

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
