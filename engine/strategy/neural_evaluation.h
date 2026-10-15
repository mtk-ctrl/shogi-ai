#pragma once
#include "strategy/material.h"
#include "models/selfplay_net_v217.h"
#include <cmath>

namespace shogi::strategy {
// Independent small MLP from our own fixed-version self-play. Not NNUE and not
// an imported engine model. No search/rule/terminal value is replaced here.
inline double selfplay_probability(const rules::Snapshot& s) {
    float hidden[selfplay_net::Hidden];
    std::copy(std::begin(selfplay_net::b1),std::end(selfplay_net::b1),hidden);
    const auto add=[&](int feature,float value) {
        const auto* weights=selfplay_net::w1+feature*selfplay_net::Hidden;
        for(int j=0;j<selfplay_net::Hidden;++j)hidden[j]+=value*weights[j];
    };
    constexpr int plain[]={-1,0,1,2,3,5,6,4,7};
    constexpr int promoted[]={-1,8,9,10,11,12,13,-1,-1};
    for(int sq=0;sq<81;++sq) {
        const auto& p=s.board[sq];if(!p.kind)continue;
        const int plane=p.promoted ? promoted[p.kind] : plain[p.kind];
        const int row_major=(sq%9)*9+8-sq/9;
        add(row_major*28+int(p.color)*14+plane,1);
    }
    // Python's hand order is P,L,N,S,G,B,R; Snapshot uses P,L,N,S,B,R,G.
    constexpr int hand_order[]={0,1,2,3,5,6,4};
    for(int c=0;c<2;++c)for(int k=0;k<7;++k)if(s.hands[c][k])
        add(81*28+c*7+hand_order[k],s.hands[c][k]/4.0f);
    add(81*28+14,s.turn==rules::Color::Black ? 1.0f : -1.0f);
    double logit=selfplay_net::b2[0];
    for(int j=0;j<selfplay_net::Hidden;++j)
        logit+=std::tanh(hidden[j])*selfplay_net::w2[j];
    return 1.0/(1.0+std::exp(-std::clamp(logit,-40.0,40.0)));
}
inline int blend_selfplay_evaluation(const rules::Snapshot& s,int classical,unsigned percent,int limit) {
    if(!percent)return classical;
    constexpr double temperature=3300.0;
    const double prior=1.0/(1.0+std::exp(-std::clamp(classical/temperature,-40.0,40.0)));
    const double w=std::min(percent,100u)/100.0;
    const double mixed=std::clamp((1-w)*prior+w*selfplay_probability(s),1e-9,1-1e-9);
    return std::clamp(int(std::lround(temperature*std::log(mixed/(1-mixed)))),-limit,limit);
}
} // namespace shogi::strategy
