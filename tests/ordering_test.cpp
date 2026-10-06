#include "strategy/alphabeta3.h"
#include "strategy/alphabeta3_ordered.h"
#include "strategy/alphabeta3_tt.h"
#include "strategy/move_order.h"
#include "strategy/promotion_policy.h"
#include "strategy/transposition_table.h"
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
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
                empty = 0;
                sfen += it->second;
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

bool has_move(const std::vector<std::string>& moves, const std::string& move) {
    return std::find(moves.begin(), moves.end(), move) != moves.end();
}

int main() {
    try {
        auto p = fixture({{"9i","K"},{"5a","k"},{"4e","R"}});
        const auto snap = p.snapshot();
        const int checking = strategy::MoveOrder::score_move(snap, "4e5e");
        const int quiet = strategy::MoveOrder::score_move(snap, "4e4d");
        require(checking > quiet, "checking move must be ordered before a quiet move; scores="
                + std::to_string(checking) + "/" + std::to_string(quiet));
        play(p, "4e5e");
        require(p.in_check(), "ordering fixture must really give check");
        std::cout << "PASS checks are searched first\n";

        p = fixture({{"9i","K"},{"1a","k"},{"5e","B"},{"4d","r"},{"6d","p"}});
        const auto capture_snap = p.snapshot();
        const int rook_capture = strategy::MoveOrder::score_move(capture_snap, "5e4d");
        const int pawn_capture = strategy::MoveOrder::score_move(capture_snap, "5e6d");
        require(rook_capture > pawn_capture, "capturing a rook must outrank capturing a pawn");
        std::cout << "PASS high-value captures are searched early\n";

        p = fixture({{"9i","K"},{"1a","k"},{"5c","P"}});
        const auto promo_snap = p.snapshot();
        require(strategy::MoveOrder::score_move(promo_snap, "5c5b+")
                    > strategy::MoveOrder::score_move(promo_snap, "5c5b"),
                "promotion must outrank the equivalent non-promotion");
        std::cout << "PASS promotions are searched early\n";

        // Playing policy: pawn, bishop and rook promotions strictly extend the
        // unpromoted movement, so suppress their non-promoted twin whenever both
        // forms are legal. Silver remains optional because its move set changes.
        auto legal = p.legal_moves();
        require(has_move(legal, "5c5b") && has_move(legal, "5c5b+"),
                "pawn fixture must offer both promotion choices");
        auto policy = strategy::PromotionPolicy::force_monotonic_promotions(p.snapshot(), legal);
        require(!has_move(policy, "5c5b") && has_move(policy, "5c5b+"),
                "pawn must promote when the promoted twin is legal");

        p = fixture({{"9i","K"},{"1a","k"},{"5d","R"}});
        legal = p.legal_moves();
        require(has_move(legal, "5d5c") && has_move(legal, "5d5c+"),
                "rook fixture must offer both promotion choices");
        policy = strategy::PromotionPolicy::force_monotonic_promotions(p.snapshot(), legal);
        require(!has_move(policy, "5d5c") && has_move(policy, "5d5c+"),
                "rook must promote when the promoted twin is legal");

        p = fixture({{"9i","K"},{"1a","k"},{"5d","B"}});
        legal = p.legal_moves();
        require(has_move(legal, "5d4c") && has_move(legal, "5d4c+"),
                "bishop fixture must offer both promotion choices");
        policy = strategy::PromotionPolicy::force_monotonic_promotions(p.snapshot(), legal);
        require(!has_move(policy, "5d4c") && has_move(policy, "5d4c+"),
                "bishop must promote when the promoted twin is legal");

        p = fixture({{"9i","K"},{"1a","k"},{"5c","S"}});
        legal = p.legal_moves();
        require(has_move(legal, "5c5b") && has_move(legal, "5c5b+"),
                "silver fixture must offer both promotion choices");
        policy = strategy::PromotionPolicy::force_monotonic_promotions(p.snapshot(), legal);
        require(has_move(policy, "5c5b") && has_move(policy, "5c5b+"),
                "silver non-promotion must remain available");

        p = fixture({{"9i","K"},{"1a","k"},{"5c","P"}});
        const std::vector<std::string> restricted_only_nonpromotion = {"5c5b"};
        policy = strategy::PromotionPolicy::force_monotonic_promotions(
            p.snapshot(), restricted_only_nonpromotion);
        require(policy.size() == 1 && policy.front() == "5c5b",
                "USI searchmoves restriction must not invent an unavailable promoted twin");
        std::cout << "PASS pawn/rook/bishop forced promotion policy; silver and searchmoves stay valid\n";

        p = fixture({{"9i","K"},{"1a","k"},{"5e","R"},{"2b","b"},{"7g","P"}});
        const auto danger_snap = p.snapshot();
        require(strategy::MoveOrder::score_move(danger_snap, "5e5f")
                    > strategy::MoveOrder::score_move(danger_snap, "7g7f"),
                "moving a valuable piece off a major-piece ray must get priority");
        std::cout << "PASS escaping a major-piece ray is searched early\n";

        // Hand-drop tactics stay completely OFF unless requested. ON recognizes
        // a second direct target, rejects an unsupported immediate loss, accepts
        // a defended non-losing exchange, and recognizes slider skewers.
        p = fixture({{"9i","K"},{"1a","k"},{"4d","r"},{"6d","n"}}, "S");
        auto hand_snap = p.snapshot();
        const int fork_off = strategy::MoveOrder::score_move(hand_snap, "S*5e");
        const int fork_on = strategy::MoveOrder::score_move(hand_snap, "S*5e", true);
        require(fork_on > fork_off, "silver fork must gain ordering priority only when enabled");

        p = fixture({{"9i","K"},{"1a","k"},{"4d","r"},{"5d","p"},{"6d","g"}}, "S");
        hand_snap = p.snapshot();
        require(strategy::MoveOrder::score_move(hand_snap, "S*5e", true)
                    == strategy::MoveOrder::score_move(hand_snap, "S*5e", false),
                "unsupported drop lost to a pawn must not receive a fork bonus");

        p = fixture({{"9i","K"},{"1a","k"},{"4d","r"},{"5d","g"},{"5f","G"}}, "S");
        hand_snap = p.snapshot();
        require(strategy::MoveOrder::score_move(hand_snap, "S*5e", true)
                    > strategy::MoveOrder::score_move(hand_snap, "S*5e", false),
                "supported non-losing exchange may retain the fork bonus");

        p = fixture({{"9i","K"},{"1a","k"},{"5a","b"},{"5c","g"}}, "R");
        hand_snap = p.snapshot();
        require(strategy::MoveOrder::score_move(hand_snap, "R*5e", true)
                    > strategy::MoveOrder::score_move(hand_snap, "R*5e", false),
                "rook drop must recognize an enemy piece behind the front target as a skewer");
        std::cout << "PASS compressed hand-drop forks/skewers and exchange safety\n";

        // Effective-response mode keeps a genuine fork, but rejects an apparent
        // fork when one target can answer with a forcing counter-check that
        // prevents the dropped piece from taking the other target immediately.
        p = fixture({{"9i","K"},{"1a","k"},{"4d","n"},{"6d","n"}}, "S");
        auto effective_moves = strategy::MoveOrder::order(p, p.legal_moves(), true, true);
        require(!effective_moves.empty(), "effective-response ordering must return legal moves");
        const int genuine_base = strategy::MoveOrder::score_move(p.snapshot(), "S*5e", false);
        strategy::MoveOrder::Diagnostics genuine_diag;
        (void)strategy::MoveOrder::order(p, std::vector<std::string>{"S*5e"}, true, true, &genuine_diag);
        require(genuine_diag.geometric_candidates == 1 && genuine_diag.effective_candidates == 1,
                "genuine silver fork must survive legal-response validation");
        require(strategy::MoveOrder::score_move(p.snapshot(), "S*5e", true) > genuine_base,
                "genuine fork fixture must remain a geometric candidate");

        p = fixture({{"5i","K"},{"1a","k"},{"4d","r"},{"6d","n"}}, "S");
        strategy::MoveOrder::Diagnostics refuted_diag;
        (void)strategy::MoveOrder::order(p, std::vector<std::string>{"S*5e"}, true, true, &refuted_diag);
        require(refuted_diag.geometric_candidates == 1 && refuted_diag.effective_candidates == 0,
                "counter-check must refute the apparent immediate fork");
        require(refuted_diag.reply_checks > 0, "response validator must inspect legal replies");
        std::cout << "PASS legal-response validation keeps real forks and rejects forcing counter-checks\n";

        // The neutral hash follows the full position and survives undo exactly.
        p = rules::Position();
        const auto start_key = p.hash_key();
        play(p, "7g7f");
        require(p.hash_key() != start_key, "position hash must change after a move");
        require(p.undo(), "undo after hash test must succeed");
        require(p.hash_key() == start_key, "position hash must restore after undo");
        std::cout << "PASS neutral position hash changes and restores with the position\n";

        // Direct fixed-table behavior: exact key+depth hit, then logical clear by generation.
        strategy::TranspositionTable table;
        table.new_search();
        require(!table.probe(0x12345678ULL, 2), "fresh TT must miss");
        table.store(0x12345678ULL, 2, 314, strategy::TranspositionTable::Bound::Exact, "7g7f");
        const auto* direct_hit = table.probe(0x12345678ULL, 2);
        require(direct_hit && direct_hit->value == 314, "stored TT entry must hit");
        require(strategy::TranspositionTable::best_move(*direct_hit) == "7g7f",
                "TT must retain its move hint");
        require(!table.probe(0x12345678ULL, 1), "same position at a different depth must not alias");
        table.new_search();
        require(!table.probe(0x12345678ULL, 2), "new generation must make old entries invisible");
        std::cout << "PASS fixed-size TT key/depth/generation behavior\n";

        strategy::AlphaBeta3 baseline;
        strategy::AlphaBeta3Ordered ordered;
        strategy::AlphaBeta3TT cached;
        p = rules::Position();
        std::uint64_t baseline_nodes = 0;
        std::uint64_t ordered_nodes = 0;
        std::uint64_t cached_nodes = 0;
        for (unsigned sample = 0; sample < 4; ++sample) {
            require(p.status().result == rules::Result::Ongoing, "comparison position must be ongoing");
            const auto before = p.sfen();
            const unsigned seed = 70000u + sample;
            baseline.set_seed(seed);
            ordered.set_seed(seed);
            cached.set_seed(seed);
            const auto expected = baseline.choose(p);
            const auto ordered_move = ordered.choose(p);
            const auto cached_move = cached.choose(p);
            require(ordered_move == expected, "move ordering must preserve the v0.0.6 root choice");
            require(cached_move == ordered_move, "TT must preserve the v0.0.7 root choice");
            require(p.sfen() == before, "all searches must restore the root position");
            baseline_nodes += baseline.last_stats().nodes;
            ordered_nodes += ordered.last_stats().nodes;
            cached_nodes += cached.last_stats().nodes;
            play(p, cached_move);
            if (p.status().result != rules::Result::Ongoing) break;
            const auto replies = p.legal_moves();
            require(!replies.empty(), "comparison needs a deterministic reply");
            play(p, replies.front());
        }
        std::cout << "PASS v0.0.8 preserves v0.0.7/v0.0.6 choices; nodes cached/ordered/baseline "
                  << cached_nodes << "/" << ordered_nodes << "/" << baseline_nodes << "\n";

        // Two independent black pawn moves around a white king move create leaf
        // transpositions within one 3-ply search. Confirm the integrated table is used.
        p = fixture({{"9i","K"},{"1a","k"},{"7g","P"},{"3g","P"}});
        const std::vector<std::string> transpose_roots = {"7g7f", "3g3f"};
        ordered.set_seed(1234);
        cached.set_seed(1234);
        const auto without_tt = ordered.choose(p, transpose_roots);
        const auto with_tt = cached.choose(p, transpose_roots);
        require(with_tt == without_tt, "TT transposition fixture must preserve the selected move");
        require(cached.last_stats().tt_hits > 0, "transposition fixture must produce at least one TT hit");
        require(cached.last_stats().tt_exact_hits > 0, "transposition fixture must reuse an exact value");
        std::cout << "PASS integrated TT reuses transposed positions; hits="
                  << cached.last_stats().tt_hits << " exact=" << cached.last_stats().tt_exact_hits << "\n";

        // Repetition history is path-dependent. Disable TT for the whole search
        // once the incoming game already contains a repeated exact position.
        p = fixture({{"9i","K"},{"1a","k"}});
        play(p, "9i9h");
        play(p, "1a1b");
        play(p, "9h9i");
        play(p, "1b1a");
        require(p.has_repeated_history(), "king cycle must be detected as repeated history");
        ordered.set_seed(9876);
        cached.set_seed(9876);
        const auto repetition_expected = ordered.choose(p);
        const auto repetition_actual = cached.choose(p);
        require(repetition_actual == repetition_expected,
                "repetition-safe TT fallback must preserve the ordered-search choice");
        require(cached.last_stats().tt_disabled_repetition == 1,
                "TT must explicitly report repetition-history disablement");
        require(cached.last_stats().tt_probes == 0,
                "disabled TT must not probe path-independent cache entries");
        std::cout << "PASS TT disables itself for repetition-sensitive history\n";

        p = fixture({{"5a","k"},{"4a","l"},{"7a","l"},
                     {"4b","p"},{"6b","p"},{"7b","p"},
                     {"5c","P"},{"7c","G"},{"9e","B"},
                     {"5i","R"},{"9i","K"}});
        const std::vector<std::string> mate_candidates = {"5c5b", "9i8i"};
        cached.set_seed(4242);
        require(cached.choose(p, mate_candidates) == "5c5b",
                "TT search must retain the forced three-ply mate under explicit searchmoves");
        std::cout << "PASS forced third-ply mate survives transposition caching\n";
    } catch (const std::exception& e) {
        std::cerr << "FAIL " << e.what() << '\n';
        return 1;
    }
}
