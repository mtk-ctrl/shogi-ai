# GitHub Actions workflow index

この文書はworkflowの入口であり、運用Ruleの正本ではない。
作業前に `docs/00_開発ルーター.md` を読み、必要なRuleへ進む。

## 主な読み先
- 通常開発・CI: `docs/rules/R10_開発・採用・通常仕上げ.md`
- 対局条件: `docs/rules/R20_対局・比較・統計.md`
- runner配分・停止・ETA・結果確認タイマー: `docs/rules/R21_Actionsランナー運用.md`
- Nightly: `docs/rules/R30_夜間研究.md`
- Android / APK / release: `docs/rules/R60_Android・APK・リリース.md`
- Rule同期: `docs/rules/R90_ルール変更・同期手順.md`
- Book / Experience: `docs/hold/H10_Book・Experience方針保留.md`

## 軽量チェック
`Document Rule Consistency` は、docs・Rule・ルーター変更時だけ起動する。
active Ruleがルーターに登録されていること、ルーターの参照先が存在することを確認し、エンジンの重いビルドは行わない。

## workflow追加時
一時実験や重い比較は原則 `workflow_dispatch` とし、通常pushへ不要な重い処理や通知を追加しない。
固定局数の対局workflowでは、起動時にその時点の空きrunner数へ再配分できる構造を優先する。
時間枠型Nightlyでは、研究フェーズを守りながら空きrunnerを最大活用する。
