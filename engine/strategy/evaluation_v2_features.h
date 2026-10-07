#pragma once
#include "strategy/attack_map.h"
#include "strategy/evaluation_params.h"
#include <algorithm>
#include <array>
#include <cmath>

namespace shogi::strategy {

struct V2SideFeatures {
    int influence = 0;
    int potential = 0;
    int coordination = 0;
    int hand_potential = 0;
    int threat = 0;
};

inline int v2_distance(int a, int b) {
    if (a < 0 || b < 0) return 99;
    return std::max(std::abs(a / 9 - b / 9), std::abs(a % 9 - b % 9));
}

// Board-wide control outside the king zones. Safety/Pressure own the immediate
// king neighbourhood; Influence measures the rest of the usable board.
inline int v2_influence_side(const rules::Snapshot& s, const AttackMap& a, int side) {
    int score = 0;
    for (int sq = 0; sq < 81; ++sq) {
        if (v2_distance(sq, a.kings[0]) <= 2 || v2_distance(sq, a.kings[1]) <= 2)
            continue;
        const int mine = std::min(a.nonking[side][sq], 3);
        const int theirs = std::min(a.nonking[1-side][sq], 3);
        if (mine <= theirs) continue;
        int points = 2 * (mine - theirs);
        const int f = sq / 9, r = sq % 9;
        if (f >= 2 && f <= 6 && r >= 2 && r <= 6) ++points;
        // Empty controlled squares describe usable influence without double
        // counting attacked pieces already handled by Danger/Threat.
        if (!s.board[sq].kind) score += points;
    }
    return score;
}

inline bool v2_safe_empty(const rules::Snapshot& s, const AttackMap& a,
                          int side, int sq, int value) {
    if (sq < 0 || sq >= 81 || s.board[sq].kind) return false;
    return !(a.nonking[1-side][sq] && a.least[1-side][sq] < value);
}

inline bool v2_on_ray(int slider, int target, int df, int dr) {
    const int sf = slider / 9, sr = slider % 9;
    const int tf = target / 9, tr = target % 9;
    const int x = tf - sf, y = tr - sr;
    if (df == 0) return x == 0 && y * dr > 0;
    if (dr == 0) return y == 0 && x * df > 0;
    return std::abs(x) == std::abs(y) && x * df > 0 && y * dr > 0;
}

// Cheap one-move latent mobility. It never generates legal moves: it asks
// whether the first friendly blocker has a reasonably safe geometric square
// off the slider's ray, then counts a few squares that would become available.
inline int v2_latent_ray(const rules::Snapshot& s, const AttackMap& a, int side,
                         int from, int df, int dr) {
    int f = from / 9 + df, r = from % 9 + dr;
    while (f >= 0 && f < 9 && r >= 0 && r < 9 && !s.board[f*9+r].kind) {
        f += df; r += dr;
    }
    if (f < 0 || f >= 9 || r < 0 || r >= 9) return 0;
    const int blocker = f * 9 + r;
    const auto& bp = s.board[blocker];
    if (!bp.kind || bp.kind == 8 || int(bp.color) != side) return 0;
    if (a.nonking[1-side][blocker] && !a.nonking[side][blocker]) return 0;

    const int bv = piece_value(bp.kind, bp.promoted);
    bool can_leave_ray = false, can_advance_on_ray = false;
    for (int j = 0; j < a.sizes[blocker]; ++j) {
        const int to = a.targets[blocker][j];
        if (!v2_safe_empty(s, a, side, to, bv)) continue;
        if (v2_on_ray(from, to, df, dr)) can_advance_on_ray = true;
        else can_leave_ray = true;
    }
    if (!can_leave_ray && !can_advance_on_ray) return 0;

    int gained = 0;
    for (f += df, r += dr; f >= 0 && f < 9 && r >= 0 && r < 9; f += df, r += dr) {
        if (s.board[f*9+r].kind) break;
        ++gained;
        if (gained >= 4) break;
    }
    if (can_leave_ray) return gained;
    // A pawn/lance advancing on the same file usually opens only the square it
    // vacated, not the whole line. Keep this intentionally conservative.
    return gained ? 1 : 0;
}

inline int v2_potential_side(const rules::Snapshot& s, const AttackMap& a, int side) {
    int score = 0;
    for (int sq = 0; sq < 81; ++sq) {
        const auto& p = s.board[sq];
        if (!p.kind || int(p.color) != side) continue;
        int gained = 0;
        auto ray = [&](int df, int dr) { gained += v2_latent_ray(s, a, side, sq, df, dr); };
        if (p.kind == 5) {
            for (int df : {-1,1}) for (int dr : {-1,1}) ray(df,dr);
        } else if (p.kind == 6) {
            ray(-1,0); ray(1,0); ray(0,-1); ray(0,1);
        } else if (p.kind == 2 && !p.promoted) {
            ray(0, side == 0 ? -1 : 1);
        } else continue;
        score += std::min(gained, 8) * (p.kind == 2 ? 3 : 5);
    }
    return score;
}

inline int v2_coordination_side(const rules::Snapshot& s, const AttackMap& a, int side) {
    int score = 0;
    for (int sq = 0; sq < 81; ++sq) {
        const auto& p = s.board[sq];
        if (!p.kind || p.kind == 8 || int(p.color) != side) continue;
        const int defenders = std::min(a.nonking[side][sq], 3);
        if (!defenders) continue;
        int points = 2 + defenders;
        if (p.kind == 5 || p.kind == 6) ++points;
        // Coordination is about the network itself. Immediate king shelter is
        // already Safety, so halve overlap in the closest ring.
        if (v2_distance(sq, a.kings[side]) <= 1) points /= 2;
        score += points;
    }
    return score;
}

inline int v2_hand_potential_side(const rules::Snapshot& s, int side) {
    // Small option-value premium for keeping a reusable piece in hand. It is
    // deliberately tiny versus Material; deployment must earn its keep through
    // pressure, activity, influence or threat.
    constexpr int premium[7] = {2, 4, 6, 8, 12, 14, 9};
    int score = 0;
    for (int kind = 1; kind <= 7; ++kind)
        score += s.hands[side][kind-1] * premium[kind-1];
    return score;
}

inline int v2_capture_swing(const rules::Piece& p) {
    if (!p.kind || p.kind == 8) return 0;
    return piece_value(p.kind, p.promoted) + piece_value(p.kind, false);
}

inline int v2_skewer_from(const rules::Snapshot& s, int from,
                          const rules::Piece& p, int df, int dr) {
    int first = 0;
    for (int f = from/9 + df, r = from%9 + dr;
         f >= 0 && f < 9 && r >= 0 && r < 9; f += df, r += dr) {
        const auto& q = s.board[f*9+r];
        if (!q.kind) continue;
        if (q.color == p.color || q.kind == 8) return 0;
        const int gain = v2_capture_swing(q);
        if (!first) { first = gain; continue; }
        return std::min(first, gain);
    }
    return 0;
}

inline bool v2_promotion_zone(int side, int sq) {
    const int rank = sq % 9;
    return side == 0 ? rank <= 2 : rank >= 6;
}

// Opponent Threat Quality: static forcing resources that the other side must
// respect even before material is actually won.  This deliberately measures
// quality, not just move count: checks dominate promotion access, while attacks
// on valuable pieces scale with the threatened swing.  The feature remains
// symmetric and cheap enough for every leaf.
inline int v2_forcing_resources(const rules::Snapshot& s, const AttackMap& a, int side) {
    int score = 0;
    const int enemy_king = a.kings[1-side];
    if (enemy_king >= 0) {
        // A current checking line is the strongest forcing resource.
        if (a.nonking[side][enemy_king]) score += 240;
        // Controlled king-ring squares are latent checking/infiltration routes.
        for (int sq=0; sq<81; ++sq)
            if (sq != enemy_king && AttackMap::near(sq, enemy_king)
                && a.nonking[side][sq]) score += 10;
    }

    for (int from=0; from<81; ++from) {
        const auto& p=s.board[from];
        if (!p.kind || p.kind==8 || int(p.color)!=side) continue;
        const int attacker_value=piece_value(p.kind,p.promoted);
        for (int j=0; j<a.sizes[from]; ++j) {
            const int to=a.targets[from][j];
            const auto& q=s.board[to];

            // High-value-piece attack prevention: count only a meaningful
            // threatened swing and discount obviously expensive attackers.
            if (q.kind && q.kind!=8 && int(q.color)==1-side) {
                const int victim=piece_value(q.kind,q.promoted);
                score += std::max(0, victim-attacker_value/2) / 8;
            }

            // Promotion prevention: an unpromoted promotable piece already
            // reaching the zone is a concrete next-step resource. Capturing
            // into the zone is more forcing than an empty-square route.
            if (!p.promoted && p.kind>=1 && p.kind<=6
                && v2_promotion_zone(side,to)) {
                score += q.kind && int(q.color)==1-side ? 24 : 8;
            }
        }
    }
    return score;
}

inline int v2_threat_side(const rules::Snapshot& s, const AttackMap& a, int side) {
    int best = 0, second = 0;
    for (int from = 0; from < 81; ++from) {
        const auto& p = s.board[from];
        if (!p.kind || p.kind == 8 || int(p.color) != side) continue;

        int hi = 0, lo = 0;
        for (int j = 0; j < a.sizes[from]; ++j) {
            const int to = a.targets[from][j];
            const auto& q = s.board[to];
            if (!q.kind || q.kind == 8 || q.color == p.color) continue;
            const int gain = v2_capture_swing(q);
            if (gain > hi) { lo = hi; hi = gain; }
            else if (gain > lo) lo = gain;
        }
        int candidate = lo; // only the second target is the extra fork value.

        if (p.kind == 2 && !p.promoted) {
            candidate = std::max(candidate, v2_skewer_from(
                s, from, p, 0, side == 0 ? -1 : 1));
        } else if (p.kind == 5) {
            for (int df : {-1,1}) for (int dr : {-1,1})
                candidate = std::max(candidate, v2_skewer_from(s, from, p, df, dr));
        } else if (p.kind == 6) {
            candidate = std::max({candidate,
                v2_skewer_from(s,from,p,-1,0), v2_skewer_from(s,from,p,1,0),
                v2_skewer_from(s,from,p,0,-1), v2_skewer_from(s,from,p,0,1)});
        }
        if (!candidate) continue;

        // Cheap refutation screen: an undefended attacked forking piece should
        // not receive speculative value. A defended but cheaply attacked piece
        // keeps only half of the unresolved threat.
        if (a.nonking[1-side][from]) {
            if (!a.nonking[side][from]) candidate = 0;
            else if (a.least[1-side][from] < piece_value(p.kind,p.promoted))
                candidate /= 2;
        }
        if (candidate > best) { second = best; best = candidate; }
        else if (candidate > second) second = candidate;
    }
    return best + second / 2 + v2_forcing_resources(s,a,side);
}

inline V2SideFeatures v2_features(const rules::Snapshot& s, const AttackMap& a,
                                  const EvaluationParameters& p, int side) {
    V2SideFeatures f;
    if (p.influence_weight) f.influence = std::min(v2_influence_side(s,a,side), p.influence_cap);
    if (p.potential_weight) f.potential = std::min(v2_potential_side(s,a,side), p.potential_cap);
    if (p.coordination_weight) f.coordination = std::min(v2_coordination_side(s,a,side), p.coordination_cap);
    if (p.hand_potential_weight) f.hand_potential = std::min(v2_hand_potential_side(s,side), p.hand_potential_cap);
    if (p.threat_weight) f.threat = std::min(v2_threat_side(s,a,side), p.threat_cap);
    return f;
}

} // namespace shogi::strategy
