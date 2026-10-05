#include "rules/position.h"
#include <algorithm>
#include <iostream>
#include <random>
#include <set>
#include <stdexcept>

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

std::set<std::string> generated_usi(const rules::Position& p,
                                    const std::vector<rules::GeneratedMove>& moves) {
    std::set<std::string> out;
    for (const auto& move : moves) out.insert(p.generated_move_usi(move));
    return out;
}

std::set<std::string> strings(const std::vector<std::string>& moves) {
    return {moves.begin(), moves.end()};
}

void compare_generated_sets(const rules::Position& p) {
    require(generated_usi(p, p.legal_generated_moves()) == strings(p.legal_moves()),
            "generated legal moves must equal public legal moves");
    require(generated_usi(p, p.checking_generated_moves()) == strings(p.checking_moves()),
            "generated checking moves must equal legacy legal+gives_check filtering");
    require(p.turn() == p.snapshot().turn, "fast turn accessor must equal snapshot turn");
}

int main() {
    try {
        rules::Position p;
        compare_generated_sets(p);
        const auto root_sfen = p.sfen();
        const auto root_history = p.history_key();
        const auto generated = p.legal_generated_moves();
        require(generated.size() == 30, "startpos must have 30 generated legal moves");

        // A generated token must produce exactly the same child as the public
        // string path, then restore board and history exactly on undo.
        for (std::size_t i = 0; i < std::min<std::size_t>(generated.size(), 12); ++i) {
            auto expected = p.clone();
            const auto usi = p.generated_move_usi(generated[i]);
            std::string error;
            require(expected.play(usi, error), "reference play failed: " + error);
            require(p.play_generated_move(generated[i], error), "generated play failed: " + error);
            require(p.sfen() == expected.sfen(), "generated move child differs from public play child");
            require(p.undo(), "generated move undo failed");
            require(p.sfen() == root_sfen && p.history_key() == root_history,
                    "generated move undo must restore root and history");
        }
        std::cout << "PASS generated moves reproduce public move children and undo\n";

        // Tokens are position-bound: using one after a different move must fail
        // transactionally rather than silently applying a stale move.
        const auto stale = generated.front();
        std::string error;
        require(p.play(p.legal_moves().back(), error), error);
        const auto changed = p.sfen();
        require(!p.play_generated_move(stale, error), "stale generated token must be rejected");
        require(p.sfen() == changed, "stale generated token rejection must be transactional");
        require(p.undo(), "stale-token setup undo");
        std::cout << "PASS stale generated token is rejected\n";

        // Exact mate-five fixture used by the mate-search regression tests.
        p = from_sfen(
            "l3lk3/2g3n+P1/1p7/p2+R2P2/3p5/P1P1p4/2SPPP2L/5S3/+n+l1GKG1N1 b BGS6Prbsnp 105");
        compare_generated_sets(p);

        // An in-check position exercises the conservative LEGAL_ALL +
        // gives_check fallback used for counter-check situations.
        p = from_sfen("4k4/9/9/9/4r4/9/9/9/4K4 b - 1");
        require(p.in_check(), "counter-check fixture must be in check");
        compare_generated_sets(p);
        std::cout << "PASS fixed checking-move equivalence including in-check position\n";

        // Compare both APIs across deterministic legal playouts. This catches
        // optional promotions, drops and varied board geometry without using
        // upstream types in the test.
        std::mt19937 rng(20261005);
        int positions = 0;
        int in_check_positions = 0;
        for (int game = 0; game < 12; ++game) {
            p = rules::Position();
            for (int ply = 0; ply < 120 && p.status().result == rules::Result::Ongoing; ++ply) {
                compare_generated_sets(p);
                if (p.in_check()) ++in_check_positions;
                ++positions;
                const auto moves = p.legal_moves();
                require(!moves.empty(), "ongoing random position must have a legal move");
                require(p.play(moves[rng() % moves.size()], error), error);
            }
        }
        require(positions >= 500, "generated-move random coverage unexpectedly small");
        std::cout << "PASS generated/public move-set equivalence across " << positions
                  << " random positions (" << in_check_positions << " in check)\n";

        // repetition_status() must preserve the same repetition/perpetual-check
        // rule result while avoiding status()'s separate legal-move terminal scan.
        p = from_sfen("4k4/9/9/9/9/9/9/9/4K4 b - 1");
        for (int repeat = 0; repeat < 3; ++repeat) {
            for (const auto& move : {"5i6i", "5a6a", "6i5i", "6a5a"})
                require(p.play(move, error), error);
        }
        require(p.repetition_status().result == rules::Result::Draw,
                "repetition_status must report fourfold draw");
        require(p.status().result == p.repetition_status().result,
                "status and repetition_status must agree on repetition terminal");
        std::cout << "PASS repetition-only status preserves fourfold result\n";

        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL " << error.what() << '\n';
        return 1;
    }
}
