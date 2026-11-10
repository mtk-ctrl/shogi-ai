#!/bin/sh
# Usage: feature_probe2.build.sh <repo root> <output binary>   (needs build/ from scripts/prepare_rules.py)
R=$1; O=$2
g++ -std=c++17 -O2 -pthread -DSHOGI_RULES_ONLY -DUSER_ENGINE -DNO_SSE -DASSERT_LV=3 \
  -I$R/build/generated -I$R/engine -I$R/build/yaneuraou-rules/source \
  $R/build/yaneuraou-rules/source/bitboard.cpp $R/build/yaneuraou-rules/source/position.cpp \
  $R/build/yaneuraou-rules/source/movegen.cpp $R/build/yaneuraou-rules/source/types.cpp \
  $R/engine/rules/upstream_support.cpp $R/engine/rules/position.cpp \
  $R/research/eval-tuning/feature_probe2.cpp -o $O
