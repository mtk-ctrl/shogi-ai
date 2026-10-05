#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <string>
#include <vector>

namespace shogi::strategy {

// Long-lived move-hint cache. Unlike the transposition table, this table is not
// cleared between choose() calls or usinewgame. V1 deliberately stores only a
// move hint and search depth: it never returns a cached evaluation or bound, so
// an old entry can affect move ordering but cannot by itself terminate search.
// Entries written by the current choose() are not visible until the next search;
// the normal TT owns transpositions inside one search.
class ExperienceCache {
public:
    struct Entry {
        std::uint64_t key = 0;
        std::uint32_t generation = 0;
        std::int8_t depth = -1;
        std::array<char, 6> best_move{};
    };

    static constexpr std::size_t Capacity = 1u << 17; // 131,072 entries
    static constexpr std::size_t ApproxBytes = Capacity * sizeof(Entry);
    static constexpr std::uint32_t FileVersion = 1;

    ExperienceCache() : entries_(Capacity) {}

    void new_search() {
        ++generation_;
        if (generation_ == 0) {
            clear();
            generation_ = 1;
        }
    }

    const Entry* probe(std::uint64_t key) const {
        const auto& entry = entries_[index(key)];
        return entry.generation != 0 && entry.generation != generation_
            && entry.key == key ? &entry : nullptr;
    }

    // Returns true when a different live entry had to be replaced.
    bool store(std::uint64_t key, int depth, const std::string& best_move) {
        if (best_move.empty()) return false;
        auto& entry = entries_[index(key)];
        const bool live = entry.generation != 0;
        const bool same = live && entry.key == key;

        // Keep the deeper hint for the same position. For equal depth, refresh
        // with the newer completed search.
        if (same && depth < entry.depth) return false;
        // On collision, also prefer a deeper existing result.
        if (live && !same && depth < entry.depth) return false;

        const bool replaced = live && !same;
        entry.key = key;
        entry.depth = static_cast<std::int8_t>(depth);
        entry.generation = generation_;
        entry.best_move.fill('\0');
        const auto n = std::min(best_move.size(), entry.best_move.size() - 1);
        std::copy_n(best_move.data(), n, entry.best_move.data());
        return replaced;
    }

    void clear() {
        for (auto& entry : entries_) entry.generation = 0;
    }

    std::size_t size() const {
        return static_cast<std::size_t>(std::count_if(entries_.begin(), entries_.end(),
            [](const Entry& entry) { return entry.generation != 0; }));
    }

    // Save only move hints. The caller supplies a configuration signature so a
    // cache produced by different evaluation/search settings is never loaded.
    // Any I/O failure is non-fatal: normal search remains available.
    bool save(const std::string& path, std::uint64_t config_signature) const {
        if (path.empty()) return false;
        const std::string temp = path + ".tmp";
        std::ofstream out(temp, std::ios::binary | std::ios::trunc);
        if (!out) return false;

        const std::array<char, 8> magic{'S','H','G','X','P','C','0','1'};
        const std::uint32_t count = static_cast<std::uint32_t>(size());
        out.write(magic.data(), static_cast<std::streamsize>(magic.size()));
        write_value(out, FileVersion);
        write_value(out, config_signature);
        write_value(out, count);
        for (const auto& entry : entries_) {
            if (entry.generation == 0) continue;
            write_value(out, entry.key);
            write_value(out, entry.depth);
            out.write(entry.best_move.data(), static_cast<std::streamsize>(entry.best_move.size()));
        }
        out.flush();
        if (!out) {
            out.close();
            std::remove(temp.c_str());
            return false;
        }
        out.close();
        if (std::rename(temp.c_str(), path.c_str()) != 0) {
            std::remove(temp.c_str());
            return false;
        }
        return true;
    }

    bool load(const std::string& path, std::uint64_t expected_signature) {
        if (path.empty()) return false;
        std::ifstream in(path, std::ios::binary);
        if (!in) return false;

        std::array<char, 8> magic{};
        std::uint32_t version = 0, count = 0;
        std::uint64_t signature = 0;
        in.read(magic.data(), static_cast<std::streamsize>(magic.size()));
        read_value(in, version);
        read_value(in, signature);
        read_value(in, count);
        const std::array<char, 8> expected_magic{'S','H','G','X','P','C','0','1'};
        if (!in || magic != expected_magic || version != FileVersion
            || signature != expected_signature || count > Capacity) {
            return false;
        }

        clear();
        generation_ = 1;
        for (std::uint32_t i = 0; i < count; ++i) {
            std::uint64_t key = 0;
            std::int8_t depth = -1;
            std::array<char, 6> move{};
            read_value(in, key);
            read_value(in, depth);
            in.read(move.data(), static_cast<std::streamsize>(move.size()));
            if (!in) {
                clear();
                return false;
            }
            move.back() = '\0';
            const std::string best(move.data());
            if (best.empty()) continue;
            store(key, static_cast<int>(depth), best);
        }
        // Loaded entries are generation 1. The next choose() advances to 2,
        // making them visible as prior-search experience.
        return true;
    }

    static std::string best_move(const Entry& entry) {
        return std::string(entry.best_move.data());
    }

private:
    static constexpr std::size_t Mask = Capacity - 1;

    template<class T>
    static void write_value(std::ostream& out, const T& value) {
        out.write(reinterpret_cast<const char*>(&value), sizeof(value));
    }

    template<class T>
    static void read_value(std::istream& in, T& value) {
        in.read(reinterpret_cast<char*>(&value), sizeof(value));
    }

    static std::size_t index(std::uint64_t key) {
        // SplitMix64 finalizer gives low bits enough diffusion for a direct map.
        key ^= key >> 30;
        key *= 0xbf58476d1ce4e5b9ULL;
        key ^= key >> 27;
        key *= 0x94d049bb133111ebULL;
        key ^= key >> 31;
        return static_cast<std::size_t>(key & Mask);
    }

    std::vector<Entry> entries_;
    std::uint32_t generation_ = 1;
};

static_assert((ExperienceCache::Capacity & (ExperienceCache::Capacity - 1)) == 0,
              "Experience cache capacity must be a power of two");
static_assert(sizeof(ExperienceCache::Entry) <= 24,
              "Keep the introductory experience cache compact enough for a phone");

} // namespace shogi::strategy
