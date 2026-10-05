#pragma once

#include "strategy/mate_search.h"
#include <algorithm>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

namespace shogi::strategy {

struct MateAssistResult {
    std::string forced_move;
    int forced_plies = 0;
    std::vector<std::string> candidates;
    std::uint64_t offense_nodes = 0;
    std::uint64_t defense_nodes = 0;
    std::size_t defense_examined = 0;
    std::size_t proven_unsafe = 0;
    bool offense_timeout = false;
    bool defense_timeout = false;
    bool all_proven_unsafe = false;

    bool has_forced_move() const { return !forced_move.empty(); }
    bool timeout() const { return offense_timeout || defense_timeout; }
};

// Small-budget root helper for ordinary timed play.
// 1) prove a short mate for the side to move;
// 2) for each root candidate, reject it only when the opponent is proven to
//    have a short forced mate after that move.
// Unproven/timeout candidates are never rejected. If every candidate is proven
// losing, the original candidate set is returned so normal search still chooses
// the best practical defence instead of producing an empty root.
class MateAssist {
public:
    static constexpr int MaxPly = 3;

    MateAssistResult run(rules::Position& position,
                         const std::vector<std::string>& root_candidates,
                         SearchControl& control,
                         std::int64_t budget_ms) const {
        MateAssistResult out;
        out.candidates = root_candidates;
        if (root_candidates.empty() || budget_ms <= 0
            || control.stop.load(std::memory_order_relaxed))
            return out;

        const auto original_deadline = control.deadline_ns.load(std::memory_order_relaxed);
        const auto started = SearchControl::now_ns();
        auto assist_deadline = started + budget_ms * 1000000;
        if (original_deadline && original_deadline < assist_deadline)
            assist_deadline = original_deadline;
        DeadlineGuard deadline_guard{control, original_deadline};

        // Reserve roughly 60% of the bounded helper budget for defence. A hard
        // offensive position therefore cannot consume the entire helper budget
        // before candidate safety is checked.
        const auto offense_budget_ms = std::max<std::int64_t>(1, (budget_ms + 2) / 3);
        auto offense_deadline = started + offense_budget_ms * 1000000;
        if (offense_deadline > assist_deadline) offense_deadline = assist_deadline;
        control.deadline_ns.store(offense_deadline, std::memory_order_relaxed);

        {
            MateSearch solver;
            auto probe = position.clone();
            const auto result = solver.solve(probe, MaxPly, control, root_candidates);
            out.offense_nodes += result.nodes;
            if (result.found() && !result.pv.empty()) {
                out.forced_move = result.pv.front();
                out.forced_plies = result.mate_plies();
                return out;
            }
            if (result.outcome == MateSearchResult::Outcome::Timeout)
                out.offense_timeout = true;
        }

        // Restore the full helper deadline for defence even if the offensive
        // probe exhausted its own slice.
        control.deadline_ns.store(assist_deadline, std::memory_order_relaxed);
        if (control.stop.load(std::memory_order_relaxed)
            || SearchControl::now_ns() >= assist_deadline) {
            out.defense_timeout = true;
            return out;
        }

        // Root candidates are already legal. Generate opaque rule-layer tokens
        // once, map them to their USI strings once, and then reuse direct
        // play/undo. This avoids a fresh LEGAL_ALL scan for every candidate.
        std::unordered_map<std::string, rules::GeneratedMove> generated_by_usi;
        const auto generated = position.legal_generated_moves();
        generated_by_usi.reserve(generated.size());
        for (const auto& token : generated)
            generated_by_usi.emplace(position.generated_move_usi(token), token);

        if (SearchControl::now_ns() >= assist_deadline) {
            out.defense_timeout = true;
            return out;
        }

        std::vector<std::string> retained;
        retained.reserve(root_candidates.size());
        for (std::size_t i = 0; i < root_candidates.size(); ++i) {
            if (control.stop.load(std::memory_order_relaxed)
                || SearchControl::now_ns() >= assist_deadline) {
                out.defense_timeout = true;
                retained.insert(retained.end(), root_candidates.begin() + i,
                                root_candidates.end());
                break;
            }

            const auto& move = root_candidates[i];
            const auto it = generated_by_usi.find(move);
            if (it == generated_by_usi.end())
                throw std::logic_error("mate assist root candidate is not legal in source position");
            std::string error;
            if (!position.play_generated_move(it->second, error))
                throw std::logic_error(error);
            Undo undo{position};
            ++out.defense_examined;

            bool unsafe = false;
            if (position.repetition_status().result == rules::Result::Ongoing) {
                MateSearch solver;
                const auto result = solver.solve(position, MaxPly, control);
                out.defense_nodes += result.nodes;
                if (result.found()) {
                    unsafe = true;
                } else if (result.outcome == MateSearchResult::Outcome::Timeout) {
                    out.defense_timeout = true;
                    retained.push_back(move); // unknown is kept, never rejected
                    retained.insert(retained.end(), root_candidates.begin() + i + 1,
                                    root_candidates.end());
                    break;
                }
            }

            if (unsafe) ++out.proven_unsafe;
            else retained.push_back(move);
        }

        if (out.proven_unsafe == root_candidates.size()) {
            out.all_proven_unsafe = true;
            out.candidates = root_candidates;
        } else if (!retained.empty()) {
            out.candidates = std::move(retained);
        }
        return out;
    }

private:
    struct Undo {
        rules::Position& position;
        ~Undo() { position.undo(); }
    };
    struct DeadlineGuard {
        SearchControl& control;
        std::int64_t previous;
        ~DeadlineGuard() {
            control.deadline_ns.store(previous, std::memory_order_relaxed);
        }
    };
};

} // namespace shogi::strategy
