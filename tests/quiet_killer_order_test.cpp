#include "strategy/quiet_killer_order.h"
#include <cassert>
#include <iostream>
#include <numeric>
#include <random>

using shogi::strategy::prioritize_quiet_killers;
int main() {
    std::mt19937 rng(20261016);
    for (int trial = 0; trial < 20000; ++trial) {
        const int n = trial % 20 == 0 ? 600 : rng() % 100;
        std::vector<std::string> moves;
        for (int i = 0; i < n; ++i)
            moves.push_back(std::string(rng() % 3 ? "q" : "t") + std::to_string(i));
        std::shuffle(moves.begin(), moves.end(), rng);
        std::array<std::string, 2> hints;
        for (auto& hint : hints)
            hint = n && rng() % 4 ? moves[rng() % n] : (rng() % 2 ? "" : "absent");
        if (trial % 7 == 0) hints[1] = hints[0];
        const auto quiet = [](const std::string& m) { return !m.empty() && m[0] == 'q'; };
        // Independent oracle: stable-sort the extracted quiet subsequence.
        auto expected = moves;
        std::vector<std::size_t> slots;
        std::vector<std::string> extracted;
        for (std::size_t i = 0; i < moves.size(); ++i) if (quiet(moves[i])) {
            slots.push_back(i); extracted.push_back(moves[i]);
        }
        const auto priority = [&](const auto& m) { return m == hints[0] ? 2 : m == hints[1] ? 1 : 0; };
        const auto expected_hits = std::count_if(extracted.begin(), extracted.end(),
            [&](const auto& m) { return priority(m) > 0; });
        std::stable_sort(extracted.begin(), extracted.end(),
            [&](const auto& a, const auto& b) { return priority(a) > priority(b); });
        for (std::size_t i = 0; i < slots.size(); ++i) expected[slots[i]] = extracted[i];
        const auto hits = prioritize_quiet_killers(moves, hints, quiet);
        assert(moves == expected);
        assert(hits == static_cast<std::uint64_t>(expected_hits));
    }
    std::cout << "PASS 20000 exact-order cases, tactical slots, absent/duplicate hints and 600 candidates\n";
}
