#pragma once
#include "strategy/iterative_search.h"
#include <optional>

namespace shogi::strategy {
struct GoLimits {
    int max_depth = 3;
    std::uint64_t nodes = 0;
    std::int64_t budget_ms = -1;
    std::int64_t requested_movetime_ms = -1;
    bool ponder = false, infinite = false;
};

inline GoLimits parse_go_limits(const std::vector<std::string>& tokens,
                                rules::Color turn, int default_depth = 3) {
    auto number = [&](const std::string& key) -> std::optional<std::int64_t> {
        auto it = std::find(tokens.begin(), tokens.end(), key);
        if (it == tokens.end() || ++it == tokens.end()) return {};
        if (it->empty() || it->find_first_not_of("0123456789") != std::string::npos) return {};
        try { return std::stoll(*it); } catch (...) { return {}; }
    };
    auto bounded = [&](const std::string& key) {
        return std::min<std::int64_t>(number(key).value_or(0), 86400000);
    };
    GoLimits out;
    out.ponder = std::find(tokens.begin(), tokens.end(), "ponder") != tokens.end();
    out.infinite = std::find(tokens.begin(), tokens.end(), "infinite") != tokens.end();
    if (auto nodes = number("nodes"); nodes && *nodes > 0) out.nodes = *nodes;
    const auto remaining = number(turn == rules::Color::Black ? "btime" : "wtime");
    if (auto fixed = number("movetime")) {
        out.requested_movetime_ms = std::min<std::int64_t>(*fixed, 86400000);
        out.budget_ms = out.requested_movetime_ms;
    }
    else if (remaining || number("byoyomi")) {
        const auto rem = std::min<std::int64_t>(remaining.value_or(0), 86400000);
        const auto byo = bounded("byoyomi");
        const auto inc = bounded(turn == rules::Color::Black ? "binc" : "winc");
        const auto moves = std::clamp<std::int64_t>(number("movestogo").value_or(30), 1, 1000);
        out.budget_ms = std::min(rem + byo + inc, std::max<std::int64_t>(1, rem / moves + byo + inc * 3 / 4));
    }
    if (out.budget_ms >= 0)
        out.budget_ms -= std::min<std::int64_t>(10, out.budget_ms / 10); // I/O margin
    out.max_depth = (out.budget_ms >= 0 || out.nodes || out.ponder || out.infinite)
        ? IterativeSearch::MaxDepth : default_depth;
    if (auto depth = number("depth"); depth && *depth > 0)
        out.max_depth = static_cast<int>(std::min<std::int64_t>(*depth, IterativeSearch::MaxDepth));
    return out;
}
} // namespace shogi::strategy
