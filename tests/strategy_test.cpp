#include "strategy/alphabeta2.h"
#include "strategy/alphabeta3.h"
#include "strategy/material.h"
#include "strategy/minimax2.h"
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <limits>
#include <map>
#include <random>
#include <stdexcept>
#include <vector>

using namespace shogi;
void require(bool ok, const std::string& message) {
    if (!ok) throw std::runtime_error(message);
}
rules::Position fixture(std::map<std::string, std::string> pieces,
                        std::string hands = "-", std::string turn = "b") {
    std::string sfen;
    for (char rank = 'a'; rank <= 'i'; ++rank) {
        int empty = 0;
        for (char file = '9'; file >= '1'; --file) {
            auto it = pieces.find(std::string{file, rank});
            if (it == pieces.end()) ++empty;
            else {
                if (empty) sfen += char('0' + empty);
                empty = 0; sfen += it->second;
            }
        }
        if (empty) sfen += char('0' + empty);
        if (rank != 'i') sfen += '/';
    }
    rules::Position position;
    std::string error;
    require(position.set(sfen + " " + turn + " " + hands + " 1", {}, error), error);
    return position;
}
void play(rules::Position& position, const std::string& move) {
    std::string error;
    require(position.play(move, error), move + ": " + error);
}
void undo(rules::Position& position) {
    require(position.undo(), "undo failed");
}
int score(const rules::Position& position) { return strategy::material_black(position.snapshot()); }
int material_for(const rules::Position& position, rules::Color root) {
    const int sign = root == rules::Color::Black ? 1 : -1;
    return sign * strategy::material_black(position.snapshot());
}
int terminal_for(rules::Result result, rules::Color root) {
    return strategy::AlphaBeta3::terminal_score(result, root);
}

struct Brute3Result {
    std::string move;
    int score = std::numeric_limits<int>::min();
    std::uint64_t nodes = 0;
};

// Test-only exhaustive 3-ply minimax oracle. It deliberately performs no pruning.
Brute3Result brute_minimax3(rules::Position& position, unsigned seed,
                            const std::vector<std::string>& allowed = {}) {
    auto moves = position.legal_moves();
    if (!allowed.empty()) {
        moves.erase(std::remove_if(moves.begin(), moves.end(), [&](const auto& move) {
            return std::find(allowed.begin(), allowed.end(), move) == allowed.end();
        }), moves.end());
    }
    require(!moves.empty(), "brute_minimax3 requires at least one root move");
    require(position.status().result == rules::Result::Ongoing, "brute_minimax3 requires ongoing root");

    const auto root = position.snapshot().turn;
    int best = std::numeric_limits<int>::min();
    std::vector<std::string> tied;
    std::uint64_t nodes = 0;

    for (const auto& move : moves) {
        play(position, move);
        ++nodes;
        int root_score;
        const auto child_status = position.status();
        if (child_status.result != rules::Result::Ongoing) {
            root_score = terminal_for(child_status.result, root);
        } else {
            int worst_reply = std::numeric_limits<int>::max();
            const auto replies = position.legal_moves();
            require(!replies.empty(), "ongoing child has no replies");
            for (const auto& reply : replies) {
                play(position, reply);
                ++nodes;
                int reply_score;
                const auto reply_status = position.status();
                if (reply_status.result != rules::Result::Ongoing) {
                    reply_score = terminal_for(reply_status.result, root);
                } else {
                    int best_continuation = std::numeric_limits<int>::min();
                    const auto continuations = position.legal_moves();
                    require(!continuations.empty(), "ongoing reply has no continuations");
                    for (const auto& continuation : continuations) {
                        play(position, continuation);
                        ++nodes;
                        const auto continuation_status = position.status();
                        const int continuation_score = continuation_status.result == rules::Result::Ongoing
                            ? material_for(position, root)
                            : terminal_for(continuation_status.result, root);
                        best_continuation = std::max(best_continuation, continuation_score);
                        undo(position);
                    }
                    reply_score = best_continuation;
                }
                worst_reply = std::min(worst_reply, reply_score);
                undo(position);
            }
            root_score = worst_reply;
        }
        undo(position);

        if (root_score > best) {
            best = root_score;
            tied.clear();
        }
        if (root_score == best) tied.push_back(move);
    }

    std::mt19937 rng(seed);
    const auto index = std::uniform_int_distribution<std::size_t>(0, tied.size() - 1)(rng);
    return {tied[index], best, nodes};
}

int main() {
    try {
        rules::Position p;
        strategy::Material material;
        strategy::Minimax2 minimax;
        strategy::AlphaBeta2 alphabeta2;
        strategy::AlphaBeta3 alphabeta3;
        require(score(p) == 0, "equal starting material");
        p = fixture({{"9i","K"},{"1a","k"}}, "2R2B2G2S2N2L2P");
        require(score(p) == 14860, "all hand kinds including Bishop/Rook/Gold ordering");
        p = fixture({{"9i","K"},{"1a","k"}}, "2r2b2g2s2n2l2p", "w");
        require(score(p) == -14860, "white hand values and absolute perspective");
        p = fixture({{"9i","K"},{"2a","k"},{"5c","+P"},{"6c","+L"},
                     {"7c","+N"},{"8c","+S"},{"5e","+B"},{"6e","+R"}});
        require(score(p) == 7600, "all promoted piece values");
        std::cout << "PASS material, hands, promotion and color perspective\n";

        p = fixture({{"9i","K"},{"1a","k"},{"5e","R"},{"3e","b"},{"5c","p"}});
        auto before = p.sfen();
        require(material.choose(p) == "5e3e", "one-ply black takes bishop over pawn");
        require(p.sfen() == before, "material choose restores position");
        p = fixture({{"1i","K"},{"9a","k"},{"5e","r"},{"7e","B"},{"5g","P"}}, "-", "w");
        require(material.choose(p) == "5e7e", "one-ply white maximizes its own material");
        std::cout << "PASS v0.0.3 material baseline remains available\n";

        p = fixture({{"9i","K"},{"1a","k"},{"5e","R"},{"5d","p"},{"5a","r"}});
        before = p.sfen();
        require(material.choose(p) == "5e5d", "baseline reproduces poisoned-pawn mistake");
        const auto two_ply = minimax.choose(p);
        require(two_ply != "5e5d", "two-ply minimax must see the rook recapture");
        minimax.set_seed(2026);
        alphabeta2.set_seed(2026);
        require(alphabeta2.choose(p) == minimax.choose(p), "alpha-beta matches minimax on poisoned pawn");
        require(p.sfen() == before && p.status().result == rules::Result::Ongoing,
                "two-ply search must restore root position and history");
        require(alphabeta3.choose(p, {"5e5d"}) == "5e5d", "three-ply searchmoves restriction is respected");
        std::cout << "PASS prior two-ply poisoned-pawn behavior remains covered\n";

        p = fixture({{"9i","K"},{"5a","k"},{"4a","l"},{"6a","l"},
                     {"4b","p"},{"6b","p"},{"5c","P"},{"4c","G"}});
        before = p.sfen();
        require(alphabeta3.choose(p, {"5c5b", "4c4b"}) == "5c5b",
                "immediate mate outranks material");
        require(p.sfen() == before, "mate search restores root position");
        play(p, "5c5b");
        require(p.status().result == rules::Result::BlackWin, "fixture move is checkmate");
        std::cout << "PASS immediate terminal win still has priority over material\n";

        // Forced mate in three plies: 5c5b+ is not required; the unpromoted pawn
        // checks K5a, K6a is the only reply, then G7c6b is mate. B9e protects G6b.
        p = fixture({{"5a","k"},{"4a","l"},{"7a","l"},
                     {"4b","p"},{"6b","p"},{"7b","p"},
                     {"5c","P"},{"7c","G"},{"9e","B"},
                     {"5i","R"},{"9i","K"}});
        before = p.sfen();
        const std::vector<std::string> mate_candidates = {"5c5b", "9i8i"};
        const auto mate_oracle = brute_minimax3(p, 4242, mate_candidates);
        require(mate_oracle.move == "5c5b" && mate_oracle.score == strategy::AlphaBeta3::WinScore,
                "test oracle must identify the forced three-ply mate");
        alphabeta3.set_seed(4242);
        require(alphabeta3.choose(p, mate_candidates) == mate_oracle.move,
                "three-ply alpha-beta must find the forced mate");
        require(p.sfen() == before, "three-ply mate search restores root position");
        std::cout << "PASS three-ply search finds a forced mate on the third move\n";

        require(strategy::AlphaBeta3::terminal_score(rules::Result::BlackWin, rules::Color::Black)
                == strategy::AlphaBeta3::WinScore, "black win from black perspective");
        require(strategy::AlphaBeta3::terminal_score(rules::Result::BlackWin, rules::Color::White)
                == -strategy::AlphaBeta3::WinScore, "black win from white perspective");
        require(strategy::AlphaBeta3::terminal_score(rules::Result::Draw, rules::Color::Black) == 0,
                "draw score");

        // Keep the v0.0.5 proof: two-ply alpha-beta exactly matches unpruned Minimax2.
        p = rules::Position();
        std::uint64_t visited2 = 0, full2 = 0, cutoffs2 = 0;
        for (unsigned ply = 0; ply < 24; ++ply) {
            if (p.status().result != rules::Result::Ongoing) break;
            const unsigned seed = 10000u + ply;
            minimax.set_seed(seed);
            alphabeta2.set_seed(seed);
            const auto expected = minimax.choose(p);
            const auto actual = alphabeta2.choose(p);
            require(actual == expected, "two-ply alpha-beta must select exactly the minimax move");
            const auto stats = alphabeta2.last_stats();
            require(stats.nodes <= stats.full_nodes, "two-ply alpha-beta cannot visit more than full minimax tree");
            visited2 += stats.nodes;
            full2 += stats.full_nodes;
            cutoffs2 += stats.cutoffs;
            play(p, actual);
        }
        require(full2 > 0 && cutoffs2 > 0 && visited2 < full2, "two-ply alpha-beta must still prune");
        std::cout << "PASS v0.0.5 alpha-beta/minimax equivalence remains covered; nodes "
                  << visited2 << "/" << full2 << ", cutoffs " << cutoffs2 << "\n";

        // New v0.0.6 proof: compare the production AlphaBeta3 against a separate
        // exhaustive 3-ply minimax oracle on two deterministic positions.
        p = rules::Position();
        std::uint64_t visited3 = 0, full3 = 0, cutoffs3 = 0;
        for (unsigned sample = 0; sample < 2; ++sample) {
            const unsigned seed = 30000u + sample;
            const auto root_before = p.sfen();
            const auto oracle = brute_minimax3(p, seed);
            alphabeta3.set_seed(seed);
            const auto actual = alphabeta3.choose(p);
            require(actual == oracle.move, "three-ply alpha-beta must match exhaustive minimax");
            require(p.sfen() == root_before, "three-ply comparison must restore position");
            const auto stats = alphabeta3.last_stats();
            require(stats.nodes <= oracle.nodes, "three-ply alpha-beta cannot visit more nodes than exhaustive minimax");
            visited3 += stats.nodes;
            full3 += oracle.nodes;
            cutoffs3 += stats.cutoffs;
            play(p, actual);
            if (sample == 0 && p.status().result == rules::Result::Ongoing) {
                // Advance the opponent with a deterministic legal reply so the
                // second comparison is not just the initial position again.
                const auto replies = p.legal_moves();
                require(!replies.empty(), "deterministic comparison needs a reply");
                play(p, replies.front());
            }
        }
        require(full3 > 0 && cutoffs3 > 0 && visited3 < full3,
                "three-ply alpha-beta must prune versus exhaustive minimax");
        std::cout << "PASS exact three-ply minimax equivalence; nodes "
                  << visited3 << "/" << full3 << ", cutoffs " << cutoffs3 << "\n";

        p = rules::Position();
        alphabeta3.set_seed(12345); auto first = alphabeta3.choose(p);
        alphabeta3.set_seed(12345); require(alphabeta3.choose(p) == first, "three-ply tie seed reproducibility");
        require(p.sfen() == rules::Position::start_sfen(), "initial board unchanged");

        p = fixture({{"5i","K"},{"5a","k"}});
        for (int i = 0; i < 2; ++i)
            for (auto move : {"5i6i","5a6a","6i5i","6a5a"}) play(p, move);
        for (auto move : {"5i6i","5a6a","6i5i"}) play(p, move);
        before = p.sfen();
        require(alphabeta3.choose(p, {"6a5a"}) == "6a5a", "evaluate fourth repetition child");
        require(p.sfen() == before && p.status().result == rules::Result::Ongoing,
                "speculative repetition must restore history");
        play(p, "6a5a");
        require(p.status().result == rules::Result::Draw, "actual fourth repetition still detected");
        auto legal = p.legal_moves();
        auto move = alphabeta3.choose(p);
        require(std::find(legal.begin(), legal.end(), move) != legal.end(), "USI terminal compatibility");
        require(p.status().result == rules::Result::Draw, "terminal history preserved");
        std::cout << "PASS ties, repetition history and terminal compatibility\n";
    } catch (const std::exception& e) {
        std::cerr << "FAIL " << e.what() << '\n'; return 1;
    }
}
