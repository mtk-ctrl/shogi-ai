#include "rules/position.h"
#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <map>
#include <random>
#include <sstream>
#include <stdexcept>

using shogi::rules::Position;
using shogi::rules::Result;
void require(bool value, const std::string& message) {
    if (!value) throw std::runtime_error(message);
}
std::string fixture(std::map<std::string, std::string> pieces, std::string hands = "-", std::string turn = "b") {
    std::string out;
    for (char rank = 'a'; rank <= 'i'; ++rank) {
        int empty = 0;
        for (char file = '9'; file >= '1'; --file) {
            std::string square{file, rank};
            auto it = pieces.find(square);
            if (it == pieces.end()) ++empty;
            else {
                if (empty) out += char('0' + empty);
                empty = 0; out += it->second;
            }
        }
        if (empty) out += char('0'+empty);
        if (rank != 'i') out += '/';
    }
    return out + " " + turn + " " + hands + " 1";
}
Position load(const std::string& sfen) {
    Position p;
    std::string error;
    require(p.set(sfen, {}, error), "set: " + sfen + ": " + error);
    return p;
}
bool has(const Position& p, const std::string& move) {
    auto moves = p.legal_moves();
    return std::find(moves.begin(), moves.end(), move) != moves.end();
}
void play(Position& p, const std::string& move) {
    std::string error;
    require(p.play(move, error), "play: " + move + ": " + error);
}
uint64_t perft(Position& p, int depth) {
    if (!depth) return 1;
    auto moves = p.legal_moves();
    if (depth == 1) return moves.size();
    uint64_t count = 0;
    const auto before = p.sfen();
    for (const auto& move : moves) {
        play(p, move);
        count += perft(p, depth-1);
        require(p.undo(), "perft undo");
        require(p.sfen() == before, "perft restoration");
    }
    return count;
}

int main(int argc, char** argv) {
    try {
        // Test-only oracle interface. Never exposed in the production USI binary.
        if (argc > 1 && std::string(argv[1]) == "--probe") {
            Position p;
            std::string line, error;
            while (std::getline(std::cin, line)) {
                bool ok = true;
                if (line.rfind("position ", 0) == 0) ok = p.set_usi(line, error);
                else if (line.rfind("play ", 0) == 0) ok = p.play(line.substr(5), error);
                else if (line == "undo") ok = p.undo();
                else if (line == "quit") break;
                if (!ok) { std::cout << "ERROR " << error << std::endl; continue; }
                auto moves = p.legal_moves();
                std::sort(moves.begin(), moves.end());
                std::cout << p.sfen() << '|' << p.in_check() << '|' << int(p.status().result) << '|';
                for (const auto& move : moves) std::cout << move << ' ';
                std::cout << std::endl;
            }
            return 0;
        }
        Position p;
        for (auto [depth, expected] : std::vector<std::pair<int, uint64_t>>{{1,30},{2,900},{3,25470},{4,719731}})
            require(perft(p, depth) == expected, "startpos perft " + std::to_string(depth));
        std::cout << "PASS initial perft depths 1-4: 30, 900, 25470, 719731\n";

        p = load(fixture({{"9i","K"},{"1a","k"},{"5c","P"}}));
        require(has(p,"5c5b") && has(p,"5c5b+"), "optional pawn promotion");
        p = load(fixture({{"9i","K"},{"1a","k"},{"5b","P"},{"7c","N"}}));
        require(has(p,"5b5a+") && !has(p,"5b5a"), "mandatory pawn promotion");
        require(has(p,"7c6a+") && !has(p,"7c6a"), "mandatory knight promotion");
        p = load(fixture({{"9i","K"},{"1a","k"},{"5g","P"}}, "PLN"));
        require(!has(p,"P*5e") && has(p,"P*4e"), "nifu");
        require(!has(p,"P*4a") && !has(p,"L*4a") && !has(p,"N*4a") && !has(p,"N*4b")
                && has(p,"N*4c"), "dead-rank drops");
        auto pawnmate = std::map<std::string,std::string>{{"9i","K"},{"5a","k"},{"4a","l"},{"6a","l"},
                      {"4b","p"},{"6b","p"},{"5c","G"}};
        p = load(fixture(pawnmate,"P"));
        require(!has(p,"P*5b"), "uchifuzume is forbidden");
        pawnmate.erase("6a");
        p = load(fixture(pawnmate,"P"));
        require(has(p,"P*5b"), "pawn drop check with escape is allowed");
        pawnmate["6a"] = "l"; pawnmate["5c"] = "P"; pawnmate["4c"] = "G";
        p = load(fixture(pawnmate));
        play(p,"5c5b");
        require(p.in_check() && p.status().result == Result::BlackWin && p.legal_moves().empty(), "walking pawn mate");
        std::cout << "PASS promotion, nifu, dead ranks, pawn-drop mate and mate by moving pawn\n";

        p = load(fixture({{"5i","K"},{"1a","k"},{"5a","r"},{"5h","G"}}));
        require(!has(p,"5h4h") && has(p,"5h5g"), "pinned piece");
        p = load(fixture({{"5i","K"},{"9a","k"},{"5a","r"},{"1e","b"}}));
        require(p.in_check(), "double check");
        for (const auto& m : p.legal_moves()) require(m.substr(0,2)=="5i", "double check king-only evasion");
        p = load(fixture({{"9i","K"},{"1a","k"},{"5e","R"},{"5c","+p"}}));
        auto before = p.sfen();
        play(p,"5e5c+");
        require(p.snapshot().hands[0][0] == 1, "captured promoted pawn becomes pawn in hand");
        play(p,"1a1b"); play(p,"P*4d");
        require(p.snapshot().hands[0][0] == 0, "drop removes hand piece");
        for (int i=0;i<3;++i) require(p.undo(),"undo capture/drop");
        require(p.sfen()==before,"capture/promotion/drop restore");
        std::cout << "PASS pins, double check, capture, demotion, drop and undo\n";

        p = load(fixture({{"5i","K"},{"5a","k"}}));
        for (int repeat=0;repeat<3;++repeat) {
            for (auto m : {"5i6i","5a6a","6i5i","6a5a"}) play(p,m);
            require(p.status().result == (repeat==2 ? Result::Draw : Result::Ongoing), "exact fourfold repetition");
        }
        require(p.clone().status().result==Result::Draw,"clone keeps repetition history");
        require(p.undo() && p.status().result==Result::Ongoing,"undo terminal repetition");
        p = load(fixture({{"3i","K"},{"3a","k"}}));
        const std::vector<std::string> black = {"3i4i","4i5i","5i6i","6i7i","7i7h","7h6h","6h5h","5h4h","4h3h","3h3i"};
        const std::vector<std::string> white = {"3a4a","4a5a","5a6a","6a7a","7a7b","7b6b","6b5b","5b4b","4b3b","3b3a"};
        for (int repeat=0;repeat<3;++repeat) for (int i=0;i<10;++i) { play(p,black[i]);play(p,white[i]); }
        require(p.status().result==Result::Draw,"repetition beyond upstream default 16-ply horizon");
        p = load(fixture({{"9i","K"},{"5a","k"},{"4b","R"}}));
        for (int repeat=0;repeat<3;++repeat) for (auto m : {"4b5b","5a4a","5b4b","4a5a"}) play(p,m);
        require(p.status().result==Result::WhiteWin,"continuous checking side loses");
        std::cout << "PASS fourfold, 20-ply repetition cycle, perpetual-check loss and history-preserving clone\n";

        p = load(fixture({{"5b","K"},{"9i","k"},{"9c","P"},{"8c","P"},{"7c","P"},{"6c","P"},
                         {"5c","P"},{"4c","P"},{"3c","P"},{"2c","P"},{"1c","P"},{"4b","G"}}, "2R2B"));
        require(p.can_declare_win(),"27-point declaration positive");
        require(!Position().can_declare_win(),"declaration negative");
        std::string error;
        p = Position(); before=p.sfen();
        for (const auto& bad : {"position startpos moves 7g7f 7g7f", "position startpos garbage",
             "position sfen 9/9/9/9/9/9/9/9/9 b - 1", "position sfen 9/9/9/9/9/9/9/9/9 b 99999999999999P 1",
             "position sfen 9/9/9/9/9/9/9/9/4K4 b - 1", "position sfen 8k/9/9/9/9/9/9/9/K8 b 0P 1"}) {
            require(!p.set_usi(bad,error),"invalid input rejected");
            require(p.sfen()==before,"failed input transactional");
        }
        require(!p.play("resign",error) && !p.play("0000",error),"special tokens not board moves");
        require(!p.undo(),"root undo rejected");
        std::cout << "PASS declaration and transactional malformed-input handling\n";

        std::mt19937 rng(20261003);
        int total=0;
        for (int game=0;game<30;++game) {
            p = Position();
            std::vector<std::string> states{p.sfen()};
            for (int ply=0;ply<400 && p.status().result==Result::Ongoing;++ply) {
                auto moves=p.legal_moves();
                play(p,moves[rng()%moves.size()]); states.push_back(p.sfen()); ++total;
                if (ply%37==0) require(p.clone().sfen()==p.sfen(),"random clone");
            }
            while (states.size()>1) { states.pop_back(); require(p.undo(),"random undo");require(p.sfen()==states.back(),"random restoration"); }
        }
        std::cout << "PASS 30 random playouts, " << total << " moves and complete undo\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << "FAIL " << e.what() << '\n'; return 1; }
}
