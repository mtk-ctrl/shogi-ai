#pragma once
// Experimental divergent phase-weight profiles. No change to the production engine.
// Three independent anchor vectors, not a common intensity multiplier.
#include "strategy/evaluation_params.h"
#include <algorithm>
#include <array>
#include <cmath>

namespace shogi::strategy {
inline double phase_smoothstep(double x) {
    x = std::clamp(x, 0.0, 1.0);
    return x*x*(3.0 - 2.0*x);
}
inline int phase_interpolate(int maturity, int opening, int middle, int endgame) {
    const int m = std::clamp(maturity,0,100);
    const double raw = m <= 50
      ? opening + (middle-opening)*phase_smoothstep(m / 50.0)
      : middle + (endgame-middle)*phase_smoothstep((m-50) / 50.0);
    return static_cast<int>(std::lround(raw));
}
inline constexpr int ExperimentalPhaseIntensityPct = 100;
inline EvaluationParameters phase_turn_parameters(EvaluationParameters p, int maturity) {
    constexpr std::array<int,10> baseline{100,480,380,410,150,140,210,340,60,20};
    constexpr std::array<int,10> opening{120, 1400, 180, 180, 500, 120, 200, 1000, 30, 10};
    constexpr std::array<int,10> middle{120, 1000, 350, 300, 650, 130, 160, 750, 80, 120};
    constexpr std::array<int,10> endgame{100, 850, 1300, 350, 600, 90, 70, 420, 250, 500};
    std::array<int*,10> weights{{
      &p.material_weight, &p.weights[0], &p.weights[1], &p.weights[2], &p.weights[3],
      &p.influence_weight, &p.potential_weight, &p.coordination_weight,
      &p.hand_potential_weight, &p.threat_weight
    }};
    for(std::size_t i=0;i<weights.size();++i) {
       const int target=phase_interpolate(maturity,opening[i],middle[i],endgame[i]);
       // Preserve external USI overrides and explicitly disabled features.
       *weights[i]=std::clamp(int(std::lround(double(*weights[i])*target/baseline[i])),0,10000);
    }
    return p;
}
} // namespace shogi::strategy
