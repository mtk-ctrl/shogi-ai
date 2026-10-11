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
    constexpr std::array<int,10> opening{80, 220, 550, 1600, 150, 600, 1500, 1100, 50, 30};
    constexpr std::array<int,10> middle{90, 250, 750, 1050, 200, 380, 700, 600, 100, 420};
    constexpr std::array<int,10> endgame{100, 250, 1250, 250, 450, 100, 120, 150, 200, 1300};
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
