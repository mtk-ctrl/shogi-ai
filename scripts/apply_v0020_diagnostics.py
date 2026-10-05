from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


path = Path("engine/strategy/iterative_search.h")
text = path.read_text()
text = replace_once(
    text,
    '#include <atomic>\n#include <chrono>\n',
    '#include <array>\n#include <atomic>\n#include <chrono>\n',
    "array include",
)
text = replace_once(
    text,
    '''    struct Stats : BasicAlphaBeta3TT<Evaluator>::Stats {\n        std::uint64_t qnodes = 0, qcutoffs = 0, qlimit_leaves = 0;\n        int seldepth = 0;\n    };''',
    '''    struct Stats : BasicAlphaBeta3TT<Evaluator>::Stats {\n        static constexpr std::size_t CutoffRankBuckets = 8;\n        std::uint64_t qnodes = 0, qcutoffs = 0, qlimit_leaves = 0;\n        std::array<std::uint64_t, CutoffRankBuckets> cutoff_move_rank{};\n        std::uint64_t cutoff_move_rank_overflow = 0;\n        std::uint64_t cutoff_move_rank_sum = 0;\n        int seldepth = 0;\n    };''',
    "stats fields",
)
text = replace_once(
    text,
    '''    void visit(int ply) {\n        ++stats_.nodes;\n        stats_.seldepth = std::max(stats_.seldepth, ply);\n        if (ply < static_cast<int>(stats_.nodes_by_ply.size())) ++stats_.nodes_by_ply[ply];\n    }''',
    '''    void visit(int ply) {\n        ++stats_.nodes;\n        stats_.seldepth = std::max(stats_.seldepth, ply);\n        if (ply < static_cast<int>(stats_.nodes_by_ply.size())) ++stats_.nodes_by_ply[ply];\n    }\n    void record_cutoff_rank(std::size_t zero_based_rank) {\n        stats_.cutoff_move_rank_sum += zero_based_rank + 1;\n        if (zero_based_rank < stats_.cutoff_move_rank.size())\n            ++stats_.cutoff_move_rank[zero_based_rank];\n        else\n            ++stats_.cutoff_move_rank_overflow;\n    }''',
    "cutoff recorder",
)
text = replace_once(
    text,
    '''        Node best{maximizing ? -Infinity : Infinity, {}};\n        for (const auto& move : moves) {''',
    '''        Node best{maximizing ? -Infinity : Infinity, {}};\n        for (std::size_t move_index = 0; move_index < moves.size(); ++move_index) {\n            const auto& move = moves[move_index];''',
    "indexed full-width loop",
)
text = replace_once(
    text,
    '''                ++stats_.cutoffs;\n                if (maximizing) ++stats_.max_cutoffs; else ++stats_.min_cutoffs;\n                break;''',
    '''                ++stats_.cutoffs;\n                if (maximizing) ++stats_.max_cutoffs; else ++stats_.min_cutoffs;\n                record_cutoff_rank(move_index);\n                break;''',
    "cutoff rank hook",
)
path.write_text(text)

path = Path("tests/search_test.cpp")
text = path.read_text()
text = replace_once(
    text,
    '''        p = rules::Position();\n        for (unsigned sample = 0; sample < 6; ++sample) {''',
    '''        p = rules::Position();\n        std::array<std::uint64_t, strategy::IterativeSearch::Stats::CutoffRankBuckets> cutoff_ranks{};\n        std::uint64_t cutoff_overflow = 0, cutoff_rank_sum = 0, cutoff_count = 0;\n        for (unsigned sample = 0; sample < 6; ++sample) {''',
    "diagnostic accumulators",
)
text = replace_once(
    text,
    '''            const auto actual = features.choose(p, 3, control);\n            require(actual.move == expected && actual.score == fixed.last_score(), "v0.0.13 depth-three compatibility");\n            validate_pv(p, actual); play(p, expected);\n        }\n        std::cout << "PASS v0.0.13 exact depth-three move/score equivalence on six opening positions\\n";''',
    '''            const auto actual = features.choose(p, 3, control);\n            require(actual.move == expected && actual.score == fixed.last_score(), "v0.0.13 depth-three compatibility");\n            const auto& stats = features.last_stats();\n            cutoff_count += stats.cutoffs;\n            cutoff_overflow += stats.cutoff_move_rank_overflow;\n            cutoff_rank_sum += stats.cutoff_move_rank_sum;\n            for (std::size_t i = 0; i < cutoff_ranks.size(); ++i)\n                cutoff_ranks[i] += stats.cutoff_move_rank[i];\n            validate_pv(p, actual); play(p, expected);\n        }\n        std::uint64_t recorded_cutoffs = cutoff_overflow;\n        for (const auto count : cutoff_ranks) recorded_cutoffs += count;\n        require(cutoff_count > 0 && recorded_cutoffs == cutoff_count, "every full-width cutoff has a rank");\n        std::cout << "DIAG cutoff-rank total=" << cutoff_count\n                  << " first=" << cutoff_ranks[0]\n                  << " second=" << cutoff_ranks[1]\n                  << " third=" << cutoff_ranks[2]\n                  << " overflow8=" << cutoff_overflow\n                  << " avg=" << (double(cutoff_rank_sum) / cutoff_count) << '\\n';\n        std::cout << "PASS v0.0.13 exact depth-three move/score equivalence on six opening positions\\n";''',
    "diagnostic aggregation",
)
path.write_text(text)
