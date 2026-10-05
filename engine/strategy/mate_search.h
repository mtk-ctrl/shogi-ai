#pragma once

#include "strategy/iterative_search.h"
#include <algorithm>
#include <cstdint>
#include <vector>

namespace shogi::strategy {

struct MateSearchResult {
    enum class Outcome { Mate, NoMate, Timeout };
    Outcome outcome = Outcome::NoMate;
    std::vector<std::string> pv;
    std::uint64_t nodes = 0;

    bool found() const { return outcome == Outcome::Mate; }
    int mate_plies() const { return found() ? static_cast<int>(pv.size()) : 0; }
};

// Self-authored tsume solver. The attacker only considers checking moves; the
// defender considers every legal evasion. Rules, legal moves and repetition
// adjudication still come from the rules layer.
class MateSearch {
public:
    static constexpr int MaxMatePly = 7;

    MateSearchResult solve(rules::Position& position, int max_plies, SearchControl& control,
                           const std::vector<std::string>& allowed_root = {}) {
        control_ = &control;
        attacker_ = position.turn();
        nodes_ = 0;
        allowed_root_ = &allowed_root;

        const int capped = std::clamp(max_plies, 1, MaxMatePly);
        const int last = capped % 2 == 0 ? capped - 1 : capped;
        try {
            for (int limit = 1; limit <= last; limit += 2) {
                auto line = attack(position, limit, true);
                if (line.mate) {
                    allowed_root_ = nullptr;
                    return {MateSearchResult::Outcome::Mate, std::move(line.pv), nodes_};
                }
            }
        } catch (const Interrupted&) {
            allowed_root_ = nullptr;
            return {MateSearchResult::Outcome::Timeout, {}, nodes_};
        }
        allowed_root_ = nullptr;
        return {MateSearchResult::Outcome::NoMate, {}, nodes_};
    }

private:
    struct Interrupted {};
    struct Line {
        bool mate = false;
        std::vector<std::string> pv;
    };
    struct Undo {
        rules::Position& position;
        ~Undo() { position.undo(); }
    };

    SearchControl* control_ = nullptr;
    rules::Color attacker_ = rules::Color::Black;
    std::uint64_t nodes_ = 0;
    const std::vector<std::string>* allowed_root_ = nullptr;

    void check_stop() const {
        const auto deadline = control_->deadline_ns.load(std::memory_order_relaxed);
        if (control_->stop.load(std::memory_order_relaxed)
            || (control_->node_limit && nodes_ >= control_->node_limit)
            || (deadline && SearchControl::now_ns() >= deadline))
            throw Interrupted{};
    }

    void visit() {
        check_stop();
        ++nodes_;
    }

    static void make(rules::Position& position, const rules::GeneratedMove& move) {
        std::string error;
        if (!position.play_generated_move(move, error)) throw std::logic_error(error);
    }

    Line attack(rules::Position& position, int remaining, bool root = false) {
        visit();
        if (position.repetition_status().result != rules::Result::Ongoing) return {};
        if (remaining <= 0 || position.turn() != attacker_) return {};

        Line best;
        // These opaque tokens are already known legal checking moves from this
        // exact position. We can play them without a second legal-move scan and
        // stringify only a move that actually becomes part of a mating PV.
        for (const auto& move : position.checking_generated_moves()) {
            check_stop();
            std::string root_usi;
            if (root && allowed_root_ && !allowed_root_->empty()) {
                root_usi = position.generated_move_usi(move);
                if (std::find(allowed_root_->begin(), allowed_root_->end(), root_usi)
                    == allowed_root_->end())
                    continue;
            }
            Line candidate;
            {
                make(position, move);
                Undo undo{position};

                if (position.repetition_status().result == rules::Result::Ongoing) {
                    // The checking move guarantees in_check(). Generate the
                    // defender's complete legal reply set once. Empty means
                    // immediate checkmate; otherwise pass the same set into the
                    // AND node instead of regenerating it in status()/defend().
                    auto replies = position.legal_generated_moves();
                    if (replies.empty()) {
                        candidate.mate = true;
                    } else if (remaining > 1) {
                        auto child = defend(position, remaining - 1, std::move(replies));
                        if (child.mate) {
                            candidate.mate = true;
                            candidate.pv = std::move(child.pv);
                        }
                    }
                }
            }
            if (candidate.mate) {
                if (root_usi.empty()) root_usi = position.generated_move_usi(move);
                candidate.pv.insert(candidate.pv.begin(), std::move(root_usi));
                if (!best.mate || candidate.pv.size() < best.pv.size())
                    best = std::move(candidate);
            }
        }
        return best;
    }

    Line defend(rules::Position& position, int remaining,
                std::vector<rules::GeneratedMove> replies) {
        visit();
        if (remaining <= 0 || position.turn() == attacker_ || !position.in_check()) return {};

        Line hardest{true, {}};
        for (const auto& move : replies) {
            check_stop();
            Line child;
            {
                make(position, move);
                Undo undo{position};
                child = attack(position, remaining - 1);
            }
            if (!child.mate) return {};

            if (child.pv.size() + 1 > hardest.pv.size()) {
                std::vector<std::string> line{position.generated_move_usi(move)};
                line.insert(line.end(), child.pv.begin(), child.pv.end());
                hardest.pv = std::move(line);
            }
        }
        return hardest;
    }
};

} // namespace shogi::strategy