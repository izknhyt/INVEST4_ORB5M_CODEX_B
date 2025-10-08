# DoD チェックリスト — P2 ルーター拡張

- タスク名: ルーター拡張 (カテゴリ配分・相関・キャパ/執行ガード)
- バックログ ID / アンカー: [P2-ルーター拡張](../task_backlog.md#p2-マルチ戦略ポートフォリオ化)
- 担当: <!-- operator_name -->
- チェックリスト保存先: docs/checklists/p2_router.md

## Ready 昇格チェック項目
- [x] 高レベルのビジョンガイド（例: [docs/logic_overview.md](../logic_overview.md), [docs/simulation_plan.md](../simulation_plan.md)）を再読し、タスク方針が整合している。
- [x] ルーター設計ノート [docs/router_architecture.md](../router_architecture.md) を精読し、v0/v1/v2 の責務とデータフローを共有理解として整理した。
- [x] 対象フェーズの進捗ノート（例: `docs/progress_phase*.md`）を確認し、前提条件や未解決の検証ギャップがない。
- [x] 関連ランブック（例: [docs/state_runbook.md](../state_runbook.md)）を再読し、必要なオペレーション手順が揃っている。
- [x] バックログ該当項目の DoD を最新化し、関係者へ共有済みである。

- [x] カテゴリ別利用率と上限（category utilisation / caps）を manifest リスク情報とポートフォリオテレメトリから算出し、`PortfolioState` へ反映した。
- [x] コリレーションキャップおよびグロスエクスポージャー上限を取り込み、`router_v1` が期待するフィールド（`strategy_correlations`, `gross_exposure_pct`, `gross_exposure_cap_pct`）を欠損なく提供した。
- [x] 相関メタデータ（`correlation_meta`）にペアの manifest ID・カテゴリ・予算バケットを保持し、同一バケット超過をハード失格、異なるバケット超過をスコア減点に振り分けるロジックをテストで証明した。`telemetry.json` とポートフォリオサマリーの相関ヒートマップに `bucket_category` / `bucket_budget_pct` が出力され、オフラインレビューでもバケット差分を追跡できることを確認した。
- [x] カテゴリ/グロスヘッドルームとカテゴリ予算 (`category_budget_pct` / `category_budget_headroom_pct`) を `PortfolioState` へ保持し、manifest `governance.category_budget_pct` や CSV から供給された値が残ること、テレメトリ起点の headroom がある場合でも再計算で失われないことを確認した上で `router_v1.select_candidates` のスコアリングと理由ログに反映した。
- [x] BacktestRunner のランタイム指標から実行ヘルス（`reject_rate` / `slippage_bps` / `fill_latency_ms` など数値項目）を集計し、`_check_execution_health` の段階的なボーナス/ペナルティ、ペナルティマップ（`ExecutionHealthStatus.penalties`）、理由ログ（値・ガード・マージン・比率・スコア差分）が `select_candidates` へ反映されることを確認した。
- [x] v2 拡張で参照する予算・相関・ヘルス項目を [docs/router_architecture.md](../router_architecture.md) の計画に沿って記録し、必要なテレメトリ項目を `PortfolioState` 経由で公開した。
- [x] ルーターサマリー出力前に `scripts/build_router_snapshot.py` で最新 run を `runs/router_pipeline/latest` へ集約した（`--manifest-run` で対象 run を明示、または `runs/index.csv` の `manifest_id` 列から自動検出）。`--category-budget-csv` / `--category-budget` / `--correlation-window-minutes` などの CLI 上書きがある場合でも、新しいテレメトリフィールドが `telemetry.json` に保持され、カテゴリ予算の出所が理由ログに反映されることを確認した。
- [x] 受け入れテスト（`python3 -m pytest tests/test_router_v1.py tests/test_router_pipeline.py`）を実行し、カテゴリ配分／カテゴリ予算ペナルティ／相関ガード／執行ヘルスが期待通りに機能することを証明した。

## 成果物とログ更新
- [x] `state.md` の `## Log` へ完了サマリを追記した。
- [x] [docs/todo_next_archive.md](../todo_next_archive.md) の該当エントリへ移し、`docs/todo_next.md` 側からは削除した。
- [x] 関連コード/レポート/Notebook のパスを記録した。
- [ ] レビュー/承認者を記録した。

> Ready 昇格チェックと固有 DoD を満たしたら、`docs/todo_next.md` から本チェックリストへリンクし、完了後はアーカイブ ([docs/todo_next_archive.md](../todo_next_archive.md)) へ移して同期してください。
