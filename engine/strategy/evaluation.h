#pragma once
#include "strategy/attack_map.h"
#include "strategy/evaluation_params.h"
#include <cstdint>

namespace shogi::strategy {
struct SideFeatures {
    int gold_guards=0, silver_guards=0, pawn_guards=0;
    int king_attacked=0, occupied_ring=0, denied_empty=0, partners=0;
    int major_mobility=0, minor_mobility=0;
    int exposure=0;
};
struct EvaluationBreakdown {
    InfluenceBreakdown influence{};
    int material=0;
    std::array<SideFeatures,2> raw{};
    std::array<std::array<int,4>,2> side_points{};
    // Signed Black-minus-White terms; danger already has its minus sign.
    std::array<int,4> terms{};
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
        const auto& p=s.board[sq];
        if(!p.kind || p.kind==8 || int(p.color)!=side || !a.count[1-side][sq])continue;
        const int value=piece_value(p.kind,p.promoted);
        out.exposure += a.count[side][sq] ? std::max(0,value-a.least[1-side][sq]) : value;
    }
}
inline EvaluationBreakdown evaluate(const rules::Snapshot& s,
                                     const EvaluationParameters& p=EvaluationParameters{}) {
    EvaluationBreakdown b;
    b.material=material_black(s);
    if(!p.influence_enabled&&std::all_of(p.weights.begin(),p.weights.end(),[](int w){return w==0;})){
        b.total=b.material;return b;
    }
    AttackMap a(s);
    for(int c=0;c<2;++c) {
        auto& f=b.raw[c];
        king_safety_features(s,a,c,f);pressure_features(s,a,c,f);
        activity_features(s,a,c,p,f);danger_features(s,a,c,f);
        b.side_points[c]={
            f.gold_guards*p.guard_gold+f.silver_guards*p.guard_silver+f.pawn_guards*p.guard_pawn,
            f.king_attacked*p.pressure_king+f.occupied_ring*p.pressure_occupied+
                f.denied_empty*p.pressure_empty+f.partners*p.pressure_partner,
            f.major_mobility*p.mobility_major+f.minor_mobility*p.mobility_minor,
            int(std::int64_t(f.exposure)*p.danger_numerator/p.danger_denominator)};
        for(int i=0;i<4;++i)b.side_points[c][i]=std::min(b.side_points[c][i],p.caps[i]);
    }
    const auto legacy_side_points=b.side_points;
    if(p.influence_enabled) {
        b.influence=influence_features(s,a,p.influence);
        for(int side=0;side<2;++side) {
            b.side_points[side][0]=b.influence.side[side].guard;
            b.side_points[side][1]=b.influence.side[side].pressure;
        }
    }
    for(int i=0;i<4;++i) {
        int weight=p.influence_enabled&&i<2?p.influence.weight:p.weights[i];
        if(p.influence_enabled&&i==0&&p.influence.guard_weight>=0)weight=p.influence.guard_weight;
        if(p.influence_enabled&&i==1&&p.influence.pressure_weight>=0)weight=p.influence.pressure_weight;
        b.terms[i]=(b.side_points[0][i]-b.side_points[1][i])*weight/100;
        if(p.influence_enabled&&i<2) {
            int old=(legacy_side_points[0][i]-legacy_side_points[1][i])*p.weights[i]/100;
            b.terms[i]=(b.terms[i]*(100-p.influence.legacy_mix)+old*p.influence.legacy_mix)/100;
        }
        if(i==3)b.terms[i]=-b.terms[i];
        b.positional_unclamped+=b.terms[i];
    }
    b.positional=std::clamp(b.positional_unclamped,-p.positional_cap,p.positional_cap);
    b.total=std::clamp(b.material+b.positional,-p.StaticLimit,p.StaticLimit);
    b.clamp_adjustment=b.total-b.material-b.positional_unclamped;
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
