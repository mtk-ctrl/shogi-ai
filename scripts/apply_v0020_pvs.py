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
    '''    struct Stats : BasicAlphaBeta3TT<Evaluator>::Stats {\n        std::uint64_t qnodes = 0, qcutoffs = 0, qlimit_leaves = 0;\n        int seldepth = 0;\n    };''',
    '''    struct Stats : BasicAlphaBeta3TT<Evaluator>::Stats {\n        std::uint64_t qnodes = 0, qcutoffs = 0, qlimit_leaves = 0;\n        std::uint64_t pvs_scout_searches = 0, pvs_researches = 0;\n        int seldepth = 0;\n    };''',
    "PVS stats",
)
text = replace_once(
    text,
    '''    void set_quiescence_enabled(bool enabled) {\n        if (quiescence_enabled_ != enabled) experience_.clear();\n        quiescence_enabled_ = enabled;\n    }''',
    '''    void set_quiescence_enabled(bool enabled) {\n        if (quiescence_enabled_ != enabled) experience_.clear();\n        quiescence_enabled_ = enabled;\n    }\n    void set_pvs_enabled(bool enabled) { pvs_enabled_ = enabled; }''',
    "PVS setter",
)
old_loop = '''        auto moves = ordered(p, p.legal_moves(), tt_move);\n        const bool maximizing = p.snapshot().turn == root_;\n        Node best{maximizing ? -Infinity : Infinity, {}};\n        for (const auto& move : moves) {\n            check_stop();\n            Node child;\n            {\n                make(p, move);\n                Undo undo{p};\n                visit(ply + 1);\n                child = search(p, depth - 1, ply + 1, alpha, beta,\n                               next_history(history, p.hash_key()));\n            }\n            const int value = child.value;'''
new_loop = '''        auto moves = ordered(p, p.legal_moves(), tt_move);\n        const bool maximizing = p.snapshot().turn == root_;\n        Node best{maximizing ? -Infinity : Infinity, {}};\n        bool first_child = true;\n        for (const auto& move : moves) {\n            check_stop();\n            Node child;\n            {\n                make(p, move);\n                Undo undo{p};\n                const auto child_history = next_history(history, p.hash_key());\n                auto run = [&](int child_alpha, int child_beta) {\n                    visit(ply + 1);\n                    return search(p, depth - 1, ply + 1, child_alpha, child_beta, child_history);\n                };\n                // Principal Variation Search: the first move gets the full window.\n                // Later moves first prove that they cannot improve the current bound\n                // with a one-point scout window. Only a genuine improvement is\n                // re-searched at the full window. Root move handling is unchanged so\n                // the exact root tie set remains compatible with v0.0.19.\n                if (!pvs_enabled_ || first_child || alpha + 1 >= beta) {\n                    child = run(alpha, beta);\n                } else if (maximizing) {\n                    ++stats_.pvs_scout_searches;\n                    child = run(alpha, alpha + 1);\n                    if (child.value > alpha && child.value < beta) {\n                        ++stats_.pvs_researches;\n                        child = run(alpha, beta);\n                    }\n                } else {\n                    ++stats_.pvs_scout_searches;\n                    child = run(beta - 1, beta);\n                    if (child.value < beta && child.value > alpha) {\n                        ++stats_.pvs_researches;\n                        child = run(alpha, beta);\n                    }\n                }\n            }\n            first_child = false;\n            const int value = child.value;'''
text = replace_once(text, old_loop, new_loop, "PVS child loop")
text = replace_once(
    text,
    '''    bool experience_enabled_ = false;\n    bool quiescence_enabled_ = true;\n    bool experience_allowed_ = false;''',
    '''    bool experience_enabled_ = false;\n    bool quiescence_enabled_ = true;\n    bool pvs_enabled_ = true;\n    bool experience_allowed_ = false;''',
    "PVS member",
)
path.write_text(text)

path = Path("tests/search_test.cpp")
text = path.read_text()
text = replace_once(
    text,
    '''        strategy::FeatureAlphaBeta3TT fixed;\n        strategy::IterativeSearch features;\n        features.set_quiescence_enabled(false);\n        p = rules::Position();\n        for (unsigned sample = 0; sample < 6; ++sample) {\n            fixed.set_seed(70000 + sample); features.set_seed(70000 + sample);\n            const auto expected = fixed.choose(p);\n            strategy::SearchControl control;\n            const auto actual = features.choose(p, 3, control);\n            require(actual.move == expected && actual.score == fixed.last_score(), "v0.0.13 depth-three compatibility");\n            validate_pv(p, actual); play(p, expected);\n        }\n        std::cout << "PASS v0.0.13 exact depth-three move/score equivalence on six opening positions\\n";''',
    '''        strategy::FeatureAlphaBeta3TT fixed;\n        strategy::IterativeSearch features;\n        strategy::IterativeSearch baseline_pvs_off;\n        features.set_quiescence_enabled(false);\n        baseline_pvs_off.set_quiescence_enabled(false);\n        baseline_pvs_off.set_pvs_enabled(false);\n        std::uint64_t baseline_nodes = 0, pvs_nodes = 0, pvs_scouts = 0, pvs_researches = 0;\n        p = rules::Position();\n        for (unsigned sample = 0; sample < 6; ++sample) {\n            fixed.set_seed(70000 + sample);\n            features.set_seed(70000 + sample);\n            baseline_pvs_off.set_seed(70000 + sample);\n            const auto expected = fixed.choose(p);\n            auto baseline_position = p.clone();\n            strategy::SearchControl baseline_control;\n            const auto baseline = baseline_pvs_off.choose(baseline_position, 3, baseline_control);\n            strategy::SearchControl control;\n            const auto actual = features.choose(p, 3, control);\n            require(actual.move == expected && actual.score == fixed.last_score(), "v0.0.13 depth-three compatibility");\n            require(actual.move == baseline.move && actual.score == baseline.score, "PVS preserves fixed-depth move and score");\n            baseline_nodes += baseline_pvs_off.last_stats().nodes;\n            pvs_nodes += features.last_stats().nodes;\n            pvs_scouts += features.last_stats().pvs_scout_searches;\n            pvs_researches += features.last_stats().pvs_researches;\n            validate_pv(p, actual); play(p, expected);\n        }\n        std::cout << "DIAG PVS nodes baseline=" << baseline_nodes << " pvs=" << pvs_nodes\n                  << " delta_pct=" << (100.0 * (double(pvs_nodes) - baseline_nodes) / baseline_nodes)\n                  << " scouts=" << pvs_scouts << " researches=" << pvs_researches << '\\n';\n        std::cout << "PASS v0.0.13 exact depth-three move/score equivalence on six opening positions\\n";''',
    "PVS fixed-depth comparison",
)
path.write_text(text)
