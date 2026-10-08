#pragma once

#include "strategy/alphabeta3_tt.h"
#include "strategy/position_knowledge.h"
#include <optional>
#include "strategy/move_hint_cache.h"
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <functional>

namespace shogi::strategy {

// All decisions, limits and search code here are ours. Upstream supplies rules.
enum class LongThinkReason : int {
    None = 0,
    InCheck,
    ScoreDrop150,
    IterationScoreChange150,
    IterationMoveChange,
    UnfinishedDepth2,
    BudgetDeadline,
};

inline const char* long_think_reason_name(LongThinkReason reason) {
    switch (reason) {
    case LongThinkReason::InCheck: return "in_check";
    case LongThinkReason::ScoreDrop150: return "score_drop_150";
    case LongThinkReason::IterationScoreChange150: return "iteration_score_change_150";
    case LongThinkReason::IterationMoveChange: return "iteration_move_change";
    case LongThinkReason::UnfinishedDepth2: return "unfinished_depth2";
    case LongThinkReason::BudgetDeadline: return "budget_deadline";
    default: return "none";
    }
}

struct SearchControl {
    std::atomic<bool> stop{false};
    std::atomic<std::int64_t> deadline_ns{0}; // current soft/hard deadline; zero means no time limit
    std::int64_t hard_deadline_ns = 0;        // optional continuation ceiling
    std::uint64_t node_limit = 0;
    bool adaptive_long_think = false;
    bool force_long_think = false;
    bool has_previous_score = false;
    int previous_score = 0;
    std::atomic<int> long_think_reason{static_cast<int>(LongThinkReason::None)};
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
        std::uint64_t qnodes = 0, qcutoffs = 0, qlimit_leaves = 0;
        std::uint64_t knowledge_probes = 0, knowledge_hits = 0, knowledge_promotions = 0;
        std::uint64_t knowledge_research_ms = 0, knowledge_research_nodes = 0, knowledge_stable_ms = 0;
        int knowledge_research_depth = 0, knowledge_score_value = 0;
        std::string knowledge_score_kind;
        std::uint64_t knowledge_disabled_repetition = 0;
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
    void set_evaluator(Evaluator e) { evaluator_ = e; }
    struct DirectResearch {
        std::string move, research_id;
        std::size_t ply_index = 0, pv_length = 0;
    };
    void clear_research_continuation() { research_continuation_ = {}; }
    void set_position_knowledge_enabled(bool enabled) {
        position_knowledge_enabled_ = enabled;
        if (!enabled) clear_research_continuation();
    }
    bool load_position_knowledge(const std::string& path) {
        clear_research_continuation();
        return position_knowledge_.load(path);
    }
    void clear_position_knowledge() {
        clear_research_continuation();
        position_knowledge_.clear();
    }
    // An adopted long-search move overrides short search; continuation is
    // permitted only after the exact expected opponent reply AND history.
    std::optional<DirectResearch> select_research_move(
        const rules::Position& position, const std::vector<std::string>& restricted = {}) {
        if (!position_knowledge_enabled_ || position.has_repeated_history()) {
            clear_research_continuation();
            return std::nullopt;
        }
        std::vector<std::string> pv;
        std::string id;
        std::size_t index = 0;
        if (!research_continuation_.pv.empty()
            && PositionKnowledge::canonical_key(position) == research_continuation_.expected_key
            && position.history_key() == research_continuation_.expected_history
            && research_continuation_.next < research_continuation_.pv.size()) {
            pv = research_continuation_.pv;
            id = research_continuation_.research_id;
            index = research_continuation_.next;
        } else {
            clear_research_continuation();
            const auto* entry = position_knowledge_.probe(position);
            if (!entry || entry->mode != "research_decision"
                || entry->research_pv.empty()
                || entry->initial_history_key != position.history_key()) return std::nullopt;
            pv = entry->research_pv;
            id = entry->research_id;
        }
        const auto& move = pv[index];
        if (!restricted.empty()
            && std::find(restricted.begin(), restricted.end(), move) == restricted.end()) {
            clear_research_continuation();
            return std::nullopt;
        }
        const auto legal = position.legal_moves();
        if (std::find(legal.begin(), legal.end(), move) == legal.end()) {
            clear_research_continuation();
            return std::nullopt;
        }
        auto next = position.clone();
        std::string error;
        if (!next.play_generated_legal(move, error)) {
            clear_research_continuation();
            return std::nullopt;
        }
        ResearchContinuation future;
        // Index 1 is an opponent reply, index 2 our next studied move.
        if (index + 2 < pv.size() && next.play(pv[index + 1], error)
            && !next.has_repeated_history()) {
            future.pv = pv;
            future.research_id = id;
            future.next = index + 2;
            future.expected_key = PositionKnowledge::canonical_key(next);
            future.expected_history = next.history_key();
        }
        research_continuation_ = std::move(future);
        return DirectResearch{move, id, index, pv.size()};
    }
    std::size_t position_knowledge_size() const { return position_knowledge_.size(); }
    void set_quiescence_enabled(bool enabled) { quiescence_enabled_ = enabled; }
    const Stats& last_stats() const { return stats_; }

    SearchResult choose(rules::Position& position, int max_depth, SearchControl& control,
                        const std::vector<std::string>& allowed = {},
                        const std::function<void(const SearchResult&)>& completed = {}) {
        stats_ = {};
        control_ = &control;
        tt_.new_search();
        iteration_hints_.clear();
        root_in_check_ = position.in_check();
        has_previous_completed_ = false;
        has_last_completed_ = false;
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
        std::string root_knowledge_move;
        if (position_knowledge_enabled_) {
            if (position.has_repeated_history()) {
                ++stats_.knowledge_disabled_repetition;
            } else {
                ++stats_.knowledge_probes;
                if (const auto* hint = position_knowledge_.probe(position)) {
                    if (std::find(original.begin(), original.end(), hint->move) != original.end()) {
                        root_knowledge_move = hint->move;
                        ++stats_.knowledge_hits;
                        stats_.knowledge_research_ms = hint->research_ms;
                        stats_.knowledge_research_depth = hint->research_depth;
                        stats_.knowledge_research_nodes = hint->research_nodes;
                        stats_.knowledge_score_kind = hint->score_kind;
                        stats_.knowledge_score_value = hint->score_value;
                        stats_.knowledge_stable_ms = hint->stable_ms;
                    }
                }
            }
        }
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
                auto moves = ordered(position, original, {}, depth >= 4 && result.depth ? result.move : "",
                                     root_knowledge_move);
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
                previous_completed_ = last_completed_;
                has_previous_completed_ = has_last_completed_;
                last_completed_ = result;
                has_last_completed_ = true;
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
    bool maybe_extend_deadline(std::int64_t now) const {
        if (!control_->adaptive_long_think
            || control_->long_think_reason.load(std::memory_order_relaxed)
                != static_cast<int>(LongThinkReason::None)
            || control_->hard_deadline_ns <= now) return false;

        // Prefer instability; spend a remaining coupon only when the per-game
        // budget needs this turn to finish near the target move number.
        // Continue the current search instead of restarting from the root.
        if (has_last_completed_ && last_completed_.has_score
            && is_mate_score(last_completed_.score)) return false;

        LongThinkReason reason = LongThinkReason::None;
        if (root_in_check_) {
            reason = LongThinkReason::InCheck;
        } else if (control_->has_previous_score && has_last_completed_
                   && last_completed_.has_score
                   && control_->previous_score - last_completed_.score >= 150) {
            reason = LongThinkReason::ScoreDrop150;
        } else if (has_previous_completed_ && has_last_completed_
                   && previous_completed_.has_score && last_completed_.has_score
                   && !is_mate_score(previous_completed_.score)
                   && !is_mate_score(last_completed_.score)
                   && std::abs(previous_completed_.score - last_completed_.score) >= 150) {
            reason = LongThinkReason::IterationScoreChange150;
        } else if (has_previous_completed_ && has_last_completed_
                   && previous_completed_.move != last_completed_.move) {
            reason = LongThinkReason::IterationMoveChange;
        } else if (!has_last_completed_ || last_completed_.depth < 2) {
            reason = LongThinkReason::UnfinishedDepth2;
        } else if (control_->force_long_think) {
            reason = LongThinkReason::BudgetDeadline;
        }
        if (reason == LongThinkReason::None) return false;

        control_->long_think_reason.store(static_cast<int>(reason), std::memory_order_relaxed);
        control_->deadline_ns.store(control_->hard_deadline_ns, std::memory_order_relaxed);
        return true;
    }
    void check_stop() const {
        if (control_->stop.load(std::memory_order_relaxed)
            || (control_->node_limit && stats_.nodes >= control_->node_limit))
            throw Interrupted{};
        const auto deadline = control_->deadline_ns.load(std::memory_order_relaxed);
        if (deadline) {
            const auto now = SearchControl::now_ns();
            if (now >= deadline && !maybe_extend_deadline(now)) throw Interrupted{};
        }
    }
    void visit(int ply) {
        ++stats_.nodes;
        stats_.seldepth = std::max(stats_.seldepth, ply);
        if (ply < static_cast<int>(stats_.nodes_by_ply.size())) ++stats_.nodes_by_ply[ply];
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
        auto moves = ordered(p, p.legal_moves(), tt_move);
        const bool maximizing = p.snapshot().turn == root_;
        Node best{maximizing ? -Infinity : Infinity, {}};
        for (const auto& move : moves) {
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
                break;
            }
        }
        const auto bound = best.value <= original_alpha ? Bound::Upper
            : best.value >= original_beta ? Bound::Lower : Bound::Exact;
        ++stats_.tt_store_calls;
        if (tt_.store(score_key, depth, to_table(best.value, ply), bound, best.pv.front()))
            ++stats_.tt_replacements;
        iteration_hints_.store(p.hash_key(), depth, best.pv.front());
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
                                    const std::string& knowledge_move = {}) {
        ++stats_.order_calls;
        stats_.ordered_moves += moves.size();
        auto result = MoveOrder::order(p.snapshot(), moves);
        auto promote = [&](const std::string& hint) {
            auto it = std::find(result.begin(), result.end(), hint);
            if (it == result.end()) return false;
            std::rotate(result.begin(), it, std::next(it)); return true;
        };
        if (promote(knowledge_move)) ++stats_.knowledge_promotions;
        // At introductory depths, horizon changes made previous-iteration
        // ordering worse on contact positions. Preserve the accepted ordering
        // through depth three; use iterative hints when going deeper.
        if (iteration_depth_ >= 4)
            if (const auto* e = iteration_hints_.probe(p.hash_key())) promote(MoveHintCache::best_move(*e));
        if (promote(tt_move)) ++stats_.tt_move_first;
        promote(previous_root);
        return result;
    }

    std::mt19937 rng_;
    Evaluator evaluator_;
    Stats stats_{};
    TranspositionTable tt_;
    MoveHintCache iteration_hints_;
    PositionKnowledge position_knowledge_;
    struct ResearchContinuation {
        std::vector<std::string> pv;
        std::string research_id, expected_key;
        std::uint64_t expected_history = 0;
        std::size_t next = 0;
    };
    ResearchContinuation research_continuation_{};
    bool position_knowledge_enabled_ = true;
    bool quiescence_enabled_ = true;
    bool board_scores_ = false;
    rules::Color root_ = rules::Color::Black;
    int iteration_depth_ = 0;
    bool root_in_check_ = false;
    bool has_previous_completed_ = false, has_last_completed_ = false;
    SearchResult previous_completed_{}, last_completed_{};
    SearchControl* control_ = nullptr;
};
using IterativeSearch = BasicIterativeSearch<FeatureEvaluator>;
} // namespace shogi::strategy
