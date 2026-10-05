#pragma once

#include "embedded_opening_book.h"
#include <algorithm>
#include <cstdint>
#include <fstream>
#include <istream>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace shogi::strategy {

struct OpeningBookEntry {
    std::string move;
    std::uint32_t samples = 0;
    std::uint32_t wins = 0;
    std::uint32_t draws = 0;
    std::uint32_t losses = 0;
    std::uint32_t score_milli = 0;
    std::uint32_t weight = 0;
};

class OpeningBook {
public:
    bool load(const std::string& path) {
        std::ifstream input(path);
        if (input) return load_stream(input);

        // Android OEX hosts normally receive only the engine executable.  Keep
        // the standard self-play book available even when the external TSV is
        // not beside the executable.  Custom paths still fail normally so a
        // configuration mistake is never silently replaced by the default.
        if (path == "shogi-ai-book.tsv") return load_text(detail::kEmbeddedOpeningBook);

        clear();
        return false;
    }

    bool load_text(std::string_view text) {
        std::istringstream input{std::string(text)};
        return load_stream(input);
    }

    void clear() { moves_.clear(); entry_count_ = 0; }
    std::size_t positions() const { return moves_.size(); }
    std::size_t entries() const { return entry_count_; }

    std::optional<OpeningBookEntry> pick(std::uint64_t key,
        const std::vector<std::string>& allowed_moves, std::uint64_t seed) const {
        const auto found = moves_.find(key);
        if (found == moves_.end()) return std::nullopt;
        std::vector<const OpeningBookEntry*> eligible;
        std::uint64_t total_weight = 0;
        for (const auto& entry : found->second) {
            if (std::find(allowed_moves.begin(), allowed_moves.end(), entry.move) == allowed_moves.end()) continue;
            eligible.push_back(&entry);
            total_weight += entry.weight;
        }
        if (eligible.empty() || total_weight == 0) return std::nullopt;
        std::uint64_t target = mix64(key ^ (seed + 0x9e3779b97f4a7c15ULL)) % total_weight;
        for (const auto* entry : eligible) {
            if (target < entry->weight) return *entry;
            target -= entry->weight;
        }
        return *eligible.back();
    }

private:
    bool load_stream(std::istream& input) {
        clear();
        std::string line;
        while (std::getline(input, line)) {
            if (line.empty() || line[0] == '#') continue;
            std::istringstream row(line);
            std::uint64_t key = 0;
            OpeningBookEntry entry;
            if (!(row >> key >> entry.move >> entry.samples >> entry.wins >> entry.draws
                      >> entry.losses >> entry.score_milli >> entry.weight)) {
                clear();
                return false;
            }
            std::string extra;
            if (row >> extra || entry.move.empty() || entry.samples == 0 || entry.weight == 0
                || entry.score_milli > 1000
                || entry.samples != entry.wins + entry.draws + entry.losses) {
                clear();
                return false;
            }
            moves_[key].push_back(std::move(entry));
            ++entry_count_;
        }
        for (auto& pair : moves_) {
            auto& entries = pair.second;
            std::stable_sort(entries.begin(), entries.end(), [](const auto& a, const auto& b) {
                if (a.score_milli != b.score_milli) return a.score_milli > b.score_milli;
                if (a.samples != b.samples) return a.samples > b.samples;
                return a.move < b.move;
            });
        }
        return entry_count_ > 0;
    }

    static std::uint64_t mix64(std::uint64_t x) {
        x += 0x9e3779b97f4a7c15ULL;
        x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL;
        x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;
        return x ^ (x >> 31);
    }
    std::unordered_map<std::uint64_t, std::vector<OpeningBookEntry>> moves_;
    std::size_t entry_count_ = 0;
};

} // namespace shogi::strategy
