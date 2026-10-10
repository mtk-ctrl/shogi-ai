#pragma once
// Research-only stage-aware mate time budget. The allocation is a CEILING,
// not a reservation. Unused time belongs to regular alpha-beta search.
#include <algorithm>
#include <cstdint>

namespace shogi::strategy {
struct MateTimePolicy {
    enum class Profile { Cautious, Standard, Aggressive };
    struct Allocation {
        std::int64_t total_ms = 0;
        std::int64_t short_ms = 0;
        std::int64_t extended_ms = 0;
        bool urgent = false;
    };

    static int interpolate(int x, int lo, int hi, int from, int to) {
        return from + (to - from) * std::clamp(x - lo, 0, hi - lo) / (hi - lo);
    }

    static Allocation choose(int maturity, int king_threat, bool learned_signal,
                             std::int64_t available_ms, Profile profile=Profile::Standard) {
        Allocation out;
        if (maturity <= 33 || available_ms <= 0) return out; // opening: STRICT ZERO
        maturity = std::clamp(maturity, 0, 100);
        king_threat = std::clamp(king_threat, 0, 100);
        // A safe gating policy: phase controls base budget and both king danger
        // and an optional learned score can raise it. Neither proves mate.
        out.urgent = king_threat >= 75 || learned_signal;
        int normal, maximum;
        if (maturity <= 66) {
            normal = interpolate(maturity, 34, 66, 10, 15);
            maximum = 40;
        } else if (maturity <= 85) {
            normal = interpolate(maturity, 67, 85, 20, 30);
            maximum = 60;
        } else {
            normal = interpolate(maturity, 86, 100, 30, 40);
            maximum = 100;
        }
        if (profile == Profile::Cautious) {
            normal = normal / 2;
            maximum = std::min(maximum, 50);
        } else if (profile == Profile::Aggressive) {
            normal = (normal * 3) / 2;
            maximum = std::min(100, maximum + 20);
        }
        // Never exceed 50% of the nominal 200ms allotment. The original
        // search deadline, reduced for protocol overhead, remains authoritative.
        out.total_ms = std::min<std::int64_t>({available_ms, 100, out.urgent ? maximum : normal});
        out.short_ms = std::min<std::int64_t>(5, out.total_ms);
        // A weak threat never burns time in a large 7-ply tree.
        if (king_threat >= 35 || learned_signal)
            out.extended_ms = out.total_ms - out.short_ms;
        return out;
    }
};
} // namespace shogi::strategy
