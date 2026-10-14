# 最終候補の検査完了

2026-10-15確認。研究PR262の候補commitは305e5a7eee4c75d03f6b11d6cdb2c98d30eb53d3。既定SearchResearchMask=23。正式版はv2.0.13/profile47のまま、PRは未統合。

- Quick Strategy CI: https://github.com/mtk-ctrl/shogi-ai/actions/runs/38650963142 — success、対象commit一致、2026-10-15 08:00:31 JSTまでに完了。
- Document Rule Consistency: https://github.com/mtk-ctrl/shogi-ai/actions/runs/38650968240 — success、対象commit一致。
- Quick job116149343077のログで `python3 tests/test_search_research.py build/shogi-ai` の実行と、2026-10-15 08:00:02 JSTの `PASS all 32 combinations: poisoned pawn, both-color scores, mate distance, legal PV, actual mask` を確認。

300局の結果・原記録監査はRESULTS.md、selection-match-audit.json、final-match-audit.jsonに保存。選択用200局と独立100局は混ぜない。最終独立100局は53勝2分45敗、54.0%、概算95%44.3～63.7%。棋力向上も非劣性も未証明。

検査済み候補を新たな文書更新で変更せず、最終検査証拠と報告はresearch/search-expansion-evidence-20261015へ保存した。証拠branch内のEngine実装を採用対象とせず、上記候補commitとmask23を採用判断対象とする。採否は本人判断。Actions対局artifactは2027-01-12期限、長期移送は未実施。
