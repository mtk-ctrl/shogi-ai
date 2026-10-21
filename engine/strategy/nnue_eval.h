#pragma once
// Research-only, self-authored NNUE-style sparse accumulator.
// Scores are Black-relative centipawns. Never imports an external evaluator.
#include "rules/position.h"
#include <algorithm>
#include <cstdint>
#include <fstream>
#include <limits>
#include <memory>
#include <string>
#include <vector>

namespace shogi::strategy {
class NnueModel {
public:
    static constexpr std::uint32_t Features = 81 * 2 * 14 + 2 * 7 * 18 + 2;
    static constexpr std::uint32_t KingFeatures = Features + 2 * 9 * 81 * 2 * 14;
    static constexpr std::uint32_t Actions = 88 * 81 * 2;
    static constexpr int Scale = 256;
    using Accumulator = std::vector<std::int32_t>;

    static std::vector<std::uint32_t> features(const rules::Snapshot& s, bool kings = false) {
        std::vector<std::uint32_t> f;
        f.reserve(100);
        for (int square = 0; square < 81; ++square) {
            const auto& p = s.board[square];
            if (!p.kind) continue;
            if (p.kind < 1 || p.kind > 8 || (p.promoted && p.kind > 6))
                return {};
            const int channel = p.promoted ? p.kind + 7 : p.kind - 1;
            f.push_back((static_cast<unsigned>(p.color) * 14u + channel) * 81u + square);
        }
        constexpr std::uint32_t hand_base = 81u * 2u * 14u;
        for (int side = 0; side < 2; ++side) {
            for (int kind = 0; kind < 7; ++kind) {
                const int count = s.hands[side][kind];
                if (count < 0 || count > 18) return {};
                for (int n = 0; n < count; ++n)
                    f.push_back(hand_base + (side * 7u + kind) * 18u + n);
            }
        }
        f.push_back(Features - 2 + static_cast<unsigned>(s.turn));
        if (kings) {
            // Two independent king perspectives, each in a 3x3 spatial bucket.
            // All piece identities/locations remain exact within that bucket.
            for (int side = 0; side < 2; ++side) {
                int king = -1;
                for (int sq = 0; sq < 81; ++sq)
                    if (s.board[sq].kind == 8 && static_cast<int>(s.board[sq].color) == side) king = sq;
                if (king < 0) continue;
                const int bucket = (king / 9 / 3) * 3 + (king % 9 / 3);
                for (int sq = 0; sq < 81; ++sq) {
                    const auto& p = s.board[sq];
                    if (!p.kind) continue;
                    const int channel = p.promoted ? p.kind + 7 : p.kind - 1;
                    f.push_back(Features + ((side * 9u + bucket) * 28u
                        + static_cast<unsigned>(p.color) * 14u + channel) * 81u + sq);
                }
            }
        }
        std::sort(f.begin(), f.end());
        return f;
    }

    bool load(const std::string& path) {
        // Transactional load; reject truncated/extended and malformed models.
        NnueModel candidate;
        std::ifstream file(path, std::ios::binary | std::ios::ate);
        if (!file) return false;
        const auto length = file.tellg();
        if (length < 16 || length > 96 * 1024 * 1024) return false;
        file.seekg(0);
        std::vector<unsigned char> bytes(static_cast<std::size_t>(length));
        if (!file.read(reinterpret_cast<char*>(bytes.data()), bytes.size())) return false;
        const std::string magic(bytes.begin(), bytes.begin() + 8);
        if (magic != "KMNNUE01" && magic != "KMNNUE02" && magic != "KMNNUE03") return false;
        std::size_t offset = 8;
        auto u32 = [&]() -> std::uint32_t {
            const auto n = std::uint32_t(bytes[offset]) |
                 std::uint32_t(bytes[offset+1]) << 8 |
                 std::uint32_t(bytes[offset+2]) << 16 |
                 std::uint32_t(bytes[offset+3]) << 24;
            offset += 4; return n;
        };
        const auto width = u32(), count = u32();
        if (count != (magic == "KMNNUE01" ? Features : KingFeatures)
            || width < 16 || width > 512) return false;
        const std::size_t expected = 16 + 4ull * width
            + 2ull * count * width + 2ull * width + 4
            + (magic == "KMNNUE03" ? Actions * (2ull * width + 4ull) : 0);
        if (bytes.size() != expected) return false;
        auto i16 = [&]() -> std::int16_t {
            const auto n = std::uint16_t(bytes[offset]) |
                 std::uint16_t(bytes[offset+1]) << 8;
            offset += 2; return static_cast<std::int16_t>(n);
        };
        candidate.width_ = width;
        candidate.feature_count_ = count;
        candidate.bias_.reserve(width);
        for (unsigned i = 0; i < width; ++i) {
            const auto bias = static_cast<std::int32_t>(u32());
            if (bias < -(1 << 29) || bias > (1 << 29)) return false;
            candidate.bias_.push_back(bias);
        }
        candidate.embedding_.reserve(static_cast<std::size_t>(count) * width);
        for (std::size_t i = 0; i < static_cast<std::size_t>(count) * width; ++i)
            candidate.embedding_.push_back(i16());
        candidate.output_.reserve(width);
        for (unsigned i = 0; i < width; ++i) candidate.output_.push_back(i16());
        candidate.output_bias_ = static_cast<std::int32_t>(u32());
        if (magic == "KMNNUE03") {
            candidate.policy_.reserve(Actions * width);
            for (std::size_t i = 0; i < Actions * width; ++i) candidate.policy_.push_back(i16());
            for (unsigned i = 0; i < Actions; ++i)
                candidate.policy_bias_.push_back(static_cast<std::int32_t>(u32()));
        }
        *this = std::move(candidate);
        return true;
    }

    bool valid() const { return width_ >= 16 && embedding_.size() == feature_count_ * width_; }
    unsigned width() const { return width_; }
    unsigned feature_count() const { return feature_count_; }
    bool has_policy() const { return policy_.size() == Actions * width_ && !policy_.empty(); }
    static int action_id(const std::string& move) {
        if (move.size() != 4 && move.size() != 5) return -1;
        auto square = [](char file, char rank) { return file >= '1' && file <= '9'
            && rank >= 'a' && rank <= 'i' ? (file-'1')*9 + rank-'a' : -1; };
        const int to = square(move[2], move[3]);
        int from = -1;
        if (move[1] == '*') {
            const auto k = std::string("PLNSBRG").find(move[0]);
            if (k == std::string::npos || move.size() != 4) return -1;
            from = 81 + k;
        } else from = square(move[0], move[1]);
        if (to < 0 || from < 0 || (move.size() == 5 && move[4] != '+')) return -1;
        return (from * 81 + to) * 2 + (move.size() == 5);
    }
    std::int64_t policy_score(const Accumulator& acc, const std::string& move) const {
        const int action = action_id(move);
        if (!has_policy() || action < 0 || acc.size() != width_) return 0;
        std::int64_t total = policy_bias_[action];
        for (unsigned i = 0; i < width_; ++i)
            total += static_cast<std::int64_t>(std::clamp(acc[i], 0, 4 * Scale))
                   * policy_[static_cast<std::size_t>(action) * width_ + i];
        return total;
    }

    Accumulator accumulate(const rules::Snapshot& s) const {
        Accumulator acc = bias_;
        if (!valid()) return {};
        for (const auto feature : features(s, feature_count_ == KingFeatures)) {
            const auto offset = static_cast<std::size_t>(feature) * width_;
            for (unsigned i = 0; i < width_; ++i)
                acc[i] += embedding_[offset+i];
        }
        return acc;
    }

    // For an actual move, change only the sparse feature rows that differ.
    // The search may retain these accumulators along its reversible path.
    Accumulator update(const rules::Snapshot& before, const rules::Snapshot& after,
                       const Accumulator& old) const {
        if (!valid() || old.size() != width_) return {};
        Accumulator result = old;
        const auto left = features(before, feature_count_ == KingFeatures),
                   right = features(after, feature_count_ == KingFeatures);
        std::size_t i = 0, j = 0;
        while (i < left.size() || j < right.size()) {
            if (j == right.size() || (i < left.size() && left[i] < right[j])) {
                const auto offset = static_cast<std::size_t>(left[i++]) * width_;
                for (unsigned k = 0; k < width_; ++k) result[k] -= embedding_[offset+k];
            } else if (i == left.size() || right[j] < left[i]) {
                const auto offset = static_cast<std::size_t>(right[j++]) * width_;
                for (unsigned k = 0; k < width_; ++k) result[k] += embedding_[offset+k];
            } else { ++i; ++j; }
        }
        return result;
    }

    int score(const Accumulator& accumulator) const {
        if (!valid() || accumulator.size() != width_) return 0;
        std::int64_t total = output_bias_;
        for (unsigned i = 0; i < width_; ++i)
            total += static_cast<std::int64_t>(
                std::clamp(accumulator[i], 0, 4 * Scale)) * output_[i];
        constexpr std::int64_t denom = Scale * Scale;
        const auto rounded = total >= 0 ? (total * 1000 + denom / 2) / denom
            : -((-total * 1000 + denom / 2) / denom);
        return static_cast<int>(std::clamp<std::int64_t>(rounded, -30000, 30000));
    }
    int evaluate(const rules::Snapshot& s) const { return score(accumulate(s)); }

private:
    std::uint32_t width_ = 0;
    std::uint32_t feature_count_ = Features;
    std::vector<std::int32_t> bias_;
    std::vector<std::int16_t> embedding_, output_;
    std::int32_t output_bias_ = 0;
    std::vector<std::int16_t> policy_;
    std::vector<std::int32_t> policy_bias_;
};
} // namespace shogi::strategy
