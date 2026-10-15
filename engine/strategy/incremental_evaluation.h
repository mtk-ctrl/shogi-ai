#pragma once
#include "strategy/attack_map.h"
#include <optional>

namespace shogi::strategy {
// Research only: compare complete snapshots, so undo, unrelated positions and
// evaluation-cache hits cannot leave stale state. No rule/search result cached.
inline bool same_piece(const rules::Piece& a, const rules::Piece& b) {
    return a.kind == b.kind && (!a.kind || (a.color == b.color && a.promoted == b.promoted));
}
struct MaterialTotals { int board = 0, hand = 0; };
class IncrementalMaterial {
public:
    const MaterialTotals& update(const rules::Snapshot& s) {
        for (int sq=0; sq<81; ++sq) if (!same_piece(previous_.board[sq],s.board[sq])) {
            const auto contribution=[](const rules::Piece& p) {
                return (p.color==rules::Color::Black ? 1 : -1)*piece_value(p.kind,p.promoted);
            };
            total_.board += contribution(s.board[sq])-contribution(previous_.board[sq]);
            previous_.board[sq]=s.board[sq];
        }
        for (int c=0;c<2;++c) for (int k=0;k<7;++k) {
            total_.hand += (c==0 ? 1 : -1)*(s.hands[c][k]-previous_.hands[c][k])*hand_piece_value(k+1);
            previous_.hands[c][k]=s.hands[c][k];
        }
        return total_;
    }
private:
    rules::Snapshot previous_{};
    MaterialTotals total_{};
};

class IncrementalAttackMap {
    struct PieceAttacks {
        std::array<std::uint8_t,32> targets{}, escape{};
        std::uint8_t size=0, escape_size=0;
    };
    static PieceAttacks attacks(const rules::Snapshot& s,int from) {
        PieceAttacks out;
        const auto& p=s.board[from];
        if(!p.kind)return out;
        const int side=int(p.color), f=from/9,r=from%9;
        auto ray=[&](int df,int dr,bool sliding) {
            bool through=false;
            for(int x=f+df,y=r+dr;x>=0 && x<9 && y>=0 && y<9;x+=df,y+=dr) {
                const int to=x*9+y;
                const auto& q=s.board[to];
                if(p.kind!=8)out.escape[out.escape_size++]=to;
                if(!through)out.targets[out.size++]=to;
                if(!sliding)break;
                if(q.kind) {
                    if(!through && q.kind==8 && q.color!=p.color)through=true;
                    else break;
                }
            }
        };
        const int fw=side==0 ? -1 : 1;
        if(p.kind==7 || (p.promoted && p.kind<=4)) {
            for(int df=-1;df<=1;++df)ray(df,fw,false);
            ray(-1,0,false);ray(1,0,false);ray(0,-fw,false);
        } else switch(p.kind) {
            case 1:ray(0,fw,false);break;
            case 2:ray(0,fw,true);break;
            case 3:ray(-1,2*fw,false);ray(1,2*fw,false);break;
            case 4:
                for(int df=-1;df<=1;++df)ray(df,fw,false);
                ray(-1,-fw,false);ray(1,-fw,false);break;
            case 5:
                for(int df:{-1,1})for(int dr:{-1,1})ray(df,dr,true);
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
        return out;
    }
    static bool depends_on(const rules::Piece& p,int from,int changed) {
        if(!p.kind || (p.promoted && p.kind<=4))return false;
        const int df=changed/9-from/9,dr=changed%9-from%9;
        if(p.kind==5)return std::abs(df)==std::abs(dr);
        if(p.kind==6)return df==0 || dr==0;
        return p.kind==2 && df==0 && (p.color==rules::Color::Black ? dr<0 : dr>0);
    }
public:
    const AttackMap& update(const rules::Snapshot& s,unsigned reuse_mask) {
        const bool geometry=reuse_mask&2,index=reuse_mask&4;
        std::array<int,81> changed{};
        int count=0;
        for(int sq=0;sq<81;++sq)if(!same_piece(previous_.board[sq],s.board[sq]))changed[count++]=sq;
        if(!map_ || count>12) {
            map_.emplace(rules::Snapshot{},geometry,index);
            previous_=rules::Snapshot{};
            pieces_={};contributors_={};escape_count_={};
            count=0;
            for(int sq=0;sq<81;++sq)if(s.board[sq].kind)changed[count++]=sq;
        }
        map_->geometry_lookup=geometry;map_->occupied_index=index;
        std::array<bool,81> affected{};
        for(int j=0;j<count;++j)affected[changed[j]]=true;
        for(int from=0;from<81;++from)if(!affected[from])
            for(int j=0;j<count;++j)if(depends_on(s.board[from],from,changed[j])) {
                affected[from]=true;break;
            }
        std::array<std::array<bool,81>,2> dirty{};
        for(int from=0;from<81;++from)if(affected[from]) {
            const auto& old=previous_.board[from];
            const int side=int(old.color);
            if(old.kind) {
                const auto& a=pieces_[from];
                for(int i=0;i<a.size;++i) {
                    const int to=a.targets[i];
                    --map_->count[side][to];
                    if(old.kind!=8)--map_->nonking[side][to];
                    contributors_[side][to][from/64]&=~(std::uint64_t(1)<<(from%64));
                    dirty[side][to]=true;
                }
                for(int i=0;i<a.escape_size;++i) {
                    const int to=a.escape[i];
                    map_->escape_control[side][to]=--escape_count_[side][to]>0;
                }
            }
            auto& a=pieces_[from];a=attacks(s,from);
            map_->targets[from]=a.targets;map_->sizes[from]=a.size;
            const auto& p=s.board[from];
            const int c=int(p.color);
            if(p.kind) {
                for(int i=0;i<a.size;++i) {
                    const int to=a.targets[i];
                    ++map_->count[c][to];
                    if(p.kind!=8)++map_->nonking[c][to];
                    contributors_[c][to][from/64]|=std::uint64_t(1)<<(from%64);
                    dirty[c][to]=true;
                }
                for(int i=0;i<a.escape_size;++i) {
                    const int to=a.escape[i];
                    map_->escape_control[c][to]=++escape_count_[c][to]>0;
                }
            }
        }
        for(int c=0;c<2;++c)for(int to=0;to<81;++to)if(dirty[c][to]) {
            int least=AttackMap::NoAttacker;
            for(int word=0;word<2;++word) {
                auto bits=contributors_[c][to][word];
                while(bits) {
                    const int from=word*64+__builtin_ctzll(bits);bits&=bits-1;
                    const auto& p=s.board[from];
                    if(p.kind!=8)least=std::min(least,piece_value(p.kind,p.promoted));
                }
            }
            map_->least[c][to]=least;
        }
        map_->occupied={};map_->occupied_sizes={};map_->kings={-1,-1};
        for(int sq=0;sq<81;++sq) {
            const auto& p=s.board[sq];
            if(p.kind) {
                const int c=int(p.color);
                map_->occupied[c][map_->occupied_sizes[c]++]=sq;
                if(p.kind==8)map_->kings[c]=sq;
            }
        }
        previous_=s;
        return *map_;
    }
private:
    rules::Snapshot previous_{};
    std::optional<AttackMap> map_;
    std::array<PieceAttacks,81> pieces_{};
    std::array<std::array<std::array<std::uint64_t,2>,81>,2> contributors_{};
    std::array<std::array<int,81>,2> escape_count_{};
};
} // namespace shogi::strategy
