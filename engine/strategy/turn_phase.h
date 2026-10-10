#pragma once
// Adopted turn-entry diagnostic only. This does not alter move selection,
// leaf evaluation weights, mate search or time management.
#include "strategy/phase_diagnostics.h"
#include <algorithm>

namespace shogi::strategy {
struct TurnPhase {
    PhaseDiagnostics components;
    int maturity = 0;  // 0..100
    const char* stage = "opening";
};

inline TurnPhase classify_turn_phase(const rules::Snapshot& position) {
    TurnPhase out;
    out.components = diagnose_phase(position);
    // 2026-10-10 held-out research: development 44.08%, battle 38.52%,
    // invasion 17.39%, offset -5. This is a diagnostic coefficient, NOT
    // a claim of increased playing strength or a model of moves to finish.
    const int raw = (4408*out.components.development
                    + 3852*out.components.battle
                    + 1739*out.components.invasion + 5000)/10000 - 5;
    out.maturity = std::clamp(raw, 0, 100);
    out.stage = out.maturity <= 33 ? "opening"
              : out.maturity <= 66 ? "middle" : "end";
    // Keep king threat independent of maturity; an early attack is not
    // evidence that the overall board has reached the endgame.
    return out;
}
}  // namespace shogi::strategy
