#pragma once

#include "strategy/alphabeta3.h"
#include "strategy/evaluation.h"
#include "strategy/move_order.h"
#include "strategy/transposition_table.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <iterator>
#include <limits>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

namespace shogi::strategy {

// Fixed 3-ply alpha-beta + move ordering + per-search transposition table.
template<class Evaluator = MaterialEvaluator>
class BasicAlphaBeta3TT {
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
        std::uint64_t tt_probes = 0;
        std::uint64_t tt_hits = 0;
        std::uint64_t tt_exact_hits = 0;
        std::uint64_t tt_bound_cutoffs = 0;
        std::uint64_t tt_store_calls = 0;
        std::uint64_t tt_replacements = 0;
        std::uint64_t tt_move_first = 0;
        std::uint64_t tt_disabled_repetition = 0;

        std::array<std::uint64_t, 4> nodes_by_ply{};
    };

    explicit BasicAlphaBeta3TT(unsigned seed = 5489u, Evaluator evaluator = Evaluator{})
        : rng_(seed), evaluator_(evaluator) {}

    void set_evaluator(Evaluator evaluator) { evaluator_ = evaluator; }
    int last_score() const { return last_score_; }
    void set_seed(unsigned seed) { rng_.seed(seed); }
    const Stats& last_stats() const { return stats_; }
    static constexpr std::size_t tt_capacity() { return TranspositionTable::Capacity; }
    static constexpr std::size_t tt_approx_bytes() { return TranspositionTable::ApproxBytes; }

    std::string choose(rules::Position& position,
                       const std::vector<std::string>& allowed = {}) {
        stats_ = {};
        last_score_ = 0;
        tt_.new_search();
        tt_enabled_ = !position.has_repeated_history();
        if (!tt_enabled_) ++stats_.tt_disabled_repetition;

        auto original_moves = position.legal_moves();
        if (!allowed.empty()) {
            original_moves.erase(std::remove_if(original_moves.begin(), original_moves.end(), [&](const auto& move) {
                return std::find(allowed.begin(), allowed.end(), move) == allowed.end();
            }), original_moves.end());
        }
        if (original_moves.empty()) return "resign";
        if (position.status().result != rules::Result::Ongoing) return random_move(original_moves);

        const rules::Color root = position.snapshot().turn;
        const std::uint64_t root_key = position.hash_key();
        const auto moves = ordered(position, original_moves);
        int alpha = std::numeric_limits<int>::min();
        std::vector<std::string> tied;

        for (const auto& move : moves) {
            std::string error;
            if (!position.play(move, error)) throw std::logic_error(error);
            Undo undo{position};
            record_node(1);

            const int score = search_min(position, root, alpha);
            if (score > alpha) {
                alpha = score;
                tied.clear();
            }
            if (score == alpha) tied.push_back(move);
        }

        // Preserve seeded tie-breaking despite transposition-table ordering hints.
        std::stable_sort(tied.begin(), tied.end(), [&](const auto& a, const auto& b) {
            return original_index(original_moves, a) < original_index(original_moves, b);
        });
        last_score_ = alpha;
        const std::string selected = random_move(tied);
        return selected;
    }

    static int terminal_score(rules::Result result, rules::Color root) {
        return AlphaBeta3::terminal_score(result, root);
    }

private:
    using Bound = TranspositionTable::Bound;
    using Entry = TranspositionTable::Entry;

    struct Undo {
        rules::Position& position;
        ~Undo() { position.undo(); }
    };

    int search_min(rules::Position& position, rules::Color root, int alpha) {
        constexpr int depth = 2;
        const std::uint64_t key = tt_enabled_ ? position.hash_key() : 0;
        std::string tt_hint;
        if (const Entry* hit = probe(key, depth)) {
            tt_hint = TranspositionTable::best_move(*hit);
            if (hit->bound == Bound::Exact) {
                ++stats_.tt_exact_hits;
                return hit->value;
            }
            if (hit->bound == Bound::Upper && hit->value < alpha) {
                ++stats_.tt_bound_cutoffs;
                return hit->value;
            }
        }

        const auto status = position.status();
        if (status.result != rules::Result::Ongoing) {
            ++stats_.terminal_nodes;
            const int value = terminal_score(status.result, root);
            store(key, depth, value, Bound::Exact, {});
            return value;
        }

        int worst_reply = std::numeric_limits<int>::max();
        std::string worst_move;
        const auto replies = ordered(position, position.legal_moves(), tt_hint);
        if (replies.empty()) throw std::logic_error("ongoing position has no legal reply");

        for (const auto& reply : replies) {
            std::string error;
            if (!position.play(reply, error)) throw std::logic_error(error);
            Undo undo{position};
            record_node(2);

            const int reply_score = search_max(position, root, worst_reply);
            if (reply_score < worst_reply) {
                worst_reply = reply_score;
                worst_move = reply;
            }
            if (worst_reply < alpha) {
                ++stats_.cutoffs;
                ++stats_.min_cutoffs;
                store(key, depth, worst_reply, Bound::Upper, worst_move);
                return worst_reply;
            }
        }

        store(key, depth, worst_reply, Bound::Exact, worst_move);
        return worst_reply;
    }

    int search_max(rules::Position& position, rules::Color root, int beta) {
        constexpr int depth = 1;
        const std::uint64_t key = tt_enabled_ ? position.hash_key() : 0;
        std::string tt_hint;
        if (const Entry* hit = probe(key, depth)) {
            tt_hint = TranspositionTable::best_move(*hit);
            if (hit->bound == Bound::Exact) {
                ++stats_.tt_exact_hits;
                return hit->value;
            }
            if (hit->bound == Bound::Lower
                && beta != std::numeric_limits<int>::max()
                && hit->value >= beta) {
                ++stats_.tt_bound_cutoffs;
                return hit->value;
            }
        }

        const auto status = position.status();
        if (status.result != rules::Result::Ongoing) {
            ++stats_.terminal_nodes;
            const int value = terminal_score(status.result, root);
            store(key, depth, value, Bound::Exact, {});
            return value;
        }

        int best = std::numeric_limits<int>::min();
        std::string best_move;
        const auto continuations = ordered(position, position.legal_moves(), tt_hint);
        if (continuations.empty()) throw std::logic_error("ongoing position has no legal continuation");

        for (const auto& continuation : continuations) {
            std::string error;
            if (!position.play(continuation, error)) throw std::logic_error(error);
            Undo undo{position};
            record_node(3);

            const int score = search_leaf(position, root);
            if (score > best) {
                best = score;
                best_move = continuation;
            }
            if (beta != std::numeric_limits<int>::max() && best >= beta) {
                ++stats_.cutoffs;
                ++stats_.max_cutoffs;
                store(key, depth, best, Bound::Lower, best_move);
                return best;
            }
        }

        store(key, depth, best, Bound::Exact, best_move);
        return best;
    }

    int search_leaf(rules::Position& position, rules::Color root) {
        constexpr int depth = 0;
        const std::uint64_t key = tt_enabled_ ? position.hash_key() : 0;
        if (const Entry* hit = probe(key, depth)) {
            if (hit->bound == Bound::Exact) {
                ++stats_.tt_exact_hits;
                return hit->value;
            }
        }

        const auto status = position.status();
        int value;
        if (status.result != rules::Result::Ongoing) {
            ++stats_.terminal_nodes;
            value = terminal_score(status.result, root);
        } else {
            ++stats_.leaf_evals;
            value = evaluate_for(position.snapshot(), root);
        }
        store(key, depth, value, Bound::Exact, {});
        return value;
    }

    const Entry* probe(std::uint64_t key, int depth) {
        if (!tt_enabled_) return nullptr;
        ++stats_.tt_probes;
        const Entry* entry = tt_.probe(key, depth);
        if (entry) ++stats_.tt_hits;
        return entry;
    }

    void store(std::uint64_t key, int depth, int value, Bound bound,
               const std::string& best_move) {
        if (!tt_enabled_) return;
        ++stats_.tt_store_calls;
        if (tt_.store(key, depth, value, bound, best_move)) ++stats_.tt_replacements;
    }


    std::vector<std::string> ordered(const rules::Position& position,
                                     const std::vector<std::string>& moves,
                                     const std::string& tt_move = {}) {
        ++stats_.order_calls;
        stats_.ordered_moves += moves.size();
        auto result = MoveOrder::order(position.snapshot(), moves);

        auto promote_hint = [&](const std::string& hint) {
            if (hint.empty()) return;
            const auto it = std::find(result.begin(), result.end(), hint);
            if (it == result.end()) return;
            std::rotate(result.begin(), it, std::next(it));
            ++stats_.tt_move_first;
        };
        promote_hint(tt_move);
        return result;
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

    int evaluate_for(const rules::Snapshot& snapshot, rules::Color root) const {
        const int sign = root == rules::Color::Black ? 1 : -1;
        return sign * evaluator_(snapshot);
    }

    std::string random_move(const std::vector<std::string>& moves) {
        return moves[std::uniform_int_distribution<std::size_t>(0, moves.size() - 1)(rng_)];
    }

    std::mt19937 rng_;
    Evaluator evaluator_;
    int last_score_ = 0;
    Stats stats_{};
    TranspositionTable tt_;
    bool tt_enabled_ = true;
};

using AlphaBeta3TT = BasicAlphaBeta3TT<MaterialEvaluator>;
using FeatureAlphaBeta3TT = BasicAlphaBeta3TT<FeatureEvaluator>;

} // namespace shogi::strategy
