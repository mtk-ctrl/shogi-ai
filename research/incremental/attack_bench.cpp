// Research: how much of one static evaluation is the AttackMap build? Reads SFENs on stdin.
#include "strategy/evaluation.h"
#include "strategy/phase_weights.h"
#include "strategy/turn_phase.h"
#include <chrono>
#include <iostream>
#include <sstream>
#include <vector>
using namespace shogi;
int main(int argc, char** argv) {
    const int repeats = argc > 1 ? std::stoi(argv[1]) : 300;
    std::vector<rules::Snapshot> S; std::vector<strategy::EvaluationParameters> P; std::string line, err;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        // each line: space-separated USI moves from the initial position; sample every 4th ply
        std::vector<std::string> mv; { std::stringstream ss(line); std::string t; while (ss >> t) mv.push_back(t); }
        for (size_t k = 8; k <= mv.size(); k += 4) {
            rules::Position p;
            if (!p.set("lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b - 1", std::vector<std::string>(mv.begin(), mv.begin() + k), err)) break;
            auto s = p.snapshot(); S.push_back(s);
            P.push_back(strategy::phase_turn_parameters(strategy::EvaluationParameters{}, strategy::classify_turn_phase(s).maturity));
        }
    }
    volatile long sink = 0; using C = std::chrono::steady_clock;
    auto t0 = C::now();
    for (int r = 0; r < repeats; ++r) for (size_t i = 0; i < S.size(); ++i) sink += strategy::evaluate(S[i], P[i], 15).total;
    auto t1 = C::now();
    for (int r = 0; r < repeats; ++r) for (size_t i = 0; i < S.size(); ++i) { strategy::AttackMap a(S[i], true, true, true); sink += a.count[0][40]; }
    auto t2 = C::now();
    const double n = double(repeats) * S.size();
    const double full = std::chrono::duration<double, std::nano>(t1 - t0).count() / n;
    const double am = std::chrono::duration<double, std::nano>(t2 - t1).count() / n;
    std::cout << "positions " << S.size() << "  evaluate " << full << " ns  attackmap " << am << " ns  share " << 100 * am / full << "%\n";
}
