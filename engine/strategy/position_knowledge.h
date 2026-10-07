#pragma once

#include "rules/position.h"
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_map>

namespace shogi::strategy {

class PositionKnowledge {
public:
    bool load(const std::string& path) {
        std::ifstream in(path);
        if (!in) {
            moves_.clear();
            return false;
        }
        std::unordered_map<std::string, std::string> loaded;
        std::string line;
        while (std::getline(in, line)) {
            if (line.empty() || line[0] == '#') continue;
            const auto first = line.find('\t');
            if (first == std::string::npos) {
                moves_.clear();
                return false;
            }
            const auto second = line.find('\t', first + 1);
            const std::string key = line.substr(0, first);
            const std::string move = line.substr(first + 1, second == std::string::npos
                ? std::string::npos : second - first - 1);
            if (key.empty() || move.empty()) {
                moves_.clear();
                return false;
            }
            const auto [it, inserted] = loaded.emplace(key, move);
            if (!inserted && it->second != move) {
                moves_.clear();
                return false;
            }
        }
        if (loaded.empty()) {
            moves_.clear();
            return false;
        }
        moves_.swap(loaded);
        return true;
    }

    void clear() { moves_.clear(); }
    std::size_t size() const { return moves_.size(); }

    const std::string* probe(const rules::Position& position) const {
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
    std::unordered_map<std::string, std::string> moves_;
};

} // namespace shogi::strategy
