#pragma once
#include "strategy/attack_map.h"
#include "strategy/evaluation_params.h"
#include "strategy/evaluation_v2_features.h"
#include <cstdint>

namespace shogi::strategy {
struct SideFeatures {
    int gold_guards=0, silver_guards=0, pawn_guards=0;
    int king_attacked=0, occupied_ring=0, denied_empty=0, partners=0;
    int major_mobility=0, minor_mobility=0;
    int exposure=0;
    V2SideFeatures v2{};
};
struct EvaluationBreakdown {
    int material=0, material_term=0;
    std::array<SideFeatures,2> raw{};
    // 0 safety, 1 pressure, 2 activity, 3 danger,
    // 4 influence, 5 potential, 6 coordination, 7 hand potential, 8 threat.
    std::array<std::array<int,9>,2> side_points{};
    std::array<int,9> terms{};
    int positional_unclamped=0, positional=0, clamp_adjustment=0, total=0;
};

inline void king_safety_features(const rules::Snapshot& s, const AttackMap& a,
                                 int side, SideFeatures& out) {
    for(int sq=0;sq<81;++sq) {
        const auto& p=s.board[sq];
        if (!p.kind || int(p.color)!=side || !AttackMap::near(sq,a.kings[side])) continue;
        if(p.kind==7 || (p.promoted && p.kind<=4)) ++out.gold_guards;
        else if(p.kind==4) ++out.silver_guards;
        else if(p.kind==1) ++out.pawn_guards;
    }
}
// Evaluation-v2 shelter: distinguish WHERE the pieces defend, rather than
// awarding the same safety to every nearby gold/silver/pawn arrangement.
// Ring 1 covers the eight squares adjacent to the king; ring 2 the next 16.
// Pressure already assesses attacks on the enemy king, while this term
// measures our own king's coverage, contested entrances and safe escapes.
inline int v2_king_shelter(const rules::Snapshot& s, const AttackMap& a,
                          int side, const SideFeatures& f,
                          const EvaluationParameters& p) {
    const int king = a.kings[side];
    if (king < 0) return 0;
    int score = f.gold_guards * (p.guard_gold / 2)
              + f.silver_guards * (p.guard_silver / 2)
              + f.pawn_guards * (p.guard_pawn / 2);
    for (int sq=0; sq<81; ++sq) {
        const int dist = std::max(std::abs(sq/9-king/9), std::abs(sq%9-king%9));
        if (dist == 0 || dist > 2) continue;
        const int ours = std::min(a.nonking[side][sq], 3);
        const int theirs = std::min(a.nonking[1-side][sq], 3);
        if (dist == 1) {
            // Multiple defenders are useful, but do not grow without bound.
            if (ours) score += 4 + 2*(ours-1);
            // A contested entrance defended by us is preferable to a hole.
            if (theirs) {
                if (!ours) score -= 9;
                else if (ours < theirs) score -= 4;
                else score += 2;
            }
            // A genuinely available escape matters independently of guards.
            if (!s.board[sq].kind && !theirs) score += 3;
            if (s.board[sq].kind && int(s.board[sq].color) != side)
                score -= 6;
        } else {
            // The outer ring is a buffer, not another copy of the inner ring.
            if (ours) score += 1 + (theirs ? 2 : 0)
                              + (theirs && ours >= theirs ? 2 : 0);
            if (theirs && !ours) score -= 2;
        }
    }
    if (a.nonking[1-side][king]) score -= 12;
    return std::clamp(score, -p.v2_caps[0], p.v2_caps[0]);
}
inline void pressure_features(const rules::Snapshot& s, const AttackMap& a,
                               int side, SideFeatures& out) {
    const int king=a.kings[1-side];
    if(king<0)return;
    out.king_attacked=a.nonking[side][king]>0;
    for(int sq=0;sq<81;++sq) {
        if(sq==king || !AttackMap::near(sq,king))continue;
        if(s.board[sq].kind) out.occupied_ring += a.nonking[side][sq]>0;
        else out.denied_empty += a.escape_control[side][sq];
    }
    int participants=0;
    for(int sq=0;sq<81;++sq) {
        const auto& p=s.board[sq];
        if(!p.kind || p.kind==8 || int(p.color)!=side)continue;
        if(a.count[1-side][sq] && !a.count[side][sq])continue;
        for(int j=0;j<a.sizes[sq];++j) if(AttackMap::near(a.targets[sq][j],king)) {
            ++participants;break;
        }
    }
    out.partners=std::max(0,participants-1);
}
inline void activity_features(const rules::Snapshot& s, const AttackMap& a,
                              int side, const EvaluationParameters& p, SideFeatures& out) {
    for(int sq=0;sq<81;++sq) {
        const auto& piece=s.board[sq];
        if(!piece.kind || piece.kind==8 || int(piece.color)!=side)continue;
        const int value=piece_value(piece.kind,piece.promoted);
        int n=0;
        for(int j=0;j<a.sizes[sq];++j) {
            const int to=a.targets[sq][j];
            if(s.board[to].kind || AttackMap::near(to,a.kings[0]) || AttackMap::near(to,a.kings[1]))continue;
            if(a.count[1-side][to] && a.least[1-side][to]<value)continue;
            ++n;
        }
        n=std::min(n,p.mobility_piece_cap);
        if(piece.kind==5 || piece.kind==6)out.major_mobility+=n;
        else out.minor_mobility+=n;
    }
}
inline void danger_features(const rules::Snapshot& s, const AttackMap& a,
                            int side, SideFeatures& out) {
    for(int sq=0;sq<81;++sq) {
        const auto& q=s.board[sq];
        if(!q.kind || q.kind==8 || int(q.color)!=side || !a.count[1-side][sq])continue;
        const int value=piece_value(q.kind,q.promoted);
        out.exposure += a.count[side][sq] ? std::max(0,value-a.least[1-side][sq]) : value;
    }
}

inline EvaluationBreakdown evaluate(const rules::Snapshot& s,
                                     const EvaluationParameters& p=EvaluationParameters{}) {
    EvaluationBreakdown b;
    b.material=material_black(s);
    b.material_term = p.v2_enabled
        ? int(std::int64_t(b.material) * p.material_weight / 100)
        : b.material;

    const bool no_legacy = std::all_of(p.weights.begin(),p.weights.end(),[](int w){return w==0;});
    const bool no_v2 = p.influence_weight==0 && p.potential_weight==0
        && p.coordination_weight==0 && p.hand_potential_weight==0 && p.threat_weight==0;
    if(no_legacy && (!p.v2_enabled || no_v2)){
        b.total=std::clamp(b.material_term,-p.StaticLimit,p.StaticLimit);
        return b;
    }

    AttackMap a(s);
    for(int c=0;c<2;++c) {
        auto& f=b.raw[c];
        king_safety_features(s,a,c,f);pressure_features(s,a,c,f);
        activity_features(s,a,c,p,f);danger_features(s,a,c,f);
        const auto& caps = p.v2_enabled ? p.v2_caps : p.caps;
        b.side_points[c][0]=p.v2_enabled
            ? v2_king_shelter(s,a,c,f,p)
            : std::min(f.gold_guards*p.guard_gold+f.silver_guards*p.guard_silver
                       +f.pawn_guards*p.guard_pawn,caps[0]);
        b.side_points[c][1]=std::min(
            f.king_attacked*p.pressure_king+f.occupied_ring*p.pressure_occupied+
            f.denied_empty*p.pressure_empty+f.partners*p.pressure_partner,caps[1]);
        b.side_points[c][2]=std::min(
            f.major_mobility*p.mobility_major+f.minor_mobility*p.mobility_minor,caps[2]);
        b.side_points[c][3]=std::min(
            int(std::int64_t(f.exposure)*p.danger_numerator/p.danger_denominator),caps[3]);

        if(p.v2_enabled) {
            f.v2=v2_features(s,a,p,c);
            b.side_points[c][4]=f.v2.influence;
            b.side_points[c][5]=f.v2.potential;
            b.side_points[c][6]=f.v2.coordination;
            b.side_points[c][7]=f.v2.hand_potential;
            b.side_points[c][8]=f.v2.threat;
        }
    }

    for(int i=0;i<4;++i) {
        b.terms[i]=(b.side_points[0][i]-b.side_points[1][i])*p.weights[i]/100;
        if(i==3)b.terms[i]=-b.terms[i];
        b.positional_unclamped+=b.terms[i];
    }
    if(p.v2_enabled) {
        const int extra_weights[5]={p.influence_weight,p.potential_weight,
            p.coordination_weight,p.hand_potential_weight,p.threat_weight};
        for(int i=4;i<9;++i) {
            b.terms[i]=(b.side_points[0][i]-b.side_points[1][i])*extra_weights[i-4]/100;
            b.positional_unclamped+=b.terms[i];
        }
    }

    b.positional=std::clamp(b.positional_unclamped,-p.positional_cap,p.positional_cap);
    b.total=std::clamp(b.material_term+b.positional,-p.StaticLimit,p.StaticLimit);
    b.clamp_adjustment=b.total-b.material_term-b.positional_unclamped;
    return b;
}
struct MaterialEvaluator {
    int operator()(const rules::Snapshot& s) const {return material_black(s);}
};
class FeatureEvaluator {
public:
    explicit FeatureEvaluator(EvaluationParameters p={}):params_(p){params_.validate();}
    int operator()(const rules::Snapshot& s) const {return evaluate(s,params_).total;}
    const EvaluationParameters& parameters() const {return params_;}
private:
    EvaluationParameters params_;
};
} // namespace shogi::strategy
