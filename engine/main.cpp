#include "rules/position.h"
#include "strategy/iterative_search.h"
#include "strategy/mate_search.h"
#include "strategy/mate_assist.h"
#include "strategy/opening_book.h"
#include "strategy/search_limits.h"
#include "strategy/promotion_policy.h"
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

namespace {
std::uint64_t experience_signature(const shogi::strategy::EvaluationParameters& p,
                                   bool material_profile, bool quiescence_enabled) {
    // FNV-1a over every evaluation setting that can change move preference plus
    // a search-semantics version. Disk experience from incompatible settings is
    // ignored rather than silently influencing move ordering.
    std::uint64_t h = 1469598103934665603ULL;
    auto mix = [&](std::uint64_t value) {
        for (int i = 0; i < 8; ++i) {
            h ^= (value >> (i * 8)) & 0xffULL;
            h *= 1099511628211ULL;
        }
    };
    mix(3); // Quiescence, history-safe score keys and extended mate distance.
    mix(quiescence_enabled ? 1 : 0);
    mix(shogi::strategy::IterativeSearch::QuiescenceDepth);
    mix(material_profile ? 1 : 0);
    mix(p.guard_gold); mix(p.guard_silver); mix(p.guard_pawn);
    mix(p.pressure_king); mix(p.pressure_occupied); mix(p.pressure_empty);
    mix(p.pressure_partner); mix(p.mobility_major); mix(p.mobility_minor);
    mix(p.mobility_piece_cap); mix(p.danger_numerator); mix(p.danger_denominator);
    for (int value : p.caps) mix(static_cast<std::uint64_t>(value));
    for (int value : p.weights) mix(static_cast<std::uint64_t>(value));
    mix(p.positional_cap);
    return h;
}
} // namespace

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);
    shogi::rules::Position position;
    shogi::strategy::IterativeSearch strategy;
    shogi::strategy::OpeningBook opening_book;
    shogi::strategy::EvaluationParameters evaluation_parameters;
    bool material_profile = false;
    bool quiescence_enabled = true;
    bool mate_assist_enabled = true;
    bool opening_book_enabled = true;
    bool opening_book_loaded = false;
    bool valid_position = true;
    bool entering_king = true;
    bool experience_enabled = true;
    bool experience_loaded = false;
    bool experience_dirty = false;
    unsigned random_seed = 5489u;
    std::string opening_book_file = "shogi-ai-book.tsv";
    std::string experience_file = "shogi-ai-experience.bin";
    int default_depth = 3;
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
        if (!session->mate_search && experience_enabled && strategy.last_stats().experience_stores > 0) experience_dirty = true;
        session.reset();
    };
    strategy.set_experience_enabled(true);

    auto ensure_opening_book_loaded = [&]() {
        if (!opening_book_enabled || opening_book_loaded) return;
        if (opening_book.load(opening_book_file)) {
            std::ostringstream out;
            out << "info string opening_book loaded " << opening_book.positions()
                << " positions " << opening_book.entries() << " entries\n";
            emit(out.str());
        }
        opening_book_loaded = true;
    };
    auto current_experience_signature = [&]() {
        return experience_signature(evaluation_parameters, material_profile, quiescence_enabled);
    };
    auto ensure_experience_loaded = [&]() {
        if (!experience_enabled || experience_loaded) return;
        if (strategy.load_experience(experience_file, current_experience_signature())) {
            std::cout << "info string experience cache loaded " << strategy.experience_size()
                      << " entries\n" << std::flush;
        }
        // A missing, stale, corrupt or unwritable file is non-fatal. Mark the
        // attempt complete so ordinary search proceeds without repeated I/O.
        experience_loaded = true;
        experience_dirty = false;
    };
    auto persist_experience = [&]() {
        if (!experience_enabled || !experience_loaded || !experience_dirty) return;
        if (strategy.save_experience(experience_file, current_experience_signature())) {
            experience_dirty = false;
        }
    };
    auto invalidate_experience = [&]() {
        strategy.clear_experience();
        experience_loaded = false;
        experience_dirty = false;
    };
    auto bestmove = [&](const std::string& move) { emit("bestmove " + move + "\n"); };

    while (std::getline(std::cin, line)) {
        std::istringstream input(line);
        std::string command;
        input >> command;
        if (command != "isready" && command != "stop" && command != "ponderhit" && command != "quit")
            finish_search(true);
        if (command == "usi") {
            std::cout << "id name KUMOJI v1.0.1\nid author mtk-ctrl + ChatGPT\n"
                      << "option name USI_Ponder type check default false\n"
                      << "option name USI_EnteringKingRule type combo default CSARule27 var CSARule27 var NoEnteringKing\n"
                      << "option name SearchDepth type spin default 3 min 1 max 64\n"
                      << "option name Quiescence type check default true\n"
                      << "option name MateAssist type check default true\n"
                      << "option name OpeningBook type check default true\n"
                      << "option name OpeningBookFile type string default shogi-ai-book.tsv\n"
                      << "option name RandomSeed type spin default 5489 min 0 max 2147483647\n"
                      << "option name EvalProfile type combo default features var features var material\n"
                      << "option name EvalSafety type spin default 50 min 0 max 400\n"
                      << "option name EvalPressure type spin default 150 min 0 max 400\n"
                      << "option name EvalActivity type spin default 150 min 0 max 400\n"
                      << "option name EvalDanger type spin default 200 min 0 max 400\n"
                      << "option name ExperienceCache type check default true\n"
                      << "option name ExperienceFile type string default shogi-ai-experience.bin\n"
                      << "usiok\n" << std::flush;
        } else if (command == "eval") {
            const auto b = shogi::strategy::evaluate(position.snapshot(), material_profile
                ? shogi::strategy::EvaluationParameters::material_only() : evaluation_parameters);
            std::cout << "info string evaluation material " << b.material
                      << " safety " << b.terms[0] << " pressure " << b.terms[1]
                      << " activity " << b.terms[2] << " danger " << b.terms[3]
                      << " clamp " << b.clamp_adjustment << " total " << b.total << '\n' << std::flush;
        } else if (command == "isready") {
            if (!session) {
                ensure_experience_loaded();
                ensure_opening_book_loaded();
            }
            emit("readyok\n");
        } else if (command == "usinewgame") {
            persist_experience();
            ensure_experience_loaded();
            ensure_opening_book_loaded();
            strategy.set_seed(random_seed);
            std::string error;
            valid_position = position.set(shogi::rules::Position::start_sfen(), {}, error);
        } else if (command == "position") {
            std::string error;
            valid_position = position.set_usi(line, error);
            if (!valid_position) std::cout << "info string " << error << '\n' << std::flush;
        } else if (command == "go") {
            ensure_experience_loaded();
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

            // A book hit is a complete move decision, not a search-order hint.
            // Ponder/infinite remain search sessions so their stop semantics are unchanged.
            ensure_opening_book_loaded();
            if (opening_book_enabled && !contains("ponder") && !contains("infinite")) {
                if (const auto picked = opening_book.pick(position.hash_key(), candidates, random_seed)) {
                    std::ostringstream out;
                    out << "info string opening_book hit move " << picked->move
                        << " samples " << picked->samples
                        << " score_milli " << picked->score_milli << "\n";
                    emit(out.str());

                    // Book moves bypass ordinary search, but GUIs such as ShogiDroid
                    // still need a score sample to build a continuous evaluation graph.
                    // Evaluate the position after the selected legal book move and
                    // convert Black-minus-White into the root side's perspective.
                    auto book_position = position.clone();
                    std::string book_error;
                    if (book_position.play_generated_legal(picked->move, book_error)) {
                        const auto root_turn = position.turn();
                        const auto book_eval = shogi::strategy::evaluate(
                            book_position.snapshot(), material_profile
                                ? shogi::strategy::EvaluationParameters::material_only()
                                : evaluation_parameters);
                        const int book_score = root_turn == shogi::rules::Color::Black
                            ? book_eval.total : -book_eval.total;
                        std::ostringstream score;
                        score << "info depth 0 seldepth 0 time 0 nodes 0 score cp " << book_score
                              << " pv " << picked->move << "\n";
                        emit(score.str());
                    }
                    bestmove(picked->move);
                    continue;
                }
            }

            const auto limits = shogi::strategy::parse_go_limits(tokens, position.snapshot().turn, default_depth);
            const auto started_ns = shogi::strategy::SearchControl::now_ns();
            session = std::make_unique<Session>();
            auto* active = session.get();
            active->release = !limits.ponder && !limits.infinite;
            active->ponder_budget_ms = limits.budget_ms;
            active->control.node_limit = limits.nodes;
            if (!limits.ponder && !limits.infinite && limits.budget_ms >= 0)
                active->control.deadline_ns.store(started_ns + limits.budget_ms * 1000000);
            auto search_position = position.clone();
            active->worker = std::thread([&, active, started_ns, limits,
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
                try {
                    // Keep ordinary fixed-depth/node/ponder semantics unchanged.
                    // Timed play gets a small shared attack+defence mate budget
                    // inside the original absolute move deadline.
                    if (mate_assist_enabled && limits.budget_ms >= 10 && !limits.ponder
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
                    if (!mate_assist_forced)
                        result = strategy.choose(p, limits.max_depth, active->control, candidates, info);
                } catch (const std::exception& error) {
                    if (!active->suppress.load()) emit("info string search error " + std::string(error.what()) + "\n");
                }
                if (!result.has_score) info(result);
                if (!mate_assist_forced && !active->suppress.load()) {
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
                        << " experience_probes " << stats.experience_probes << " experience_hits " << stats.experience_hits
                        << " experience_move_first " << stats.experience_move_first << " experience_stores " << stats.experience_stores
                        << " experience_replacements " << stats.experience_replacements
                        << " experience_disabled_repetition " << stats.experience_disabled_repetition << '\n';
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
                        persist_experience();
                        quiescence_enabled = value == "true";
                        strategy.set_quiescence_enabled(quiescence_enabled);
                        invalidate_experience();
                    }
                } else if (name == "MateAssist") {
                    if (value == "true" || value == "false") mate_assist_enabled = value == "true";
                } else if (name == "OpeningBook") {
                    if (value == "true" || value == "false") {
                        opening_book_enabled = value == "true";
                        if (opening_book_enabled) opening_book_loaded = false;
                    }
                } else if (name == "OpeningBookFile") {
                    if (!value.empty() && value.find('\n') == std::string::npos && value.find('\r') == std::string::npos) {
                        opening_book_file = value;
                        opening_book.clear();
                        opening_book_loaded = false;
                    }
                } else if (name == "USI_EnteringKingRule") entering_king = (value == "CSARule27");
                else if (name == "ExperienceCache") {
                    if (value == "true" || value == "false") {
                        if (experience_enabled && value == "false") persist_experience();
                        experience_enabled = value == "true";
                        strategy.set_experience_enabled(experience_enabled);
                        if (experience_enabled) experience_loaded = false;
                    }
                } else if (name == "ExperienceFile") {
                    if (!value.empty() && value.find('\n') == std::string::npos && value.find('\r') == std::string::npos) {
                        persist_experience();
                        experience_file = value;
                        invalidate_experience();
                    }
                } else if (name == "EvalProfile") {
                    if (value == "features" || value == "material") {
                        persist_experience();
                        material_profile = value == "material";
                        strategy.set_evaluator(shogi::strategy::FeatureEvaluator(material_profile
                            ? shogi::strategy::EvaluationParameters::material_only() : evaluation_parameters));
                        experience_loaded = false;
                        experience_dirty = false;
                    }
                } else if (name == "EvalSafety" || name == "EvalPressure" || name == "EvalActivity" || name == "EvalDanger") {
                    try {
                        std::size_t used = 0;
                        const int weight = std::stoi(value, &used);
                        if (used == value.size() && weight >= 0 && weight <= 400) {
                            persist_experience();
                            const int index = name == "EvalSafety" ? 0 : name == "EvalPressure" ? 1 : name == "EvalActivity" ? 2 : 3;
                            evaluation_parameters.weights[index] = weight;
                            strategy.set_evaluator(shogi::strategy::FeatureEvaluator(material_profile
                                ? shogi::strategy::EvaluationParameters::material_only() : evaluation_parameters));
                            experience_loaded = false;
                            experience_dirty = false;
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
        } else if (command == "gameover") {
            persist_experience();
        } else if (command == "quit") {
            finish_search(true);
            persist_experience();
            break;
        }
    }
    finish_search(true);
    persist_experience();
}
