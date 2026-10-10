#pragma once
// Experimental mate-in-seven predictor. It never proves mate: only the
// existing self-authored MateSearch can certify a mating move.
#include "strategy/evaluation.h"
#include "strategy/turn_phase.h"
#include <array>
#include <cmath>
#include <fstream>
#include <sstream>
#include <string>

namespace shogi::strategy {
struct MateLearning {
    static constexpr int FeatureCount = 8;
    using Features = std::array<double, FeatureCount>;

    // Fixed schema shared with tools/learning/mate_learning.py. Features are
    // computed from the current side's perspective, not Black's.
    static Features features(const rules::Position& position) {
        const auto s = position.snapshot();
        const int us = static_cast<int>(s.turn), them = 1 - us;
        const auto b = evaluate(s);
        const auto& attack = b.raw[us];
        const auto& guards = b.raw[them];
        const auto phase = classify_turn_phase(s);
        return {
            double(phase.maturity),
            double(attack.king_attacked),
            double(attack.occupied_ring),
            double(attack.denied_empty),
            double(attack.partners),
            double(guards.gold_guards * 2 + guards.silver_guards + guards.pawn_guards),
            double(attack.v2.hand_potential),
            double(guards.v2.hand_potential)
        };
    }

    bool load(const std::string& path) {
        valid_ = false;  // Failed reloads never retain a stale active model.
        std::ifstream in(path);
        if (!in) return false;
        std::string header;
        if (!std::getline(in, header) || header != "KUMOJI_MATE_GATE_V1") return false;
        Features mean{}, scale{}, weight{};
        if (!read_row(in, "mean", mean) || !read_row(in, "scale", scale)
            || !read_row(in, "weight", weight)) return false;
        for (int i = 0; i < FeatureCount; ++i) {
            if (scale[i] <= 0 || scale[i] > 1e8 || std::abs(mean[i]) > 1e8
                || std::abs(weight[i]) > 50.0) return false;
        }
        double bias = 0, threshold = 0;
        if (!read_scalar(in, "bias", bias) || !read_scalar(in, "threshold", threshold)
            || std::abs(bias) > 50 || threshold < 0.5 || threshold > 0.99)
            return false;
        std::string extra;
        if (in >> extra) return false;
        mean_ = mean;
        scale_ = scale;
        weight_ = weight;
        bias_ = bias;
        threshold_ = threshold;
        valid_ = true;
        return true;
    }

    bool valid() const { return valid_; }
    double threshold() const { return threshold_; }
    double probability(const Features& x) const {
        if (!valid_) return 0.0;
        double z = bias_;
        for (int i = 0; i < FeatureCount; ++i)
            z += weight_[i] * ((x[i] - mean_[i]) / scale_[i]);
        z = std::max(-30.0, std::min(30.0, z));
        return 1.0 / (1.0 + std::exp(-z));
    }
private:
    static bool read_row(std::istream& in, const char* expected, Features& out) {
        std::string line, key, trailing;
        if (!std::getline(in, line) || line.size() > 2048) return false;
        std::istringstream row(line);
        if (!(row >> key) || key != expected) return false;
        for (auto& value : out)
            if (!(row >> value) || !std::isfinite(value)) return false;
        return !(row >> trailing);
    }
    static bool read_scalar(std::istream& in, const char* expected, double& out) {
        std::string line, key, trailing;
        if (!std::getline(in, line) || line.size() > 256) return false;
        std::istringstream row(line);
        return (row >> key >> out) && key == expected && std::isfinite(out)
            && !(row >> trailing);
    }
    Features mean_{}, scale_{}, weight_{};
    double bias_ = 0, threshold_ = 0.8;
    bool valid_ = false;
};
} // namespace shogi::strategy
