#pragma once
#include "strategy/attack_map.h"
#include <array>
#include <algorithm>

namespace shogi::strategy {
// Research evaluation. All arrival times are local geometric estimates, not
// mate/forcing-line proofs. Ordinary legal search remains the final judge.
struct InfluenceParameters {
    std::array<int,5> guard_points{0,6,16,22,24};
    int outer_guard_percent=50, guard_cap=60;
    int pressure_per_surplus=12, surplus_cap=3, site_cap=60, pressure_cap=100;
    int weight=150;
};
struct InfluenceSide {
    int guard=0, pressure=0, overloads=0, pinned=0;
    int reinforcement_one=0, reinforcement_two=0, reinforcement_unknown=0;
    int fastest_threat=0; // 0=unknown, otherwise estimated own moves (1/2).
    std::array<int,2> sites{-1,-1};
};
struct InfluenceBreakdown { std::array<InfluenceSide,2> side{}; };

inline int influence_distance(int a,int b) {
    if(a<0||b<0)return 99;
    return std::max(std::abs(a/9-b/9),std::abs(a%9-b%9));
}
inline bool influence_attacks(const rules::Snapshot& s,const rules::Piece& p,
                              int from,int to,int vacated=-1) {
    if(from==to||from<0||to<0||!p.kind)return false;
    const int df=to/9-from/9, dr=to%9-from%9;
    const int fw=int(p.color)==0?-1:1, fdr=dr*fw;
    bool slider=false, reaches=false;
    if(p.kind==7||(p.promoted&&p.kind<=4))
        reaches=(fdr==1&&std::abs(df)<=1)||(dr==0&&std::abs(df)==1)||(df==0&&fdr==-1);
    else switch(p.kind) {
        case 1: reaches=df==0&&fdr==1;break;
        case 2: reaches=df==0&&fdr>0;slider=reaches;break;
        case 3: reaches=std::abs(df)==1&&fdr==2;break;
        case 4: reaches=(fdr==1&&std::abs(df)<=1)||(fdr==-1&&std::abs(df)==1);break;
        case 5: slider=std::abs(df)==std::abs(dr);reaches=slider||(p.promoted&&std::abs(df)+std::abs(dr)==1);break;
        case 6: slider=df==0||dr==0;reaches=slider||(p.promoted&&std::abs(df)==1&&std::abs(dr)==1);break;
        case 8: reaches=std::max(std::abs(df),std::abs(dr))==1;break;
    }
    if(!reaches||!slider)return reaches;
    const int dx=(df>0)-(df<0),dy=(dr>0)-(dr<0);
    for(int f=from/9+dx,r=from%9+dy;f!=to/9||r!=to%9;f+=dx,r+=dy)
        if(f*9+r!=vacated&&s.board[f*9+r].kind)return false;
    return true;
}

struct EffectiveInfluence {
    // Half-piece units; kings are excluded because their recaptures require
    // destination legality. Pinned pieces retain only attacks on their pin ray.
    std::array<std::array<int,81>,2> units{};
    std::array<int,81> pin_df{},pin_dr{},unit{};
    std::array<int,2> overloads{},pinned{};
    EffectiveInfluence(const rules::Snapshot& s,const AttackMap& a) {
        for(int side=0;side<2;++side) {
            const int king=a.kings[side];if(king<0)continue;
            for(int df=-1;df<=1;++df)for(int dr=-1;dr<=1;++dr) {
                if(!df&&!dr)continue;
                int blocker=-1;
                for(int f=king/9+df,r=king%9+dr;f>=0&&f<9&&r>=0&&r<9;f+=df,r+=dr) {
                    int at=f*9+r;const auto& p=s.board[at];if(!p.kind)continue;
                    if(blocker<0&&int(p.color)==side&&p.kind!=8){blocker=at;continue;}
                    if(blocker>=0&&int(p.color)!=side&&
                       influence_attacks(s,p,at,king,blocker)) {
                        pin_df[blocker]=df;pin_dr[blocker]=dr;++pinned[side];
                    }
                    break;
                }
            }
        }
        auto allowed=[&](int from,int to) {
            return !(pin_df[from]||pin_dr[from])||
                (to/9-from/9)*pin_dr[from]==(to%9-from%9)*pin_df[from];
        };
        for(int from=0;from<81;++from) {
            const auto& p=s.board[from];if(!p.kind||p.kind==8)continue;
            unit[from]=2;
            for(int j=0;j<a.sizes[from];++j)if(allowed(from,a.targets[from][j]))
                units[int(p.color)][a.targets[from][j]]+=2;
        }
        // A sole defender simultaneously supporting two attacked valuable/king
        // zone pieces is provisionally half effective, not arbitrarily exempt.
        for(int from=0;from<81;++from) {
            const auto& p=s.board[from];if(!unit[from])continue;
            const int side=int(p.color);int responsibilities=0;
            for(int j=0;j<a.sizes[from];++j) {
                int to=a.targets[from][j];const auto& q=s.board[to];
                if(!allowed(from,to)||!q.kind||q.kind==8||int(q.color)!=side)continue;
                if(units[1-side][to]>0&&units[side][to]==2&&
                   (piece_value(q.kind,q.promoted)>=500||influence_distance(to,a.kings[side])<=1))
                    ++responsibilities;
            }
            if(responsibilities>=2){unit[from]=1;++overloads[side];}
        }
        for(auto& row:units)row.fill(0);
        for(int from=0;from<81;++from)if(unit[from])
            for(int j=0;j<a.sizes[from];++j)if(allowed(from,a.targets[from][j]))
                units[int(s.board[from].color)][a.targets[from][j]]+=unit[from];
    }
    bool movable(int from,int to)const {
        return !(pin_df[from]||pin_dr[from])||
            (to/9-from/9)*pin_dr[from]==(to%9-from%9)*pin_df[from];
    }
};

inline bool influence_drop_allowed(const rules::Snapshot& s,int side,int kind,int at) {
    if(s.board[at].kind)return false;
    const int last=side==0?0:8, rank=at%9;
    if((kind==1||kind==2)&&rank==last)return false;
    if(kind==3&&(side==0?rank<=1:rank>=7))return false;
    if(kind==1)for(int r=0;r<9;++r) {
        const auto& p=s.board[at/9*9+r];
        if(p.kind==1&&!p.promoted&&int(p.color)==side)return false;
    }
    return true;
}

// Local reinforcement reachability in one/two OWN moves on the current board.
// Only new contributors count. Vacated squares are transparent to the moved
// piece. No opponent response, opening a pin, forced check evasion, exchanges,
// or pawn-drop mate is proved here. Unknown arrival keeps multiplier neutral.
inline int influence_arrival(const rules::Snapshot& s,const AttackMap& a,
                             const EffectiveInfluence& e,int side,int target) {
    auto useful=[&](const rules::Piece& p,int at,int vacated) {
        // Avoid claiming a checking drop as reinforcement: uchifuzume and
        // check evasion need the real rules/search, not geometric inference.
        if(influence_attacks(s,p,at,a.kings[1-side],vacated))return false;
        return influence_attacks(s,p,at,target,vacated);
    };
    // Hand support is independent of origin and cannot expose the own king.
    // When already checked, treat arrival as unknown unless ordinary search
    // proves a response; this estimate is intentionally not a legal generator.
    if(a.kings[side]>=0&&a.count[1-side][a.kings[side]]>0)return 0;
    for(int kind=1;kind<=7;++kind)if(s.hands[side][kind-1]>0) {
        rules::Piece p{kind,side==0?rules::Color::Black:rules::Color::White,false};
        for(int at=0;at<81;++at)if(influence_drop_allowed(s,side,kind,at)&&
            (!a.count[1-side][at]||a.least[1-side][at]>=piece_value(kind,false))&&useful(p,at,-1))return 1;
    }
    int best=0;
    for(int from=0;from<81;++from) {
        const auto& p=s.board[from];if(!p.kind||p.kind==8||int(p.color)!=side)continue;
        if(influence_attacks(s,p,from,target)&&e.movable(from,target))continue;
        for(int j=0;j<a.sizes[from];++j) {
            int mid=a.targets[from][j];
            // Quiet, non-promoting paths only. Unknown is preferable to
            // inventing legal capture/promoting/checking reinforcement paths.
            if(s.board[mid].kind||!e.movable(from,mid))continue;
            if((p.kind==1||p.kind==2)&&!p.promoted&&mid%9==(side==0?0:8))continue;
            if(p.kind==3&&!p.promoted&&(side==0?mid%9<=1:mid%9>=7))continue;
            if(a.count[1-side][mid]&&a.least[1-side][mid]<piece_value(p.kind,p.promoted))continue;
            if(useful(p,mid,from))return 1;
            if(best==2)continue;
            // Second step is a reachability estimate; original pin constraints
            // remain in force and the original square is treated as vacated.
            for(int at=0;at<81;++at) {
                if(s.board[at].kind&&at!=from)continue;
                if(!e.movable(from,at)||!influence_attacks(s,p,mid,at,from))continue;
                if((p.kind==1||p.kind==2)&&!p.promoted&&at%9==(side==0?0:8))continue;
                if(p.kind==3&&!p.promoted&&(side==0?at%9<=1:at%9>=7))continue;
                if(a.count[1-side][at]&&a.least[1-side][at]<piece_value(p.kind,p.promoted))continue;
                if(useful(p,at,from)){best=2;break;}
            }
        }
    }
    return best;
}

inline InfluenceBreakdown influence_features(const rules::Snapshot& s,const AttackMap& a,
                                             const InfluenceParameters& p) {
    InfluenceBreakdown out;EffectiveInfluence e(s,a);
    struct Site {int square,base,arrival;};
    std::array<std::array<Site,81>,2> sites{};std::array<int,2> sizes{};
    for(int side=0;side<2;++side) {
        auto& r=out.side[side];r.overloads=e.overloads[side];r.pinned=e.pinned[side];
        for(int at=0;at<81;++at) {
            const auto& q=s.board[at];int d=influence_distance(at,a.kings[side]);
            if(q.kind&&q.kind!=8&&int(q.color)==side&&d<=2) {
                int u=std::min(e.units[side][at],8), n=u/2;
                int points=p.guard_points[n];
                if((u%2)&&n<4)points+=(p.guard_points[n+1]-points)/2;
                r.guard+=d<=1?points:points*p.outer_guard_percent/100;
            }
            if(influence_distance(at,a.kings[1-side])>2||q.kind==8||
               (q.kind&&int(q.color)==side))continue;
            // Occupied squares are exchange sites. Empty squares only count
            // inside the immediate king ring, as prospective invasion sites.
            if(!q.kind&&influence_distance(at,a.kings[1-side])>1)continue;
            int surplus=std::clamp(e.units[side][at]-e.units[1-side][at],0,2*p.surplus_cap);
            if(!surplus)continue;
            // A rook vs pawn is not automatically a favorable exchange even
            // with a numerical edge. Preserve ordinary Danger/search handling.
            if(q.kind&&a.least[side][at]>piece_value(q.kind,q.promoted)&&e.units[1-side][at]>0)continue;
            int base=p.pressure_per_surplus*surplus/2;
            if(influence_distance(at,a.kings[1-side])==2)base/=2;
            if(base>0)sites[side][sizes[side]++]={at,base,0};
        }
        r.guard=std::min(r.guard,p.guard_cap);
        std::sort(sites[side].begin(),sites[side].begin()+sizes[side],
            [](const Site& x,const Site& y){return x.base>y.base||(x.base==y.base&&x.square<y.square);});
        // Equal-priority ties must not depend on board orientation. Include all
        // tied sites in averaging, then cap concentration, rather than choosing
        // a coordinate-first target that breaks color/rotation symmetry.
        int first=-1,second=-1;
        if(sizes[side])first=sites[side][0].base;
        for(int i=0;i<sizes[side];++i)if(sites[side][i].base<first){second=sites[side][i].base;break;}
        int sum_first=0,n_first=0,sum_second=0,n_second=0;
        for(int i=0;i<sizes[side];++i) {
            auto& t=sites[side][i];if(t.base!=first&&t.base!=second)continue;
            int arrival=influence_arrival(s,a,e,1-side,t.square);t.arrival=arrival;
            // An arrival in one own move is potentially timely; two moves is
            // slower. Unreachable in this approximation is unknown, not 2x.
            int multiplier=arrival==2?150:100;
            int points=std::min(p.site_cap,t.base*multiplier/100);
            if(t.base==first){sum_first+=points;++n_first;}
            else{sum_second+=points;++n_second;}
            if(arrival==1)++r.reinforcement_one;
            else if(arrival==2)++r.reinforcement_two;else ++r.reinforcement_unknown;
        }
        // Nearby targets are one front; using the best tier plus half of the
        // next tier prevents the same pieces scoring a full bonus repeatedly.
        r.pressure=(n_first?sum_first/n_first:0)+(n_second?sum_second/n_second/2:0);
        r.pressure=std::min(r.pressure,p.pressure_cap);
        if(sizes[side])r.fastest_threat=1;
        else {
            // Only estimate a future threat on immediately contested king-ring
            // squares; absence is unknown, not a declaration that no attack exists.
            int king=a.kings[1-side];
            if(king>=0)for(int df=-1;df<=1&&r.fastest_threat==0;++df)
                for(int dr=-1;dr<=1&&r.fastest_threat==0;++dr) {
                    int f=king/9+df,row=king%9+dr;if(f<0||f>=9||row<0||row>=9||(!df&&!dr))continue;
                    int at=f*9+row;
                    if(e.units[side][at]>0&&e.units[side][at]>=e.units[1-side][at]&&
                       influence_arrival(s,a,e,side,at)==1)r.fastest_threat=2;
                }
        }
    }
    for(int side=0;side<2;++side) {
        int mine=out.side[side].fastest_threat,theirs=out.side[1-side].fastest_threat;
        int tempo=mine&&theirs?(mine<theirs?150:mine>theirs?50:100):100;
        out.side[side].pressure=std::min(p.pressure_cap,out.side[side].pressure*tempo/100);
    }
    return out;
}
} // namespace shogi::strategy
