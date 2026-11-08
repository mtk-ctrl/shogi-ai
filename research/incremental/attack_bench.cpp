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
    long checksum = 0; for (size_t i = 0; i < S.size(); ++i) checksum = checksum * 1000003 + strategy::evaluate(S[i], P[i], 15).total;
    volatile long sink = 0; using C = std::chrono::steady_clock;
    auto t0 = C::now();
    for (int r = 0; r < repeats; ++r) for (size_t i = 0; i < S.size(); ++i) sink += strategy::evaluate(S[i], P[i], 15).total;
    auto t1 = C::now();
    for (int r = 0; r < repeats; ++r) for (size_t i = 0; i < S.size(); ++i) { strategy::AttackMap a(S[i], true, true, true); sink += a.count[0][40]; }
    auto t2 = C::now();
    // per-section timing (AttackMap built once per position outside the timers)
    double t_v2b=0,t_inf=0,t_pot=0,t_coo=0,t_thr=0,t_ks=0,t_pr=0,t_ac=0,t_da=0,t_v2=0,t_kd=0,t_ke=0,t_am=0;
    for (int r = 0; r < repeats; ++r) for (size_t i = 0; i < S.size(); ++i) {
        const auto& s = S[i]; const auto& p = P[i];
        auto a0 = C::now(); strategy::AttackMap a(s, true, true, true); auto a1 = C::now(); t_am += (a1 - a0).count();
        strategy::SideFeatures f[2];
        auto tm = [&](double& acc, auto fn) { auto x = C::now(); fn(); acc += (C::now() - x).count(); };
        tm(t_ks, [&] { for (int c = 0; c < 2; ++c) strategy::king_safety_features(s, a, c, f[c]); });
        tm(t_pr, [&] { for (int c = 0; c < 2; ++c) strategy::pressure_features(s, a, c, f[c]); });
        tm(t_ac, [&] { for (int c = 0; c < 2; ++c) strategy::activity_features(s, a, c, p, f[c]); });
        tm(t_da, [&] { for (int c = 0; c < 2; ++c) strategy::danger_features(s, a, c, f[c]); });
        tm(t_v2, [&] { for (int c = 0; c < 2; ++c) f[c].v2 = strategy::v2_features(s, a, p, c); });
        tm(t_kd, [&] { sink += strategy::v2_king_drop_side(s, a, 0) + strategy::v2_king_drop_side(s, a, 1); });
        tm(t_ke, [&] { int f0[strategy::KingExtFeatures], f1[strategy::KingExtFeatures];
                       strategy::king_ext_features(s, a, 0, f0); strategy::king_ext_features(s, a, 1, f1); sink += f0[1] + f1[1]; });
        tm(t_inf, [&] { for (int c = 0; c < 2; ++c) sink += strategy::v2_influence_side(s, a, c); });
        tm(t_pot, [&] { for (int c = 0; c < 2; ++c) sink += strategy::v2_potential_side(s, a, c); });
        tm(t_coo, [&] { for (int c = 0; c < 2; ++c) sink += strategy::v2_coordination_side(s, a, c); });
        tm(t_thr, [&] { for (int c = 0; c < 2; ++c) sink += strategy::v2_threat_side(s, a, c); });
        tm(t_v2b, [&] { for (int c = 0; c < 2; ++c) f[c].v2 = strategy::v2_features(s, a, p, c); });
        sink += f[0].exposure;
    }
    const double n = double(repeats) * S.size();
    const double full = std::chrono::duration<double, std::nano>(t1 - t0).count() / n;
    std::cout << "positions " << S.size() << "  evaluate(total) " << full << " ns  checksum " << checksum << "\n";
    auto row = [&](const char* name, double t) { std::cout << "  " << name << ": " << t / n << " ns  (" << 100 * t / n / full << "%)\n"; };
    row("attackmap build", t_am); row("king_safety", t_ks); row("pressure", t_pr); row("activity", t_ac);
    row("danger", t_da); row("v2_features(influence/potential/coordination/hand/threat)", t_v2);
    row("  influence", t_inf); row("  potential", t_pot); row("  coordination", t_coo); row("  threat", t_thr);
    row("v2_features again (end of loop)", t_v2b); row("king_drop(v2)", t_kd); row("king_ext", t_ke);
}
