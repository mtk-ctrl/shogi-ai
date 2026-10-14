#pragma once
namespace shogi::strategy {
// Research-only switches. Zero reproduces PR #259; no official promotion.
inline constexpr unsigned DefaultSearchResearchMask = 23;
enum SearchResearch : unsigned {
    GeneratedPlay = 1, SharedLegal = 2, OrderReuse = 4,
    QuiescenceReuse = 8, EarlyHints = 16,
};
}
