#include "strategy/evaluation.h"
#include <iostream>
#include <map>
#include <random>
#include <stdexcept>
using namespace shogi;
void require(bool b,const char* msg){if(!b)throw std::runtime_error(msg);}
int sq(const std::string& s){return (s[0]-'1')*9+s[1]-'a';}
rules::Snapshot snap(std::map<std::string,std::string> pieces){
    rules::Snapshot s;std::string names=" PLNSBRGK";
    for(auto [at,p]:pieces){char c=p.back();s.board[sq(at)]={int(names.find(char(std::toupper(c)))),
        std::isupper(c)?rules::Color::Black:rules::Color::White,p[0]=='+'};}return s;
}
rules::Snapshot rotate(const rules::Snapshot& s){
    auto t=s;t.turn=s.turn==rules::Color::Black?rules::Color::White:rules::Color::Black;
    std::swap(t.hands[0],t.hands[1]);
    for(int i=0;i<81;++i){t.board[80-i]=s.board[i];t.board[80-i].color=s.board[i].color==rules::Color::Black?rules::Color::White:rules::Color::Black;}return t;
}
int main(){try{
    using namespace strategy;InfluenceParameters ip;
    auto s=snap({{"5i","K"},{"1a","k"},{"5h","G"},{"4h","G"}});
    AttackMap a(s);EffectiveInfluence e(s,a);
    require(e.units[0][sq("5h")]==2,"one effective defender");
    s.board[sq("6i")]={4,rules::Color::Black,false};AttackMap b(s);EffectiveInfluence f(s,b);
    require(f.units[0][sq("5h")]==4,"two distinct effective defenders");
    require(ip.guard_points[2]-ip.guard_points[1]>ip.guard_points[1],"second defender is more valuable near king");
    auto pinned=snap({{"5i","K"},{"1a","k"},{"5h","G"},{"5a","r"}});
    AttackMap pa(pinned);EffectiveInfluence pe(pinned,pa);
    require(pe.pinned[0]==1&&pe.units[0][sq("4h")]==0&&pe.units[0][sq("5g")]==2,"pinned guard only works along pin line");
    auto overloaded=snap({{"9i","K"},{"1a","k"},{"5e","S"},{"3e","S"},{"4f","G"},{"5a","r"},{"3a","r"}});
    AttackMap oa(overloaded);EffectiveInfluence oe(overloaded,oa);
    require(oe.overloads[0]==1&&oe.unit[sq("4f")]==1,"one guard cannot fully defend two simultaneously attacked valuable pieces");
    auto hand=snap({{"9i","K"},{"1a","k"}});hand.hands[0][0]=1;
    require(influence_drop_allowed(hand,0,1,sq("5e")),"ordinary pawn drop candidate");
    require(!influence_drop_allowed(hand,0,1,sq("5a")),"dead pawn drop excluded");
    hand.board[sq("5g")]={1,rules::Color::Black,false};
    require(!influence_drop_allowed(hand,0,1,sq("5e")),"nifu excluded from reinforcement estimate");
    hand.board[sq("5g")].promoted=true;
    require(influence_drop_allowed(hand,0,1,sq("5e")),"promoted pawn does not cause nifu");
    require(!influence_drop_allowed(hand,0,3,sq("5b")),"dead knight drop excluded");
    auto no_defender=snap({{"9i","K"},{"1a","k"},{"5e","R"}});AttackMap nd(no_defender);EffectiveInfluence ne(no_defender,nd);
    require(influence_arrival(no_defender,nd,ne,1,sq("5e"))==0,"no found arrival is unknown, not proof of impossible reinforcement");
    auto slow=snap({{"9i","K"},{"1a","k"},{"8e","g"}});
    AttackMap sa(slow);EffectiveInfluence se(slow,sa);
    require(influence_arrival(slow,sa,se,1,sq("5e"))==2,"gold reinforcement estimated two own moves away");
    std::swap(slow.board[sq("8e")],slow.board[sq("7e")]);
    AttackMap fa(slow);EffectiveInfluence fe(slow,fa);
    require(influence_arrival(slow,fa,fe,1,sq("5e"))==1,"closer gold reinforcement estimated one own move away");
    slow=snap({{"9i","K"},{"1a","k"}});slow.hands[1][6]=1;
    AttackMap ha(slow);EffectiveInfluence he(slow,ha);
    require(influence_arrival(slow,ha,he,1,sq("5e"))==1,"hand gold provides immediate reinforcement estimate");
    EvaluationParameters p;p.influence_enabled=true;
    std::mt19937 rng(20261006);
    for(int i=0;i<200;++i){
        auto random=snap({{"9i","K"},{"1a","k"}});
        for(int j=0;j<14;++j){int at=rng()%81;if(random.board[at].kind)continue;
            random.board[at]={int(rng()%7+1),rng()%2?rules::Color::Black:rules::Color::White,false};}
        for(auto& row:random.hands)for(int& v:row)v=rng()%2;
        auto x=evaluate(random,p),y=evaluate(rotate(random),p);
        require(x.total==-y.total&&x.material==-y.material,"rotated color swap exactly negates evaluation");
        for(int k=0;k<4;++k)require(x.terms[k]==-y.terms[k],"individual terms are symmetric");
        require(x.total==x.material+x.terms[0]+x.terms[1]+x.terms[2]+x.terms[3]+x.clamp_adjustment,"breakdown sums exactly");
        require(x.influence.side[0].guard<=ip.guard_cap&&x.influence.side[1].pressure<=ip.pressure_cap,"bounded influence scores");
        auto changed=random;changed.turn=rules::Color::White;
        require(evaluate(changed,p).total==x.total,"local static timing estimates do not invent a side-to-move bonus");
    }
    p.influence_enabled=false;
    require(evaluate(overloaded,p).total==evaluate(overloaded).total,"disabled influence restores original evaluation");
    std::cout<<"PASS influence redundancy/pins/overload/drop constraints/unknown/symmetry/bounds/OFF\n";
}catch(const std::exception& ex){std::cerr<<"FAIL "<<ex.what()<<'\n';return 1;}}
