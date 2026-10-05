#include "strategy/iterative_search.h"
#include "strategy/search_limits.h"
#include <iostream>
#include <map>

using namespace shogi;
void require(bool ok, const std::string& message) { if (!ok) throw std::runtime_error(message); }
void play(rules::Position& p, const std::string& move) {
    std::string error; require(p.play(move, error), error);
}
rules::Position fixture(const std::map<std::string, std::string>& pieces, const std::string& turn = "b") {
    std::string sf;
    for (char rank = 'a'; rank <= 'i'; ++rank) {
        int empty = 0;
        for (char file = '9'; file >= '1'; --file) {
            auto it = pieces.find(std::string{file, rank});
            if (it == pieces.end()) ++empty;
            else { if (empty) sf += char('0' + empty); empty = 0; sf += it->second; }
        }
        if (empty) sf += char('0' + empty);
        if (rank != 'i') sf += '/';
    }
    rules::Position p; std::string error;
    require(p.set(sf + " " + turn + " - 1", {}, error), error); return p;
}
// Independent exhaustive minimax: no ordering, TT, iteration or pruning.
int brute(rules::Position& p, int depth, int ply, rules::Color root) {
    const auto status = p.status();
    if (status.result != rules::Result::Ongoing) {
        if (status.result == rules::Result::Draw) return 0;
        const bool win = (status.result == rules::Result::BlackWin) == (root == rules::Color::Black);
        int value = status.reason == "checkmate" ? strategy::IterativeSearch::MateScore - ply
            : strategy::IterativeSearch::RuleWinScore;
        return win ? value : -value;
    }
    if (!depth) return (root == rules::Color::Black ? 1 : -1) * strategy::material_black(p.snapshot());
    const bool max = p.snapshot().turn == root;
    int value = max ? -100001000 : 100001000;
    for (const auto& move : p.legal_moves()) {
        play(p, move); int child = brute(p, depth - 1, ply + 1, root); require(p.undo(), "oracle undo");
        value = max ? std::max(value, child) : std::min(value, child);
    }
    return value;
}
void validate_pv(rules::Position& root, const strategy::SearchResult& result) {
    auto p = root.clone();
    require(!result.pv.empty() && result.pv.front() == result.move, "PV starts at chosen move");
    for (const auto& m : result.pv) play(p, m);
}
int main() {
    try {
        strategy::BasicIterativeSearch<strategy::MaterialEvaluator> search;
        search.set_quiescence_enabled(false); // Fixed-horizon oracle/legacy regression.
        auto p = fixture({{"9i","K"},{"1a","k"},{"7g","P"},{"3c","p"}});
        for (int sample = 0; sample < 2; ++sample) {
            for (int depth = 1; depth <= 4; ++depth) {
                const auto before = p.sfen(); const auto history = p.history_key();
                const auto expected = brute(p, depth, 0, p.snapshot().turn);
                strategy::SearchControl control; std::vector<int> completed;
                auto result = search.choose(p, depth, control, {}, [&](const auto& r) { completed.push_back(r.depth); });
                require(result.score == expected && result.depth == depth, "variable-depth exhaustive equivalence");
                require(completed.size() == static_cast<std::size_t>(depth), "each completed iteration reported");
                require(p.sfen() == before && p.history_key() == history, "root and history restored");
                validate_pv(p, result);
            }
            play(p, p.legal_moves().front());
        }
        std::cout << "PASS exhaustive minimax at depths 1..4 for both turns, PV and history restoration\n";
        p = fixture({{"9i","K"},{"1a","k"},{"7g","P"},{"3g","P"}});
        strategy::SearchControl transpositions;
        search.choose(p, 3, transpositions, {"7g7f", "3g3f"});
        require(search.last_stats().tt_exact_hits > 0, "safe shallow search retains board transpositions");
        std::cout << "PASS safe three-ply transpositions retain exact score reuse\n";
        strategy::FeatureAlphaBeta3TT fixed;
        strategy::IterativeSearch features;
        strategy::IterativeSearch baseline_pvs_off;
        features.set_quiescence_enabled(false);
        baseline_pvs_off.set_quiescence_enabled(false);
        baseline_pvs_off.set_pvs_enabled(false);
        std::uint64_t baseline_nodes = 0, pvs_nodes = 0, pvs_scouts = 0, pvs_researches = 0;
        p = rules::Position();
        for (unsigned sample = 0; sample < 6; ++sample) {
            fixed.set_seed(70000 + sample);
            features.set_seed(70000 + sample);
            baseline_pvs_off.set_seed(70000 + sample);
            const auto expected = fixed.choose(p);
            auto baseline_position = p.clone();
            strategy::SearchControl baseline_control;
            const auto baseline = baseline_pvs_off.choose(baseline_position, 3, baseline_control);
            strategy::SearchControl control;
            const auto actual = features.choose(p, 3, control);
            require(actual.move == expected && actual.score == fixed.last_score(), "v0.0.13 depth-three compatibility");
            require(actual.move == baseline.move && actual.score == baseline.score, "PVS preserves fixed-depth move and score");
            baseline_nodes += baseline_pvs_off.last_stats().nodes;
            pvs_nodes += features.last_stats().nodes;
            pvs_scouts += features.last_stats().pvs_scout_searches;
            pvs_researches += features.last_stats().pvs_researches;
            validate_pv(p, actual); play(p, expected);
        }
        std::cout << "DIAG PVS nodes baseline=" << baseline_nodes << " pvs=" << pvs_nodes
                  << " delta_pct=" << (100.0 * (double(pvs_nodes) - baseline_nodes) / baseline_nodes)
                  << " scouts=" << pvs_scouts << " researches=" << pvs_researches << '\n';
        std::cout << "PASS v0.0.13 exact depth-three move/score equivalence on six opening positions\n";
        features.set_quiescence_enabled(true);
        p = rules::Position(); const auto before = p.sfen(); const auto history = p.history_key();
        strategy::SearchControl stop;
        const auto interrupted = features.choose(p, 5, stop, {}, [&](const auto& r) { if (r.depth == 1) stop.stop.store(true); });
        require(interrupted.depth == 1 && interrupted.has_score, "keep completed iteration after cancellation");
        require(p.sfen() == before && p.history_key() == history, "cancel restores board/history");
        strategy::SearchControl expired; expired.deadline_ns.store(1);
        const auto fallback = features.choose(p, 5, expired);
        require(fallback.depth == 0 && !fallback.has_score, "no score invented before first completed iteration");
        validate_pv(p, fallback);
        strategy::SearchControl nodes; nodes.node_limit = 1;
        const auto bounded = features.choose(p, 5, nodes);
        require(features.last_stats().nodes <= 1 && p.sfen() == before && p.history_key() == history,
                "node budget and interrupted history restoration");
        validate_pv(p, bounded);
        std::cout << "PASS stop/deadline/node budget preserve completed result or legal fallback\n";
        p = fixture({{"5a","k"},{"4a","l"},{"7a","l"},{"4b","p"},{"6b","p"},{"7b","p"},
                     {"5c","P"},{"7c","G"},{"9e","B"},{"5i","R"},{"9i","K"}});
        strategy::SearchControl mate_control;
        const auto mate = features.choose(p, 3, mate_control, {"5c5b", "5i4i"});
        require(mate.move == "5c5b" && mate.score == strategy::IterativeSearch::MateScore - 3, "mate distance three");
        validate_pv(p, mate);
        std::cout << "PASS forced mate has correct three-ply distance\n";
        p = fixture({{"5i","K"},{"5a","k"}});
        const auto empty_history = p.history_key();
        for (int cycle = 0; cycle < 2; ++cycle)
            for (auto move : {"5i6i","5a6a","6i5i","6a5a"}) play(p, move);
        require(p.history_key() != empty_history, "identical board distinguishes history");
        for (auto move : {"5i6i","5a6a","6i5i"}) play(p, move);
        const auto repeat_before = p.history_key(); strategy::SearchControl repetition;
        const auto draw = features.choose(p, 4, repetition, {"6a5a"});
        require(draw.score == 0 && p.history_key() == repeat_before && p.status().result == rules::Result::Ongoing,
                "speculative fourth repetition is draw and history survives");
        play(p, "6a5a"); require(p.status().result == rules::Result::Draw, "real fourth repetition preserved");
        auto limits = strategy::parse_go_limits({"btime","30000","wtime","60000","byoyomi","1000"}, rules::Color::Black);
        require(limits.budget_ms == 1990 && limits.max_depth == 64, "clock allocation and margin");
        limits = strategy::parse_go_limits({"movetime","100","depth","5"}, rules::Color::White);
        require(limits.budget_ms == 90 && limits.max_depth == 5, "fixed time plus explicit depth");
        limits = strategy::parse_go_limits({"movetime","0"}, rules::Color::Black);
        require(limits.budget_ms == 0, "zero clock must not become unlimited");
        std::cout << "PASS repetition contexts, clock parsing and zero-time behavior\n";
    } catch (const std::exception& error) { std::cerr << "FAIL " << error.what() << '\n'; return 1; }
}
