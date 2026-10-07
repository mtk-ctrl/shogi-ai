---
hold_id: H10
status: hold
authority: non-normative
---

# Book・Experience 方針保留

## 状態
2026-10-07、オーナーは「対局記録・研究記録・局面知識」の構成を承認した。今後はBook / Experienceの二分法を必須としない。正本はR25、接続する保存・即活用仕様はdocs/35。
本書は残る未決事項を保留する。既存コード・USIのBook / Experienceという名称は当面互換性のため残る。

## 現在確認できている衝突・論点
1. **Book自動main反映**
   - 整理前の旧 `nightly-book-learning.yml` には条件付きでBookをmainへpushする実装があった。現在は `docs/hold/workflows/nightly-book-learning.yml` へ退避され、実行されない。
   - 旧 `NIGHTLY_RESEARCH_SYSTEM.md` には、新credit assignment完成までBook自動更新を止める設計記述がある。
   - どちらを今後の正式方針にするかは保留。

2. **外部対局由来Experience**
   - READMEの旧記述は外部対局をExperience Cache更新対象外としていた。
   - 旧 `docs/23_外部エンジン対局基盤.md` は、KUMOJI自身が探索した結果なら保存可としていた。
   - `tools/floodgate/client.py` には保留前の既存実装として `ExperienceCache=true` と `experience_eligible=true` が残っている。これは実装事実であり、今後の正式方針を確定する根拠にはしない。
   - 2026-10-08の追加確認2で、外部AI対局の雲路自身の探索結果を局面知識の候補に含めることを本人が選択した。出所の正本はR50。
   - 旧Experienceへの自動投入、実戦での直接利用条件、自動継続更新・昇格・世代管理の方式は引き続き未決。既存Floodgateの挙動全体を今回追認したとはしない。

3. **runner / lane構造**
   - 旧Book Nightlyには4 runner × 各4 local laneの実装がある。
   - R21は通常の固定局数比較で1 Actions job = 1 laneを原則とする。
   - Book / Experience固有の永続状態と並列化方式は、役割分担の決定と合わせて再設計する。保留中はR21だけを理由に旧Book workflowを書き換えない。

4. **役割分担**
   - Opening Bookが「候補手を直接選ぶもの」なのか、探索優先度・局面知識の一部なのか。
   - Experienceがmove ordering hint、探索結果再利用、局面評価データのどこまでを担うのか。
   - 局面ごとの評価値データをBook/Experienceとは別資産として持つか。

5. **保存・世代管理**
   - Engine version、Book version、Experience version、使用条件をどの粒度で紐付けるか。
   - 対局ごと・着手ごとのtelemetryと学習資産をどう分離するか。

## 保留中にしてよいこと
- 現在の実装・artifact・保存状況を調査する。
- 既存Book / Experienceを使った対局を、条件を明示して行う。
- データ欠損や永続化不具合を修正する。ただし修正が学習方針変更を含む場合は確認する。

## 保留中にしてはいけないこと
- 既存workflowがそうなっているという理由だけで、それを今後の正式方針に確定する。
- 未承認の局面知識の直接利用基準・正式昇格・更新方針を新たに固定する。
- 外部対局由来Experienceの可否を片方の旧文書だけで決める。
- 自動main反映の是非を勝手に決める。

## 旧設計
- `docs/hold/source/16_ExperienceCache設計.md`
- `docs/hold/source/22_自前棋譜小規模定跡.md`
- `docs/archive/pre-router/NIGHTLY_RESEARCH_SYSTEM.md`
- `docs/archive/pre-router/23_外部エンジン対局基盤.md`


## Workflowの保留
Book / Experienceの実装方針に依存するGitHub Actions workflowは、誤実行を防ぐため `docs/hold/workflows/` へ退避している。
ここへ移したYAMLはGitHub Actionsから自動・手動実行されない。

特に、旧 `nightly-book-learning.yml` と旧 `nightly-research.yml` のscheduleは現在停止している。
退避時には、未決の方針でmainや学習資産を自動更新しないための一時凍結としていた。
2026-10-07の問6本人回答により、現在の夜間定期対局の停止理由は、変革期の優先課題へ開発を集中するためと確定した。将来の夜間対局を望まないという判断ではない。
H10の解消だけで夜間対局を再開しない。停止範囲と再開判断の正本はR30とする。

旧External Engine BenchmarkのFull-engineモードも、Book / Experienceを利用する部分だけ旧版を `docs/hold/workflows/external-engine-benchmark-legacy.yml` に保存した。
現役のExternal Engine BenchmarkはCore条件のみを扱う。

## 部分決定（2026-10-07）
オーナーは通常対局の蓄積対象を「実際に指した手と必要な評価・探索情報」に限定した。
未着手候補手の全記録・探索木の全記録案は採用しない。
この部分の正本は `docs/rules/R25_着手記録の保存.md`。
活用順の提案は `docs/27_着手データ活用計画.md`。
問7の本人回答により、人間との対局の学習利用はオーナー本人との対局だけに限る。対象の正本はR50。この対象の決定だけで、Book / Experienceの役割・更新アルゴリズムや自己対局の方針を新たに確定しない。
概念構成とmove_order_hintの接続仕様はR25・docs/35へ確定範囲を追加した。研究結果の直接利用の具体的基準、知識版の正式採用、自動main反映は引き続き保留である。夜間定期対局の一時停止と未決定の再開時期はR30に従う。

## 2026-10-07追記: 概念統合後の論点
過去の論点4・5は検討経緯として残す。今後の設計を再びBook / Experienceへ必ず分割する要求にはしない。
「定跡」は局面知識の序盤の手順・分岐を整理した部分とする。対局由来/研究由来は出所属性とする。
最初に接続する即活用方式は過去の選択手を先に読むmove_order_hint。新しい原本からの生成・読込みは未実装である。
research_decisionの確認・変更条件、既定動作、永続状態の並列更新、自動main反映は未決。外部AI対局での雲路自身の探索結果を候補に含める出所判断は、2026-10-08にR50へ確定した。旧Experienceへの投入や候補の正式昇格まで確定していない。採用判断はR10に従う。
仕様: `docs/35_局面知識の統合設計と即活用.md`。本人の承認範囲: `docs/decisions/2026-10-07_局面知識への統合と即活用方式.md`。
