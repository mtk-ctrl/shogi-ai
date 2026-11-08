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
    const int king = a.kings[side];
    if (king < 0) return;
    const int enemy = 1 - side;
    const int kf = king / 9, kr = king % 9;
    bool strong_drop = false;
    for (int k = 2; k <= 7; ++k) if (s.hands[enemy][k - 1]) strong_drop = true;
    int maxring = 0;
    for (int sq = 0; sq < 81; ++sq) {
        const int d = a.distance(sq, king);
        const auto& p = s.board[sq];
        const bool own = p.kind && int(p.color) == side && p.kind != 8;
        if (sq != king && d <= 2 && !p.kind && strong_drop && a.count[enemy][sq] && !a.nonking[side][sq]) ++out[0];  // supported drop spots (radius 2)
        if (own && d <= 1 && (p.kind == 7 || p.kind == 4)) ++out[1];                                              // gold/silver next to king
        if (own && d <= 2) out[2] += strategy::piece_value(p.kind, p.promoted) / 100;                             // defender value near
        if (p.kind && p.kind != 8 && int(p.color) == enemy && d <= 3) out[3] += strategy::piece_value(p.kind, p.promoted) / 100; // attacker value near
        if (sq != king && d == 2 && !p.kind && !a.escape_control[enemy][sq]) ++out[6];                            // second ring free
        if (sq != king && d <= 1) maxring = std::max(maxring, a.count[enemy][sq]);
    }
    // pawn shield: own pawns directly in front of king and adjacent files
    const int fwd = side == 0 ? -1 : 1;
    for (int df = -1; df <= 1; ++df) { const int f = kf + df, r = kr + fwd; if (f >= 0 && f < 9 && r >= 0 && r < 9) { const auto& q = s.board[f * 9 + r]; if (q.kind == 1 && !q.promoted && int(q.color) == side) ++out[4]; } }
    out[5] = 0; for (int df = -1; df <= 1; ++df) for (int rr = 1; rr <= 2; ++rr) { const int f = kf + df, r = kr + fwd * rr; if (f >= 0 && f < 9 && r >= 0 && r < 9 && !s.board[f * 9 + r].kind) ++out[5]; } // empty squares in front (two ranks)
    out[7] = maxring;
    out[8] = (kf == 0 || kf == 8 ? 1 : 0) + ((side == 0 ? kr : 8 - kr) >= 7 ? 1 : 0);                             // edge file / back rank
    out[9] = s.hands[enemy][6] + s.hands[enemy][3];                                                              // gold + silver in hand
    out[10] = s.hands[enemy][4] + s.hands[enemy][5];                                                             // bishop + rook in hand
    out[11] = s.hands[enemy][2];                                                                                 // knights in hand
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
