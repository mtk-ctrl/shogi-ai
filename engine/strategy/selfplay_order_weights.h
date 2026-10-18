#pragma once
#include <array>
namespace shogi::strategy {
inline constexpr std::array<int,64> SelfplayOrderWeights{125,-21,-243,411,-553,608,21,-395,138,1219,1153,1674,2098,3942,1975,0,-253,216,-166,-20,1301,-399,0,0,-396,1246,432,-795,2777,33,1042,11,2177,1380,-210,-790,2582,-1598,0,2678,560,-248,198,-74,458,744,-32,134,-925,537,711,724,258,-699,-49,-488,1602,1001,760,-783,-719,115,935,252};
inline constexpr const char* SelfplayOrderModel = "fb1b4ad58e7e14a649e5a80db7c38709cf4356aaf8b89be4d775468e500e4f9c";
inline constexpr bool SelfplayOrderReady = true;
}
