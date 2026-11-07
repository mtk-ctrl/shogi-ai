#pragma once
namespace shogi::strategy {
// Diagnostic switches; the owner adopted profile 23 in v2.0.14.
// Zero reproduces PR #259. QuiescenceReuse is experimental and default OFF.
inline constexpr unsigned DefaultSearchResearchMask = 23;
enum SearchResearch : unsigned {
    GeneratedPlay = 1, SharedLegal = 2, OrderReuse = 4,
    QuiescenceReuse = 8, EarlyHints = 16,
};
// The owner adopted SelectiveUSI in v2.0.15 and LazyQTerminal in v2.0.24. Other flags stay experimental/OFF.
inline constexpr unsigned DefaultSearchEfficiencyMask = 24; // v2.0.24: LazyQTerminal (16) adopted
enum SearchEfficiency : unsigned {
    RuleCheckOrdering = 1, OrderingWorkspace = 2, LazySnapshot = 4,
    SelectiveUSI = 8, LazyQTerminal = 16, // research: skip full legal generation at stand-pat qnodes
};
// Formally adopted in v2.0.16: geometry distance table + occupied-square evaluation scanning.
// LegalTokenCache=OFF; the previously adopted 23/8 defaults above stay unchanged.
inline constexpr unsigned DefaultSearchReuseMask = 6;
// v2.0.20: PVS + quiet cutoff killers. History ordering formally adopted in v2.0.21.
inline constexpr unsigned DefaultSearchProbeMask = 7;
// v2.0.22: late-move reduction (bit 2) formally adopted. v2.0.23: futility
// pruning (bit 4) formally adopted. Bit 1 (null move) is research code and
// stays off by default.
inline constexpr unsigned DefaultSearchPruneMask = 6;
enum SearchReuse : unsigned {
    LegalTokenCache = 1, GeometryLookup = 2, OccupiedIndex = 4,
};
}
