#pragma once

#include "strategy/alphabeta3_tt.h"
#include "strategy/search_research.h"
#include "strategy/position_knowledge.h"
#include <optional>
#include "strategy/move_hint_cache.h"
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <functional>
#include <cstdint>
#include <vector>
#include <type_traits>
#include <unordered_map>
#include <cstring>

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
        std::uint64_t generated_plays = 0, legal_batches = 0, order_reuse_hits = 0;
        std::uint64_t qtt_probes = 0, qtt_hits = 0, qtt_cutoffs = 0;
        std::uint64_t ordering_rule_checks = 0, eval_cache_hits = 0, lazy_snapshots = 0;
        std::uint64_t selective_usi_skipped = 0;
        std::uint64_t legal_cache_hits = 0, legal_cache_misses = 0;
        std::uint64_t legal_cache_replacements = 0;
        int seldepth = 0;
    };
    static constexpr int MateScore = AlphaBeta3::WinScore;
    static constexpr int RuleWinScore = 90000000;
    static constexpr int MaxDepth = 64;
    static constexpr int QuiescenceDepth = 8;
    static constexpr int MaxPly = 128;
    static bool is_mate_score(int value) { return std::abs(value) >= MateScore - MaxPly; }

    explicit BasicIterativeSearch(unsigned seed = 5489u, Evaluator evaluator = Evaluator{})
        : rng_(seed), evaluator_(evaluator) { set_reuse_mask(reuse_mask_); }
    void set_seed(unsigned seed) { rng_.seed(seed); }
    void set_evaluator(Evaluator e) { evaluator_ = e; set_reuse_mask(reuse_mask_); }
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
    // Adopted research is keyed by board/hands/side, independent of arrival route.
    // Avoid repetition-sensitive history; continuation requires the precise
    // reply and ACTUAL history after the researched move.
    std::optional<DirectResearch> select_research_move(
        const rules::Position& position, const std::vector<std::string>& restricted = {}) {
        if (!position_knowledge_enabled_ || position.has_repeated_history()) {
            clear_research_continuation();
            return std::nullopt;
        }
        std::vector<std::string> pv;
        std::string id;
        std::size_t index = 0;
        // A full study of THIS exact position outranks a continuation copied
        // from an earlier study, which may propose a different move here.
        // Original arrival history remains provenance, not an applicability gate.
        const auto* entry = position_knowledge_.probe(position);
        if (entry && entry->mode == "research_decision" && !entry->research_pv.empty()) {
            clear_research_continuation();
            pv = entry->research_pv;
            id = entry->research_id;
        } else if (!research_continuation_.pv.empty()
                   && PositionKnowledge::canonical_key(position) == research_continuation_.expected_key
                   && position.history_key() == research_continuation_.expected_history
                   && research_continuation_.next < research_continuation_.pv.size()) {
            pv = research_continuation_.pv;
            id = research_continuation_.research_id;
            index = research_continuation_.next;
        } else {
            clear_research_continuation();
            return std::nullopt;
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
    void set_research_mask(unsigned mask) { research_mask_ = mask & 31; }
    unsigned research_mask() const { return research_mask_; }
    void set_efficiency_mask(unsigned mask) { efficiency_mask_ = mask & 15; }
    unsigned efficiency_mask() const { return efficiency_mask_; }
    void set_next_mask(unsigned mask) { next_mask_ = mask & 15; }
    void set_reuse_mask(unsigned mask) {
        reuse_mask_ = mask & 15;
        if constexpr (std::is_same_v<Evaluator,FeatureEvaluator>) evaluator_.set_reuse_mask(reuse_mask_);
    }
    unsigned reuse_mask() const { return reuse_mask_; }

    SearchResult choose(rules::Position& position, int max_depth, SearchControl& control,
                        const std::vector<std::string>& allowed = {},
                        const std::function<void(const SearchResult&)>& completed = {}) {
        stats_ = {};
        control_ = &control;
        tt_.new_search();
        qtt_.new_search();
        for (auto& batch : legal_batches_) batch.valid = false;
        pv_lengths_.fill(0);
        iteration_hints_.clear();
        // The cache contains static evaluations only. A new go must not reuse
        // evaluations from a previous position, weight set or search session.
        ++eval_epoch_;
        if (!eval_epoch_) {
            for (auto& cell : eval_cache_) cell.epoch = 0;
            for (auto& cell : order_cache_) cell.epoch = 0;
            for (auto& cell : legal_cache_) cell.epoch = 0;
            eval_epoch_ = 1;
        }
        root_in_check_ = position.in_check();
        has_previous_completed_ = false;
        has_last_completed_ = false;
        auto original = legal(position, 0);
        if (!allowed.empty())
            original.erase(std::remove_if(original.begin(), original.end(), [&](const auto& m) {
                return std::find(allowed.begin(), allowed.end(), m) == allowed.end();
            }), original.end());
        SearchResult result;
        root_ = (efficiency_mask_ & LazySnapshot) ? position.turn() : position.snapshot().turn;
        const auto status = node_status(position, 0);
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
        root_ = (efficiency_mask_ & LazySnapshot) ? position.turn() : position.snapshot().turn;
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
            if (!(next_mask_ & 8)) tt_.new_search();
            iteration_hints_.new_search();
            try {
                check_stop();
                auto moves = ordered(position, original, {}, depth >= ((research_mask_ & EarlyHints) ? 2 : 4) && result.depth ? result.move : "",
                                     root_knowledge_move);
                int best = -Infinity;
                std::vector<SearchResult> tied;
                for (const auto& move : moves) {
                    check_stop();
                    Node child;
                    {
                        make(position, move, 0);
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
                        const auto tail = pv_materialize(1);
                        candidate.pv.insert(candidate.pv.end(), tail.begin(), tail.end());
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
    struct Node { int value; };
    // Per-ply principal variation scratch: eliminate vector allocation at each node.
    std::array<std::array<std::array<char, 6>, MaxPly + 1>, MaxPly + 1> pv_rows_{};
    std::array<int, MaxPly + 1> pv_lengths_{};
    void pv_push(int ply, const std::string& move) {
        pv_rows_[ply][0].fill(0);
        std::memcpy(pv_rows_[ply][0].data(), move.data(), std::min<std::size_t>(5, move.size()));
        const int append = ply < MaxPly ? std::min(pv_lengths_[ply + 1], MaxPly - ply) : 0;
        for (int i = 0; i < append; ++i) pv_rows_[ply][i + 1] = pv_rows_[ply + 1][i];
        pv_lengths_[ply] = append + 1;
    }
    std::string pv_first(int ply) const {
        return pv_lengths_[ply] ? std::string(pv_rows_[ply][0].data()) : std::string{};
    }
    std::vector<std::string> pv_materialize(int ply) const {
        std::vector<std::string> out;
        out.reserve(pv_lengths_[ply]);
        for (int i = 0; i < pv_lengths_[ply]; ++i) out.emplace_back(pv_rows_[ply][i].data());
        return out;
    }
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
    struct LegalBatch {
        bool valid = false;
        std::uint64_t key = 0;
        std::vector<rules::GeneratedMove> tokens;
        std::vector<std::string> strings;
        bool tactical_ready = false;
        std::vector<std::string> tactical;
        std::vector<std::size_t> tactical_indexes;
        std::unordered_map<std::string, std::size_t> token_indexes;
    };
    std::array<LegalBatch, MaxPly + 1> legal_batches_{};
    struct LegalCell {
        std::uint64_t key = 0;
        std::uint32_t epoch = 0;
        std::vector<rules::GeneratedMove> tokens;
    };
    std::vector<LegalCell> legal_cache_{2048};
    const LegalBatch& batch(const rules::Position& p, int ply) {
        auto& b = legal_batches_.at(ply);
        if (!b.valid || b.key != p.hash_key()) {
            b.valid = false;
            b.key = p.hash_key();
            if (reuse_mask_ & LegalTokenCache) {
                auto& cell = legal_cache_[b.key % legal_cache_.size()];
                if (cell.epoch == eval_epoch_ && cell.key == b.key) {
                    // Own the batch: a descendant may replace this cache slot.
                    b.tokens = cell.tokens;
                    ++stats_.legal_cache_hits;
                } else {
                    if (cell.epoch == eval_epoch_) ++stats_.legal_cache_replacements;
                    b.tokens = p.legal_generated_moves();
                    cell.key = b.key;
                    cell.epoch = eval_epoch_;
                    cell.tokens = b.tokens;
                    ++stats_.legal_cache_misses;
                }
            } else b.tokens = p.legal_generated_moves();
            b.strings.clear();
            b.tactical_ready = false;
            b.tactical.clear();
            b.tactical_indexes.clear();
            b.token_indexes.clear();
            b.valid = true;
            ++stats_.legal_batches;
        }
        return b;
    }
    std::vector<std::string> legal(const rules::Position& p, int ply) {
        if (research_mask_ & (GeneratedPlay | SharedLegal)) {
            batch(p, ply);
            auto& b = legal_batches_.at(ply);
            // Terminal and stand-pat cutoffs need only the tokens' count.
            // Convert to USI only when this node actually explores its moves.
            if (b.strings.empty() && !b.tokens.empty()) {
                b.strings.reserve(b.tokens.size());
                for (std::size_t i = 0; i < b.tokens.size(); ++i) {
                    b.strings.push_back(p.generated_move_usi(b.tokens[i]));
                    if (next_mask_ & 1) b.token_indexes.emplace(b.strings.back(), i);
                }
            }
            return b.strings;
        }
        return p.legal_moves();
    }
    std::vector<std::string> legal_tactical(const rules::Position& p, int ply) {
        batch(p, ply);
        auto& b = legal_batches_.at(ply);
        if (!b.tactical_ready) {
            for (std::size_t i = 0; i < b.tokens.size(); ++i) {
                if (!p.generated_move_is_capture_or_promotion(b.tokens[i])) continue;
                b.tactical.push_back(b.strings.empty() ? p.generated_move_usi(b.tokens[i]) : b.strings[i]);
                b.tactical_indexes.push_back(i);
                if (next_mask_ & 1) b.token_indexes.emplace(b.tactical.back(), i);
            }
            if (b.strings.empty()) stats_.selective_usi_skipped += b.tokens.size() - b.tactical.size();
            b.tactical_ready = true;
        }
        return b.tactical;
    }
    rules::Status node_status(const rules::Position& p, int ply) {
        if (!(research_mask_ & SharedLegal)) return p.status();
        // Repetition remains history-sensitive and is never cached.
        auto status = p.repetition_status();
        if (status.result != rules::Result::Ongoing) return status;
        if (batch(p, ply).tokens.empty())
            return {p.turn() == rules::Color::Black ? rules::Result::WhiteWin : rules::Result::BlackWin,
                    p.in_check() ? "checkmate" : "no legal moves"};
        return {};
    }
    void make(rules::Position& position, const std::string& move, int ply) {
        std::string error;
        if (research_mask_ & GeneratedPlay) {
            const auto& b = batch(position, ply);
            std::size_t index;
            if (next_mask_ & 1) {
                const auto it = b.token_indexes.find(move);
                if (it == b.token_indexes.end()) throw std::logic_error("move absent from indexed legal batch");
                index = it->second;
            } else if (!b.strings.empty()) {
                const auto it = std::find(b.strings.begin(), b.strings.end(), move);
                if (it == b.strings.end()) throw std::logic_error("move absent from current legal batch");
                index = it - b.strings.begin();
            } else {
                const auto it = std::find(b.tactical.begin(), b.tactical.end(), move);
                if (it == b.tactical.end()) throw std::logic_error("move absent from current tactical batch");
                index = b.tactical_indexes[it - b.tactical.begin()];
            }
            if (!position.play_generated_move(b.tokens[index], error))
                throw std::logic_error(error);
            ++stats_.generated_plays;
        } else if (!position.play_generated_legal(move, error)) throw std::logic_error(error);
    }
    // Exact board/hands/side identity; no repetition-sensitive search scores
    // are cached here. Terminal and repetition results remain uncached.
    struct EvalCell { std::uint64_t key = 0; int value = 0; std::uint32_t epoch = 0; };
    std::vector<EvalCell> eval_cache_ = std::vector<EvalCell>(1u << 15);
    std::uint32_t eval_epoch_ = 1;
    template<class SnapshotGetter>
    int eval_cached(const rules::Position& p, SnapshotGetter get_snapshot) {
        const auto key = p.hash_key();
        auto& cell = eval_cache_[key & (eval_cache_.size() - 1)];
        if (cell.epoch == eval_epoch_ && cell.key == key) {
            ++stats_.eval_cache_hits;
            return cell.value;
        }
        const int value = evaluator_(get_snapshot());
        cell = {key, value, eval_epoch_};
        return value;
    }
    int eval_node(const rules::Position& p, const rules::Snapshot& snap) {
        return eval_cached(p, [&]() -> const rules::Snapshot& { return snap; });
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
        pv_lengths_[ply] = 0;
        // No score-TT entries for qsearch: its budget and check extensions are
        // different from full-width depth. Normal ancestors use history keys.
        if (depth == 0 && quiescence_enabled_)
            return quiescence(p, ply, 0, alpha, beta);
        const auto status = node_status(p, ply);
        if (status.result != rules::Result::Ongoing) {
            ++stats_.terminal_nodes;
            return {terminal(p, status, ply)};
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
                if (!tt_move.empty()) {
                    if (ply < MaxPly) pv_lengths_[ply + 1] = 0;
                    pv_push(ply, tt_move);
                }
                return {value};
            }
            if ((entry->bound == Bound::Lower && value >= beta)
                || (entry->bound == Bound::Upper && value < alpha)) {
                ++stats_.tt_bound_cutoffs;
                return {value};
            }
        }
        if (depth == 0) {
            ++stats_.leaf_evals;
            const int sign = root_ == rules::Color::Black ? 1 : -1;
            const int value = sign * ((efficiency_mask_ & LazySnapshot)
                ? eval_cached(p, [&] { ++stats_.lazy_snapshots; return p.snapshot(); })
                : eval_node(p, p.snapshot()));
            ++stats_.tt_store_calls;
            if (tt_.store(score_key, depth, value, Bound::Exact)) ++stats_.tt_replacements;
            return {value};
        }
        auto moves = ordered(p, legal(p, ply), tt_move, {}, {}, ply);
        const bool maximizing = ((efficiency_mask_ & LazySnapshot) ? p.turn() : p.snapshot().turn) == root_;
        Node best{maximizing ? -Infinity : Infinity};
        for (const auto& move : moves) {
            check_stop();
            Node child;
            {
                make(p, move, ply);
                Undo undo{p};
                visit(ply + 1);
                child = search(p, depth - 1, ply + 1, alpha, beta,
                               next_history(history, p.hash_key()));
            }
            const int value = child.value;
            if ((maximizing && value > best.value) || (!maximizing && value < best.value)) {
                best.value = value;
                pv_push(ply, move);
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
        if (tt_.store(score_key, depth, to_table(best.value, ply), bound, pv_first(ply)))
            ++stats_.tt_replacements;
        iteration_hints_.store(p.hash_key(), depth, pv_first(ply));
        return best;
    }
    Node quiescence(rules::Position& p, int ply, int qply, int alpha, int beta) {
        if (!(research_mask_ & QuiescenceReuse)) return quiescence_impl(p, ply, qply, alpha, beta);
        check_stop();
        pv_lengths_[ply] = 0;
        // Same go, root orientation, ordered history, ply and qply. No board-only scores.
        const auto key = p.history_key() ^ (std::uint64_t(ply + 1) * 0x94d049bb133111ebULL);
        ++stats_.qtt_probes;
        if (const auto* e = qtt_.probe(key, qply)) {
            ++stats_.qtt_hits;
            const int value = from_table(e->value, ply);
            if (e->bound == Bound::Exact || (e->bound == Bound::Lower && value >= beta)
                || (e->bound == Bound::Upper && value < alpha)) {
                ++stats_.qtt_cutoffs;
                const auto move = TranspositionTable::best_move(*e);
                if (e->bound == Bound::Exact && !move.empty()) {
                    if (ply < MaxPly) pv_lengths_[ply + 1] = 0;
                    pv_push(ply, move);
                }
                return {value};
            }
        }
        auto result = quiescence_impl(p, ply, qply, alpha, beta);
        const auto bound = result.value <= alpha ? Bound::Upper
            : result.value >= beta ? Bound::Lower : Bound::Exact;
        qtt_.store(key, qply, to_table(result.value, ply), bound,
                   pv_first(ply));
        return result;
    }
    Node quiescence_impl(rules::Position& p, int ply, int qply, int alpha, int beta) {
        check_stop();
        ++stats_.qnodes; // The normal leaf was already counted by visit().
        pv_lengths_[ply] = 0;
        const auto status = node_status(p, ply);
        if (status.result != rules::Result::Ongoing) {
            ++stats_.terminal_nodes;
            return {terminal(p, status, ply)};
        }
        // Never publish a static score while in check at a safety ceiling.
        // Discard this incomplete iteration just as with stop/time exhaustion.
        if (ply >= MaxPly) throw Interrupted{};
        const bool checked = p.in_check();
        std::optional<rules::Snapshot> snapshot;
        auto get_snapshot = [&]() -> const rules::Snapshot& {
            if (!snapshot) { snapshot = p.snapshot(); ++stats_.lazy_snapshots; }
            return *snapshot;
        };
        if (!(efficiency_mask_ & LazySnapshot)) get_snapshot();
        const bool maximizing = p.turn() == root_;
        const int original_alpha = alpha, original_beta = beta;
        Node best{maximizing ? -Infinity : Infinity};
        auto cutoff = [&] {
            return maximizing ? best.value >= original_beta : best.value < original_alpha;
        };
        if (!checked) {
            ++stats_.leaf_evals;
            best.value = (root_ == rules::Color::Black ? 1 : -1)
                * ((efficiency_mask_ & LazySnapshot) ? eval_cached(p, get_snapshot)
                                                    : eval_node(p, get_snapshot()));
            if (qply >= QuiescenceDepth) {
                ++stats_.qlimit_leaves;
                return best;
            }
            // Stand pat is a bound, not a legal pass or a PV move.
            if (cutoff()) { ++stats_.qcutoffs; return best; }
            if (maximizing) alpha = std::max(alpha, best.value);
            else beta = std::min(beta, best.value);
        }
        const bool selective = !checked && (efficiency_mask_ & SelectiveUSI);
        auto moves = selective ? legal_tactical(p, ply) : legal(p, ply);
        if (!checked && !selective) {
            const auto& snapshot = get_snapshot();
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
                moves = ordered(p, moves, {}, {}, {}, ply);
            } else {
                const auto& snapshot = get_snapshot();
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
                make(p, move, ply);
                Undo undo{p};
                visit(ply + 1);
                child = quiescence(p, ply + 1, qply + 1, alpha, beta);
            }
            if ((maximizing && child.value > best.value) || (!maximizing && child.value < best.value)) {
                best.value = child.value;
                pv_push(ply, move);
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
                                    const std::string& knowledge_move = {}, int ply = 0) {
        ++stats_.order_calls;
        stats_.ordered_moves += moves.size();
        std::vector<std::string> result;
        auto sort_moves = [&] {
            std::vector<unsigned char> checks;
            if (efficiency_mask_ & RuleCheckOrdering) {
                // The moves may be a restricted subset of this node's legal batch.
                batch(p, ply);
                auto& b = legal_batches_.at(ply);
                if (b.strings.empty() && !b.tokens.empty()) {
                    b.strings.reserve(b.tokens.size());
                    for (std::size_t i = 0; i < b.tokens.size(); ++i) {
                    b.strings.push_back(p.generated_move_usi(b.tokens[i]));
                    if (next_mask_ & 1) b.token_indexes.emplace(b.strings.back(), i);
                }
                }
                checks.reserve(moves.size());
                for (const auto& m : moves) {
                    const auto it = std::find(b.strings.begin(), b.strings.end(), m);
                    if (it == b.strings.end()) throw std::logic_error("ordering move absent from legal batch");
                    checks.push_back(p.generated_move_gives_check(b.tokens[it - b.strings.begin()]));
                    ++stats_.ordering_rule_checks;
                }
            }
            return MoveOrder::order(p.snapshot(), moves,
                checks.empty() ? nullptr : &checks, efficiency_mask_ & OrderingWorkspace,
                (next_mask_ & 4) ? 2 : ((next_mask_ & 2) ? 1 : 0), (reuse_mask_ & 8) != 0);
        };
        if (research_mask_ & OrderReuse) {
            const auto key = p.hash_key();
            auto& cell = order_cache_[key & (order_cache_.size() - 1)];
            if (cell.epoch == eval_epoch_ && cell.key == key && cell.original == moves) {
                result = cell.ordered;
                ++stats_.order_reuse_hits;
            } else {
                result = sort_moves();
                cell = {key, eval_epoch_, moves, result};
            }
        } else result = sort_moves();
        auto promote = [&](const std::string& hint) {
            auto it = std::find(result.begin(), result.end(), hint);
            if (it == result.end()) return false;
            std::rotate(result.begin(), it, std::next(it)); return true;
        };
        if (promote(knowledge_move)) ++stats_.knowledge_promotions;
        // At introductory depths, horizon changes made previous-iteration
        // ordering worse on contact positions. Preserve the accepted ordering
        // through depth three; use iterative hints when going deeper.
        if (iteration_depth_ >= ((research_mask_ & EarlyHints) ? 2 : 4))
            if (const auto* e = iteration_hints_.probe(p.hash_key())) promote(MoveHintCache::best_move(*e));
        if (promote(tt_move)) ++stats_.tt_move_first;
        promote(previous_root);
        return result;
    }

    std::mt19937 rng_;
    Evaluator evaluator_;
    Stats stats_{};
    TranspositionTable tt_;
    TranspositionTable qtt_;
    unsigned research_mask_ = DefaultSearchResearchMask;
    unsigned efficiency_mask_ = DefaultSearchEfficiencyMask;
    unsigned reuse_mask_ = DefaultSearchReuseMask;
    unsigned next_mask_ = 4;
    struct OrderCell {
        std::uint64_t key = 0;
        std::uint32_t epoch = 0;
        std::vector<std::string> original, ordered;
    };
    std::vector<OrderCell> order_cache_ = std::vector<OrderCell>(1u << 12);
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
