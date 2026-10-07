#pragma once

namespace shogi::strategy {
// Per-game long-think allocation. Instability may use any remaining coupon
// from FirstPly onward; a coupon has no individually assigned move window.
struct LongThinkBudget {
    static constexpr int MaxUses = 10;
    static constexpr int FirstPly = 24;
    static constexpr int TargetPly = 150;

    static constexpr bool available(int current_ply, int used) {
        return current_ply >= FirstPly && used >= 0 && used < MaxUses;
    }

    static constexpr int own_turns_until_target(int current_ply) {
        return current_ply > TargetPly ? 0 : (TargetPly - current_ply) / 2 + 1;
    }

    static constexpr bool must_spend(int current_ply, int used) {
        // Count this turn as well. If exceptions skip a turn, catch up at the
        // next eligible turn rather than discarding the remaining coupons.
        return available(current_ply, used)
            && own_turns_until_target(current_ply) <= MaxUses - used;
    }
};
} // namespace shogi::strategy
