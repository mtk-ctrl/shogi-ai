#!/usr/bin/env python3
from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8", newline="\n")


def replace_required(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise SystemExit(f"required text not found in {path}: {old!r}")
    write(path, text.replace(old, new))


# Normalize the 2026-10-05 journal filenames to integration order.
renames = [
    ("journal/2026-10-05_09_夜間自己対局自動化.md", "journal/2026-10-05_12_夜間自己対局自動化.md"),
    ("journal/2026-10-05_10_やねうら王との棋力測定.md", "journal/2026-10-05_13_やねうら王との棋力測定.md"),
    ("journal/2026-10-05_11_Book勝敗フィードバック学習.md", "journal/2026-10-05_14_Book勝敗フィードバック学習.md"),
    ("journal/2026-10-05_11_Book実戦フィードバック学習と移転前停止.md", "journal/2026-10-05_15_Book実戦フィードバック学習と移転前停止.md"),
    ("journal/2026-10-05_自前棋譜小規模定跡.md", "journal/2026-10-05_09_自前棋譜小規模定跡.md"),
    ("journal/2026-10-05_自前定跡Book世代管理と2000局追加実験.md", "journal/2026-10-05_10_自前定跡Book世代管理と2000局追加実験.md"),
]
for src, dst in renames:
    s, d = Path(src), Path(dst)
    if not s.exists():
        raise SystemExit(f"missing journal source: {src}")
    if d.exists():
        raise SystemExit(f"journal target already exists: {dst}")
    s.rename(d)

# Update Markdown references after renaming.
for p in Path(".").rglob("*.md"):
    text = p.read_text(encoding="utf-8")
    updated = text
    for src, dst in renames:
        updated = updated.replace(src, dst)
        updated = updated.replace(Path(src).name, Path(dst).name)
    if updated != text:
        p.write_text(updated, encoding="utf-8", newline="\n")

# Keep current nightly documentation aligned with the actual workflow.
replace_required("docs/22_自前棋譜小規模定跡.md", "- 04:47 JST開始", "- 00:05 JST開始")
replace_required(
    "docs/22_自前棋譜小規模定跡.md",
    "- GitHub Actions 1 runner内で2レーン並列",
    "- GitHub Actions 1 runner（public repository の標準 `ubuntu-latest`、4 CPU）内で4レーン並列",
)
p = Path("docs/22_自前棋譜小規模定跡.md")
text = p.read_text(encoding="utf-8")
smoke = "- public化後のスモークテストで4 CPU / 4レーン、8局完走、違法0、Book hit 66、照合不一致0を確認\n"
marker = "- Experience Cacheは両者OFF\n"
if smoke not in text:
    if marker not in text:
        raise SystemExit("docs/22 smoke insertion marker missing")
    text = text.replace(marker, marker + smoke)
    p.write_text(text, encoding="utf-8", newline="\n")

replace_required("journal/2026-10-05_14_Book勝敗フィードバック学習.md", "- 04:47 JST開始", "- 00:05 JST開始")
replace_required(
    "journal/2026-10-05_14_Book勝敗フィードバック学習.md",
    "- 2レーン並列",
    "- 4レーン並列（public repository の標準 `ubuntu-latest` 1 runner / 4 CPU）",
)

# Rewrite the original nightly note so it records both history and the current setup.
write(
    "journal/2026-10-05_12_夜間自己対局自動化.md",
    """# 夜間自己対局・Book学習の自動化

## 目的

夜間のGitHub Actions計算資源を使い、shogi-ai自身の実戦結果を人手なしで継続的に蓄積し、Opening Bookの改善へつなげる。

## 現在の運用

現在の正本は `.github/workflows/nightly-book-learning.yml` である。

- repositoryはpublicで、標準 `ubuntu-latest` runnerを使用する。
- 毎日00:05 JSTに開始する。
- 1 runnerの4 CPUを4レーンで使用する。
- 各レーンはBook ON対Core（同一shogi-ai、Book OFF）を先後交代で実行する。
- 両者 `go movetime 50`、最大200 ply、Experience Cache OFFとする。
- 05:20 JST以降は新しい対局バッチを開始せず、集計・検証・Book更新を05:30頃までに終える。
- 外部エンジンとの対局はこの学習経路へ入れない。やねうら王等は棋力測定専用である。

## 学習と保存

Book側が実際に選択した手だけをBook hitとして記録し、棋譜を自作ルール層で再生して局面ハッシュ・指し手・最終勝敗を照合する。違法対局0、20局以上、正しく照合できたBook hit 50件以上を自動反映の最低条件とする。実行途中にmainのBookが変わった場合は上書きしない。

生の対局結果と集計結果はActions artifactへ保存し、学習候補はUSIで読み込み検証してから本番Bookへ反映する。

## public化後のスモークテスト

新しいpublic `mtk-ctrl/shogi-ai` で本番と同じ経路の短時間スモークを実施した。

- runner: 4 CPU
- 並列: 4レーン
- 対局: 8局完走
- 違法局: 0
- Book hit: 66
- 正常照合: 66、unmatched 0、move mismatch 0
- 40 Book entryについて学習候補を生成
- 学習後BookのUSI読み込み検証に成功

この結果から、夜間本番を1 runner / 4レーンで開始できると判断した。実測局数を見て、必要な場合だけrunner数やレーン数を再検討する。

## 旧構成

導入当初はprivate repositoryのActions分数制限を前提に、複数runnerで単純な自己対局棋譜を蓄積する `Nightly Self Play` を設計した。その後repositoryをpublicへ移転し、標準runnerを長時間利用できるようになったため、旧 `nightly-self-play.yml` は廃止した。

現在は単なる棋譜蓄積よりも、Book ON対Core OFFの勝敗をBook改善へ直接使う `Nightly Book Learning` を正本とする。
""",
)

# Make the external-engine boundary visible at the top-level README.
readme = Path("README.md")
text = readme.read_text(encoding="utf-8")
section = """## やねうら王・外部エンジンとの境界

- やねうら王から利用するのは、合法手生成・局面管理・王手判定・千日手等の**ルール層だけ**である。
- 探索・評価・move ordering・置換表・詰み探索・戦略・学習はshogi-ai側で自作する。
- やねうら王その他の外部エンジンとの対局は**棋力測定専用**とし、相手の評価値・PV・推奨手・対局棋譜をOpening Book、評価関数、NNUE等の教師データへ使用しない。

詳細：[外部エンジン対局基盤](docs/23_外部エンジン対局基盤.md)。

"""
if "## やねうら王・外部エンジンとの境界" not in text:
    marker = "## 現在地\n"
    if marker not in text:
        raise SystemExit("README insertion marker missing")
    text = text.replace(marker, section + marker, 1)
    readme.write_text(text, encoding="utf-8", newline="\n")

# Document the importer-side fail-safe for external/ineligible results.
p = Path("docs/23_外部エンジン対局基盤.md")
text = p.read_text(encoding="utf-8")
extra = (
    "\nさらにBook取込側でも、`tools/book/import_arena_games.py` は "
    "`learning_eligible=false`、`opening_book_eligible=false`、または "
    "`kind=external_engine_benchmark` と明示されたJSONを拒否する。保存先の分離だけに依存せず、誤って外部結果ディレクトリを入力しても学習へ混入しない二重防御とする。\n"
)
marker = "外部対局結果は `benchmarks/external-results/` に保存する。自己対局Book生成の既定入力である `benchmarks/results/` には保存しない。ランナー自身も `benchmarks/results/` 配下への出力を拒否する。\n"
if extra.strip() not in text:
    if marker not in text:
        raise SystemExit("docs/23 insertion marker missing")
    text = text.replace(marker, marker + extra, 1)
    p.write_text(text, encoding="utf-8", newline="\n")

# Harden the Book importer itself.
p = Path("tools/book/import_arena_games.py")
text = p.read_text(encoding="utf-8")
old_doc = "This tool uses only shogi-ai's own benchmark records. It does not import moves\nfrom another engine or an external opening database."
new_doc = "This tool accepts shogi-ai self-play benchmark records only. Files explicitly\nmarked as ineligible for learning/opening-book use, and external-engine benchmark\nrecords, are rejected before any move is imported."
if old_doc not in text:
    raise SystemExit("importer doc marker missing")
text = text.replace(old_doc, new_doc, 1)
old_stats = '        "files_with_games": 0,\n        "raw_games": 0,\n'
new_stats = '        "files_with_games": 0,\n        "skipped_ineligible_files": 0,\n        "skipped_ineligible_games": 0,\n        "raw_games": 0,\n'
if old_stats not in text:
    raise SystemExit("importer stats marker missing")
text = text.replace(old_stats, new_stats, 1)
old_parse = '''        except (OSError, json.JSONDecodeError):
            continue
        details = data.get("details") if isinstance(data, dict) else None
        if not isinstance(details, list):
            continue
'''
new_parse = '''        except (OSError, json.JSONDecodeError):
            continue
        details = data.get("details") if isinstance(data, dict) else None
        if isinstance(data, dict) and (
            data.get("learning_eligible") is False
            or data.get("opening_book_eligible") is False
            or data.get("kind") == "external_engine_benchmark"
        ):
            stats["skipped_ineligible_files"] += 1
            if isinstance(details, list):
                stats["skipped_ineligible_games"] += len(details)
            continue
        if not isinstance(details, list):
            continue
'''
if old_parse not in text:
    raise SystemExit("importer parse marker missing")
text = text.replace(old_parse, new_parse, 1)
p.write_text(text, encoding="utf-8", newline="\n")

# Add a regression test to the existing opening-book pipeline test suite.
p = Path("tests/test_opening_book_pipeline.py")
text = p.read_text(encoding="utf-8")
method = '''    def test_import_rejects_external_or_explicitly_ineligible_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = {"winner": "A", "a_black": True, "reason": "checkmate",
                    "moves": ["7g7f", "3c3d", "2g2f"]}
            (root / "selfplay.json").write_text(
                json.dumps({"details": [game]}), encoding="utf-8")
            (root / "external.json").write_text(json.dumps({
                "kind": "external_engine_benchmark",
                "learning_eligible": False,
                "opening_book_eligible": False,
                "details": [game],
            }), encoding="utf-8")

            games, stats = importer.collect(root)
            self.assertEqual(len(games), 1)
            self.assertEqual(stats["skipped_ineligible_files"], 1)
            self.assertEqual(stats["skipped_ineligible_games"], 1)

'''
marker = "    def test_builder_keeps_supported_early_alternatives(self):\n"
if "test_import_rejects_external_or_explicitly_ineligible_files" not in text:
    if marker not in text:
        raise SystemExit("test insertion marker missing")
    text = text.replace(marker, method + marker, 1)
    p.write_text(text, encoding="utf-8", newline="\n")

# Record the clean public migration and the smoke test.
write(
    "journal/2026-10-05_16_publicリポジトリ移転と夜間スモーク.md",
    """# publicリポジトリ移転と夜間スモーク

## 移転

メールアドレスを含む旧Git履歴をpublic側へ持ち込まないため、旧repositoryを `shogi-ai-old` へ改名し、新しいpublic `mtk-ctrl/shogi-ai` を作成した。

移転元の最終チェックポイントは `c5b201a741baa2a3778822071d0e1e32a418d911` である。このコミットのtree `c37d82e93d861e879493866d6eeb06f5759ebdeb` と同一のファイルスナップショットを、新repositoryへ過去履歴なしで再構成した。

新repository側のコミットはGitHubのnoreplyアドレスを使用する。旧 `shogi-ai-old` はprivate化し、過去の開発履歴をバックアップとして保持する。

## public化の目的

private repositoryのGitHub-hosted Actions分数制限を避け、標準runnerを夜間の自己対局・Book学習へ継続的に利用できるようにする。公開後も、第三者へ書込権限を付与しない限りmainを直接変更することはできない。

トップレベルにGPL-3.0 LICENSEを置き、やねうら王由来のルール層とのライセンス境界を維持する。

## 夜間スモーク

新repository上で `Nightly Book Learning` と同じ主要経路を短時間実行し、次を確認した。

- GitHub-hosted runner: 4 CPU
- Book ON対Core OFF: 4レーン並列
- 8局完走、違法局0
- Book hit 66
- 66 hitすべて棋譜と正常照合、unmatched 0、move mismatch 0
- 40 Book entryの学習候補を生成
- 学習後BookのUSI読み込み検証成功

スモーク用one-shot workflowは確認後に削除した。本番は00:05 JST開始、05:20対局打切り、05:30頃までに集計・検証を完了する構成とする。

## 学習境界

夜間学習に使用するのはshogi-ai自身のBook ON対Core OFF対局だけである。やねうら王その他の外部エンジンは棋力測定専用とし、その棋譜・評価値・PV・推奨手は強化用データへ取り込まない。
""",
)

# Extend the changelog index with the post-v0.0.19 work.
p = Path("journal/CHANGELOG.md")
text = p.read_text(encoding="utf-8")
if "## 2026-10-05 — publicリポジトリ移転・夜間スモーク" not in text:
    text = text.rstrip() + """

## 2026-10-05 — 自前棋譜Opening Book

- 外部定跡・プロ棋譜・他エンジンの推奨手を使わず、shogi-ai自身の自己対局だけから小規模Bookを生成
- Book候補は自作ルール層で全手再生してから採用

詳細：`journal/2026-10-05_09_自前棋譜小規模定跡.md`

## 2026-10-05 — Book世代管理・2000局追加実験

- 自己対局を追加してBookを世代更新し、gen3を採用
- 勝率の低い定跡手を実戦結果から減衰させる継続学習へ進む方針を確定

詳細：`journal/2026-10-05_10_自前定跡Book世代管理と2000局追加実験.md`

## 2026-10-05 — 外部エンジン棋力測定基盤

- やねうら王等の外部エンジンを教師ではなく固定の物差しとして利用
- 外部対局結果を自己対局データから隔離し、評価値・PV・推奨手・棋譜を学習へ使用しない方針を固定
- Material版の探索nodesを100段階にしたプロジェクト専用尺度を整備

詳細：`journal/2026-10-05_11_外部エンジン100段階評価基盤.md` / `docs/23_外部エンジン対局基盤.md`

## 2026-10-05 — 夜間Book学習自動化

- public repositoryの標準4 CPU runnerを1台使い、4レーンでBook ON対Core OFFを夜間実行
- 00:05 JST開始、05:20対局打切り、05:30頃までに集計・検証
- Book hitを棋譜と厳密照合し、十分な証拠がある場合だけ本番Bookへ自動反映

詳細：`journal/2026-10-05_12_夜間自己対局自動化.md`

## 2026-10-05 — やねうら王との棋力測定

- 固定したやねうら王Material版との対局で現在棋力を測定
- 外部エンジンは棋力測定専用とし、対局棋譜も強化学習へ使用しない

詳細：`journal/2026-10-05_13_やねうら王との棋力測定.md`

## 2026-10-05 — Book勝敗フィードバック学習

- Book ON対同一Core OFFの最終勝敗を、実際にBookが選択した手へだけフィードバック
- 低勝率手は削除せず重みを下げ、将来の探索改善で復活できる余地を残す

詳細：`journal/2026-10-05_14_Book勝敗フィードバック学習.md` / `journal/2026-10-05_15_Book実戦フィードバック学習と移転前停止.md`

## 2026-10-05 — publicリポジトリ移転・夜間スモーク

- 旧repository最終 `c5b201a...` のファイルスナップショットだけを、過去履歴なしで新public `shogi-ai` へ移転
- 旧repositoryはprivateバックアップとして保持し、新履歴はnoreplyメールで開始
- public runner 4 CPU / 4レーンの夜間経路を8局でスモークし、違法0・Book hit 66・照合不一致0を確認
- 外部対局JSONをBook取込へ誤投入しても拒否する防御を追加

詳細：`journal/2026-10-05_16_publicリポジトリ移転と夜間スモーク.md`
""" + "\n"
    p.write_text(text, encoding="utf-8", newline="\n")

# Verify the journal directory now has one unique sequence for every 2026-10-05 record.
names = sorted(p.name for p in Path("journal").glob("2026-10-05_*.md"))
prefixes = [name.split("_", 2)[1] for name in names]
if len(prefixes) != len(set(prefixes)):
    raise SystemExit(f"duplicate journal sequence remains: {names}")
if any(not prefix.isdigit() or len(prefix) != 2 for prefix in prefixes):
    raise SystemExit(f"unnumbered 2026-10-05 journal remains: {names}")
print("journal order:")
print("\n".join(names))

# This is a one-shot maintenance helper; remove it in the synchronized commit.
Path(__file__).unlink()
