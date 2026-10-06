#pragma once
#include <array>
#include <stdexcept>

namespace shogi::strategy {
// All tunable positional constants. Material values remain in material.h.
struct EvaluationParameters {
    int guard_gold = 12, guard_silver = 10, guard_pawn = 4;
    int pressure_king = 12, pressure_occupied = 6, pressure_empty = 4;
    int pressure_partner = 8;
    int mobility_major = 2, mobility_minor = 1, mobility_piece_cap = 12;
    int danger_numerator = 1, danger_denominator = 8;
    std::array<int, 4> caps{80, 120, 100, 160};
    // King safety, attack pressure, activity, danger; percentages.
    // v0.0.13 adopts c03 after the joint balance tuning:
    // Safety=50, Pressure=150, Activity=150, Danger=200.
    std::array<int, 4> weights{50, 150, 150, 200};
    // Experimental two-ring, direction-aware king defence coordination.
    // Zero by default so the adopted engine is bit-for-bit behaviourally unchanged.
    int king_defense_weight = 0;
    int king_defense_cap = 120;
    int positional_cap = 300;
    static constexpr int StaticLimit = 1000000; // Far below mate=100000000.

    static EvaluationParameters material_only() {
        EvaluationParameters p;
        p.weights.fill(0);
        return p;
    }
    void validate() const {
        const int values[] = {guard_gold, guard_silver, guard_pawn, pressure_king,
            pressure_occupied, pressure_empty, pressure_partner, mobility_major,
            mobility_minor, mobility_piece_cap, danger_numerator, king_defense_weight,
            king_defense_cap, positional_cap};
        for (int v : values) if (v < 0 || v > 10000)
            throw std::invalid_argument("evaluation parameter outside 0..10000");
        if (danger_denominator < 1 || danger_denominator > 10000)
            throw std::invalid_argument("invalid danger denominator");
        for (int v : caps) if (v < 0 || v > 10000)
            throw std::invalid_argument("invalid evaluation cap");
        for (int v : weights) if (v < 0 || v > 400)
            throw std::invalid_argument("evaluation weight outside 0..400");
    }
};
} // namespace shogi::strategy
