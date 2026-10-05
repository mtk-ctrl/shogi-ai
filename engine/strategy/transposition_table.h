#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace shogi::strategy {

// Our own small fixed-size transposition table. It intentionally stores only
// data produced by the current search implementation; no upstream TT/search
// code is used. A generation number makes every choose() start logically empty
// without clearing several MiB of memory each move.
class TranspositionTable {
public:
    enum class Bound : std::uint8_t { Exact, Lower, Upper };

    struct Entry {
        std::uint64_t key = 0;
        std::int32_t value = 0;
        std::uint32_t generation = 0;
        std::int8_t depth = -1;
        Bound bound = Bound::Exact;
        std::array<char, 6> best_move{};
    };

    static constexpr std::size_t Capacity = 1u << 18; // 262,144 entries
    static constexpr std::size_t ApproxBytes = Capacity * sizeof(Entry);

    TranspositionTable() : entries_(Capacity) {}

    void new_search() {
        ++generation_;
        if (generation_ == 0) {
            for (auto& entry : entries_) entry.generation = 0;
            generation_ = 1;
        }
    }

    const Entry* probe(std::uint64_t key, int depth) const {
        const auto& entry = entries_[index(key, depth)];
        if (entry.generation != generation_ || entry.key != key || entry.depth != depth)
            return nullptr;
        return &entry;
    }

    // Returns true when a different live entry had to be replaced.
    bool store(std::uint64_t key, int depth, int value, Bound bound,
               const std::string& best_move = {}) {
        auto& entry = entries_[index(key, depth)];
        const bool live = entry.generation == generation_;
        const bool same = live && entry.key == key && entry.depth == depth;

        // Keep an exact result over a later bound-only result for the same node.
        if (same && entry.bound == Bound::Exact && bound != Bound::Exact) return false;

        // On a collision, prefer the result searched to at least as much depth.
        if (live && !same && depth < entry.depth) return false;

        const bool replaced = live && !same;
        entry.key = key;
        entry.value = value;
        entry.generation = generation_;
        entry.depth = static_cast<std::int8_t>(depth);
        entry.bound = bound;
        entry.best_move.fill('\0');
        const auto n = std::min(best_move.size(), entry.best_move.size() - 1);
        std::copy_n(best_move.data(), n, entry.best_move.data());
        return replaced;
    }

    static std::string best_move(const Entry& entry) {
        return std::string(entry.best_move.data());
    }

private:
    static constexpr std::uint64_t DepthSalt = 0x9E3779B97F4A7C15ULL;
    static constexpr std::size_t Mask = Capacity - 1;

    static std::size_t index(std::uint64_t key, int depth) {
        return static_cast<std::size_t>((key ^ (DepthSalt * std::uint64_t(depth + 1))) & Mask);
    }

    std::vector<Entry> entries_;
    std::uint32_t generation_ = 0;
};

static_assert((TranspositionTable::Capacity & (TranspositionTable::Capacity - 1)) == 0,
              "TT capacity must be a power of two");
static_assert(sizeof(TranspositionTable::Entry) <= 32,
              "Keep the introductory TT compact enough for a phone");

} // namespace shogi::strategy
