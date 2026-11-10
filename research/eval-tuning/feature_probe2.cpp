// Research tool (not part of the engine): candidate "strategic" features that the current
// evaluation does not look at (pawn structure, advancement, castle depth, major-piece reach,
// hanging pieces, side to move). For each SFEN on stdin print:
//   maturity, engine total (Black view, adopted profile), side-to-move (+1 Black / -1 White),
// then for Black and for White the NF features listed in kNames (each from that side's view).
// Build: see feature_probe2.build.sh. Run with --names to print the feature names.
#include "strategy/evaluation.h"
#include "strategy/phase_weights.h"
#include "strategy/turn_phase.h"
#include "strategy/attack_map.h"
#include "strategy/evaluation_strategic_ext.h"
#include <iostream>
#include <string>
#include <algorithm>
using namespace shogi;
static const char* kNames[] = {
    "pawn_hand", "pawn_free_files", "pawn_adv", "minor_adv", "major_adv", "bishop_reach",
    "rook_reach", "camp_pieces", "promoted_n", "hanging_n", "loseable_n", "castle2",
    "shield_pawns", "king_edge", "rook_near_enemy_king_file", "hand_kinds", "rook_open_file",
    "zone_control"};
static constexpr int NF = sizeof(kNames) / sizeof(kNames[0]);

static int adv(int side, int rank) { return side == 0 ? 8 - rank : rank; }

static void features(const rules::Snapshot& s, const strategy::AttackMap& a, int side, int out[NF]) {
    for (int i = 0; i < NF; ++i) out[i] = 0;
    const int enemy = 1 - side;
    const int king = a.kings[side], eking = a.kings[enemy];
    bool pawn_on_file[9] = {};
    for (int sq = 0; sq < 81; ++sq) {
        const auto& p = s.board[sq];
        if (p.kind == 1 && !p.promoted && int(p.color) == side) pawn_on_file[sq / 9] = true;
    }
    int free_files = 0;
    for (int f = 0; f < 9; ++f) free_files += pawn_on_file[f] ? 0 : 1;
    out[0] = std::min(s.hands[side][0], 6);
    out[1] = free_files;
    for (int k = 2; k <= 7; ++k) if (s.hands[side][k - 1] > 0) ++out[15];
    for (int sq = 0; sq < 81; ++sq) {
        const auto& p = s.board[sq];
        if (!p.kind || int(p.color) != side) continue;
        const int f = sq / 9, r = sq % 9, ad = adv(side, r);
        if (p.kind == 8) continue;
        const int value = strategy::piece_value(p.kind, p.promoted);
        if (p.kind == 1 && !p.promoted) out[2] += ad;
        else if (p.kind == 5 || p.kind == 6) {
            out[4] += ad;
            if (p.kind == 5) out[5] += a.sizes[sq]; else out[6] += a.sizes[sq];
            if (p.kind == 6 && !p.promoted && !pawn_on_file[f]) ++out[16];
            if (p.kind == 6 && !p.promoted && eking >= 0 && std::abs(f - eking / 9) <= 1) ++out[14];
        } else if (!(p.kind == 1 && p.promoted)) out[3] += ad;
        if (ad >= 6) ++out[7];
        if (p.promoted && p.kind != 7) ++out[8];
        if (a.count[enemy][sq] > 0) {
            if (a.count[side][sq] == 0) ++out[9];
            if (a.least[enemy][sq] < value) ++out[10];
        }
        if (king >= 0 && (p.kind == 7 || p.kind == 4 || (p.promoted && p.kind <= 4)) && a.distance(sq, king) <= 2) ++out[11];
        if (king >= 0 && p.kind == 1 && !p.promoted && std::abs(f - king / 9) <= 1 && ad > adv(side, king % 9)) ++out[12];
    }
    if (king >= 0) out[13] = std::min(king / 9, 8 - king / 9);
    for (int sq = 0; sq < 81; ++sq) if (adv(side, sq % 9) >= 6 && a.count[side][sq] > 0) ++out[17];
}

int main(int argc, char** argv) {
    if (argc > 1 && std::string(argv[1]) == "--names") {
        for (int i = 0; i < NF; ++i) std::cout << kNames[i] << (i + 1 < NF ? "\t" : "\n");
        return 0;
    }
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
        std::cout << maturity << '\t' << b.total << '\t' << (int(s.turn) == 0 ? 1 : -1);
        for (int side = 0; side < 2; ++side) {
            int f[NF]; features(s, a, side, f);
            // The engine's EvalStratExt uses its own copy; they must agree (castle2, pawn_hand, zone_control, major_adv, hand_kinds).
            int g[strategy::StratExtFeatures]; strategy::strategic_ext_features(s, a, side, g);
            const int idx[strategy::StratExtFeatures] = {11, 0, 17, 4, 15};
            for (int i = 0; i < strategy::StratExtFeatures; ++i)
                if (g[i] != f[idx[i]]) { std::cerr << "feature mismatch " << kNames[idx[i]] << ": " << line << "\n"; return 2; }
            for (int i = 0; i < NF; ++i) std::cout << '\t' << f[i];
        }
        std::cout << '\n';
    }
}
