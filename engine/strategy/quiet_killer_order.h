#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <utility>
#include <vector>

namespace shogi::strategy {

// Stable extraction of at most two quiet priorities. Occupied tactical slots
// never move. This is equivalent to sorting only the quiet subsequence by the
// two priorities, without constructing or sorting that subsequence.
template<class IsQuiet>
std::uint64_t prioritize_quiet_killers(std::vector<std::string>& moves,
                                     const std::array<std::string, 2>& priorities,
                                     IsQuiet quiet) {
    std::size_t first = 0;
    std::uint64_t hits = 0;
    for (const auto& hint : priorities) {
        if (hint.empty()) continue;
        const auto found = std::find(moves.begin() + first, moves.end(), hint);
        if (found == moves.end() || !quiet(*found)) continue;
        std::size_t hole = static_cast<std::size_t>(found - moves.begin());
        auto selected = std::move(*found);
        for (std::size_t j = hole; j > first;) {
            --j;
            if (quiet(moves[j])) {
                moves[hole] = std::move(moves[j]);
                hole = j;
            }
        }
        moves[hole] = std::move(selected);
        first = hole + 1;
        ++hits;
    }
    return hits;
}

} // namespace shogi::strategy
