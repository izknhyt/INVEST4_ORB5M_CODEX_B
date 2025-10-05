# DoD チェックリスト — P2 ルーター拡張

- タスク名: ルーター拡張 (カテゴリ配分・相関・キャパ/執行ガード)
- バックログ ID / アンカー: [P2-ルーター拡張](../task_backlog.md#p2-マルチ戦略ポートフォリオ化)
- 担当: <!-- operator_name -->
- チェックリスト保存先: docs/checklists/p2_router.md

## Ready 昇格チェック項目
- [ ] 高レベルのビジョンガイド（例: [docs/logic_overview.md](../logic_overview.md), [docs/simulation_plan.md](../simulation_plan.md)）を再読し、タスク方針が整合している。
- [ ] ルーター設計ノート [docs/router_architecture.md](../router_architecture.md) を精読し、v0/v1/v2 の責務とデータフローを共有理解として整理した。
- [ ] 対象フェーズの進捗ノート（例: `docs/progress_phase*.md`）を確認し、前提条件や未解決の検証ギャップがない。
- [ ] 関連ランブック（例: [docs/state_runbook.md](../state_runbook.md)）を再読し、必要なオペレーション手順が揃っている。
- [ ] バックログ該当項目の DoD を最新化し、関係者へ共有済みである。

## バックログ固有の DoD
- [ ] カテゴリ別利用率と上限（category utilisation / caps）を manifest リスク情報とポートフォリオテレメトリから算出し、`PortfolioState` へ反映した。
- [ ] コリレーションキャップおよびグロスエクスポージャー上限を取り込み、`router_v1` が期待するフィールド（`strategy_correlations`, `gross_exposure_pct`, `gross_exposure_cap_pct`）を欠損なく提供した。
- [ ] カテゴリ/グロスヘッドルームを `PortfolioState` へ保持し、`router_v1.select_candidates` のスコアリングと理由ログに反映した。
- [ ] BacktestRunner のランタイム指標から実行ヘルス（`reject_rate`, `slippage_bps`）を集計し、ルーター判定で利用できることを確認した。
- [ ] v2 拡張で参照する予算・相関・ヘルス項目を [docs/router_architecture.md](../router_architecture.md) の計画に沿って記録し、必要なテレメトリ項目を `PortfolioState` 経由で公開した。
- [ ] ルーターサマリー出力前に `scripts/build_router_snapshot.py` で最新 run を `runs/router_pipeline/latest` へ集約した（`--manifest-run` で対象 run を明示、または `runs/index.csv` の `manifest_id` 列から自動検出）。
- [ ] 受け入れテスト（`python3 -m pytest tests/test_router_v1.py tests/test_router_pipeline.py`）を実行し、カテゴリ配分／相関ガード／執行ヘルスが期待通りに機能することを証明した。

## 成果物とログ更新
- [ ] `state.md` の `## Log` へ完了サマリを追記した。
- [ ] [docs/todo_next.md](../todo_next.md) の該当エントリを Archive へ移動した。
- [ ] 関連コード/レポート/Notebook のパスを記録した。
- [ ] レビュー/承認者を記録した。

> Ready 昇格チェックと固有 DoD を満たしたら、`docs/todo_next.md` から本チェックリストへリンクし、進捗を同期してください。
