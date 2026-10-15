#pragma once
#include "strategy/material.h"
#include <array>
#include <algorithm>
#include <limits>
#include <cstdint>

namespace shogi::strategy {
inline constexpr auto SquareDistances = [] {
    std::array<std::array<std::uint8_t,81>,81> table{};
    for (int a=0;a<81;++a) for (int b=0;b<81;++b) {
        const int df=a/9-b/9, dr=a%9-b%9;
        table[a][b]=std::max(df<0?-df:df,dr<0?-dr:dr);
    }
    return table;
}();
// Precomputed next-square steps for all 81 squares and all directions (-2..2).
// The actual occupied-square ray cutoff remains calculated at runtime.
inline constexpr auto RayNextSquare = [] {
    std::array<std::array<std::array<std::uint8_t,5>,5>,81> next{};
    for (int from = 0; from < 81; ++from) {
        for (int df = -2; df <= 2; ++df) for (int dr = -2; dr <= 2; ++dr) {
            const int f = from/9 + df, r = from%9 + dr;
            next[from][df+2][dr+2] = df == 0 && dr == 0
                ? 255 : (f>=0 && f<9 && r>=0 && r<9 ? static_cast<std::uint8_t>(f*9+r) : 255);
        }
    }
    return next;
}();
inline constexpr auto AllSquares = [] {
    std::array<std::uint8_t,81> squares{};
    for (int i=0;i<81;++i) squares[i]=i;
    return squares;
}();
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
    std::array<std::array<std::uint8_t,81>,2> occupied{};
    std::array<std::uint8_t,2> occupied_sizes{};
    bool geometry_lookup=false, occupied_index=false, ray_lookup=false;
    struct SquareRange {
        const std::uint8_t* first;
        const std::uint8_t* last;
        auto begin() const { return first; }
        auto end() const { return last; }
    };
    SquareRange squares(int side) const {
        return occupied_index
            ? SquareRange{occupied[side].data(),occupied[side].data()+occupied_sizes[side]}
            : SquareRange{AllSquares.data(),AllSquares.data()+AllSquares.size()};
    }
    int distance(int a,int b) const {
        if(a<0 || b<0)return 99;
        if(geometry_lookup)return SquareDistances[a][b];
        return std::max(std::abs(a/9-b/9),std::abs(a%9-b%9));
    }
    bool near_square(int a,int b) const {
        return geometry_lookup ? distance(a,b)<=1 : near(a,b);
    }

    explicit AttackMap(const rules::Snapshot& s, bool geometry=false, bool index=false,
                       bool ray_table=false)
        : geometry_lookup(geometry),occupied_index(index),ray_lookup(ray_table) {
        for (auto& row : least) row.fill(NoAttacker);
        for (int from = 0; from < 81; ++from) {
            const auto& p = s.board[from];
            if (!p.kind) continue;
            const int side = int(p.color), f = from / 9, r = from % 9;
            if(occupied_index)occupied[side][occupied_sizes[side]++]=from;
            if (p.kind == 8) kings[side] = from;
            const int value = p.kind == 8 ? NoAttacker : piece_value(p.kind, p.promoted);
            auto ray = [&](int df, int dr, bool sliding) {
                bool through_king = false;
                int x=f+df, y=r+dr;
                int next_sq = ray_lookup ? int(RayNextSquare[from][df+2][dr+2]) : -1;
                while (ray_lookup ? next_sq != 255 : (x>=0 && x<9 && y>=0 && y<9)) {
                    const int to = ray_lookup ? next_sq : x*9+y;
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
                    if (ray_lookup) next_sq = RayNextSquare[to][df+2][dr+2];
                    else { x += df; y += dr; }
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
