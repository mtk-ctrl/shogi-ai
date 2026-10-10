#pragma once
#include <array>
#include <stdexcept>

namespace shogi::strategy {
// Explainable static-evaluation parameters. Defaults are the experimental guard-zone candidate based on
// Evaluation-v2 B (2026-10-10). Main production profile is unchanged.  The former v1 evaluator
// remains reproducible through explicit USI options and legacy_v1().
struct EvaluationParameters {
    int guard_gold = 12, guard_silver = 10, guard_pawn = 4;
    int pressure_king = 12, pressure_occupied = 6, pressure_empty = 4;
    int pressure_partner = 8;
    int mobility_major = 2, mobility_minor = 1, mobility_piece_cap = 12;
    int danger_numerator = 1, danger_denominator = 8;

    // Feature caps and adopted B-profile weights.
    std::array<int, 4> caps{80, 120, 100, 160};
    std::array<int, 4> weights{550, 474, 150, 200};

    // Evaluation-v2 keeps Material as one axis rather than an implicit master
    // axis. B is the production default after direct and external validation.
    bool v2_enabled = true;
    int material_weight = 100;
    std::array<int, 4> v2_caps{160, 240, 200, 400};
    int influence_weight = 30;
    int potential_weight = 40;
    int coordination_weight = 100;
    int hand_potential_weight = 40;
    int threat_weight = 5;
    int influence_cap = 160;
    int potential_cap = 120;
    int coordination_cap = 120;
    int hand_potential_cap = 120;
    int threat_cap = 600;

    // In legacy-v1 reproduction this is +/-300.  The adopted B profile uses
    // the wider v2 bound validated in the parameter search.
    int positional_cap = 5000;
    static constexpr int StaticLimit = 1000000; // Far below mate=100000000.

    static EvaluationParameters legacy_v1() {
        EvaluationParameters p;
        p.weights = {50, 150, 150, 200};
        p.v2_enabled = false;
        p.material_weight = 100;
        p.influence_weight = 0;
        p.potential_weight = 0;
        p.coordination_weight = 0;
        p.hand_potential_weight = 0;
        p.threat_weight = 0;
        p.positional_cap = 300;
        return p;
    }

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
        for (int v : weights) if (v < 0 || v > 10000)
            throw std::invalid_argument("evaluation weight outside 0..10000");
        const int extra_weights[] = {material_weight, influence_weight, potential_weight,
            coordination_weight, hand_potential_weight, threat_weight};
        for (int v : extra_weights) if (v < 0 || v > 10000)
            throw std::invalid_argument("v2 evaluation weight outside 0..10000");
    }
};
} // namespace shogi::strategy
