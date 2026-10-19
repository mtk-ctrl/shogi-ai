#pragma once
// Own-game learned positional residual. It adds no legal-move restrictions,
// changes no search/time policy, and uses the evaluator's existing AttackMap.
#include "strategy/attack_map.h"
#include "strategy/structured_value_weights.h"
#include <array>
#include <cstdint>

namespace shogi::strategy {
inline constexpr int StructuredPieceTypes=14;
inline constexpr int StructuredPst=0;
inline constexpr int StructuredKing=1134;
inline constexpr int StructuredHand=1386;
inline constexpr int StructuredAttack=1421;
inline constexpr int StructuredMobility=1547;
inline constexpr int StructuredBaseFeatures=1631;
inline constexpr int StructuredFeatureCount=4893;
static_assert(StructuredValueWeights.size()==StructuredFeatureCount);

inline std::array<int,3> structured_stage_weights(int maturity) {
    int m=std::clamp(maturity,0,100);
    return {std::max(0,50-m)*2,100-std::abs(m-50)*2,std::max(0,m-50)*2};
}
template<class Emit>
inline void structured_base_features(const rules::Snapshot& s,const AttackMap& a,Emit emit) {
    for(int side=0;side<2;++side) {
        const int sign=side==0 ? 1 : -1;
        for(int sq:a.squares(side)) {
            const auto& p=s.board[sq];
            const int type=p.promoted ? p.kind+7 : p.kind-1;
            if(type<0 || type>=StructuredPieceTypes)continue;
            const int normalized=side==0 ? sq : 80-sq;
            emit(StructuredPst+type*81+normalized,sign);
            for(int relation=0;relation<2;++relation) {
                const int king=a.kings[relation ? 1-side : side];
                const int d=king<0 ? 8 : a.distance(sq,king);
                emit(StructuredKing+(relation*14+type)*9+d,sign);
            }
            const int defenders=std::min(2,a.nonking[side][sq]);
            const int attackers=std::min(2,a.nonking[1-side][sq]);
            emit(StructuredAttack+type*9+defenders*3+attackers,sign);
            emit(StructuredMobility+type*6+std::min(5,int(a.sizes[sq])/4),sign);
        }
        for(int kind=0;kind<7;++kind) {
            // Count thresholds, not just presence: learning can distinguish
            // the first reusable piece from additional pieces of the same type.
            for(int n=0;n<std::min(5,s.hands[side][kind]);++n)
                emit(StructuredHand+kind*5+n,sign);
        }
    }
}
template<class Emit>
inline void structured_features(const rules::Snapshot& s,const AttackMap& a,int maturity,Emit emit) {
    const auto phase=structured_stage_weights(maturity);
    structured_base_features(s,a,[&](int index,int sign) {
        for(int stage=0;stage<3;++stage)if(phase[stage])
            emit(stage*StructuredBaseFeatures+index,sign*phase[stage]);
    });
}
inline int structured_value(const rules::Snapshot& s,const AttackMap& a,int maturity,int scale) {
    if(!StructuredValueReady || scale<0)return 0;
    std::int64_t parent=0,delta=0;
    structured_features(s,a,maturity,[&](int index,int value) {
        parent+=std::int64_t(StructuredParentWeights[index])*value;
        delta+=std::int64_t(StructuredValueWeights[index])*value;
    });
    // cp/64, with new deltas rounded to multiples of four so the declared
    // 50/100/150% choices can be materialized exactly into the next parent.
    const auto dot=parent*100+delta*scale;
    return static_cast<int>(std::clamp<std::int64_t>(dot,-1200LL*640000,1200LL*640000)/640000);
}
}
