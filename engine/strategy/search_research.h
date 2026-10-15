#pragma once
namespace shogi::strategy {
// Diagnostic switches; the owner adopted profile 23 in v2.0.14.
// Zero reproduces PR #259. QuiescenceReuse is experimental and default OFF.
inline constexpr unsigned DefaultSearchResearchMask = 23;
enum SearchResearch : unsigned {
    GeneratedPlay = 1, SharedLegal = 2, OrderReuse = 4,
    QuiescenceReuse = 8, EarlyHints = 16,
};
// Second-round research only; this default is not an official adoption.
inline constexpr unsigned DefaultSearchEfficiencyMask = 8;
enum SearchEfficiency : unsigned {
    RuleCheckOrdering = 1, OrderingWorkspace = 2, LazySnapshot = 4,
    SelectiveUSI = 8,
};
}
