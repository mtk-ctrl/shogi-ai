#pragma once
#include "strategy/material.h"
#include <array>
#include <algorithm>
#include <limits>
#include <cstdint>

namespace shogi::strategy {
// Geometric attacks, including friendly-occupied endpoints. Not legal moves:
// pins, drops and king capture legality belong to the rules layer.
struct AttackMap {
    static constexpr int NoAttacker = std::numeric_limits<int>::max();
    std::array<std::array<int, 81>, 2> count{}, nonking{}, least{};
    // Ordinary attacks plus slider x-rays THROUGH the enemy king, used ONLY
    // for estimating empty escape-square denial after that king moves.
    std::array<std::array<bool, 81>, 2> escape_control{};
    std::array<std::array<std::uint8_t, 32>, 81> targets{};
    std::array<std::uint8_t, 81> sizes{};
    std::array<int, 2> kings{-1, -1};

    explicit AttackMap(const rules::Snapshot& s) {
        for (auto& row : least) row.fill(NoAttacker);
        for (int from = 0; from < 81; ++from) {
            const auto& p = s.board[from];
            if (!p.kind) continue;
            const int side = int(p.color), f = from / 9, r = from % 9;
            if (p.kind == 8) kings[side] = from;
            const int value = p.kind == 8 ? NoAttacker : piece_value(p.kind, p.promoted);
            auto ray = [&](int df, int dr, bool sliding) {
                bool through_king = false;
                for (int x=f+df,y=r+dr; x>=0 && x<9 && y>=0 && y<9; x+=df,y+=dr) {
                    const int to=x*9+y;
                    const auto& q=s.board[to];
                    if (p.kind != 8) escape_control[side][to]=true;
                    if (!through_king) {
                        ++count[side][to];
                        if (p.kind != 8) ++nonking[side][to];
                        least[side][to]=std::min(least[side][to],value);
                        targets[from][sizes[from]++]=static_cast<std::uint8_t>(to);
                    }
                    if (!sliding) break;
                    if (q.kind) {
                        if (!through_king && q.kind==8 && q.color!=p.color) through_king=true;
                        else break;
                    }
                }
            };
            const int fw=side==0 ? -1 : 1;
            const bool gold = p.kind==7 || (p.promoted && p.kind<=4);
            if (gold) {
                for(int df=-1;df<=1;++df) ray(df,fw,false);
                ray(-1,0,false);ray(1,0,false);ray(0,-fw,false);
            } else switch(p.kind) {
                case 1: ray(0,fw,false); break;
                case 2: ray(0,fw,true); break;
                case 3: ray(-1,2*fw,false);ray(1,2*fw,false); break;
                case 4:
                    for(int df=-1;df<=1;++df) ray(df,fw,false);
                    ray(-1,-fw,false);ray(1,-fw,false);break;
                case 5:
                    for(int df:{-1,1}) for(int dr:{-1,1}) ray(df,dr,true);
                    if(p.promoted){ray(-1,0,false);ray(1,0,false);ray(0,-1,false);ray(0,1,false);}
                    break;
                case 6:
                    ray(-1,0,true);ray(1,0,true);ray(0,-1,true);ray(0,1,true);
                    if(p.promoted)for(int df:{-1,1})for(int dr:{-1,1})ray(df,dr,false);
                    break;
                case 8:
                    for(int df=-1;df<=1;++df)for(int dr=-1;dr<=1;++dr)
                        if(df||dr)ray(df,dr,false);
                    break;
            }
        }
    }
    static bool near(int a, int b) {
        return a>=0 && b>=0 && std::abs(a/9-b/9)<=1 && std::abs(a%9-b%9)<=1;
    }
};
} // namespace shogi::strategy
