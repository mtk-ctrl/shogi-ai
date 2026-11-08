// Research tool (not part of the engine): candidate king-danger features per side for
// offline testing against game results. For each SFEN on stdin print:
// maturity, engine total (Black view, current adopted profile), then for Black king and
// White king the features listed in kNames (about that side's own king being attacked).
#include "strategy/evaluation.h"
#include "strategy/phase_weights.h"
#include "strategy/turn_phase.h"
#include "strategy/attack_map.h"
#include "strategy/evaluation_king_ext.h"
#include <iostream>
#include <string>
#include <algorithm>
using namespace shogi;
static constexpr int NF = strategy::KingExtFeatures;
static void features(const rules::Snapshot& s, const strategy::AttackMap& a, int side, int out[NF]) { strategy::king_ext_features(s, a, side, out); }
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
        strategy::AttackMap a(s, true, true, true);
        std::cout << maturity << '\t' << b.total;
        for (int side = 0; side < 2; ++side) { int f[NF]; features(s, a, side, f); for (int i = 0; i < NF; ++i) std::cout << '\t' << f[i]; }
        std::cout << '\n';
    }
}
