#pragma once

#include "strategy/alphabeta3_tt.h"
#include <array>
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <functional>

namespace shogi::strategy {

// All decisions, limits and search code here are ours. Upstream supplies rules.
struct SearchControl {
    std::atomic<bool> stop{false};
    std::atomic<std::int64_t> deadline_ns{0}; // zero means no time limit
    std::uint64_t node_limit = 0;
    static std::int64_t now_ns() {
        return std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count();
    }
};

struct SearchResult {
    std::string move = "resign";
    int score = 0; // from the root side's perspective
    int depth = 0; // zero: legal fallback; no complete iteration
    bool has_score = false;
    std::vector<std::string> pv;
};

template<class Evaluator = FeatureEvaluator>
class BasicIterativeSearch {
public:
    struct Stats : BasicAlphaBeta3TT<Evaluator>::Stats {
        static constexpr std::size_t CutoffRankBuckets = 8;
        std::uint64_t qnodes = 0, qcutoffs = 0, qlimit_leaves = 0;
        std::array<std::uint64_t, CutoffRankBuckets> cutoff_move_rank{};
        std::uint64_t cutoff_move_rank_overflow = 0;
        std::uint64_t cutoff_move_rank_sum = 0;
        std::uint64_t dynamic_order_calls = 0, dynamic_reorders = 0;
        std::uint64_t killer_cutoff_updates = 0, history_cutoff_updates = 0;
        int seldepth = 0;
    };
    static constexpr int MateScore = AlphaBeta3::WinScore;
    static constexpr int RuleWinScore = 90000000;
    static constexpr int MaxDepth = 64;
    static constexpr int QuiescenceDepth = 8;
    static constexpr int MaxPly = 128;
    static bool is_mate_score(int value) { return std::abs(value) >= MateScore - MaxPly; }

    explicit BasicIterativeSearch(unsigned seed = 5489u, Evaluator evaluator = Evaluator{})
        : rng_(seed), evaluator_(evaluator) {}
    void set_seed(unsigned seed) { rng_.seed(seed); }
    void set_evaluator(Evaluator e) { evaluator_ = e; experience_.clear(); }
    void set_experience_enabled(bool enabled) { experience_enabled_ = enabled; }
    void set_quiescence_enabled(bool enabled) {
        if (quiescence_enabled_ != enabled) experience_.clear();
        quiescence_enabled_ = enabled;
    }
    void set_dynamic_ordering_enabled(bool enabled) { dynamic_ordering_enabled_ = enabled; }
    void clear_experience() { experience_.clear(); }
    bool load_experience(const std::string& path, std::uint64_t signature) {
        return experience_.load(path, signature);
    }
    bool save_experience(const std::string& path, std::uint64_t signature) const {
        return experience_.save(path, signature);
    }
    std::size_t experience_size() const { return experience_.size(); }
    const Stats& last_stats() const { return stats_; }

    SearchResult choose(rules::Position& position, int max_depth, SearchControl& control,
                        const std::vector<std::string>& allowed = {},
                        const std::function<void(const SearchResult&)>& completed = {}) {
        stats_ = {};
        killers_ = {};
        history_scores_.fill(0);
        control_ = &control;
        tt_.new_search();
        experience_.new_search();
        experience_allowed_ = experience_enabled_ && !position.has_repeated_history();
        if (experience_enabled_ && !experience_allowed_) ++stats_.experience_disabled_repetition;
        iteration_hints_.clear();
        auto original = position.legal_moves();
        if (!allowed.empty())
            original.erase(std::remove_if(original.begin(), original.end(), [&](const auto& m) {
                return std::find(allowed.begin(), allowed.end(), m) == allowed.end();
            }), original.end());
        SearchResult result;
        root_ = position.snapshot().turn;
        const auto status = position.status();
        if (status.result != rules::Result::Ongoing) {
            result.score = terminal(position, status, 0);
            result.has_score = true;
            return result;
        }
        if (original.empty()) return result;
        // A deadline/stop may arrive before depth one finishes. Never return an
        // unsearched partial best score or an illegal move in that case.
        result.move = original.front();
        result.pv = {result.move};
        root_ = position.snapshot().turn;
        const auto root_history = position.history_key();
        const auto initial_rng = rng_;
        for (int depth = 1; depth <= std::clamp(max_depth, 1, MaxDepth); ++depth) {
            iteration_depth_ = depth;
            // With a unique incoming history, three additional plies cannot
            // produce a fourth occurrence (the same side-to-move needs at least
            // two plies between occurrences). Keep shallow board transpositions.
            // Deeper searches use the entire ordered history instead.
            // Quiescence can go beyond the shallow repetition-safe horizon.
            board_scores_ = !quiescence_enabled_ && depth <= 3 && !position.has_repeated_history();
            tt_.new_search();
            iteration_hints_.new_search();
            try {
                check_stop();
                auto moves = ordered(position, original, {}, depth >= 4 && result.depth ? result.move : "", 0);
                int best = -Infinity;
                std::vector<SearchResult> tied;
                for (const auto& move : moves) {
                    check_stop();
                    Node child;
                    {
                        make(position, move);
                        Undo undo{position};
                        visit(1);
                        child = search(position, depth - 1, 1, best, Infinity,
                                       next_history(root_history, position.hash_key()));
                    }
                    const int value = child.value;
                    if (value > best) { best = value; tied.clear(); }
                    if (value == best) {
                        SearchResult candidate;
                        candidate.move = move; candidate.score = value;
                        candidate.depth = depth; candidate.has_score = true;
                        candidate.pv = {move};
                        candidate.pv.insert(candidate.pv.end(), child.pv.begin(), child.pv.end());
                        tied.push_back(std::move(candidate));
                    }
                }
                std::sort(tied.begin(), tied.end(), [&](const auto& a, const auto& b) {
                    return std::find(original.begin(), original.end(), a.move)
                        < std::find(original.begin(), original.end(), b.move);
                });
                auto choice_rng = initial_rng;
                result = tied[std::uniform_int_distribution<std::size_t>(0, tied.size() - 1)(choice_rng)];
                rng_ = choice_rng; // consume one tie draw, not one per iteration
                store_experience(position, depth, result.move);
                if (completed) completed(result);
            } catch (const Interrupted&) {
                break; // RAII has already restored every speculative move
            }
        }
        return result;
    }

private:
    static constexpr int Infinity = MateScore + 1000;
    struct Interrupted {};
    struct Node { int value; std::vector<std::string> pv; };
    struct Undo { rules::Position& position; ~Undo() { position.undo(); } };
    using Bound = TranspositionTable::Bound;

    static std::uint64_t next_history(std::uint64_t h, std::uint64_t board) {
        return (h ^ board) * 1099511628211ULL;
    }
    void check_stop() const {
        const auto deadline = control_->deadline_ns.load(std::memory_order_relaxed);
        if (control_->stop.load(std::memory_order_relaxed)
            || (control_->node_limit && stats_.nodes >= control_->node_limit)
            || (deadline && SearchControl::now_ns() >= deadline)) throw Interrupted{};
    }
    void visit(int ply) {
        ++stats_.nodes;
        stats_.seldepth = std::max(stats_.seldepth, ply);
        if (ply < static_cast<int>(stats_.nodes_by_ply.size())) ++stats_.nodes_by_ply[ply];
    }
    void record_cutoff_rank(std::size_t zero_based_rank) {
        stats_.cutoff_move_rank_sum += zero_based_rank + 1;
        if (zero_based_rank < stats_.cutoff_move_rank.size())
            ++stats_.cutoff_move_rank[zero_based_rank];
        else
            ++stats_.cutoff_move_rank_overflow;
    }
    static constexpr int HistoryFromCount = 88; // 81 board squares + 7 drop piece kinds
    static constexpr int HistorySize = 2 * HistoryFromCount * 81 * 2;
    static int square_index(char file, char rank) {
        if (file < '1' || file > '9' || rank < 'a' || rank > 'i') return -1;
        return (file - '1') * 9 + (rank - 'a');
    }
    static int drop_source(char piece) {
        switch (piece) {
            case 'P': return 81; case 'L': return 82; case 'N': return 83;
            case 'S': return 84; case 'B': return 85; case 'R': return 86;
            case 'G': return 87; default: return -1;
        }
    }
    static int history_index(const std::string& move, rules::Color side) {
        if (move.size() < 4) return -1;
        const bool drop = move[1] == '*';
        const int from = drop ? drop_source(move[0]) : square_index(move[0], move[1]);
        const int to = drop ? square_index(move[2], move[3]) : square_index(move[2], move[3]);
        if (from < 0 || to < 0) return -1;
        const int promotion = !drop && move.size() >= 5 && move[4] == '+' ? 1 : 0;
        return (((static_cast<int>(side) * HistoryFromCount + from) * 81 + to) * 2 + promotion);
    }
    static bool quiet_move(const rules::Snapshot& snapshot, const std::string& move) {
        if (move.size() < 4) return false;
        if (move[1] == '*') return true;
        const int to = square_index(move[2], move[3]);
        if (to < 0) return false;
        const bool capture = snapshot.board[to].kind != 0;
        const bool promotion = move.size() >= 5 && move[4] == '+';
        return !capture && !promotion;
    }
    int dynamic_order_score(const rules::Snapshot& snapshot, const std::string& move, int ply) const {
        int score = 0;
        const int index = history_index(move, snapshot.turn);
        if (index >= 0) score += history_scores_[index];
        if (ply >= 0 && ply < MaxPly) {
            if (killers_[ply][0] == move) score += 2000000;
            else if (killers_[ply][1] == move) score += 1000000;
        }
        return score;
    }
    void note_cutoff(const rules::Position& p, const std::string& move, int depth, int ply) {
        if (!dynamic_ordering_enabled_) return;
        const auto snapshot = p.snapshot();
        if (!quiet_move(snapshot, move)) return;
        if (ply >= 0 && ply < MaxPly) {
            if (killers_[ply][0] != move) {
                killers_[ply][1] = killers_[ply][0];
                killers_[ply][0] = move;
            }
            ++stats_.killer_cutoff_updates;
        }
        const int index = history_index(move, snapshot.turn);
        if (index >= 0) {
            const int bonus = std::min(4096, std::max(1, depth * depth * 64));
            history_scores_[index] = std::min(1000000, history_scores_[index] + bonus);
            ++stats_.history_cutoff_updates;
        }
    }
    static void make(rules::Position& position, const std::string& move) {
        std::string error;
        if (!position.play(move, error)) throw std::logic_error(error);
    }
    int terminal(const rules::Position& p, const rules::Status& status, int ply) const {
        if (status.result == rules::Result::Draw) return 0;
        const bool black_wins = status.result == rules::Result::BlackWin;
        const bool win = black_wins == (root_ == rules::Color::Black);
        const int value = status.reason == "checkmate" ? MateScore - ply : RuleWinScore;
        return win ? value : -value;
    }
    static int to_table(int value, int ply) {
        return is_mate_score(value) ? value + (value > 0 ? ply : -ply) : value;
    }
    static int from_table(int value, int ply) {
        return is_mate_score(value) ? value - (value > 0 ? ply : -ply) : value;
    }
    Node search(rules::Position& p, int depth, int ply, int alpha, int beta,
                std::uint64_t history) {
        check_stop();
        // No score-TT entries for qsearch: its budget and check extensions are
        // different from full-width depth. Normal ancestors use history keys.
        if (depth == 0 && quiescence_enabled_)
            return quiescence(p, ply, 0, alpha, beta);
        const auto status = p.status();
        if (status.result != rules::Result::Ongoing) {
            ++stats_.terminal_nodes;
            return {terminal(p, status, ply), {}};
        }
        const int original_alpha = alpha, original_beta = beta;
        const auto score_key = board_scores_ ? p.hash_key() : history;
        std::string tt_move;
        ++stats_.tt_probes;
        if (const auto* entry = tt_.probe(score_key, depth)) {
            ++stats_.tt_hits;
            tt_move = TranspositionTable::best_move(*entry);
            const int value = from_table(entry->value, ply);
            // A PV may be shorter on a cache hit; it is still a legal prefix.
            if (entry->bound == Bound::Exact) {
                ++stats_.tt_exact_hits;
                return {value, tt_move.empty() ? std::vector<std::string>{} : std::vector<std::string>{tt_move}};
            }
            if ((entry->bound == Bound::Lower && value >= beta)
                || (entry->bound == Bound::Upper && value < alpha)) {
                ++stats_.tt_bound_cutoffs;
                return {value, {}};
            }
        }
        if (depth == 0) {
            ++stats_.leaf_evals;
            const int sign = root_ == rules::Color::Black ? 1 : -1;
            const int value = sign * evaluator_(p.snapshot());
            ++stats_.tt_store_calls;
            if (tt_.store(score_key, depth, value, Bound::Exact)) ++stats_.tt_replacements;
            return {value, {}};
        }
        auto moves = ordered(p, p.legal_moves(), tt_move, {}, ply);
        const bool maximizing = p.snapshot().turn == root_;
        Node best{maximizing ? -Infinity : Infinity, {}};
        for (std::size_t move_index = 0; move_index < moves.size(); ++move_index) {
            const auto& move = moves[move_index];
            check_stop();
            Node child;
            {
                make(p, move);
                Undo undo{p};
                visit(ply + 1);
                child = search(p, depth - 1, ply + 1, alpha, beta,
                               next_history(history, p.hash_key()));
            }
            const int value = child.value;
            if ((maximizing && value > best.value) || (!maximizing && value < best.value)) {
                best.value = value; best.pv = {move};
                best.pv.insert(best.pv.end(), child.pv.begin(), child.pv.end());
            }
            if (maximizing) alpha = std::max(alpha, value);
            else beta = std::min(beta, value);
            // Strict minimizing cutoff keeps the exact root tie set, as in
            // v0.0.13. Maximizing cutoffs can use equality against a prior reply.
            if ((maximizing && best.value >= original_beta)
                || (!maximizing && best.value < original_alpha)) {
                ++stats_.cutoffs;
                if (maximizing) ++stats_.max_cutoffs; else ++stats_.min_cutoffs;
                record_cutoff_rank(move_index);
                note_cutoff(p, move, depth, ply);
                break;
            }
        }
        const auto bound = best.value <= original_alpha ? Bound::Upper
            : best.value >= original_beta ? Bound::Lower : Bound::Exact;
        ++stats_.tt_store_calls;
        if (tt_.store(score_key, depth, to_table(best.value, ply), bound, best.pv.front()))
            ++stats_.tt_replacements;
        iteration_hints_.store(p.hash_key(), depth, best.pv.front());
        store_experience(p, depth, best.pv.front());
        return best;
    }
    Node quiescence(rules::Position& p, int ply, int qply, int alpha, int beta) {
        check_stop();
        ++stats_.qnodes; // The normal leaf was already counted by visit().
        const auto status = p.status();
        if (status.result != rules::Result::Ongoing) {
            ++stats_.terminal_nodes;
            return {terminal(p, status, ply), {}};
        }
        // Never publish a static score while in check at a safety ceiling.
        // Discard this incomplete iteration just as with stop/time exhaustion.
        if (ply >= MaxPly) throw Interrupted{};
        const bool checked = p.in_check();
        const auto snapshot = p.snapshot();
        const bool maximizing = snapshot.turn == root_;
        const int original_alpha = alpha, original_beta = beta;
        Node best{maximizing ? -Infinity : Infinity, {}};
        auto cutoff = [&] {
            return maximizing ? best.value >= original_beta : best.value < original_alpha;
        };
        if (!checked) {
            ++stats_.leaf_evals;
            best.value = (root_ == rules::Color::Black ? 1 : -1) * evaluator_(snapshot);
            if (qply >= QuiescenceDepth) {
                ++stats_.qlimit_leaves;
                return best;
            }
            // Stand pat is a bound, not a legal pass or a PV move.
            if (cutoff()) { ++stats_.qcutoffs; return best; }
            if (maximizing) alpha = std::max(alpha, best.value);
            else beta = std::min(beta, best.value);
        }
        auto moves = p.legal_moves();
        if (!checked) {
            moves.erase(std::remove_if(moves.begin(), moves.end(), [&](const auto& move) {
                const int dst = (move[2] - '1') * 9 + move[3] - 'a';
                const bool capture = snapshot.board[dst].kind != 0;
                const bool promotion = move.size() == 5 && move[4] == '+';
                return !capture && !promotion;
            }), moves.end());
        }
        // In check, include ALL legal evasions, even quiet moves and drops.
        // Non-check qsearch already contains only captures/promotions. Avoid the
        // full AttackMap-based ordering there and use a cheap MVV-LVA-like order.
        if (!moves.empty()) {
            if (checked) {
                moves = ordered(p, moves);
            } else {
                struct TacticalMove {
                    std::string move;
                    int score = 0;
                    std::size_t original_index = 0;
                };
                std::vector<TacticalMove> scored;
                scored.reserve(moves.size());
                for (std::size_t i = 0; i < moves.size(); ++i) {
                    const auto& move = moves[i];
                    const int dst = (move[2] - '1') * 9 + move[3] - 'a';
                    const int src = (move[0] - '1') * 9 + move[1] - 'a';
                    const auto& captured = snapshot.board[dst];
                    const auto& moving = snapshot.board[src];
                    int score = 0;
                    if (captured.kind != 0 && captured.kind != 8) {
                        score += 1000000
                              + 1000 * piece_value(captured.kind, captured.promoted)
                              - piece_value(moving.kind, moving.promoted);
                    }
                    if (move.size() == 5 && move[4] == '+') {
                        score += 100 * std::max(0,
                            piece_value(moving.kind, true)
                            - piece_value(moving.kind, moving.promoted));
                    }
                    scored.push_back({move, score, i});
                }
                std::stable_sort(scored.begin(), scored.end(), [](const auto& a, const auto& b) {
                    return a.score > b.score;
                });
                for (std::size_t i = 0; i < scored.size(); ++i)
                    moves[i] = std::move(scored[i].move);
            }
        }
        for (const auto& move : moves) {
            check_stop();
            Node child;
            {
                make(p, move);
                Undo undo{p};
                visit(ply + 1);
                child = quiescence(p, ply + 1, qply + 1, alpha, beta);
            }
            if ((maximizing && child.value > best.value) || (!maximizing && child.value < best.value)) {
                best.value = child.value;
                best.pv = {move};
                best.pv.insert(best.pv.end(), child.pv.begin(), child.pv.end());
            }
            if (maximizing) alpha = std::max(alpha, best.value);
            else beta = std::min(beta, best.value);
            if (cutoff()) { ++stats_.qcutoffs; break; }
        }
        return best;
    }
    std::vector<std::string> ordered(const rules::Position& p,
                                    const std::vector<std::string>& moves,
                                    const std::string& tt_move = {},
                                    const std::string& previous_root = {},
                                    int ply = -1) {
        ++stats_.order_calls;
        stats_.ordered_moves += moves.size();
        const auto snapshot = p.snapshot();
        auto scored = MoveOrder::order_scored(snapshot, moves);
        if (dynamic_ordering_enabled_ && ply >= 0) {
            auto first_quiet = std::find_if(scored.begin(), scored.end(), [](const auto& item) {
                return item.score == 0;
            });
            if (first_quiet != scored.end()) {
                ++stats_.dynamic_order_calls;
                const std::string old_first = first_quiet->move;
                std::stable_sort(first_quiet, scored.end(), [&](const auto& a, const auto& b) {
                    return dynamic_order_score(snapshot, a.move, ply)
                        > dynamic_order_score(snapshot, b.move, ply);
                });
                if (first_quiet->move != old_first) ++stats_.dynamic_reorders;
            }
        }
        std::vector<std::string> result;
        result.reserve(scored.size());
        for (const auto& item : scored) result.push_back(item.move);
        auto promote = [&](const std::string& hint) {
            auto it = std::find(result.begin(), result.end(), hint);
            if (it == result.end()) return false;
            std::rotate(result.begin(), it, std::next(it)); return true;
        };
        if (experience_allowed_) {
            ++stats_.experience_probes;
            if (const auto* e = experience_.probe(p.hash_key())) {
                ++stats_.experience_hits;
                if (promote(ExperienceCache::best_move(*e))) ++stats_.experience_move_first;
            }
        }
        // At introductory depths, horizon changes made previous-iteration
        // ordering worse on contact positions. Preserve the accepted ordering
        // through depth three; use iterative hints when going deeper.
        if (iteration_depth_ >= 4)
            if (const auto* e = iteration_hints_.probe(p.hash_key())) promote(ExperienceCache::best_move(*e));
        if (promote(tt_move)) ++stats_.tt_move_first;
        promote(previous_root);
        return result;
    }
    void store_experience(const rules::Position& p, int depth, const std::string& move) {
        if (!experience_allowed_) return;
        ++stats_.experience_stores;
        if (experience_.store(p.hash_key(), depth, move)) ++stats_.experience_replacements;
    }

    std::mt19937 rng_;
    Evaluator evaluator_;
    Stats stats_{};
    TranspositionTable tt_;
    ExperienceCache experience_, iteration_hints_;
    std::array<std::array<std::string, 2>, MaxPly> killers_{};
    std::array<int, HistorySize> history_scores_{};
    bool experience_enabled_ = false;
    bool quiescence_enabled_ = true;
    bool dynamic_ordering_enabled_ = true;
    bool experience_allowed_ = false;
    bool board_scores_ = false;
    rules::Color root_ = rules::Color::Black;
    int iteration_depth_ = 0;
    SearchControl* control_ = nullptr;
};
using IterativeSearch = BasicIterativeSearch<FeatureEvaluator>;
} // namespace shogi::strategy
