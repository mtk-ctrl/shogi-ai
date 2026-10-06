#include "strategy/alphabeta3_tt.h"
#include "strategy/promotion_policy.h"
#include <iostream>
#include <map>
#include <random>
#include <set>
using namespace shogi;
void require(bool v,const std::string& s){if(!v)throw std::runtime_error(s);}
int sq(const std::string& s){return (s[0]-'1')*9+s[1]-'a';}
rules::Snapshot snap(std::map<std::string,std::string> pieces) {
    rules::Snapshot s;
    const std::string kinds=" PLNSBRGK";
    for(auto [at,p]:pieces){bool promoted=p[0]=='+';char c=p.back();s.board[sq(at)]={int(kinds.find(char(std::toupper(c)))),std::isupper(c)?rules::Color::Black:rules::Color::White,promoted};}
    return s;
}
rules::Snapshot rotate(const rules::Snapshot& s){
    auto t=s;t.turn=s.turn==rules::Color::Black?rules::Color::White:rules::Color::Black;
    std::swap(t.hands[0],t.hands[1]);
    for(int i=0;i<81;++i){t.board[80-i]=s.board[i];t.board[80-i].color=s.board[i].color==rules::Color::Black?rules::Color::White:rules::Color::Black;}
    return t;
}
rules::Position load(const std::string& sf){rules::Position p;std::string e;require(p.set(sf,{},e),e);return p;}
void play(rules::Position& p,const std::string& m){std::string e;require(p.play(m,e),m+e);}
void symmetry(const rules::Snapshot& s){
    auto a=strategy::evaluate(s),b=strategy::evaluate(rotate(s));
    require(a.total==-b.total && a.material==-b.material,"total/material color symmetry");
    for(int i=0;i<4;++i){require(a.terms[i]==-b.terms[i],"term color symmetry");require(a.side_points[0][i]==b.side_points[1][i],"side points symmetry");}
    auto turn=s;turn.turn=turn.turn==rules::Color::Black?rules::Color::White:rules::Color::Black;
    require(strategy::evaluate(turn).total==a.total,"static evaluation independent of turn");
}
// Exhaustive test oracle has no alpha-beta, ordering or TT.
int brute(rules::Position& p,int depth,rules::Color root) {
    const auto result=p.status().result;
    if(result!=rules::Result::Ongoing){
        if(result==rules::Result::Draw)return 0;
        return ((result==rules::Result::BlackWin)==(root==rules::Color::Black))?100000000:-100000000;
    }
    if(!depth)return (root==rules::Color::Black?1:-1)*strategy::evaluate(p.snapshot()).total;
    const bool maximize=p.snapshot().turn==root;
    int best=maximize?std::numeric_limits<int>::min():std::numeric_limits<int>::max();
    for(const auto& m:p.legal_moves()){
        play(p,m);const int value=brute(p,depth-1,root);require(p.undo(),"oracle undo");
        best=maximize?std::max(best,value):std::min(best,value);
    }
    return best;
}
struct TraceEvaluator {
    bool* plain;bool* promoted;
    int operator()(const rules::Snapshot& s)const{
        const auto& p=s.board[sq("5h")];
        if(p.kind==1&&p.color==rules::Color::White){if(p.promoted)*promoted=true;else *plain=true;}
        return strategy::material_black(s);
    }
};
int main(){try{
    using namespace strategy;
    auto safe=snap({{"5i","K"},{"1a","k"},{"5h","G"},{"4h","S"},{"6h","P"}});
    auto open=snap({{"5i","K"},{"1a","k"},{"8e","G"},{"7e","S"},{"6e","P"}});
    auto a=evaluate(safe),b=evaluate(open);
    require(a.material==b.material && a.terms[0]>b.terms[0] && a.total>b.total,"same material: shelter improves evaluation");
    require(a.raw[0].gold_guards==1&&a.raw[0].silver_guards==1&&a.raw[0].pawn_guards==1,"guard accounting");
    std::cout<<"PASS same-material king shelter "<<a.total<<" > "<<b.total<<"\n";

    auto pressure=snap({{"9i","K"},{"5a","k"},{"4d","R"},{"7d","B"}});
    auto distant=snap({{"9i","K"},{"5a","k"},{"1d","R"},{"9d","B"}});
    a=evaluate(pressure);b=evaluate(distant);
    require(a.material==b.material&&a.terms[1]>b.terms[1]&&a.total>b.total,"same material: real king-zone attacks improve score");
    auto near_king=snap({{"5c","K"},{"5a","k"}});
    require(evaluate(near_king).terms[1]==0,"king proximity is not attacking pressure");
    std::cout<<"PASS real pressure and no king-proximity bonus\n";

    // Direction-aware two-ring king defence research fixtures.
    // Same material: a rook controlling the actually threatened flank must
    // count more than the same rook controlling a quiet flank.
    EvaluationParameters kd; kd.king_defense_weight=100;
    auto flank_threat=snap({{"5e","K"},{"9a","k"},{"3a","r"},{"7i","R"}});
    auto flank_defended=snap({{"5e","K"},{"9a","k"},{"3a","r"},{"3i","R"}});
    auto weak_kd=evaluate(flank_threat,kd), strong_kd=evaluate(flank_defended,kd);
    require(weak_kd.material==strong_kd.material,"king defence fixture material equality");
    require(strong_kd.raw[0].king_defense.risk_score<weak_kd.raw[0].king_defense.risk_score,
            "defence on attacked flank must reduce king risk");
    require(strong_kd.king_defense_term>weak_kd.king_defense_term,
            "directional king defence term must reward relevant flank");
    std::cout<<"PASS king defence relevant flank risk "
             <<strong_kd.raw[0].king_defense.risk_score<<" < "
             <<weak_kd.raw[0].king_defense.risk_score<<"\n";

    // Inner-ring contact should be treated as more urgent than otherwise
    // analogous outer-only contact.
    auto outer_contact=snap({{"5e","K"},{"9a","k"},{"3a","r"},{"7i","R"}});
    auto inner_contact=snap({{"5e","K"},{"9a","k"},{"4a","r"},{"7i","R"}});
    auto outer_f=king_defense_features(outer_contact,AttackMap(outer_contact),0);
    auto inner_f=king_defense_features(inner_contact,AttackMap(inner_contact),0);
    require(inner_f.inner_threat_total>outer_f.inner_threat_total,
            "inner fixture must create more inner-ring threat");
    require(inner_f.risk_score>outer_f.risk_score,
            "unanswered inner-ring threat must carry more risk than outer-only threat");
    std::cout<<"PASS two-ring urgency risk inner "<<inner_f.risk_score
             <<" > outer "<<outer_f.risk_score<<"\n";

    // Supported nearby guards should improve the threatened sector, while the
    // same pieces parked far away should not receive a castle-name bonus.
    auto guards_far=snap({{"5e","K"},{"9a","k"},{"3a","r"},{"8h","G"},{"8g","S"}});
    auto guards_near=snap({{"5e","K"},{"9a","k"},{"3a","r"},{"4e","G"},{"4f","S"}});
    auto far_f=king_defense_features(guards_far,AttackMap(guards_far),0);
    auto near_f=king_defense_features(guards_near,AttackMap(guards_near),0);
    require(near_f.supported_inner_pieces>far_f.supported_inner_pieces,
            "near guard network should contain supported inner pieces");
    require(near_f.risk_score<far_f.risk_score,
            "supported guard network in threatened zone should reduce risk");
    std::cout<<"PASS supported guard network risk "<<near_f.risk_score
             <<" < scattered "<<far_f.risk_score<<"\n";

    // Monotonic safety invariant: if enemy king-zone pressure disappears while
    // our defence stays unchanged, the feature must never become worse.
    auto no_threat=snap({{"5e","K"},{"9a","k"},{"4e","G"},{"4f","S"},{"9h","r"}});
    auto no_threat_f=king_defense_features(no_threat,AttackMap(no_threat),0);
    require(no_threat_f.risk_score<=near_f.risk_score,
            "removing enemy pressure must not worsen king defence evaluation");
    std::cout<<"PASS removing pressure never loses defence value\n";

    auto kd_rot=evaluate(rotate(guards_near),kd);
    auto kd_base=evaluate(guards_near,kd);
    require(kd_base.total==-kd_rot.total &&
            kd_base.king_defense_term==-kd_rot.king_defense_term,
            "king defence preserves color-rotation symmetry");
    std::cout<<"PASS king defence color symmetry\n";

    auto active=snap({{"9i","K"},{"1a","k"},{"5e","R"},{"4g","P"},{"6g","P"},{"5g","P"},{"5i","G"}});
    auto idle=active;std::swap(idle.board[sq("5e")],idle.board[sq("5h")]);
    // Move the same two pawns to close lateral rays around the idle rook.
    std::swap(idle.board[sq("4g")],idle.board[sq("4h")]);std::swap(idle.board[sq("6g")],idle.board[sq("6h")]);
    a=evaluate(active);b=evaluate(idle);
    require(a.material==b.material&&a.terms[2]>b.terms[2]&&a.total>b.total,"active rook outranks boxed rook");
    auto bishop=active;bishop.board[sq("5e")].kind=5;
    auto boxed=bishop;for(auto at:{"4d","6d","4f","6f"})boxed.board[sq(at)]={1,rules::Color::Black,false};
    require(evaluate(bishop).raw[0].major_mobility>evaluate(boxed).raw[0].major_mobility,"bishop rays and blockers");
    std::cout<<"PASS active rook/bishop rays and idle pieces\n";

    auto hanging=snap({{"9i","K"},{"1a","k"},{"5e","R"},{"5a","r"},{"8h","G"}});
    auto guarded=hanging;std::swap(guarded.board[sq("8h")],guarded.board[sq("5f")]);
    a=evaluate(hanging);b=evaluate(guarded);
    require(a.raw[0].exposure==1000&&b.raw[0].exposure==0,"defended equal rook exchange not penalized");
    require(a.material==b.material&&a.total<b.total,"guarded high-value piece outranks hanging piece");
    guarded.board[sq("5a")]={};guarded.board[sq("5d")]={1,rules::Color::White,false};
    require(evaluate(guarded).raw[0].exposure==900,"guard does not excuse rook lost to a pawn");
    std::cout<<"PASS hanging high-value piece, equal exchange, cheap attacker\n";

    auto xray=snap({{"9i","K"},{"5b","k"},{"5e","R"}});
    AttackMap xr(xray);
    require(xr.count[0][sq("5a")]==0&&xr.escape_control[0][sq("5a")],"king-vacated rook xray only in escape map");
    // Exact central geometric target counts: promoted minors are gold, horse/dragon include extra steps.
    for(int kind=1;kind<=8;++kind)for(bool promoted:{false,true}){
        if(promoted&&kind>=7)continue;
        rules::Snapshot s;s.board[sq("5e")]={kind,rules::Color::Black,promoted};AttackMap m(s);
        const int ordinary[]={0,1,4,2,5,16,16,6,8};
        const int n=promoted?(kind<=4?6:20):ordinary[kind];
        require(m.sizes[sq("5e")]==n,"piece attack target count");
        std::set<int> unique;for(int j=0;j<m.sizes[sq("5e")];++j)unique.insert(m.targets[sq("5e")][j]);
        require(int(unique.size())==n,"no duplicated horse/dragon target");
        symmetry(s);
    }
    auto block=snap({{"5e","L"},{"5c","P"}});AttackMap lm(block);
    require(lm.count[0][sq("5c")]==1&&lm.count[0][sq("5b")]==1&&lm.count[0][sq("5a")]==0,"friendly lance endpoint stops ray (pawn attacks next square)");
    auto knight=snap({{"5e","N"},{"5d","P"}});AttackMap nm(knight);
    require(nm.count[0][sq("4c")]==1&&nm.count[0][sq("6c")]==1,"knight jumps blockers");
    std::cout<<"PASS every piece/promotion geometry, blockers and king-vacated xray\n";

    EvaluationParameters p; p.weights={400,400,400,400};p.positional_cap=1;
    auto limited=evaluate(pressure,p);require(std::abs(limited.positional)<=1,"combined positional cap");
    auto inv=evaluate(rotate(pressure),p);require(limited.total==-inv.total,"clamp preserves symmetry");
    require(limited.total==limited.material+limited.terms[0]+limited.terms[1]+limited.terms[2]+limited.terms[3]+limited.clamp_adjustment,"breakdown sums exactly");
    p.danger_denominator=0;bool rejected=false;try{FeatureEvaluator bad(p);}catch(const std::invalid_argument&){rejected=true;}require(rejected,"invalid parameters rejected");
    require(std::abs(evaluate(pressure).total)<FeatureAlphaBeta3TT::WinScore&&EvaluationParameters::StaticLimit<FeatureAlphaBeta3TT::WinScore,"mate dominates static values");

    rules::Position position;std::mt19937 rng(1947);
    for(int n=0;n<180;++n){symmetry(position.snapshot());auto moves=position.legal_moves();if(position.status().result!=rules::Result::Ongoing){position=rules::Position();continue;}play(position,moves[rng()%moves.size()]);}
    std::cout<<"PASS 180 legal positions color/turn symmetry and bounded integer terms\n";

    auto mate=load("2l1kl3/2pp1p3/2G1P4/9/B8/9/9/9/K3R4 b - 1");
    FeatureAlphaBeta3TT search;
    require(search.choose(mate,{"5c5b","5i4i"})=="5c5b" && search.last_score()==search.WinScore,"feature search sees forced third-ply mate");
    require(search.choose(mate,{"5i4i"})=="5i4i" && search.last_score()<search.WinScore,"mate distractor really does not force mate");
    auto lose=load("4r3k/9/9/4p4/4R4/9/9/9/K8 b - 1");
    require(search.choose(lose)!="5e5d","feature search avoids poisoned pawn");
    // Same instance, changing evaluator: all results AND node counts match a fresh table.
    auto trans=load("8k/9/9/9/9/9/2P3P2/9/K8 b - 1");
    for(int n=0;n<6;++n){auto settings=n%2?EvaluationParameters::material_only():EvaluationParameters{};settings.weights[1]=n%2?0:200;
        search.set_evaluator(FeatureEvaluator(settings));search.set_seed(111);
        FeatureAlphaBeta3TT fresh(111,FeatureEvaluator(settings));
        auto before=trans.sfen();auto actual=search.choose(trans);auto expected=fresh.choose(trans);
        require(actual==expected&&search.last_score()==fresh.last_score()&&search.last_stats().nodes==fresh.last_stats().nodes,"no TT contamination after evaluator switch");require(trans.sfen()==before,"search rollback");
    }
    auto repetition=load("8k/9/9/9/9/9/9/9/K8 b - 1");
    for(auto m:{"9i9h","1a1b","9h9i","1b1a"})play(repetition,m);
    search.choose(repetition);require(search.last_stats().tt_disabled_repetition==1&&search.last_stats().tt_probes==0,"feature search keeps repetition TT fallback");
    std::cout<<"PASS mate/poisoned pawn/TT evaluator isolation/repetition rollback\n";
    // Policy is applied to root candidates by the USI caller, not to the rules.
    for(auto [kind,move]:std::vector<std::pair<std::string,std::string>>{{"S","5d4c"},{"N","5e4c"},{"L","5d5c"}}){
        auto s=snap({{"9i","K"},{"1a","k"},{move.substr(0,2),kind}});
        auto both=PromotionPolicy::force_monotonic_promotions(s,{move,move+"+"});require(both.size()==2,"silver knight lance keep nonpromotion");
    }
    std::cout<<"PASS silver/knight/lance nonpromotion retained\n";
    auto reply_position=load("8k/9/9/9/9/9/4p4/9/K8 b - 1");
    bool plain=false,promoted=false;
    BasicAlphaBeta3TT<TraceEvaluator> traced(17,TraceEvaluator{&plain,&promoted});
    traced.choose(reply_position,{"9i9h"});
    require(plain&&promoted,"opponent legal nonpromotion must reach evaluated leaves");
    std::cout<<"PASS both opponent pawn promotion choices reach search leaves\n";
    for(auto sf:{"8k/9/9/9/9/9/2P3P2/9/K8 b - 1", "8k/9/9/4p4/4R4/9/9/9/K8 b - 1", "8k/9/9/9/4s4/9/4P4/9/K8 w - 1"}){
        auto q=load(sf);auto before=q.sfen();const auto root=q.snapshot().turn;
        const int expected=brute(q,3,root);FeatureAlphaBeta3TT tested(991);
        const auto move=tested.choose(q);require(tested.last_score()==expected,"feature search exact minimax value");
        play(q,move);require(brute(q,2,root)==expected,"chosen move attains exact feature minimax");q.undo();require(q.sfen()==before,"feature oracle rollback");
    }
    std::cout<<"PASS feature search equals exhaustive three-ply oracle (both turns)\n";

}catch(const std::exception& e){std::cerr<<"FAIL "<<e.what()<<"\n";return 1;}}
