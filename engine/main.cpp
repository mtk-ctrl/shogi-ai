#include "rules/position.h"
#include "strategy/iterative_search.h"
#include "strategy/mate_search.h"
#include "strategy/mate_assist.h"
#include "strategy/search_limits.h"
#include "strategy/promotion_policy.h"
#include "strategy/long_think_budget.h"
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <atomic>
#include <condition_variable>
#include <mutex>
#include <thread>
#include <iostream>
#include <sstream>
#include <string>


int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);
    shogi::rules::Position position;
    shogi::strategy::IterativeSearch strategy;
    shogi::strategy::EvaluationParameters evaluation_parameters;
    bool material_profile = false;
    bool quiescence_enabled = true;
    bool mate_assist_enabled = true;
    bool valid_position = true;
    bool entering_king = true;
    bool position_knowledge_enabled = true;
    bool position_knowledge_loaded = false;
    unsigned random_seed = 5489u;
    std::string position_knowledge_file = "position-knowledge-v1.tsv";
    int default_depth = 3;
    bool adaptive_long_think_enabled = true;
    int long_think_used = 0;
    bool previous_root_score_valid = false;
    int previous_root_score = 0;
    std::string line;
    struct Session {
        shogi::strategy::SearchControl control;
        std::thread worker;
        std::atomic<bool> suppress{false};
        std::mutex mutex;
        std::condition_variable cv;
        bool release = false;
        bool mate_search = false;
        std::int64_t ponder_budget_ms = -1;
    };
    std::unique_ptr<Session> session;
    std::mutex output_mutex;
    auto emit = [&](const std::string& message) {
        std::lock_guard<std::mutex> lock(output_mutex);
        std::cout << message << std::flush;
    };
    auto finish_search = [&](bool discard) {
        if (!session) return;
        session->suppress.store(discard);
        session->control.stop.store(true);
        { std::lock_guard<std::mutex> lock(session->mutex); session->release = true; }
        session->cv.notify_all();
        session->worker.join();
        session.reset();
    };
    strategy.set_position_knowledge_enabled(true);

    auto ensure_position_knowledge_loaded = [&]() {
        if (!position_knowledge_enabled || position_knowledge_loaded) return;
        if (strategy.load_position_knowledge(position_knowledge_file)) {
            std::ostringstream out;
            out << "info string position_knowledge loaded " << strategy.position_knowledge_size()
                << " positions file " << position_knowledge_file << "\n";
            emit(out.str());
        } else {
            emit("info string position_knowledge unavailable file " + position_knowledge_file + "\n");
        }
        position_knowledge_loaded = true;
    };

    auto bestmove = [&](const std::string& move) { emit("bestmove " + move + "\n"); };

    while (std::getline(std::cin, line)) {
        std::istringstream input(line);
        std::string command;
        input >> command;
        if (command != "isready" && command != "stop" && command != "ponderhit" && command != "quit")
            finish_search(true);
        if (command == "usi") {
            std::cout << "id name KUMOJI v2.0.6\nid author mtk-ctrl + ChatGPT\n"
                      << "option name USI_Ponder type check default false\n"
                      << "option name USI_EnteringKingRule type combo default CSARule27 var CSARule27 var NoEnteringKing\n"
                      << "option name SearchDepth type spin default 3 min 1 max 64\n"
                      << "option name Quiescence type check default true\n"
                      << "option name MateAssist type check default true\n"
                      << "option name AdaptiveLongThink type check default true\n"
                      << "option name RandomSeed type spin default 5489 min 0 max 2147483647\n"
                      << "option name EvalProfile type combo default features var features var material\n"
                      << "option name EvalSafety type spin default " << evaluation_parameters.weights[0] << " min 0 max 10000\n"
                      << "option name EvalPressure type spin default " << evaluation_parameters.weights[1] << " min 0 max 10000\n"
                      << "option name EvalActivity type spin default " << evaluation_parameters.weights[2] << " min 0 max 10000\n"
                      << "option name EvalDanger type spin default " << evaluation_parameters.weights[3] << " min 0 max 10000\n"
                      << "option name EvalV2 type check default " << (evaluation_parameters.v2_enabled ? "true" : "false") << "\n"
                      << "option name EvalMaterialWeight type spin default " << evaluation_parameters.material_weight << " min 0 max 10000\n"
                      << "option name EvalInfluence type spin default " << evaluation_parameters.influence_weight << " min 0 max 10000\n"
                      << "option name EvalPotential type spin default " << evaluation_parameters.potential_weight << " min 0 max 10000\n"
                      << "option name EvalCoordination type spin default " << evaluation_parameters.coordination_weight << " min 0 max 10000\n"
                      << "option name EvalHandPotential type spin default " << evaluation_parameters.hand_potential_weight << " min 0 max 10000\n"
                      << "option name EvalThreat type spin default " << evaluation_parameters.threat_weight << " min 0 max 10000\n"
                      << "option name EvalPositionalCap type spin default " << evaluation_parameters.positional_cap << " min 0 max 5000\n"
                      << "option name PositionKnowledge type check default true\n"
                      << "option name PositionKnowledgeFile type string default position-knowledge-v1.tsv\n"
                      << "usiok\n" << std::flush;
        } else if (command == "eval") {
            const auto b = shogi::strategy::evaluate(position.snapshot(), material_profile
                ? shogi::strategy::EvaluationParameters::material_only() : evaluation_parameters);
            std::cout << "info string evaluation material " << b.material
                      << " material_term " << b.material_term
                      << " safety " << b.terms[0] << " pressure " << b.terms[1]
                      << " activity " << b.terms[2] << " danger " << b.terms[3]
                      << " influence " << b.terms[4] << " potential " << b.terms[5]
                      << " coordination " << b.terms[6] << " hand_potential " << b.terms[7]
                      << " threat " << b.terms[8]
                      << " positional_raw " << b.positional_unclamped
                      << " clamp " << b.clamp_adjustment << " total " << b.total << '\n' << std::flush;
        } else if (command == "isready") {
            if (!session) {
                ensure_position_knowledge_loaded();
            }
            emit("readyok\n");
        } else if (command == "usinewgame") {
            ensure_position_knowledge_loaded();
            strategy.set_seed(random_seed);
            long_think_used = 0;
            strategy.clear_research_continuation();
            previous_root_score_valid = false;
            previous_root_score = 0;
            std::string error;
            valid_position = position.set(shogi::rules::Position::start_sfen(), {}, error);
        } else if (command == "position") {
            std::string error;
            valid_position = position.set_usi(line, error);
            if (!valid_position) std::cout << "info string " << error << '\n' << std::flush;
        } else if (command == "go") {
            ensure_position_knowledge_loaded();
            std::vector<std::string> tokens, allowed;
            std::string token;
            while (input >> token) tokens.push_back(token);
            auto contains = [&](const std::string& value) {
                return std::find(tokens.begin(), tokens.end(), value) != tokens.end();
            };
            if (contains("mate")) {
                // v0.0.17 keeps a deliberately bounded self-authored tsume
                // solver. It proves mates up to five plies. Failure inside that
                // horizon is reported as timeout, never as a global "nomate".
                if (!valid_position || position.status().result != shogi::rules::Result::Ongoing) {
                    emit("checkmate timeout\n");
                    continue;
                }
                std::int64_t mate_budget_ms = 50;
                for (std::size_t i = 0; i < tokens.size(); ++i) {
                    if (tokens[i] != "mate" || i + 1 >= tokens.size()) continue;
                    if (tokens[i + 1] == "infinite") {
                        mate_budget_ms = -1;
                    } else {
                        try {
                            std::size_t used = 0;
                            const auto parsed = std::stoll(tokens[i + 1], &used);
                            if (used == tokens[i + 1].size())
                                mate_budget_ms = std::clamp<std::int64_t>(parsed, 0, 86400000);
                        } catch (...) {}
                    }
                    break;
                }
                const auto started_ns = shogi::strategy::SearchControl::now_ns();
                session = std::make_unique<Session>();
                auto* active = session.get();
                active->release = true;
                active->mate_search = true;
                if (mate_budget_ms >= 0)
                    active->control.deadline_ns.store(started_ns + mate_budget_ms * 1000000);
                auto mate_position = position.clone();
                active->worker = std::thread([&, active, started_ns,
                                              p = std::move(mate_position)]() mutable {
                    shogi::strategy::MateSearch solver;
                    const auto result = solver.solve(p, shogi::strategy::MateSearch::MaxMatePly,
                                                     active->control);
                    if (active->suppress.load()) return;
                    const auto ms = (shogi::strategy::SearchControl::now_ns() - started_ns) / 1000000;
                    std::ostringstream info;
                    info << "info string mate maxply " << shogi::strategy::MateSearch::MaxMatePly
                         << " nodes " << result.nodes << " time " << ms << "\n";
                    emit(info.str());
                    if (result.found()) {
                        std::ostringstream out;
                        out << "checkmate";
                        for (const auto& move : result.pv) out << ' ' << move;
                        out << '\n';
                        emit(out.str());
                    } else {
                        if (result.outcome == shogi::strategy::MateSearchResult::Outcome::NoMate)
                            emit("info string no mate proven within five plies\n");
                        emit("checkmate timeout\n");
                    }
                });
                continue;
            }
            const std::vector<std::string> keywords = {"btime","wtime","binc","winc","byoyomi",
                "movetime","depth","nodes","movestogo","infinite","ponder","mate"};
            bool restrict = false;
            for (std::size_t i = 0; i < tokens.size(); ++i) {
                if (tokens[i] != "searchmoves") continue;
                restrict = true;
                while (++i < tokens.size() && std::find(keywords.begin(), keywords.end(), tokens[i]) == keywords.end())
                    allowed.push_back(tokens[i]);
                break;
            }
            if (!valid_position || (restrict && allowed.empty())) { bestmove("resign"); continue; }
            const auto status = position.status();
            if (status.result != shogi::rules::Result::Ongoing) {
                emit("info string terminal " + status.reason + "\n");
                bestmove("resign"); continue;
            }
            if (!restrict && entering_king && position.can_declare_win()) {
                bestmove("win"); continue;
            }
            auto candidates = restrict ? allowed : position.legal_moves();
            candidates = shogi::strategy::PromotionPolicy::force_monotonic_promotions(
                position.snapshot(), candidates);
            if (candidates.empty()) { bestmove("resign"); continue; }

            const auto limits = shogi::strategy::parse_go_limits(tokens, position.snapshot().turn, default_depth);
            int current_ply = 1;
            {
                std::istringstream sfen_stream(position.sfen());
                std::string field;
                while (sfen_stream >> field) {
                    try {
                        std::size_t used = 0;
                        const int parsed = std::stoi(field, &used);
                        if (used == field.size()) current_ply = parsed;
                    } catch (...) {}
                }
            }
            using LongThinkBudget = shogi::strategy::LongThinkBudget;
            const bool long_think_slot =
                adaptive_long_think_enabled
                && limits.requested_movetime_ms == 200
                && !limits.ponder && !limits.infinite && limits.nodes == 0
                && LongThinkBudget::available(current_ply, long_think_used)
                && candidates.size() > 1;
            const bool long_think_fallback =
                long_think_slot && LongThinkBudget::must_spend(current_ply, long_think_used);

            const auto started_ns = shogi::strategy::SearchControl::now_ns();
            session = std::make_unique<Session>();
            auto* active = session.get();
            active->release = !limits.ponder && !limits.infinite;
            active->ponder_budget_ms = limits.budget_ms;
            active->control.node_limit = limits.nodes;
            if (!limits.ponder && !limits.infinite && limits.budget_ms >= 0)
                active->control.deadline_ns.store(started_ns + limits.budget_ms * 1000000);
            if (long_think_slot) {
                active->control.adaptive_long_think = true;
                active->control.force_long_think = long_think_fallback;
                active->control.has_previous_score = previous_root_score_valid;
                active->control.previous_score = previous_root_score;
                // parse_go_limits keeps a 10ms communication margin. Match a
                // "go movetime 1000" ceiling while continuing the same search.
                active->control.hard_deadline_ns = started_ns + 990LL * 1000000;
            }
            auto search_position = position.clone();
            active->worker = std::thread([&, active, started_ns, limits,
                                          allowed = std::move(allowed),
                                          candidates = std::move(candidates),
                                          p = std::move(search_position)]() mutable {
                auto info = [&](const shogi::strategy::SearchResult& result) {
                    if (active->suppress.load()) return;
                    const auto ms = (shogi::strategy::SearchControl::now_ns() - started_ns) / 1000000;
                    std::ostringstream out;
                    out << "info depth " << result.depth << " seldepth " << strategy.last_stats().seldepth << " time " << ms
                        << " nodes " << strategy.last_stats().nodes;
                    if (result.has_score) {
                        if (shogi::strategy::IterativeSearch::is_mate_score(result.score)) {
                            const auto distance = shogi::strategy::IterativeSearch::MateScore - std::abs(result.score);
                            out << " score mate " << (result.score > 0 ? distance : -distance);
                        } else out << " score cp " << result.score;
                    }
                    if (!result.pv.empty()) {
                        out << " pv";
                        for (const auto& move : result.pv) out << ' ' << move;
                    }
                    out << '\n';
                    emit(out.str());
                };
                shogi::strategy::SearchResult result;
                result.move = candidates.front(); result.pv = {result.move};
                bool mate_assist_forced = false;
                bool research_forced = false;
                try {
                    // Adopted research overrides 200ms search and MateAssist.
                    // No old research score is presented as a fresh evaluation.
                    if (const auto research = strategy.select_research_move(p, allowed)) {
                        research_forced = true;
                        result.move = research->move;
                        result.pv = {result.move};
                        result.depth = 0;
                        result.has_score = false;
                        previous_root_score_valid = false;
                        if (!active->suppress.load()) {
                            std::ostringstream out;
                            out << "info string research_decision id " << research->research_id
                                << " step " << (research->ply_index + 1)
                                << " total " << research->pv_length
                                << " move " << research->move << "\n";
                            emit(out.str());
                        }
                    }
                    // Keep ordinary fixed-depth/node/ponder semantics unchanged.
                    // Timed play gets a small shared attack+defence mate budget
                    // inside the original absolute move deadline.
                    if (!research_forced && mate_assist_enabled && limits.budget_ms >= 10 && !limits.ponder
                        && !limits.infinite && limits.nodes == 0) {
                        const auto assist_started = shogi::strategy::SearchControl::now_ns();
                        const auto assist_budget_ms = std::clamp<std::int64_t>(limits.budget_ms / 10, 1, 5);
                        shogi::strategy::MateAssist assist;
                        auto assist_result = assist.run(p, candidates, active->control, assist_budget_ms);
                        const auto assist_ms = (shogi::strategy::SearchControl::now_ns() - assist_started) / 1000000;
                        if (!active->suppress.load()) {
                            std::ostringstream out;
                            out << "info string mate_assist budget " << assist_budget_ms
                                << " time " << assist_ms
                                << " offense_nodes " << assist_result.offense_nodes
                                << " defense_nodes " << assist_result.defense_nodes
                                << " examined " << assist_result.defense_examined
                                << " unsafe " << assist_result.proven_unsafe
                                << " offense_timeout " << (assist_result.offense_timeout ? 1 : 0)
                                << " defense_timeout " << (assist_result.defense_timeout ? 1 : 0)
                                << " forced " << (assist_result.has_forced_move() ? 1 : 0)
                                << " forced_plies " << assist_result.forced_plies
                                << " all_unsafe " << (assist_result.all_proven_unsafe ? 1 : 0) << "\n";
                            emit(out.str());
                        }
                        if (assist_result.has_forced_move()) {
                            result.move = assist_result.forced_move;
                            result.pv = {result.move};
                            result.depth = 0;
                            result.has_score = true;
                            result.score = shogi::strategy::IterativeSearch::MateScore - assist_result.forced_plies;
                            mate_assist_forced = true;
                            // No ordinary search ran on this move. Prevent stale
                            // experience stats from the previous move being treated
                            // as new writes when the session finishes.
                            active->mate_search = true;
                        } else {
                            candidates = std::move(assist_result.candidates);
                            if (!candidates.empty()) {
                                result.move = candidates.front();
                                result.pv = {result.move};
                            }
                        }
                    }
                    if (!mate_assist_forced && !research_forced) {
                        result = strategy.choose(p, limits.max_depth, active->control, candidates, info);
                        const auto reason = static_cast<shogi::strategy::LongThinkReason>(
                            active->control.long_think_reason.load(std::memory_order_relaxed));
                        if (reason != shogi::strategy::LongThinkReason::None) {
                            ++long_think_used;
                            if (!active->suppress.load()) {
                                std::ostringstream out;
                                out << "info string long_think used " << long_think_used << "/10"
                                    << " reason " << shogi::strategy::long_think_reason_name(reason)
                                    << " base_ms 200 max_ms 1000\n";
                                emit(out.str());
                            }
                        }
                        if (result.has_score && !shogi::strategy::IterativeSearch::is_mate_score(result.score)) {
                            previous_root_score = result.score;
                            previous_root_score_valid = true;
                        } else {
                            previous_root_score_valid = false;
                        }
                    } else {
                        previous_root_score_valid = false;
                    }
                } catch (const std::exception& error) {
                    if (!active->suppress.load()) emit("info string search error " + std::string(error.what()) + "\n");
                }
                if (!result.has_score && !research_forced) info(result);
                if (!mate_assist_forced && !research_forced && !active->suppress.load()) {
                    const auto& stats = strategy.last_stats();
                    std::ostringstream out;
                    out << "info nodes " << stats.nodes << " string cutoffs " << stats.cutoffs
                        << " min_cutoffs " << stats.min_cutoffs << " max_cutoffs " << stats.max_cutoffs
                        << " leaves " << stats.leaf_evals << " terminals " << stats.terminal_nodes
                        << " qnodes " << stats.qnodes << " qcutoffs " << stats.qcutoffs
                        << " qlimit_leaves " << stats.qlimit_leaves
                        << " ply1 " << stats.nodes_by_ply[1] << " ply2 " << stats.nodes_by_ply[2]
                        << " ply3 " << stats.nodes_by_ply[3] << " order_calls " << stats.order_calls
                        << " ordered_moves " << stats.ordered_moves << " tt_probes " << stats.tt_probes
                        << " tt_hits " << stats.tt_hits << " tt_exact_hits " << stats.tt_exact_hits
                        << " tt_bound_cutoffs " << stats.tt_bound_cutoffs << " tt_stores " << stats.tt_store_calls
                        << " tt_replacements " << stats.tt_replacements << " tt_move_first " << stats.tt_move_first
                        << " tt_disabled_repetition " << stats.tt_disabled_repetition
                        << " knowledge_probes " << stats.knowledge_probes
                        << " knowledge_hits " << stats.knowledge_hits
                        << " knowledge_promotions " << stats.knowledge_promotions
                        << " knowledge_disabled_repetition " << stats.knowledge_disabled_repetition
                        << " knowledge_research_ms " << stats.knowledge_research_ms
                        << " knowledge_research_depth " << stats.knowledge_research_depth
                        << " knowledge_research_nodes " << stats.knowledge_research_nodes
                        << " knowledge_stable_ms " << stats.knowledge_stable_ms
                        << " knowledge_score_kind " << (stats.knowledge_score_kind.empty() ? "none" : stats.knowledge_score_kind)
                        << " knowledge_score_value " << stats.knowledge_score_value << '\n';
                    emit(out.str());
                }
                { std::unique_lock<std::mutex> lock(active->mutex);
                  active->cv.wait(lock, [&] { return active->release; }); }
                if (!active->suppress.load()) bestmove(result.move);
            });
        } else if (command == "stop") {
            finish_search(false);
        } else if (command == "ponderhit") {
            if (session) {
                if (session->ponder_budget_ms >= 0)
                    session->control.deadline_ns.store(shogi::strategy::SearchControl::now_ns()
                        + session->ponder_budget_ms * 1000000);
                { std::lock_guard<std::mutex> lock(session->mutex); session->release = true; }
                session->cv.notify_all();
            }
        } else if (command == "setoption") {
            std::string name, value, part;
            input >> part;
            if (part == "name") {
                while (input >> part && part != "value") { if (!name.empty()) name += ' '; name += part; }
                if (part == "value") std::getline(input >> std::ws, value);
                if (name == "SearchDepth") {
                    try { std::size_t used = 0; int depth = std::stoi(value, &used);
                        if (used == value.size() && depth >= 1 && depth <= 64) default_depth = depth;
                    } catch (...) {}
                } else if (name == "Quiescence") {
                    if (value == "true" || value == "false") {
                        quiescence_enabled = value == "true";
                        strategy.set_quiescence_enabled(quiescence_enabled);
                    }
                } else if (name == "MateAssist") {
                    if (value == "true" || value == "false") mate_assist_enabled = value == "true";
                } else if (name == "AdaptiveLongThink") {
                    if (value == "true" || value == "false")
                        adaptive_long_think_enabled = value == "true";
                } else if (name == "USI_EnteringKingRule") entering_king = (value == "CSARule27");
                else if (name == "PositionKnowledge") {
                    if (value == "true" || value == "false") {
                        position_knowledge_enabled = value == "true";
                        strategy.set_position_knowledge_enabled(position_knowledge_enabled);
                        if (position_knowledge_enabled) position_knowledge_loaded = false;
                    }
                } else if (name == "PositionKnowledgeFile") {
                    if (!value.empty() && value.find('\n') == std::string::npos && value.find('\r') == std::string::npos) {
                        position_knowledge_file = value;
                        strategy.clear_position_knowledge();
                        position_knowledge_loaded = false;
                    }
                } else if (name == "EvalProfile") {
                    if (value == "features" || value == "material") {
                        material_profile = value == "material";
                        strategy.set_evaluator(shogi::strategy::FeatureEvaluator(material_profile
                            ? shogi::strategy::EvaluationParameters::material_only() : evaluation_parameters));
                    }
                } else if (name == "EvalV2") {
                    if (value == "true" || value == "false") {
                        evaluation_parameters.v2_enabled = value == "true";
                        strategy.set_evaluator(shogi::strategy::FeatureEvaluator(material_profile
                            ? shogi::strategy::EvaluationParameters::material_only() : evaluation_parameters));
                    }
                } else if (name == "EvalSafety" || name == "EvalPressure" || name == "EvalActivity" || name == "EvalDanger"
                           || name == "EvalMaterialWeight" || name == "EvalInfluence" || name == "EvalPotential"
                           || name == "EvalCoordination" || name == "EvalHandPotential" || name == "EvalThreat"
                           || name == "EvalPositionalCap") {
                    try {
                        std::size_t used = 0;
                        const int weight = std::stoi(value, &used);
                        const int max_value = name == "EvalPositionalCap" ? 5000 : 10000;
                        if (used == value.size() && weight >= 0 && weight <= max_value) {
                                if (name == "EvalSafety") evaluation_parameters.weights[0] = weight;
                            else if (name == "EvalPressure") evaluation_parameters.weights[1] = weight;
                            else if (name == "EvalActivity") evaluation_parameters.weights[2] = weight;
                            else if (name == "EvalDanger") evaluation_parameters.weights[3] = weight;
                            else if (name == "EvalMaterialWeight") evaluation_parameters.material_weight = weight;
                            else if (name == "EvalInfluence") evaluation_parameters.influence_weight = weight;
                            else if (name == "EvalPotential") evaluation_parameters.potential_weight = weight;
                            else if (name == "EvalCoordination") evaluation_parameters.coordination_weight = weight;
                            else if (name == "EvalHandPotential") evaluation_parameters.hand_potential_weight = weight;
                            else if (name == "EvalThreat") evaluation_parameters.threat_weight = weight;
                            else evaluation_parameters.positional_cap = weight;
                            strategy.set_evaluator(shogi::strategy::FeatureEvaluator(material_profile
                                ? shogi::strategy::EvaluationParameters::material_only() : evaluation_parameters));
                        }
                    } catch (const std::exception&) {}
                } else if (name == "RandomSeed") {
                    try {
                        auto parsed = std::stoul(value);
                        if (parsed <= 2147483647ul) {
                            random_seed = static_cast<unsigned>(parsed);
                            strategy.set_seed(random_seed);
                        }
                    } catch (...) {
                    }
                }
            }
        } else if (command == "quit") {
            finish_search(true);
            break;
        }
    }
    finish_search(true);
}
