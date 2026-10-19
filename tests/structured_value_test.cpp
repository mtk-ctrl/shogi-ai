// Header-only semantic regression: evaluation must not depend on an optional
// occupied-square or geometry optimization. No external search/teacher.
#include "strategy/structured_value.h"
#include <cassert>
#include <iostream>
#include <random>
using namespace shogi;
int main(){
    std::mt19937 random(2080101901);
    for(int trial=0;trial<128;++trial) {
        rules::Snapshot s;
        s.board[44]={8,rules::Color::Black,false};
        s.board[36]={8,rules::Color::White,false};
        for(int n=0;n<28;++n) {
            int sq=int(random()%81);if(s.board[sq].kind)continue;
            int kind=1+int(random()%7);
            s.board[sq]={kind,random()%2 ? rules::Color::Black : rules::Color::White,
                         kind<=6 && random()%4==0};
        }
        for(int side=0;side<2;++side)for(int k=0;k<7;++k)s.hands[side][k]=int(random()%3);
        const int maturity=int(random()%101);
        std::array<int,strategy::StructuredFeatureCount> reference{};
        strategy::AttackMap indexed(s,true,true);
        strategy::structured_features(s,indexed,maturity,[&](int i,int v){reference[i]+=v;});
        for(int mask=0;mask<8;++mask) {
            strategy::AttackMap a(s,mask&1,mask&2,mask&4);
            std::array<int,strategy::StructuredFeatureCount> actual{};
            strategy::structured_features(s,a,maturity,[&](int i,int v){actual[i]+=v;});
            assert(actual==reference);
            for(int scale:{50,100,150})
                assert(strategy::structured_value(s,a,maturity,scale)==strategy::structured_value(s,indexed,maturity,scale));
        }
    }
    std::cout<<"PASS 128 snapshots, all eight attack-map modes, all three learned scales\n";
}
