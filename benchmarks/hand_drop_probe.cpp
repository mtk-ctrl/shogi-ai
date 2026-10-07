// Diagnostic-only root tracing. Compiled against a generated copy of our
// search header; the production engine and its search remain unchanged.
#include "strategy/iterative_search.h"
#include "strategy/promotion_policy.h"
#include <iomanip>
#include <iostream>
#include <sstream>
#include <map>

using namespace shogi;
int main() {
    std::string line;
    while (std::getline(std::cin, line)) {
        std::vector<std::string> fields;
        std::istringstream input(line);
        for (std::string field; std::getline(input, field, '|');) fields.push_back(field);
        if (fields.size() != 7) return 2;
        rules::Position p;
        std::string error;
        if (!p.set(fields[0], {}, error)) { std::cerr << error << '\n'; return 3; }
        const auto target = fields[1];
        const int ms = std::stoi(fields[2]), depth = std::stoi(fields[3]);
        const bool material = fields[4] == "1", qsearch = fields[5] == "1", forced = fields[6] == "1";
        const auto before = p.snapshot();
        auto legal = p.legal_moves();
        auto candidates = strategy::PromotionPolicy::force_monotonic_promotions(before, legal);
        auto ordered = strategy::MoveOrder::order(before, candidates);
        const auto target_it = std::find(ordered.begin(), ordered.end(), target);
        const bool valid = target_it != ordered.end();
        if (forced && !valid) return 4;
        strategy::IterativeSearch search(5489, strategy::FeatureEvaluator(material
            ? strategy::EvaluationParameters::material_only() : strategy::EvaluationParameters{}));
        search.set_experience_enabled(false);
        search.set_quiescence_enabled(qsearch);
        struct Trace { int started = 0, finished = 0; bool target_started = false, target_finished = false; int target_value = 0; };
        std::map<int, Trace> traces;
        search.set_root_diagnostic([&](int d, const std::string& move, bool finished, int value) {
            auto& t = traces[d];
            if (finished) ++t.finished; else ++t.started;
            if (move == target) {
                if (finished) { t.target_finished = true; t.target_value = value; }
                else t.target_started = true;
            }
        });
        strategy::SearchControl control;
        const auto started = strategy::SearchControl::now_ns();
        if (ms > 0) control.deadline_ns = started + ms * 1000000LL;
        auto result = search.choose(p, depth, control, forced ? std::vector<std::string>{target} : candidates);
        const auto elapsed = (strategy::SearchControl::now_ns() - started) / 1000000.0;
        const auto& stats = search.last_stats();
        std::cout << "{\"target_legal\":" << (valid ? "true" : "false")
                  << ",\"legal_count\":" << legal.size()
                  << ",\"drop_count\":" << std::count_if(legal.begin(), legal.end(), [](const auto& m){ return m[1] == '*'; })
                  << ",\"target_order_rank\":" << (valid ? int(target_it - ordered.begin()) + 1 : -1)
                  << ",\"target_order_score\":" << (valid ? strategy::MoveOrder::score_move(before, target) : 0)
                  << ",\"bestmove\":" << std::quoted(result.move)
                  << ",\"depth\":" << result.depth << ",\"score\":" << result.score
                  << ",\"has_score\":" << (result.has_score ? "true" : "false")
                  << ",\"nodes\":" << stats.nodes << ",\"qnodes\":" << stats.qnodes
                  << ",\"elapsed_ms\":" << elapsed << ",\"pv\":[";
        for (std::size_t i = 0; i < result.pv.size(); ++i) {
            if (i) std::cout << ',';
            std::cout << std::quoted(result.pv[i]);
        }
        std::cout << "],\"root_iterations\":[";
        bool comma = false;
        for (const auto& [d,t] : traces) {
            if (comma) std::cout << ',';
            comma = true;
            std::cout << "{\"depth\":" << d << ",\"started\":" << t.started << ",\"finished\":" << t.finished
                      << ",\"target_started\":" << (t.target_started ? "true" : "false")
                      << ",\"target_finished\":" << (t.target_finished ? "true" : "false")
                      << ",\"target_returned_bound\":" << t.target_value << '}';
        }
        std::cout << "]}\n" << std::flush;
    }
}
