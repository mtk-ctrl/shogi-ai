#include "strategy/iterative_search.h"
#include <iostream>
#include <map>

using namespace shogi;
using Search = strategy::BasicIterativeSearch<strategy::MaterialEvaluator>;
void require(bool ok, const std::string& message) { if (!ok) throw std::runtime_error(message); }
void play(rules::Position& p, const std::string& m) {
    std::string error; require(p.play(m, error), m + ": " + error);
}
rules::Position fixture(const std::map<std::string, std::string>& pieces,
                        const std::string& turn = "b", const std::string& hand = "-") {
    std::string sf;
    for (char rank = 'a'; rank <= 'i'; ++rank) {
        int empty = 0;
        for (char file = '9'; file >= '1'; --file) {
            auto it = pieces.find(std::string{file, rank});
            if (it == pieces.end()) ++empty;
            else { if (empty) sf += char('0' + empty); empty = 0; sf += it->second; }
        }
        if (empty) sf += char('0' + empty);
        if (rank != 'i') sf += '/';
    }
    rules::Position p; std::string error;
    require(p.set(sf + " " + turn + " " + hand + " 1", {}, error), error); return p;
}
// Independent full-width oracle. No alpha/beta, TT, ordering or iterative search.
// Select captures from actual hand changes, promotions from the resulting board.
int oracle(rules::Position& p, int depth, int qply, int ply, rules::Color root) {
    auto status = p.status();
    if (status.result != rules::Result::Ongoing) {
        if (status.result == rules::Result::Draw) return 0;
        const bool win = (status.result == rules::Result::BlackWin) == (root == rules::Color::Black);
        const int score = status.reason == "checkmate" ? Search::MateScore - ply : Search::RuleWinScore;
        return win ? score : -score;
    }
    require(ply < Search::MaxPly, "oracle fixture exceeded safety limit");
    const auto before = p.snapshot(); const auto mover = before.turn;
    const bool max = mover == root;
    const bool checked = p.in_check();
    int score = max ? -100001000 : 100001000;
    if (!depth && !checked) {
        score = (root == rules::Color::Black ? 1 : -1) * strategy::material_black(before);
        if (qply >= Search::QuiescenceDepth) return score;
    }
    for (const auto& move : p.legal_moves()) {
        play(p, move);
        const auto after = p.snapshot();
        bool tactical = before.hands != after.hands && move[1] != '*';
        if (move[1] != '*') {
            const auto source = before.board[(move[0]-'1')*9 + move[1]-'a'];
            const auto dest = after.board[(move[2]-'1')*9 + move[3]-'a'];
            tactical = tactical || (!source.promoted && dest.promoted);
        }
        if (depth || checked || tactical) {
            const int child = oracle(p, depth ? depth - 1 : 0, depth ? 0 : qply + 1, ply + 1, root);
            score = max ? std::max(score, child) : std::min(score, child);
        }
        require(p.undo(), "oracle undo");
    }
    return score;
}
void pv_legal(rules::Position& p, const strategy::SearchResult& r) {
    auto copy = p.clone();
    require(!r.pv.empty() && r.pv.front() == r.move, "PV root");
    for (const auto& m : r.pv) play(copy, m);
}
strategy::SearchResult compare(Search& search, rules::Position& p, int depth,
                               const std::vector<std::string>& moves) {
    const auto before = p.sfen(); const auto history = p.history_key();
    const auto root = p.snapshot().turn;
    int expected = -100001000;
    for (auto& m : moves) {
        play(p,m); expected = std::max(expected, oracle(p, depth-1, 0, 1, root)); require(p.undo(), "root undo");
    }
    strategy::SearchControl c;
    auto r = search.choose(p, depth, c, moves);
    require(r.has_score && r.depth == depth && r.score == expected,
            "qsearch differs from exhaustive oracle: " + std::to_string(r.score) + " vs " + std::to_string(expected));
    require(p.sfen() == before && p.history_key() == history, "restored board and history");
    pv_legal(p,r); return r;
}
int main() {
    try {
        Search search;
        for (bool white : {false,true}) {
            std::map<std::string,std::string> pcs = {{"9i","K"},{"1a","k"},{"5h","R"},{"5d","p"},{"5a","r"}};
            std::vector<std::string> moves = {"5h5d","5h4h"};
            auto rotate = [](std::string s) { return std::string{char('0'+10-(s[0]-'0')), char('i'-(s[1]-'a'))}; };
            if (white) {
                std::map<std::string,std::string> rotated;
                for (auto& [sq,pc] : pcs) rotated[rotate(sq)] = std::string(1, pc[0] < 'a' ? pc[0]+32 : pc[0]-32);
                pcs = rotated;
                for (auto& m : moves) m = rotate(m.substr(0,2)) + rotate(m.substr(2,2));
            }
            auto p = fixture(pcs, white ? "w" : "b");
            Search fixed; fixed.set_quiescence_enabled(false); strategy::SearchControl c;
            require(fixed.choose(p,1,c,moves).move == moves[0], "fixed horizon should take poisoned pawn");
            for (int depth : {1,2}) {
                auto r = compare(search,p,depth,moves);
                require(r.move == moves[1], "qsearch avoids pawn defended by rook");
            }
        }
        std::cout << "PASS poisoned pawn for both colors and exhaustive depth 1/2 equivalence\n";
        auto checked = fixture({{"9i","K"},{"1a","k"},{"9d","R"}});
        auto evasion = compare(search,checked,1,{"9d1d"});
        require(evasion.pv.size() >= 2, "check must search quiet king evasions");
        auto block = fixture({{"9i","K"},{"5a","k"},{"4a","l"},{"6a","l"},
                              {"4b","p"},{"6b","p"},{"4h","R"}}, "b", "g");
        auto interpose = compare(search,block,1,{"4h5h"});
        require(interpose.pv.size() >= 2 && interpose.pv[1][1] == '*', "check must include blocking drops");
        std::cout << "PASS quiet evasions and blocking drops with no stand pat in check\n";
        auto promotion = fixture({{"9i","K"},{"1a","k"},{"5g","p"}});
        auto promoted = compare(search,promotion,1,{"9i9h"});
        require(promoted.score == -760 && promoted.pv.size() == 2 && promoted.pv[1] == "5g5h+",
                "quiet promotion included at horizon");
        auto quiet = fixture({{"9i","K"},{"1a","k"},{"5e","P"}});
        require(compare(search,quiet,1,{"9i9h"}).score == 120, "quiet leaf remains static");
        std::cout << "PASS non-capture promotion and quiet leaf\n";
        // Cancellation inside qsearch, including at several evasion/capture nodes.
        const auto sf = block.sfen(); const auto history = block.history_key();
        for (std::uint64_t limit : {2,3,5,10}) {
            strategy::SearchControl c; c.node_limit = limit;
            auto r = search.choose(block,5,c,{"4h5h"});
            require(search.last_stats().nodes <= limit && search.last_stats().qnodes > 0, "qnodes obey total node budget");
            require(block.sfen() == sf && block.history_key() == history, "q cancellation restores history");
            pv_legal(block,r);
        }
        strategy::SearchControl stop;
        auto r = search.choose(block,5,stop,{"4h5h"},[&](const auto& done) { if(done.depth == 1) stop.stop.store(true); });
        require(r.depth == 1 && r.has_score, "retain completed qsearch iteration on stop");
        std::cout << "PASS interruption within qsearch, total node accounting and rollback\n";
        // The fourth repetition is reached INSIDE qsearch on a quiet king evasion.
        auto repetition = fixture({{"9i","K"},{"5a","k"},{"4b","R"}});
        for (int i=0;i<2;++i) for (auto m : {"4b5b","5a4a","5b4b","4a5a"}) play(repetition,m);
        for (auto m : {"4b5b","5a4a"}) play(repetition,m);
        auto terminal = compare(search,repetition,1,{"5b4b"});
        require(terminal.score == -Search::RuleWinScore && !Search::is_mate_score(terminal.score),
                "perpetual-check loss in qsearch is not mate");
        std::cout << "PASS repetition history at qsearch horizon and non-mate rule loss\n";
    } catch (const std::exception& e) { std::cerr << "FAIL " << e.what() << '\n'; return 1; }
}
