#pragma once

#include "embedded_position_knowledge.h"
#include "rules/position.h"
#include <fstream>
#include <istream>
#include <sstream>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>
#include <cstdint>

namespace shogi::strategy {

class PositionKnowledge {
public:
    struct Entry {
        std::string move;
        std::string knowledge_version;
        std::uint64_t evidence_count = 0;
        std::uint64_t research_ms = 0;
        int research_depth = 0;
        std::uint64_t research_nodes = 0;
        std::string score_kind;
        int score_value = 0;
        std::uint64_t stable_ms = 0;
        std::string mode = "move_order_hint";
        std::string research_id;
        std::vector<std::string> research_pv;
        std::uint64_t initial_history_key = 0;
    };
    bool load(const std::string& path) {
        std::ifstream input(path);
        if (input) return load_stream(input);

        // Standalone/Android engines may receive only the executable.  The
        // default adopted snapshot therefore travels inside the binary.
        // A custom missing path is still an error and never silently replaced.
        if (path == "position-knowledge-v1.tsv")
            return load_text(detail::kEmbeddedPositionKnowledge);

        clear();
        return false;
    }

    bool load_text(std::string_view text) {
        std::istringstream input{std::string(text)};
        return load_stream(input);
    }

    void clear() { moves_.clear(); }
    std::size_t size() const { return moves_.size(); }

    const Entry* probe(const rules::Position& position) const {
        const auto key = canonical_key(position);
        const auto it = moves_.find(key);
        return it == moves_.end() ? nullptr : &it->second;
    }

    static std::string canonical_key(const rules::Position& position) {
        std::istringstream in(position.sfen());
        std::string board, turn, hand;
        if (!(in >> board >> turn >> hand)) return {};
        return board + " " + turn + " " + hand;
    }

private:
    bool load_stream(std::istream& in) {
        std::unordered_map<std::string, Entry> loaded;
        std::string line;
        while (std::getline(in, line)) {
            if (line.empty() || line[0] == '#') continue;
            const auto first = line.find('\t');
            if (first == std::string::npos) {
                clear();
                return false;
            }
            std::vector<std::string> fields;
            std::size_t start = 0;
            while (true) {
                const auto tab = line.find('\t', start);
                fields.push_back(line.substr(start, tab == std::string::npos ? std::string::npos : tab - start));
                if (tab == std::string::npos) break;
                start = tab + 1;
            }
            if (fields.size() < 2 || fields[0].empty() || fields[1].empty()) {
                clear();
                return false;
            }
            Entry entry;
            entry.move = fields[1];
            if (fields.size() > 2) entry.knowledge_version = fields[2];
            auto u64 = [&](std::size_t i) -> std::uint64_t {
                if (i >= fields.size() || fields[i].empty()) return 0;
                try { return std::stoull(fields[i]); } catch (...) { return 0; }
            };
            auto i32 = [&](std::size_t i) -> int {
                if (i >= fields.size() || fields[i].empty()) return 0;
                try { return std::stoi(fields[i]); } catch (...) { return 0; }
            };
            entry.evidence_count = u64(3);
            entry.research_ms = u64(4);
            entry.research_depth = i32(5);
            entry.research_nodes = u64(6);
            if (fields.size() > 7) entry.score_kind = fields[7];
            entry.score_value = i32(8);
            entry.stable_ms = u64(9);
            if (fields.size() > 10 && !fields[10].empty()) entry.mode = fields[10];
            if (entry.mode == "research_decision") {
                if (fields.size() < 13 || fields[11].empty()) { clear(); return false; }
                entry.research_id = fields[11];
                std::istringstream pv(fields[12]);
                std::string move;
                while (pv >> move) entry.research_pv.push_back(move);
                if (entry.research_pv.empty() || entry.research_pv.front() != entry.move
                    || fields.size() < 14 || fields[13].empty()) {
                    clear(); return false;
                }
                std::vector<std::string> history;
                if (fields[13] != "-") {
                    std::istringstream historical_moves(fields[13]);
                    while (historical_moves >> move) history.push_back(move);
                }
                rules::Position original;
                std::string error;
                if (!original.set(rules::Position::start_sfen(), history, error)
                    || canonical_key(original) != fields[0]) {
                    clear(); return false;
                }
                entry.initial_history_key = original.history_key();
            } else if (entry.mode != "move_order_hint") { clear(); return false; }
            const auto [it, inserted] = loaded.emplace(fields[0], entry);
            if (!inserted && it->second.move != entry.move) {
                clear();
                return false;
            }
            if (!inserted && entry.research_ms > it->second.research_ms)
                it->second = entry;
        }
        if (loaded.empty()) {
            clear();
            return false;
        }
        moves_.swap(loaded);
        return true;
    }

    std::unordered_map<std::string, Entry> moves_;
};

} // namespace shogi::strategy
