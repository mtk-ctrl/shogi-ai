#pragma once
// EXPERIMENT ONLY: phase-dependent root-turn evaluation weights.
// This file is not used by the adopted main engine.
// M-profile is the exact midpoint; the global phase anchors are continuous.
#include "strategy/evaluation_params.h"
#include <algorithm>
#include <array>
#include <cmath>

namespace shogi::strategy {
inline constexpr int ExperimentalPhaseIntensityPct = 50; // 50 gentle, 100 normal, 200 bold

inline double phase_smoothstep(double t) {
    t = std::clamp(t, 0.0, 1.0);
    return t * t * (3.0 - 2.0 * t);
}
inline int phase_interpolate(int maturity, int opening, int middle, int endgame) {
    const int m = std::clamp(maturity, 0, 100);
    return static_cast<int>(std::lround(m <= 50
        ? opening + (middle - opening) * phase_smoothstep(m / 50.0)
        : middle + (endgame - middle) * phase_smoothstep((m - 50) / 50.0)));
}
inline EvaluationParameters phase_turn_parameters(
    EvaluationParameters p, int maturity) {
    // Anchors are perturbations from adopted M, not absolute replacements.
    // This preserves experiments that explicitly override the M base weights.
    constexpr std::array<int, 10> M{100,480,380,410,150,140,210,340,60,20};
    constexpr std::array<int, 10> O{100,520,330,460,130,180,250,390,50,15};
    constexpr std::array<int, 10> E{100,560,440,350,180,100,150,290,75,25};
    std::array<int*,10> targets{{
        &p.material_weight, &p.weights[0], &p.weights[1],
        &p.weights[2], &p.weights[3], &p.influence_weight,
        &p.potential_weight, &p.coordination_weight,
        &p.hand_potential_weight, &p.threat_weight}};
    for (std::size_t i=0; i<targets.size(); ++i) {
        const int anchored = phase_interpolate(maturity, O[i], M[i], E[i]);
        const int deviation = anchored - M[i];
        const double relative = 1.0 + double(deviation) * ExperimentalPhaseIntensityPct
            / (100.0 * M[i]);
        // Respect explicitly disabled USI features (weight 0 remains 0).
        *targets[i] = std::clamp(static_cast<int>(std::lround(
            *targets[i] * std::max(0.0, relative))), 0, 10000);
    }
    return p;
}
} // namespace shogi::strategy
