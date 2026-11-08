// Research tool (not part of the engine): for each SFEN on stdin print the inputs
// of the static evaluation so weights can be fitted offline against game results.
// Columns: maturity, board_material, hand_material (Black view), 9 axis differences
// side_points[Black]-side_points[White] (axis order as EvaluationBreakdown), and the
// engine's own total (Black view) under profile 47 for a consistency check.
#include "strategy/evaluation.h"
#include "strategy/phase_weights.h"
#include "strategy/turn_phase.h"
#include <iostream>
#include <string>
using namespace shogi;
int main() {
    std::string line, error;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        rules::Position p;
        if (!p.set(line, {}, error)) { std::cerr << error << ": " << line << "\n"; return 1; }
        const auto s = p.snapshot();
        const int maturity = strategy::classify_turn_phase(s).maturity;
        const auto params = strategy::phase_turn_parameters(strategy::EvaluationParameters{}, maturity);
        const auto b = strategy::evaluate(s, params, 14);
        int hand = 0;
        for (int c = 0; c < 2; ++c)
            for (int k = 1; k <= 7; ++k) hand += (c == 0 ? 1 : -1) * s.hands[c][k - 1] * strategy::hand_piece_value(k);
        std::cout << maturity << '\t' << (b.material - hand) << '\t' << hand;
        for (int i = 0; i < 9; ++i) std::cout << '\t' << (b.side_points[0][i] - b.side_points[1][i]);
        std::cout << '\t' << b.total << '\n';
    }
}
