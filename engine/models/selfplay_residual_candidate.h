#pragma once
#include <string_view>
namespace shogi::strategy::detail {
// Research candidate only; the training exporter replaces this empty snapshot.
inline constexpr std::string_view SelfPlayModelText = "";
inline constexpr std::string_view SelfPlayModelSha256 = "untrained";
}
