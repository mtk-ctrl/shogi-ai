#pragma once
#include "strategy/attack_map.h"
#include "strategy/evaluation_params.h"
#include <cstdint>

namespace shogi::strategy {
struct SideFeatures {
    int gold_guards=0, silver_guards=0, pawn_guards=0;
    int king_attacked=0, occupied_ring=0, denied_empty=0, partners=0;
    int major_mobility=0, minor_mobility=0;
    int latent_major_mobility=0, latent_lance_mobility=0;
    int exposure=0;
};
struct EvaluationBreakdown {
    int material=0;
    std::array<SideFeatures,2> raw{};
    std::array<std::array<int,5>,2> side_points{};
    // Signed Black-minus-White terms; danger already has its minus sign.
    // terms[4] is Potential Mobility and is positive when Black has more.
    std::array<int,5> terms{};
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
inline bool potential_safe_empty(const rules::Snapshot& s, const AttackMap& a,
                                 int side, int sq, int value) {
    if(s.board[sq].kind || AttackMap::near(sq,a.kings[0]) || AttackMap::near(sq,a.kings[1])) return false;
    return !(a.count[1-side][sq] && a.least[1-side][sq] < value);
}

// Count squares a slider could gain after ONE quiet, reasonably safe move by
// its first friendly blocker.  If that blocker merely advances along the same
// ray (e.g. a pawn in front of a rook/lance), only the newly exposed squares
// before its new square are counted.  This avoids pretending the whole ray is
// open when the blocker still sits on it.
inline int latent_ray_after_blocker_move(const rules::Snapshot& s, const AttackMap& a,
                                         int side, int from, int df, int dr, int slider_value) {
    const int ff=from/9, rr=from%9;
    int bx=ff+df, by=rr+dr, blocker_step=1;
    while(bx>=0&&bx<9&&by>=0&&by<9&&!s.board[bx*9+by].kind) {
        bx+=df;by+=dr;++blocker_step;
    }
    if(bx<0||bx>=9||by<0||by>=9)return 0;
    const int blocker=bx*9+by;
    const auto& bp=s.board[blocker];
    if(!bp.kind || bp.kind==8 || int(bp.color)!=side)return 0;
    const int blocker_value=piece_value(bp.kind,bp.promoted);

    int best=0;
    for(int j=0;j<a.sizes[blocker];++j) {
        const int target=a.targets[blocker][j];
        if(!potential_safe_empty(s,a,side,target,blocker_value))continue;

        const int tx=target/9, ty=target%9;
        int target_step=-1;
        for(int step=1,x=ff+df,y=rr+dr;x>=0&&x<9&&y>=0&&y<9;x+=df,y+=dr,++step) {
            if(x==tx&&y==ty){target_step=step;break;}
        }
        // Moving closer to the slider on the same ray does not unlock it.
        if(target_step>0 && target_step<blocker_step)continue;

        int gained=0;
        for(int step=blocker_step,x=bx,y=by;x>=0&&x<9&&y>=0&&y<9;x+=df,y+=dr,++step) {
            if(step!=blocker_step && s.board[x*9+y].kind)break;
            if(target_step==step)break; // blocker moved here and still closes the ray.
            const int sq=x*9+y;
            // The original blocker square becomes empty after the hypothetical move.
            if(step==blocker_step || !s.board[sq].kind) {
                if(!AttackMap::near(sq,a.kings[0]) && !AttackMap::near(sq,a.kings[1])
                   && !(a.count[1-side][sq] && a.least[1-side][sq] < slider_value))
                    ++gained;
            }
        }
        best=std::max(best,gained);
    }
    return best;
}

inline void potential_mobility_features(const rules::Snapshot& s, const AttackMap& a,
                                        int side, const EvaluationParameters& p, SideFeatures& out) {
    for(int sq=0;sq<81;++sq) {
        const auto& piece=s.board[sq];
        if(!piece.kind || int(piece.color)!=side)continue;
        int n=0;
        const int value=piece_value(piece.kind,piece.promoted);
        auto add=[&](int df,int dr){n+=latent_ray_after_blocker_move(s,a,side,sq,df,dr,value);};
        if(piece.kind==5) {
            for(int df:{-1,1})for(int dr:{-1,1})add(df,dr);
        } else if(piece.kind==6) {
            add(-1,0);add(1,0);add(0,-1);add(0,1);
        } else if(piece.kind==2 && !piece.promoted) {
            add(0,side==0?-1:1);
        } else continue;
        n=std::min(n,p.potential_piece_cap);
        if(piece.kind==5||piece.kind==6)out.latent_major_mobility+=n;
        else out.latent_lance_mobility+=n;
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
    if(std::all_of(p.weights.begin(),p.weights.end(),[](int w){return w==0;})){
        b.total=b.material;return b;
    }
    AttackMap a(s);
    for(int c=0;c<2;++c) {
        auto& f=b.raw[c];
        king_safety_features(s,a,c,f);pressure_features(s,a,c,f);
        activity_features(s,a,c,p,f);
        if(p.weights[4])potential_mobility_features(s,a,c,p,f);
        danger_features(s,a,c,f);
        b.side_points[c]={
            f.gold_guards*p.guard_gold+f.silver_guards*p.guard_silver+f.pawn_guards*p.guard_pawn,
            f.king_attacked*p.pressure_king+f.occupied_ring*p.pressure_occupied+
                f.denied_empty*p.pressure_empty+f.partners*p.pressure_partner,
            f.major_mobility*p.mobility_major+f.minor_mobility*p.mobility_minor,
            int(std::int64_t(f.exposure)*p.danger_numerator/p.danger_denominator),
            f.latent_major_mobility*p.potential_major+f.latent_lance_mobility*p.potential_lance};
        for(int i=0;i<5;++i)b.side_points[c][i]=std::min(b.side_points[c][i],p.caps[i]);
    }
    for(int i=0;i<5;++i) {
        b.terms[i]=(b.side_points[0][i]-b.side_points[1][i])*p.weights[i]/100;
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
