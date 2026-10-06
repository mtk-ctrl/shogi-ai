#pragma once
#include <array>
#include <stdexcept>

namespace shogi::strategy {
// Explainable static-evaluation parameters. Defaults reproduce the adopted
// v1.0.1 evaluator exactly; EvaluationV2 is opt-in while it is researched.
struct EvaluationParameters {
    int guard_gold = 12, guard_silver = 10, guard_pawn = 4;
    int pressure_king = 12, pressure_occupied = 6, pressure_empty = 4;
    int pressure_partner = 8;
    int mobility_major = 2, mobility_minor = 1, mobility_piece_cap = 12;
    int danger_numerator = 1, danger_denominator = 8;

    // Adopted legacy feature caps and weights.
    std::array<int, 4> caps{80, 120, 100, 160};
    std::array<int, 4> weights{50, 150, 150, 200};

    // Evaluation-v2 keeps Material as one axis rather than an implicit master
    // axis. v2 is OFF by default so main remains bit-for-bit compatible.
    bool v2_enabled = false;
    int material_weight = 100;
    std::array<int, 4> v2_caps{160, 240, 200, 400};
    int influence_weight = 0;
    int potential_weight = 0;
    int coordination_weight = 0;
    int hand_potential_weight = 0;
    int threat_weight = 0;
    int influence_cap = 160;
    int potential_cap = 120;
    int coordination_cap = 120;
    int hand_potential_cap = 120;
    int threat_cap = 1600;

    // In legacy mode this remains the adopted +/-300 cap. In v2 it is a
    // tunable whole-position safety bound rather than a hard three-pawn dogma.
    int positional_cap = 300;
    static constexpr int StaticLimit = 1000000; // Far below mate=100000000.

    static EvaluationParameters material_only() {
        EvaluationParameters p;
        p.weights.fill(0);
        p.influence_weight = p.potential_weight = p.coordination_weight = 0;
        p.hand_potential_weight = p.threat_weight = 0;
        p.v2_enabled = false;
        return p;
    }

    void validate() const {
        const int values[] = {guard_gold, guard_silver, guard_pawn, pressure_king,
            pressure_occupied, pressure_empty, pressure_partner, mobility_major,
            mobility_minor, mobility_piece_cap, danger_numerator, positional_cap,
            material_weight, influence_weight, potential_weight, coordination_weight,
            hand_potential_weight, threat_weight, influence_cap, potential_cap,
            coordination_cap, hand_potential_cap, threat_cap};
        for (int v : values) if (v < 0 || v > 10000)
            throw std::invalid_argument("evaluation parameter outside 0..10000");
        if (danger_denominator < 1 || danger_denominator > 10000)
            throw std::invalid_argument("invalid danger denominator");
        for (int v : caps) if (v < 0 || v > 10000)
            throw std::invalid_argument("invalid evaluation cap");
        for (int v : v2_caps) if (v < 0 || v > 10000)
            throw std::invalid_argument("invalid v2 evaluation cap");
        for (int v : weights) if (v < 0 || v > 400)
            throw std::invalid_argument("evaluation weight outside 0..400");
        const int extra_weights[] = {material_weight, influence_weight, potential_weight,
            coordination_weight, hand_potential_weight, threat_weight};
        for (int v : extra_weights) if (v < 0 || v > 400)
            throw std::invalid_argument("v2 evaluation weight outside 0..400");
    }
};
} // namespace shogi::strategy
