#pragma once

#include <atomic>
#include <cstdint>
#include <cstring>
#include <memory>
#include <string>

#include "transposition_table.h"

namespace shogi::strategy {

// Research: a transposition table that two search threads can read and write at
// the same time. Each entry is three relaxed atomic 64-bit words; the first
// holds key ^ data1 ^ data2, so a torn read (words from two different writers)
// fails the key check and is treated as a miss, never as a wrong hit. Our own
// code; the replacement rules mirror TranspositionTable. Only the search
// generation is shared state beyond the entries: the parent bumps it once per
// go, before the lanes start, and lanes never bump it themselves.
class SharedTranspositionTable {
public:
    using Entry = TranspositionTable::Entry;
    using Bound = TranspositionTable::Bound;
    static constexpr std::size_t Capacity = TranspositionTable::Capacity;

    SharedTranspositionTable() : words_(new std::atomic<std::uint64_t>[Capacity * 3]) {
        for (std::size_t i = 0; i < Capacity * 3; ++i) words_[i].store(0, std::memory_order_relaxed);
    }

    void new_search() {
        auto next = generation_.load(std::memory_order_relaxed) + 1;
        if (next == 0) {
            for (std::size_t i = 0; i < Capacity * 3; ++i) words_[i].store(0, std::memory_order_relaxed);
            next = 1;
        }
        generation_.store(next, std::memory_order_relaxed);
    }

    bool probe(std::uint64_t key, int depth, Entry& out) const {
        Entry e;
        if (!read(index(key, depth), e)) return false;
        if (e.generation != generation_.load(std::memory_order_relaxed)
            || e.key != key || e.depth != depth) return false;
        out = e;
        return true;
    }

    // Returns true when a different live entry had to be replaced.
    bool store(std::uint64_t key, int depth, int value, Bound bound, const std::string& best_move = {}) {
        const auto slot = index(key, depth);
        const auto generation = generation_.load(std::memory_order_relaxed);
        Entry old;
        const bool valid = read(slot, old);
        const bool live = valid && old.generation == generation;
        const bool same = live && old.key == key && old.depth == depth;
        if (same && old.bound == Bound::Exact && bound != Bound::Exact) return false;
        if (live && !same && depth < old.depth) return false;
        const bool replaced = live && !same;
        std::uint64_t d1 = std::uint64_t(static_cast<std::uint32_t>(value))
            | (std::uint64_t(generation) << 32);
        std::uint64_t d2 = 0;
        char move[6] = {};
        const auto n = std::min<std::size_t>(best_move.size(), 5);
        std::memcpy(move, best_move.data(), n);
        std::memcpy(&d2, move, 6);
        d2 |= std::uint64_t(static_cast<std::uint8_t>(depth)) << 48;
        d2 |= std::uint64_t(static_cast<std::uint8_t>(bound)) << 56;
        words_[slot * 3 + 1].store(d1, std::memory_order_relaxed);
        words_[slot * 3 + 2].store(d2, std::memory_order_relaxed);
        words_[slot * 3].store(key ^ d1 ^ d2, std::memory_order_relaxed);
        return replaced;
    }

    // Research (TTMode 1): board-keyed, depth-agnostic lookup in a two-slot bucket.
    // The caller checks out.depth. Same torn-read protection as probe().
    bool probe_key(std::uint64_t key, Entry& out) const {
        const std::size_t base = key & Mask & ~std::size_t(1);
        const auto generation = generation_.load(std::memory_order_relaxed);
        for (std::size_t i = base; i < base + 2; ++i) {
            Entry e;
            if (!read(i, e)) continue;
            if (e.generation == generation && e.key == key && e.depth >= 0) { out = e; return true; }
        }
        return false;
    }

    bool store_key(std::uint64_t key, int depth, int value, Bound bound, const std::string& best_move = {}) {
        const std::size_t base = key & Mask & ~std::size_t(1);
        const auto generation = generation_.load(std::memory_order_relaxed);
        std::size_t target = base;
        bool found = false, replaced = false;
        Entry cur[2];
        bool valid[2];
        for (int i = 0; i < 2; ++i) valid[i] = read(base + i, cur[i]);
        for (int i = 0; i < 2; ++i) {
            if (valid[i] && cur[i].generation == generation && cur[i].key == key) {
                if (cur[i].depth > depth + 2 && bound != Bound::Exact) return false;
                target = base + i; found = true; break;
            }
        }
        if (!found) {
            int weakest = -1;
            for (int i = 0; i < 2; ++i) {
                const bool live = valid[i] && cur[i].generation == generation;
                if (!live) { weakest = i; break; }
                if (weakest < 0 || cur[i].depth < cur[weakest].depth) weakest = i;
            }
            const bool live = valid[weakest] && cur[weakest].generation == generation;
            if (live && depth < cur[weakest].depth) return false;
            replaced = live;
            target = base + weakest;
        }
        std::uint64_t d1 = std::uint64_t(static_cast<std::uint32_t>(value))
            | (std::uint64_t(generation) << 32);
        std::uint64_t d2 = 0;
        char move[6] = {};
        const auto n = std::min<std::size_t>(best_move.size(), 5);
        std::memcpy(move, best_move.data(), n);
        std::memcpy(&d2, move, 6);
        d2 |= std::uint64_t(static_cast<std::uint8_t>(depth)) << 48;
        d2 |= std::uint64_t(static_cast<std::uint8_t>(bound)) << 56;
        words_[target * 3 + 1].store(d1, std::memory_order_relaxed);
        words_[target * 3 + 2].store(d2, std::memory_order_relaxed);
        words_[target * 3].store(key ^ d1 ^ d2, std::memory_order_relaxed);
        return replaced;
    }

private:
    static constexpr std::uint64_t DepthSalt = 0x9E3779B97F4A7C15ULL;
    static constexpr std::size_t Mask = Capacity - 1;
    static std::size_t index(std::uint64_t key, int depth) {
        return static_cast<std::size_t>((key ^ (DepthSalt * std::uint64_t(depth + 1))) & Mask);
    }
    bool read(std::size_t slot, Entry& e) const {
        const auto c = words_[slot * 3].load(std::memory_order_relaxed);
        const auto d1 = words_[slot * 3 + 1].load(std::memory_order_relaxed);
        const auto d2 = words_[slot * 3 + 2].load(std::memory_order_relaxed);
        if (d1 == 0 && d2 == 0) return false;
        e.key = c ^ d1 ^ d2;
        e.value = static_cast<std::int32_t>(static_cast<std::uint32_t>(d1 & 0xffffffffu));
        e.generation = static_cast<std::uint32_t>(d1 >> 32);
        e.depth = static_cast<std::int8_t>(static_cast<std::uint8_t>((d2 >> 48) & 0xff));
        e.bound = static_cast<Bound>((d2 >> 56) & 0xff);
        e.best_move.fill('\0');
        std::memcpy(e.best_move.data(), &d2, 6);
        e.best_move[5] = '\0';
        return true;
    }
    std::unique_ptr<std::atomic<std::uint64_t>[]> words_;
    std::atomic<std::uint32_t> generation_{0};
};

} // namespace shogi::strategy
