// Research tool (not part of the engine): candidate king-danger features per side for
// offline testing against game results. For each SFEN on stdin print:
// maturity, engine total (Black view, current adopted profile), then for Black king and
// White king the features listed in kNames (about that side's own king being attacked).
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
    const int king = a.kings[side];
    if (king < 0) return;
    const int enemy = 1 - side;
    const int kf = king / 9, kr = king % 9;
    for (int sq = 0; sq < 81; ++sq) {
        const int d = a.distance(sq, king);
        const auto& piece = s.board[sq];
        if (sq != king && d <= 1) {
            const bool own = piece.kind && int(piece.color) == side;
            const bool empty = !piece.kind;
            if (empty && !a.escape_control[enemy][sq]) ++out[0];               // safe escape squares
            out[1] += a.count[enemy][sq];                                      // enemy attacks on ring
            out[2] += (own || empty) ? std::min(a.nonking[side][sq], 3) : 0;   // own defence of ring
            if ((own || empty) && a.count[enemy][sq] > a.nonking[side][sq]) ++out[3]; // weak ring squares
            if (empty && a.count[enemy][sq] && !a.nonking[side][sq]) ++out[8];  // undefended attacked empty ring squares
        }
        if (sq != king && d <= 2 && piece.kind && int(piece.color) == side && piece.kind != 8) ++out[5]; // own pieces near
        if (piece.kind && int(piece.color) == enemy && piece.kind != 8 && d <= 3) ++out[9];   // enemy attackers near
    }
    int hand_attackers = 0, hand_value = 0;
    for (int k = 2; k <= 7; ++k) { hand_attackers += s.hands[enemy][k - 1]; hand_value += s.hands[enemy][k - 1] * strategy::hand_piece_value(k); }
    out[4] = hand_attackers;
    out[6] = side == 0 ? 8 - kr : kr;                                          // king advance from home rank
    out[7] = std::min(hand_value, 6000) / 100;                                 // enemy attacking hand value
    // interaction: attacked ring weakness amplified by enemy pieces in hand
    out[10] = out[3] * std::min(hand_attackers, 4);
    // open file/diagonal exposure: empty squares in 4 straight lines until a piece (king's open lines)
    int open = 0;
    const int dirs[4][2] = {{1,0},{-1,0},{0,1},{0,-1}};
    for (auto& dd : dirs) { int f = kf + dd[0], r = kr + dd[1];
        while (f >= 0 && f < 9 && r >= 0 && r < 9 && !s.board[f * 9 + r].kind) { ++open; f += dd[0]; r += dd[1]; } }
    out[11] = open;
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
