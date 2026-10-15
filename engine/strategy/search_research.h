#pragma once
namespace shogi::strategy {
// Diagnostic switches; the owner adopted profile 23 in v2.0.14.
// Zero reproduces PR #259. QuiescenceReuse is experimental and default OFF.
inline constexpr unsigned DefaultSearchResearchMask = 23;
enum SearchResearch : unsigned {
    GeneratedPlay = 1, SharedLegal = 2, OrderReuse = 4,
    QuiescenceReuse = 8, EarlyHints = 16,
};
// The owner adopted SelectiveUSI alone in v2.0.15. Other flags stay experimental/OFF.
inline constexpr unsigned DefaultSearchEfficiencyMask = 8;
enum SearchEfficiency : unsigned {
    RuleCheckOrdering = 1, OrderingWorkspace = 2, LazySnapshot = 4,
    SelectiveUSI = 8,
};
// Third-round research only; the official 23/8 defaults above are unchanged.
inline constexpr unsigned DefaultSearchReuseMask = 6;
enum SearchReuse : unsigned {
    LegalTokenCache = 1, GeometryLookup = 2, OccupiedIndex = 4,
};
}
