// Research tool (not part of the engine): candidate non-king features per side for offline
// testing. For each SFEN on stdin print: maturity, engine total (Black view, current adopted
// evaluation), then 12 features for Black and 12 for White (about that side's own pieces).
#include "strategy/evaluation.h"
#include "strategy/phase_weights.h"
#include "strategy/turn_phase.h"
#include "strategy/attack_map.h"
#include <iostream>
#include <string>
#include <algorithm>
using namespace shogi;
static constexpr int NF = 12;
static void features(const rules::Snapshot& s, const strategy::AttackMap& a, int side, int out[NF]) {
    for (int i = 0; i < NF; ++i) out[i] = 0;
    const int enemy = 1 - side;
    for (int sq = 0; sq < 81; ++sq) {
        const auto& p = s.board[sq];
        if (!p.kind || p.kind == 8) continue;
        const int rank = sq % 9;
        const int depth = side == 0 ? rank : 8 - rank;           // 0 = enemy back rank, 8 = own back rank
        if (int(p.color) == side) {
            const int v = strategy::piece_value(p.kind, p.promoted);
            const int att = a.count[enemy][sq], def = a.nonking[side][sq];
            if (att && !def) { ++out[0]; out[1] += v / 100; }                        // loose pieces
            if (att && def && a.least[enemy][sq] < v) out[2] += (v - a.least[enemy][sq]) / 100;  // bad exchange risk
            if (depth <= 2) { ++out[3]; if (!p.promoted && p.kind != 7) ++out[4]; }  // in enemy camp / unpromoted there
            if (att > def) ++out[8];                                                 // attacked more than defended
        } else {
            out[9] += a.count[side][sq] ? 1 : 0;                                     // enemy pieces we attack
            if (a.count[side][sq] && !a.nonking[enemy][sq]) out[10] += strategy::piece_value(p.kind, p.promoted) / 100; // enemy loose value
        }
    }
    const int king = a.kings[side];
    if (king >= 0) { const int r = king % 9; const int d = side == 0 ? r : 8 - r; out[5] = d <= 2 ? 1 : 0; }
    int hv = 0, hn = 0;
    for (int k = 1; k <= 7; ++k) { hn += s.hands[side][k - 1]; hv += s.hands[side][k - 1] * strategy::hand_piece_value(k); }
    out[6] = hv / 100; out[7] = hn;
    out[11] = int(s.turn) == side ? 1 : 0;                                           // side to move
}
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
