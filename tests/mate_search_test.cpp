#include "strategy/mate_search.h"
#include <iostream>

using namespace shogi;

void require(bool ok, const std::string& message) {
    if (!ok) throw std::runtime_error(message);
}

void play(rules::Position& p, const std::string& move) {
    std::string error;
    require(p.play(move, error), error);
}

rules::Position from_sfen(const std::string& sfen) {
    rules::Position p;
    std::string error;
    require(p.set(sfen, {}, error), error);
    return p;
}

void validate_mate_line(rules::Position root, const strategy::MateSearchResult& result) {
    require(result.found(), "expected mate result");
    require(!result.pv.empty(), "mate PV must not be empty");
    const auto attacker = root.snapshot().turn;
    for (std::size_t i = 0; i < result.pv.size(); ++i) {
        const auto expected = i % 2 == 0 ? attacker
            : (attacker == rules::Color::Black ? rules::Color::White : rules::Color::Black);
        require(root.snapshot().turn == expected, "PV alternates turns");
        play(root, result.pv[i]);
        if (i % 2 == 0)
            require(root.in_check() || root.status().reason == "checkmate",
                    "attacker move must give check");
    }
    require(root.status().reason == "checkmate", "PV ends in checkmate");
}

int main() {
    try {
        strategy::MateSearch mate;

        // Extracted from game 0, ply 104 of the adopted 100-game 50ms match.
        // Independent python-shogi oracle: no mate in 1 or 3, forced mate in 5.
        auto p = from_sfen(
            "l3lk3/2g3n+P1/1p7/p2+R2P2/3p5/P1P1p4/2SPPP2L/5S3/+n+l1GKG1N1 b BGS6Prbsnp 105");
        const auto before = p.sfen();
        const auto history = p.history_key();

        strategy::SearchControl one_probe;
        const auto one = mate.solve(p, 1, one_probe);
        require(one.outcome == strategy::MateSearchResult::Outcome::NoMate,
                "exact five-ply fixture must not be mate in one");

        strategy::SearchControl three_probe;
        const auto three_shallow = mate.solve(p, 3, three_probe);
        require(three_shallow.outcome == strategy::MateSearchResult::Outcome::NoMate,
                "exact five-ply fixture must not be solved at three plies");

        strategy::SearchControl five_control;
        const auto five = mate.solve(p, 5, five_control);
        require(five.found() && five.mate_plies() == 5,
                "real-game exact mate in five must be found");
        require(five.pv.front() == "2b3b",
                "mate-in-five fixture begins with the oracle checking move");
        require(p.sfen() == before && p.history_key() == history,
                "mate probes restore root and history");
        validate_mate_line(p.clone(), five);
        std::cout << "PASS real-game exact mate-in-five; no mate at one/three plies\n";

        // The solver's defensive PV chooses the longest surviving defence.
        // Following its first attack+defence therefore leaves an exact mate in 3.
        auto three_pos = p.clone();
        play(three_pos, five.pv[0]);
        play(three_pos, five.pv[1]);
        strategy::SearchControl three_one_probe;
        const auto not_one = mate.solve(three_pos, 1, three_one_probe);
        require(not_one.outcome == strategy::MateSearchResult::Outcome::NoMate,
                "derived three-ply position must not be mate in one");
        strategy::SearchControl exact_three_control;
        const auto exact_three = mate.solve(three_pos, 3, exact_three_control);
        require(exact_three.found() && exact_three.mate_plies() == 3,
                "derived position must be exact mate in three");
        validate_mate_line(three_pos.clone(), exact_three);
        std::cout << "PASS exact mate-in-three derived from hardest defence\n";

        auto final_pos = p.clone();
        for (int i = 0; i < 4; ++i) play(final_pos, five.pv[i]);
        strategy::SearchControl final_control;
        const auto final = mate.solve(final_pos, 1, final_control);
        require(final.found() && final.mate_plies() == 1,
                "final attack position must be mate in one");
        validate_mate_line(final_pos.clone(), final);
        std::cout << "PASS exact mate-in-one at final attack node\n";

        auto quiet = from_sfen("4k4/9/9/9/9/9/9/9/4K4 b - 1");
        const auto quiet_before = quiet.sfen();
        strategy::SearchControl no_control;
        const auto no = mate.solve(quiet, 5, no_control);
        require(no.outcome == strategy::MateSearchResult::Outcome::NoMate,
                "bare kings have no forced mate within five plies");
        require(quiet.sfen() == quiet_before, "no-mate search restores root");
        std::cout << "PASS no-mate result within five plies\n";

        strategy::SearchControl stopped;
        stopped.stop.store(true);
        const auto timeout = mate.solve(p, 5, stopped);
        require(timeout.outcome == strategy::MateSearchResult::Outcome::Timeout,
                "pre-stopped search reports timeout");
        require(p.sfen() == before && p.history_key() == history,
                "stopped search restores root");

        strategy::SearchControl bounded;
        bounded.node_limit = 1;
        const auto node_timeout = mate.solve(p, 5, bounded);
        require(node_timeout.outcome == strategy::MateSearchResult::Outcome::Timeout,
                "node-limited search reports timeout rather than false no-mate");
        require(node_timeout.nodes <= 1, "node limit is respected");
        require(p.sfen() == before && p.history_key() == history,
                "node-limited search restores root");
        std::cout << "PASS stop/node limit report timeout and preserve position\n";
    } catch (const std::exception& error) {
        std::cerr << "FAIL " << error.what() << '\n';
        return 1;
    }
}
