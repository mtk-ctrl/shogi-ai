#pragma once
#include "strategy/attack_map.h"
#include "strategy/selfplay_order_weights.h"
#include <array>
#include <cstdint>
#include <string>

namespace shogi::strategy {
// All features use the moving side's perspective. Integer units are eighths;
// weights are logits * 10000 / 8. No evaluator or external teacher is used.
inline std::array<int,64> selfplay_order_features(const rules::Snapshot& s,
                                                const AttackMap& a,
                                                const std::string& m) {
    std::array<int,64> x{};
    if(m.size()<4)return x;
    const int to=(m[2]-'1')*9+m[3]-'a';
    if(to<0 || to>=81)return x;
    const bool drop=m[1]=='*';
    const int from=drop ? -1 : (m[0]-'1')*9+m[1]-'a';
    if(!drop && (from<0 || from>=81))return x;
    const int side=int(s.turn), enemy=1-side;
    int kind=drop ? 0 : s.board[from].kind;
    if(drop)switch(m[0]){case 'P':kind=1;break;case 'L':kind=2;break;
      case 'N':kind=3;break;case 'S':kind=4;break;case 'B':kind=5;break;
      case 'R':kind=6;break;case 'G':kind=7;break;default:return x;}
    if(kind<1 || kind>8)return x;
    const bool promoted=!drop && s.board[from].promoted;
    const int captured=s.board[to].kind;
    const int rank=side==0 ? 8-to%9 : to%9;
    const int centre=4-std::abs(to/9-4);
    const int ek=a.kings[enemy], ok=a.kings[side];
    const int ed=ek<0 ? 8 : a.distance(to,ek), od=ok<0 ? 8 : a.distance(to,ok);
    const int approach=drop || ek<0 ? 0 : a.distance(from,ek)-ed;
    const int advance=drop ? 0 : (side==0 ? from%9-to%9 : to%9-from%9);
    x[kind-1]=8;
    if(captured>0 && captured<=8)x[8+captured-1]=8;
    if(promoted)x[16+kind-1]=8;
    x[24]=drop*8; x[25]=(m.size()==5 && m[4]=='+')*8;
    x[26]=std::min(3,a.count[side][to])*4;
    x[27]=std::min(3,a.count[enemy][to])*4;
    x[28]=from<0 ? 0 : std::min(3,a.count[enemy][from])*4;
    x[29]=from<0 ? 0 : std::min(3,a.count[side][from])*4;
    x[30]=rank; x[31]=centre*2;
    x[32]=8-ed; x[33]=8-od; x[34]=approach; x[35]=advance;
    x[36]=(captured && a.count[enemy][to]==0)*8;
    x[37]=(a.count[enemy][to]>0 && a.count[side][to]==0)*8;
    x[38]=(kind==8 && a.count[enemy][to]>0)*8;
    x[39]=(captured && s.board[to].promoted)*8;
    // Piece-specific square and king approach preferences generalize beyond
    // exact positions while keeping extraction independent of candidate count.
    x[40+kind-1]=rank;
    x[48+kind-1]=centre*2;
    x[56+kind-1]=8-ed;
    return x;
}
inline int selfplay_order_bonus(const rules::Snapshot& s,const AttackMap& a,
                               const std::string& m,int scale) {
    if(!SelfplayOrderReady || scale<=0)return 0;
    const auto x=selfplay_order_features(s,a,m);
    std::int64_t dot=0;
    for(std::size_t i=0;i<x.size();++i)dot+=std::int64_t(x[i])*SelfplayOrderWeights[i];
    // A unit logit at 100% contributes one million ordering units. Existing
    // check/TT/knowledge priorities remain stronger; no legal move is removed.
    return static_cast<int>(std::clamp<std::int64_t>(dot*scale,-20000000,20000000));
}
}
