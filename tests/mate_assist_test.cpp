#include "strategy/mate_assist.h"
#include <algorithm>
#include <iostream>

using namespace shogi;

void require(bool ok, const std::string& message) {
    if (!ok) throw std::runtime_error(message);
}

rules::Position from_sfen(const std::string& sfen) {
    rules::Position p;
    std::string error;
    require(p.set(sfen, {}, error), error);
    return p;
}

void play(rules::Position& p, const std::string& move) {
    std::string error;
    require(p.play(move, error), error);
}

bool contains(const std::vector<std::string>& moves, const std::string& move) {
    return std::find(moves.begin(), moves.end(), move) != moves.end();
}

int main() {
    try {
        strategy::MateAssist assist;

        // Derived exact mate-in-three from the existing real-game fixture.
        auto attack = from_sfen(
            "l3lk3/2g3n+P1/1p7/p2+R2P2/3p5/P1P1p4/2SPPP2L/5S3/+n+l1GKG1N1 b BGS6Prbsnp 105");
        play(attack, "2b3b");
        play(attack, "4a3b");
        auto attack_candidates = attack.legal_moves();
        const auto attack_before = attack.sfen();
        strategy::SearchControl attack_control;
        const auto attack_result = assist.run(attack, attack_candidates, attack_control, 1000);
        require(attack_result.has_forced_move(), "mate assist must find exact three-ply attack");
        require(contains(attack_candidates, attack_result.forced_move),
                "forced mating move must respect root candidates");
        require(attack.sfen() == attack_before, "offensive assist restores root");
        std::cout << "PASS ordinary-go offensive assist finds a forced mate\n";

        // Black can capture the bishop with 1i1d and remove the mating net.
        // The quiet rook move 1i2i leaves White's G*5h as mate in one because
        // the bishop on 1d protects 5h and the gold covers every king escape.
        auto defend = from_sfen("k8/9/9/8b/9/9/9/9/4K3R b g 1");
        const auto legal = defend.legal_moves();
        require(contains(legal, "1i2i"), "fixture must contain unsafe rook move");
        require(contains(legal, "1i1d"), "fixture must contain bishop capture defence");
        const std::vector<std::string> choices = {"1i2i", "1i1d"};
        const auto defend_before = defend.sfen();
        strategy::SearchControl defend_control;
        const auto defend_result = assist.run(defend, choices, defend_control, 1000);
        require(!defend_result.has_forced_move(), "defensive fixture has no forced mate for Black");
        require(defend_result.proven_unsafe == 1, "exactly one candidate must be proven unsafe");
        require(!contains(defend_result.candidates, "1i2i"),
                "move allowing opponent mate must be rejected");
        require(contains(defend_result.candidates, "1i1d"),
                "move removing the mating threat must remain");
        require(defend.sfen() == defend_before, "defensive assist restores root");
        std::cout << "PASS defensive assist rejects a move that permits opponent mate\n";

        // If every candidate is forced mate, do not empty the root set. The
        // normal search still needs a legal move to maximize practical survival.
        auto all_losing = from_sfen("k8/9/9/8b/9/9/9/9/4K3R b g 1");
        const std::vector<std::string> losing_only = {"1i2i"};
        strategy::SearchControl losing_control;
        const auto losing_result = assist.run(all_losing, losing_only, losing_control, 1000);
        require(losing_result.all_proven_unsafe, "single losing candidate must be marked all-unsafe");
        require(losing_result.candidates == losing_only, "all-unsafe fallback preserves legal root set");
        std::cout << "PASS all-unsafe fallback never creates an empty root\n";
    } catch (const std::exception& error) {
        std::cerr << "FAIL " << error.what() << '\n';
        return 1;
    }
}
