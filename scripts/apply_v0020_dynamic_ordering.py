from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)

# Expose the already-computed base ordering scores so the iterative search can
# refine only the quiet suffix without rebuilding AttackMap per move.
path = Path("engine/strategy/move_order.h")
text = path.read_text()
old = '''    static std::vector<std::string> order(const rules::Snapshot& snapshot,\n                                          const std::vector<std::string>& moves) {\n        // Source-square danger is the same for every candidate. Build it once\n        // per position instead of rescanning the board for every move.\n        const AttackMap before_attacks(snapshot);\n        std::vector<OrderedMove> scored;\n        scored.reserve(moves.size());\n        for (std::size_t i = 0; i < moves.size(); ++i)\n            scored.push_back({moves[i], score_move(snapshot, moves[i], before_attacks), i});\n\n        std::stable_sort(scored.begin(), scored.end(), [](const auto& a, const auto& b) {\n            return a.score > b.score;\n        });\n\n        std::vector<std::string> ordered;\n        ordered.reserve(scored.size());\n        for (const auto& item : scored) ordered.push_back(item.move);\n        return ordered;\n    }'''
new = '''    static std::vector<OrderedMove> order_scored(const rules::Snapshot& snapshot,\n                                                 const std::vector<std::string>& moves) {\n        // Source-square danger is the same for every candidate. Build it once\n        // per position instead of rescanning the board for every move.\n        const AttackMap before_attacks(snapshot);\n        std::vector<OrderedMove> scored;\n        scored.reserve(moves.size());\n        for (std::size_t i = 0; i < moves.size(); ++i)\n            scored.push_back({moves[i], score_move(snapshot, moves[i], before_attacks), i});\n\n        std::stable_sort(scored.begin(), scored.end(), [](const auto& a, const auto& b) {\n            return a.score > b.score;\n        });\n        return scored;\n    }\n\n    static std::vector<std::string> order(const rules::Snapshot& snapshot,\n                                          const std::vector<std::string>& moves) {\n        auto scored = order_scored(snapshot, moves);\n        std::vector<std::string> ordered;\n        ordered.reserve(scored.size());\n        for (const auto& item : scored) ordered.push_back(item.move);\n        return ordered;\n    }'''
text = replace_once(text, old, new, "MoveOrder scored API")
path.write_text(text)

path = Path("engine/strategy/iterative_search.h")
text = path.read_text()
text = replace_once(
    text,
    '''        std::uint64_t cutoff_move_rank_overflow = 0;\n        std::uint64_t cutoff_move_rank_sum = 0;\n        int seldepth = 0;''',
    '''        std::uint64_t cutoff_move_rank_overflow = 0;\n        std::uint64_t cutoff_move_rank_sum = 0;\n        std::uint64_t dynamic_order_calls = 0, dynamic_reorders = 0;\n        std::uint64_t killer_cutoff_updates = 0, history_cutoff_updates = 0;\n        int seldepth = 0;''',
    "dynamic stats",
)
text = replace_once(
    text,
    '''    void set_quiescence_enabled(bool enabled) {\n        if (quiescence_enabled_ != enabled) experience_.clear();\n        quiescence_enabled_ = enabled;\n    }''',
    '''    void set_quiescence_enabled(bool enabled) {\n        if (quiescence_enabled_ != enabled) experience_.clear();\n        quiescence_enabled_ = enabled;\n    }\n    void set_dynamic_ordering_enabled(bool enabled) { dynamic_ordering_enabled_ = enabled; }''',
    "dynamic ordering setter",
)
text = replace_once(
    text,
    '''        stats_ = {};\n        control_ = &control;''',
    '''        stats_ = {};\n        killers_ = {};\n        history_scores_.fill(0);\n        control_ = &control;''',
    "reset dynamic tables",
)
text = replace_once(
    text,
    '''                auto moves = ordered(position, original, {}, depth >= 4 && result.depth ? result.move : "");''',
    '''                auto moves = ordered(position, original, {}, depth >= 4 && result.depth ? result.move : "", 0);''',
    "root dynamic ordering",
)
text = replace_once(
    text,
    '''    void record_cutoff_rank(std::size_t zero_based_rank) {\n        stats_.cutoff_move_rank_sum += zero_based_rank + 1;\n        if (zero_based_rank < stats_.cutoff_move_rank.size())\n            ++stats_.cutoff_move_rank[zero_based_rank];\n        else\n            ++stats_.cutoff_move_rank_overflow;\n    }''',
    '''    void record_cutoff_rank(std::size_t zero_based_rank) {\n        stats_.cutoff_move_rank_sum += zero_based_rank + 1;\n        if (zero_based_rank < stats_.cutoff_move_rank.size())\n            ++stats_.cutoff_move_rank[zero_based_rank];\n        else\n            ++stats_.cutoff_move_rank_overflow;\n    }\n    static constexpr int HistoryFromCount = 88; // 81 board squares + 7 drop piece kinds\n    static constexpr int HistorySize = 2 * HistoryFromCount * 81 * 2;\n    static int square_index(char file, char rank) {\n        if (file < '1' || file > '9' || rank < 'a' || rank > 'i') return -1;\n        return (file - '1') * 9 + (rank - 'a');\n    }\n    static int drop_source(char piece) {\n        switch (piece) {\n            case 'P': return 81; case 'L': return 82; case 'N': return 83;\n            case 'S': return 84; case 'B': return 85; case 'R': return 86;\n            case 'G': return 87; default: return -1;\n        }\n    }\n    static int history_index(const std::string& move, rules::Color side) {\n        if (move.size() < 4) return -1;\n        const bool drop = move[1] == '*';\n        const int from = drop ? drop_source(move[0]) : square_index(move[0], move[1]);\n        const int to = drop ? square_index(move[2], move[3]) : square_index(move[2], move[3]);\n        if (from < 0 || to < 0) return -1;\n        const int promotion = !drop && move.size() >= 5 && move[4] == '+' ? 1 : 0;\n        return (((static_cast<int>(side) * HistoryFromCount + from) * 81 + to) * 2 + promotion);\n    }\n    static bool quiet_move(const rules::Snapshot& snapshot, const std::string& move) {\n        if (move.size() < 4) return false;\n        if (move[1] == '*') return true;\n        const int to = square_index(move[2], move[3]);\n        if (to < 0) return false;\n        const bool capture = snapshot.board[to].kind != 0;\n        const bool promotion = move.size() >= 5 && move[4] == '+';\n        return !capture && !promotion;\n    }\n    int dynamic_order_score(const rules::Snapshot& snapshot, const std::string& move, int ply) const {\n        int score = 0;\n        const int index = history_index(move, snapshot.turn);\n        if (index >= 0) score += history_scores_[index];\n        if (ply >= 0 && ply < MaxPly) {\n            if (killers_[ply][0] == move) score += 2000000;\n            else if (killers_[ply][1] == move) score += 1000000;\n        }\n        return score;\n    }\n    void note_cutoff(const rules::Position& p, const std::string& move, int depth, int ply) {\n        if (!dynamic_ordering_enabled_) return;\n        const auto snapshot = p.snapshot();\n        if (!quiet_move(snapshot, move)) return;\n        if (ply >= 0 && ply < MaxPly) {\n            if (killers_[ply][0] != move) {\n                killers_[ply][1] = killers_[ply][0];\n                killers_[ply][0] = move;\n            }\n            ++stats_.killer_cutoff_updates;\n        }\n        const int index = history_index(move, snapshot.turn);\n        if (index >= 0) {\n            const int bonus = std::min(4096, std::max(1, depth * depth * 64));\n            history_scores_[index] = std::min(1000000, history_scores_[index] + bonus);\n            ++stats_.history_cutoff_updates;\n        }\n    }''',
    "dynamic helper functions",
)
text = replace_once(
    text,
    '''        auto moves = ordered(p, p.legal_moves(), tt_move);''',
    '''        auto moves = ordered(p, p.legal_moves(), tt_move, {}, ply);''',
    "search ordering ply",
)
text = replace_once(
    text,
    '''                record_cutoff_rank(move_index);\n                break;''',
    '''                record_cutoff_rank(move_index);\n                note_cutoff(p, move, depth, ply);\n                break;''',
    "cutoff learning",
)
old_ordered = '''    std::vector<std::string> ordered(const rules::Position& p,\n                                    const std::vector<std::string>& moves,\n                                    const std::string& tt_move = {},\n                                    const std::string& previous_root = {}) {\n        ++stats_.order_calls;\n        stats_.ordered_moves += moves.size();\n        auto result = MoveOrder::order(p.snapshot(), moves);\n        auto promote = [&](const std::string& hint) {\n            auto it = std::find(result.begin(), result.end(), hint);\n            if (it == result.end()) return false;\n            std::rotate(result.begin(), it, std::next(it)); return true;\n        };'''
new_ordered = '''    std::vector<std::string> ordered(const rules::Position& p,\n                                    const std::vector<std::string>& moves,\n                                    const std::string& tt_move = {},\n                                    const std::string& previous_root = {},\n                                    int ply = -1) {\n        ++stats_.order_calls;\n        stats_.ordered_moves += moves.size();\n        const auto snapshot = p.snapshot();\n        auto scored = MoveOrder::order_scored(snapshot, moves);\n        if (dynamic_ordering_enabled_ && ply >= 0) {\n            auto first_quiet = std::find_if(scored.begin(), scored.end(), [](const auto& item) {\n                return item.score == 0;\n            });\n            if (first_quiet != scored.end()) {\n                ++stats_.dynamic_order_calls;\n                const std::string old_first = first_quiet->move;\n                std::stable_sort(first_quiet, scored.end(), [&](const auto& a, const auto& b) {\n                    return dynamic_order_score(snapshot, a.move, ply)\n                        > dynamic_order_score(snapshot, b.move, ply);\n                });\n                if (first_quiet->move != old_first) ++stats_.dynamic_reorders;\n            }\n        }\n        std::vector<std::string> result;\n        result.reserve(scored.size());\n        for (const auto& item : scored) result.push_back(item.move);\n        auto promote = [&](const std::string& hint) {\n            auto it = std::find(result.begin(), result.end(), hint);\n            if (it == result.end()) return false;\n            std::rotate(result.begin(), it, std::next(it)); return true;\n        };'''
text = replace_once(text, old_ordered, new_ordered, "dynamic ordered implementation")
text = replace_once(
    text,
    '''    bool experience_enabled_ = false;\n    bool quiescence_enabled_ = true;''',
    '''    std::array<std::array<std::string, 2>, MaxPly> killers_{};\n    std::array<int, HistorySize> history_scores_{};\n    bool experience_enabled_ = false;\n    bool quiescence_enabled_ = true;\n    bool dynamic_ordering_enabled_ = true;''',
    "dynamic table members",
)
path.write_text(text)

# Invalidate persisted experience because timed-search move ordering semantics changed.
path = Path("engine/main.cpp")
text = path.read_text()
text = replace_once(
    text,
    '''    mix(3); // Quiescence, history-safe score keys and extended mate distance.''',
    '''    mix(4); // v0.0.20 killer/history ordering changes timed-search move preference.''',
    "experience signature version",
)
path.write_text(text)

# Compare the new ordering against an in-binary old-ordering control on the same
# six opening positions while preserving the existing v0.0.13 compatibility test.
path = Path("tests/search_test.cpp")
text = path.read_text()
text = replace_once(
    text,
    '''        strategy::FeatureAlphaBeta3TT fixed;\n        strategy::IterativeSearch features;\n        features.set_quiescence_enabled(false);''',
    '''        strategy::FeatureAlphaBeta3TT fixed;\n        strategy::IterativeSearch features;\n        strategy::IterativeSearch baseline_order;\n        features.set_quiescence_enabled(false);\n        baseline_order.set_quiescence_enabled(false);\n        baseline_order.set_dynamic_ordering_enabled(false);''',
    "baseline search instance",
)
text = replace_once(
    text,
    '''        std::uint64_t cutoff_overflow = 0, cutoff_rank_sum = 0, cutoff_count = 0;\n        for (unsigned sample = 0; sample < 6; ++sample) {\n            fixed.set_seed(70000 + sample); features.set_seed(70000 + sample);\n            const auto expected = fixed.choose(p);\n            strategy::SearchControl control;\n            const auto actual = features.choose(p, 3, control);''',
    '''        std::uint64_t cutoff_overflow = 0, cutoff_rank_sum = 0, cutoff_count = 0;\n        std::uint64_t baseline_nodes = 0, dynamic_nodes = 0, dynamic_reorders = 0;\n        for (unsigned sample = 0; sample < 6; ++sample) {\n            fixed.set_seed(70000 + sample);\n            features.set_seed(70000 + sample);\n            baseline_order.set_seed(70000 + sample);\n            const auto expected = fixed.choose(p);\n            auto baseline_position = p.clone();\n            strategy::SearchControl baseline_control;\n            const auto baseline_result = baseline_order.choose(baseline_position, 3, baseline_control);\n            strategy::SearchControl control;\n            const auto actual = features.choose(p, 3, control);\n            require(baseline_result.move == actual.move && baseline_result.score == actual.score,\n                    "dynamic ordering preserves fixed-depth move and score");\n            baseline_nodes += baseline_order.last_stats().nodes;''',
    "baseline comparison",
)
text = replace_once(
    text,
    '''            const auto& stats = features.last_stats();\n            cutoff_count += stats.cutoffs;''',
    '''            const auto& stats = features.last_stats();\n            dynamic_nodes += stats.nodes;\n            dynamic_reorders += stats.dynamic_reorders;\n            cutoff_count += stats.cutoffs;''',
    "dynamic node aggregation",
)
text = replace_once(
    text,
    '''                  << " overflow8=" << cutoff_overflow\n                  << " avg=" << (double(cutoff_rank_sum) / cutoff_count) << '\\n';\n        std::cout << "PASS v0.0.13 exact depth-three move/score equivalence on six opening positions\\n";''',
    '''                  << " overflow8=" << cutoff_overflow\n                  << " avg=" << (double(cutoff_rank_sum) / cutoff_count) << '\\n';\n        std::cout << "DIAG dynamic-order nodes baseline=" << baseline_nodes\n                  << " candidate=" << dynamic_nodes\n                  << " delta_pct=" << (100.0 * (double(dynamic_nodes) - baseline_nodes) / baseline_nodes)\n                  << " reorders=" << dynamic_reorders << '\\n';\n        std::cout << "PASS v0.0.13 exact depth-three move/score equivalence on six opening positions\\n";''',
    "dynamic diagnostics output",
)
path.write_text(text)
