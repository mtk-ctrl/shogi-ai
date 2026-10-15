# 正式v2.0.15の計装プロファイル

-O2 -pg、計画の先頭12局面×30回=360探索、depth2、知識ON、mate/長考/初手乱数OFF。gprofはサンプリング・計装誤差を含み、速度比較には使わない。

```text
Flat profile:

Each sample counts as 0.01 seconds.
  %   cumulative   self              self     total           
 time   seconds   seconds    calls  ms/call  ms/call  name    
 15.96      0.45     0.45   273540     0.00     0.00  shogi::strategy::evaluate(shogi::rules::Snapshot const&, shogi::strategy::EvaluationParameters const&)
  7.45      0.66     0.21 28317480     0.00     0.00  shogi::strategy::AttackMap::AttackMap(shogi::rules::Snapshot const&)::{lambda(int, int, bool)#1}::operator()(int, int, bool) const
  7.09      0.86     0.20   547080     0.00     0.00  shogi::strategy::v2_features(shogi::rules::Snapshot const&, shogi::strategy::AttackMap const&, shogi::strategy::EvaluationParameters const&, int)
  7.09      1.06     0.20   397230     0.00     0.00  shogi::rules::Position::legal_generated_moves() const
  6.03      1.23     0.17   738090     0.00     0.00  shogi::strategy::MoveOrder::analyze_after(shogi::rules::Snapshot const&, int, shogi::rules::Color, int, bool, std::vector<int, std::allocator<int> > const*, int, bool)::{lambda(int)#1}::operator()(int) const
  6.03      1.40     0.17   547080     0.00     0.00  shogi::strategy::pressure_features(shogi::rules::Snapshot const&, shogi::strategy::AttackMap const&, int, shogi::strategy::SideFeatures&)
  4.96      1.54     0.14   876780     0.00     0.00  void YaneuraOu::Position::do_move<void>(YaneuraOu::Move, YaneuraOu::StateInfo&, bool, void const*)
  4.26      1.66     0.12 26817420     0.00     0.00  shogi::strategy::MoveOrder::piece_attacks(shogi::rules::Snapshot const&, int, shogi::rules::Piece const&, int)
  4.26      1.78     0.12   547080     0.00     0.00  shogi::strategy::v2_threat_side(shogi::rules::Snapshot const&, shogi::strategy::AttackMap const&, int)
  3.19      1.87     0.09   333690     0.00     0.00  shogi::strategy::AttackMap::AttackMap(shogi::rules::Snapshot const&)
  2.84      1.95     0.08 37718104     0.00     0.00  YaneuraOu::Position::legal(YaneuraOu::Move) const
  2.84      2.03     0.08   472020     0.00     0.00  shogi::rules::Position::snapshot() const
  2.13      2.09     0.06 14539472     0.00     0.00  YaneuraOu::operator&(YaneuraOu::Bitboard const&, YaneuraOu::Square)
  2.13      2.15     0.06  2869140     0.00     0.00  void std::vector<shogi::rules::GeneratedMove, std::allocator<shogi::rules::GeneratedMove> >::_M_realloc_insert<shogi::rules::GeneratedMove const&>(__gnu_cxx::__normal_iterator<shogi::rules::GeneratedMove*, std::vector<shogi::rules::GeneratedMove, std::allocator<shogi::rules::GeneratedMove> > >, shogi::rules::GeneratedMove const&)
  2.13      2.21     0.06   547080     0.00     0.00  shogi::strategy::v2_potential_side(shogi::rules::Snapshot const&, shogi::strategy::AttackMap const&, int)
  2.13      2.27     0.06    59790     0.00     0.01  shogi::strategy::MoveOrder::order(shogi::rules::Snapshot const&, std::vector<std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >, std::allocator<std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > > > const&, std::vector<unsigned char, std::allocator<unsigned char> > const*, bool)
```
