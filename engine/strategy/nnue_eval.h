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
    static constexpr int Scale = 256;
    using Accumulator = std::vector<std::int32_t>;

    static std::vector<std::uint32_t> features(const rules::Snapshot& s) {
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
        std::sort(f.begin(), f.end());
        return f;
    }

    bool load(const std::string& path) {
        // Transactional load; reject truncated/extended and malformed models.
        NnueModel candidate;
        std::ifstream file(path, std::ios::binary | std::ios::ate);
        if (!file) return false;
        const auto length = file.tellg();
        if (length < 16 || length > 3 * 1024 * 1024) return false;
        file.seekg(0);
        std::vector<unsigned char> bytes(static_cast<std::size_t>(length));
        if (!file.read(reinterpret_cast<char*>(bytes.data()), bytes.size())) return false;
        static constexpr char magic[] = "KMNNUE01";
        if (!std::equal(bytes.begin(), bytes.begin() + 8, magic)) return false;
        std::size_t offset = 8;
        auto u32 = [&]() -> std::uint32_t {
            const auto n = std::uint32_t(bytes[offset]) |
                 std::uint32_t(bytes[offset+1]) << 8 |
                 std::uint32_t(bytes[offset+2]) << 16 |
                 std::uint32_t(bytes[offset+3]) << 24;
            offset += 4; return n;
        };
        const auto width = u32(), count = u32();
        if (count != Features || width < 16 || width > 512) return false;
        const std::size_t expected = 16 + 4ull * width
            + 2ull * count * width + 2ull * width + 4;
        if (bytes.size() != expected) return false;
        auto i16 = [&]() -> std::int16_t {
            const auto n = std::uint16_t(bytes[offset]) |
                 std::uint16_t(bytes[offset+1]) << 8;
            offset += 2; return static_cast<std::int16_t>(n);
        };
        candidate.width_ = width;
        candidate.bias_.reserve(width);
        for (unsigned i = 0; i < width; ++i)
            candidate.bias_.push_back(static_cast<std::int32_t>(u32()));
        candidate.embedding_.reserve(static_cast<std::size_t>(count) * width);
        for (std::size_t i = 0; i < static_cast<std::size_t>(count) * width; ++i)
            candidate.embedding_.push_back(i16());
        candidate.output_.reserve(width);
        for (unsigned i = 0; i < width; ++i) candidate.output_.push_back(i16());
        candidate.output_bias_ = static_cast<std::int32_t>(u32());
        *this = std::move(candidate);
        return true;
    }

    bool valid() const { return width_ >= 16 && embedding_.size() == Features * width_; }
    unsigned width() const { return width_; }

    Accumulator accumulate(const rules::Snapshot& s) const {
        Accumulator acc = bias_;
        if (!valid()) return {};
        for (const auto feature : features(s)) {
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
        const auto left = features(before), right = features(after);
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
    std::vector<std::int32_t> bias_;
    std::vector<std::int16_t> embedding_, output_;
    std::int32_t output_bias_ = 0;
};
} // namespace shogi::strategy
