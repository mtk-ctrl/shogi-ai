#include "strategy/move_order.h"
#include <iostream>
#include <stdexcept>
#include <string>
#include <random>

using namespace shogi;

namespace {

int square(char file, char rank) {
    return (file - '1') * 9 + (rank - 'a');
}

void put(rules::Snapshot& s, char file, char rank, int kind,
         rules::Color color, bool promoted = false) {
    s.board[square(file, rank)] = rules::Piece{kind, color, promoted};
}

void require(bool ok, const std::string& message) {
    if (!ok) throw std::runtime_error(message);
}

rules::Snapshot base() {
    rules::Snapshot s;
    s.turn = rules::Color::Black;
    put(s, '9', 'i', 8, rules::Color::Black);
    put(s, '1', 'a', 8, rules::Color::White);
    return s;
}

} // namespace

int main() {
    try {
        // A checking move must remain ahead of even a valuable capture.
        auto s = base();
        put(s, '5', 'e', 6, rules::Color::Black); // black rook
        put(s, '5', 'a', 8, rules::Color::White);
        s.board[square('1', 'a')] = rules::Piece{};
        put(s, '4', 'e', 6, rules::Color::White); // capturable rook
        const int check = strategy::MoveOrder::score_move(s, "5e5b");
        const int capture_rook = strategy::MoveOrder::score_move(s, "5e4e");
        require(check > capture_rook,
                "check must remain ahead of contested-piece moves");
        std::cout << "PASS check remains first\n";

        // Captures are the most direct form of piece contact.
        s = base();
        put(s, '5', 'e', 5, rules::Color::Black); // bishop
        put(s, '4', 'd', 6, rules::Color::White); // rook
        put(s, '6', 'd', 1, rules::Color::White); // pawn
        require(strategy::MoveOrder::score_move(s, "5e4d")
                    > strategy::MoveOrder::score_move(s, "5e6d"),
                "higher-value capture must be searched first");
        std::cout << "PASS captures are prioritized by tactical value\n";

        // The old heuristic only noticed bishop/rook rays. A knight attack must
        // now also make saving the endangered piece an early search candidate.
        s = base();
        put(s, '5', 'e', 7, rules::Color::Black); // gold, value 600
        put(s, '4', 'c', 3, rules::Color::White); // white knight attacks 5e
        put(s, '7', 'g', 1, rules::Color::Black); // unrelated quiet pawn
        const int escape_knight_attack = strategy::MoveOrder::score_move(s, "5e4e");
        const int quiet = strategy::MoveOrder::score_move(s, "7g7f");
        require(escape_knight_attack > quiet,
                "saving a piece attacked by a non-slider must outrank a quiet move");
        std::cout << "PASS endangered pieces from all attack types are searched early\n";

        // A move that creates an immediate attack on an enemy piece should be
        // treated as contact even when it is not itself a capture.
        s = base();
        put(s, '5', 'e', 4, rules::Color::Black); // silver
        put(s, '3', 'c', 6, rules::Color::White); // rook attacked after 5e4d
        put(s, '7', 'g', 1, rules::Color::Black);
        const int create_attack = strategy::MoveOrder::score_move(s, "5e4d");
        const int quiet_again = strategy::MoveOrder::score_move(s, "7g7f");
        require(create_attack > quiet_again,
                "creating a next-move capture threat must outrank a quiet move");
        std::cout << "PASS newly pressured enemy pieces are searched early\n";

        // Combining escape + counter-pressure should naturally rank higher than
        // a plain escape because the tactical signals are additive.
        s = base();
        put(s, '5', 'e', 4, rules::Color::Black); // silver
        put(s, '4', 'c', 3, rules::Color::White); // knight attacks 5e
        put(s, '3', 'c', 6, rules::Color::White); // rook pressured by 5e4d
        const int escape_and_pressure = strategy::MoveOrder::score_move(s, "5e4d");
        const int plain_escape = strategy::MoveOrder::score_move(s, "5e6e");
        require(escape_and_pressure > plain_escape,
                "escape plus counter-pressure must outrank a plain escape");
        std::cout << "PASS combined tactical contact gets cumulative priority\n";
        rules::Position position;
        std::mt19937 rng(2026101591);
        std::string error;
        std::size_t compared = 0;
        for (int sample = 0; sample < 400; ++sample) {
            if (position.status().result != rules::Result::Ongoing || sample % 150 == 0)
                require(position.set(rules::Position::start_sfen(), {}, error), error);
            const auto tokens = position.legal_generated_moves();
            const auto snapshot = position.snapshot();
            std::vector<std::string> moves;
            std::vector<unsigned char> checks;
            const auto before = position.sfen();
            const auto history = position.history_key();
            for (const auto& token : tokens) {
                moves.push_back(position.generated_move_usi(token));
                checks.push_back(position.generated_move_gives_check(token));
                const auto& usi = moves.back();
                const int dst = (usi[2]-'1')*9 + usi[3]-'a';
                require(position.generated_move_is_capture_or_promotion(token)
                        == (snapshot.board[dst].kind != 0 || (usi.size()==5 && usi[4]=='+')),
                        "token capture/promotion metadata disagrees with independent board/string test");
                require(position.play_generated_move(token, error), error);
                require(checks.back() == position.in_check(), "token check query disagrees with played board");
                bool rejected = false;
                try { position.generated_move_gives_check(token); }
                catch (const std::logic_error&) { rejected = true; }
                require(rejected, "stale check token must be rejected");
                require(position.undo(), "undo after check probe");
                require(position.sfen() == before && position.history_key() == history,
                        "check query/probe must preserve full position history");
                ++compared;
            }
            const auto reference = strategy::MoveOrder::order(snapshot, moves);
            require(strategy::MoveOrder::order(snapshot, moves, &checks, false) == reference,
                    "native-check ordering differs from original full-board ordering");
            require(strategy::MoveOrder::order(snapshot, moves, nullptr, true) == reference,
                    "indexed workspace ordering differs from original full-board ordering");
            require(strategy::MoveOrder::order(snapshot, moves, &checks, true) == reference,
                    "combined ordering differs from original full-board ordering");
            require(position.play_generated_move(tokens[rng() % tokens.size()], error), error);
        }
        std::cout << "PASS native checks, workspace/order identity, stale tokens and full-history restoration: "
                  << compared << " legal moves at 400 positions\n";
    } catch (const std::exception& e) {
        std::cerr << "FAIL " << e.what() << '\n';
        return 1;
    }
}
