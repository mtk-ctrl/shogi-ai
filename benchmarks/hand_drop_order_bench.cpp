#include "rules/position.h"
#include "strategy/move_order.h"
#include <chrono>
#include <cstdint>
#include <iostream>
#include <random>
#include <string>
#include <utility>
#include <vector>

using namespace shogi;

struct Sample {
    rules::Snapshot snapshot;
    std::vector<std::string> moves;
};

static int tactical_drop_count(const std::vector<std::string>& moves) {
    int n = 0;
    for (const auto& move : moves)
        if (move.size() >= 4 && move[1] == '*' && move[0] != 'P') ++n;
    return n;
}

static std::pair<double,std::uint64_t> bench(const std::vector<Sample>& samples,
                                             bool enabled, int repeats) {
    volatile std::uint64_t checksum = 0;
    const auto start = std::chrono::steady_clock::now();
    for (int r = 0; r < repeats; ++r) {
        for (const auto& sample : samples) {
            auto ordered = strategy::MoveOrder::order(sample.snapshot, sample.moves, enabled);
            checksum += ordered.size();
            if (!ordered.empty()) checksum += static_cast<unsigned char>(ordered.front()[0]);
        }
    }
    const auto ns = std::chrono::duration<double,std::nano>(
        std::chrono::steady_clock::now() - start).count();
    return {ns / (repeats * samples.size()), checksum};
}

int main() {
    std::mt19937 rng(20261006);
    std::vector<Sample> mixed, drop_rich;
    std::uint64_t mixed_moves = 0, rich_moves = 0, rich_drops = 0;

    for (int game = 0; game < 160 && (mixed.size() < 256 || drop_rich.size() < 256); ++game) {
        rules::Position p;
        for (int ply = 0; ply < 120; ++ply) {
            if (p.status().result != rules::Result::Ongoing) break;
            auto moves = p.legal_moves();
            if (moves.empty()) break;
            const int drops = tactical_drop_count(moves);
            if (ply >= 8 && mixed.size() < 256 && (ply % 3 == 0)) {
                mixed_moves += moves.size();
                mixed.push_back({p.snapshot(), moves});
            }
            if (drops > 0 && drop_rich.size() < 256) {
                rich_moves += moves.size();
                rich_drops += drops;
                drop_rich.push_back({p.snapshot(), moves});
            }
            std::string error;
            if (!p.play(moves[rng() % moves.size()], error)) return 2;
        }
    }
    if (mixed.empty() || drop_rich.empty()) return 3;

    const int repeats = 30;
    const auto mixed_off = bench(mixed, false, repeats);
    const auto mixed_on = bench(mixed, true, repeats);
    const auto rich_off = bench(drop_rich, false, repeats);
    const auto rich_on = bench(drop_rich, true, repeats);
    auto pct = [](double on, double off) { return (on / off - 1.0) * 100.0; };

    std::cout << "{\n"
              << "  \"mixed_samples\": " << mixed.size() << ",\n"
              << "  \"mixed_mean_legal_moves\": " << double(mixed_moves) / mixed.size() << ",\n"
              << "  \"mixed_off_ns_per_order\": " << mixed_off.first << ",\n"
              << "  \"mixed_on_ns_per_order\": " << mixed_on.first << ",\n"
              << "  \"mixed_overhead_pct\": " << pct(mixed_on.first, mixed_off.first) << ",\n"
              << "  \"drop_rich_samples\": " << drop_rich.size() << ",\n"
              << "  \"drop_rich_mean_legal_moves\": " << double(rich_moves) / drop_rich.size() << ",\n"
              << "  \"drop_rich_mean_tactical_drops\": " << double(rich_drops) / drop_rich.size() << ",\n"
              << "  \"drop_rich_off_ns_per_order\": " << rich_off.first << ",\n"
              << "  \"drop_rich_on_ns_per_order\": " << rich_on.first << ",\n"
              << "  \"drop_rich_overhead_pct\": " << pct(rich_on.first, rich_off.first) << ",\n"
              << "  \"checksum\": " << (mixed_off.second + mixed_on.second + rich_off.second + rich_on.second) << "\n"
              << "}\n";
}
