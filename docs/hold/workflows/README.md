# HOLD Workflow

ここにあるYAMLは、Book / Experienceの方針が未確定のため一時凍結した旧GitHub Actions workflowである。

- GitHub Actionsの実行対象ではない。
- 新しいほど正しいとはみなさない。
- H10の議論結果に合わせて、必要な機能だけを再設計して `.github/workflows/` へ戻す。
- 旧NightlyのscheduleおよびBook自動main更新は、ここへ退避したことで停止している。
- 個々のYAMLは「再利用すべき設計」ではなく「以前どう実装されていたか」の証拠として保存する。

保留中:
- `book-challenger-validation.yml`
- `book-feedback-ci.yml`
- `book-feedback-smoke-candidate.yml`
- `book-reweight-bootstrap.yml`
- `experience-cache-benchmark.yml`
- `experience-cache-match.yml`
- `experience-cache-persistence.yml`
- `nightly-book-learning.yml`
- `nightly-research.yml`
- `self-opening-book-ci.yml`
- `self-play-1000-book-refresh.yml`
- `self-play-2000-book-refresh.yml`
- `verify-nightly-book-effect.yml`
- `external-engine-benchmark-legacy.yml` — 旧Full-engineモードを含む版。現役版はCoreのみ。
