# DoD チェックリスト — P2 ポートフォリオ評価

- タスク名: ポートフォリオ評価レポート刷新（snapshot / summary / dashboard 連携）
- バックログ ID / アンカー: [P2-ポートフォリオ評価レポート](../task_backlog.md#p2-portfolio-evaluation)
- 担当: <!-- operator_name -->
- チェックリスト保存先: docs/checklists/p2_portfolio_evaluation.md

## Ready 昇格チェック項目
- [ ] [docs/logic_overview.md](../logic_overview.md) と [docs/observability_dashboard.md](../observability_dashboard.md) を再読し、想定する CLI / 成果物フローが最新の設計と一致している。
- [ ] `runs/index.csv` の対象戦略行を点検し、必要な run ディレクトリまたはサンプルメトリクスが揃っている。
- [ ] [docs/task_backlog.md#p2-マルチ戦略ポートフォリオ化](../task_backlog.md#p2-マルチ戦略ポートフォリオ化) の進捗メモと DoD を確認し、未解決の前提条件が無いことを確認した。
- [ ] `reports/portfolio_summary.json` のスキーマ差分（`budget_status`, `budget_over_pct`, `correlation_window_minutes`, `drawdowns` 等）をレビューし、 downstream で参照するビューが対応済みである。

## DoD (Definition of Done)
- [ ] `runs/index.csv` から Day ORB / Tokyo Micro の最新 run 情報を記録し、`build_router_snapshot.py` の `--manifest-run` 値へ反映したメモを残した。
- [ ] ルーター snapshot を再生成する CLI 例（`python3 scripts/build_router_snapshot.py ... --correlation-window-minutes 240 --indent 2`）と成果物パス（`runs/router_pipeline/latest/telemetry.json`, `runs/router_pipeline/latest/metrics/*.json`）をドキュメントへ追記した。
- [ ] `python3 scripts/report_portfolio_summary.py --input runs/router_pipeline/latest --output reports/portfolio_summary.json --indent 2` を実行し、`budget_status` / `budget_over_pct` / `correlation_window_minutes` / `drawdowns` をレビューしたログを残した。
- [ ] `docs/logic_overview.md` と `docs/observability_dashboard.md` に最新の CLI 例・レビューすべきフィールド・成果物リンクを追記した。
- [ ] `python3 -m pytest tests/test_portfolio_monitor.py::test_build_portfolio_summary_reports_budget_status tests/test_report_portfolio_summary.py::test_build_router_snapshot_cli_uses_router_demo_metrics tests/test_report_portfolio_summary.py::test_report_portfolio_summary_cli_budget_status` を実行し、warning/breach の分岐が再現されることと、失敗時のトラブルシュート手順（サンプルメトリクス欠損・manifest 位置ズレなど）を記録した。
- [ ] `docs/task_backlog.md` の P2 セクションへ完了メモと生成日を追記し、`docs/todo_next.md` → `docs/todo_next_archive.md` への同期、および `state.md` ログ更新を完了した。
- [ ] 成果物 (`runs/router_pipeline/latest/*`, `reports/portfolio_summary.json`) とドキュメント更新を同一コミットで反映した。
- [ ] `python3 -m pytest` を実行し、テスト結果を PR / ログに記録した。
- [ ] コマンド出力・パス・検証状況を `state.md` と関連ドキュメントにエビデンスとして残した。
- [ ] P2 レビュー用のまとめ（`docs/progress_phase2.md#p2-レビューハンドオフパッケージ`）へ再現コマンドと成果物リンクを反映し、レビュワーが単独で検証できることを確認した。

## Router demo サンプル保守ログ (P2-04)

- 対象 artefact: `reports/portfolio_samples/router_demo/telemetry.json` と `reports/portfolio_samples/router_demo/metrics/*.json`（Day ORB 5m v1 / Tokyo Micro Mean Reversion v0）。
- 保持世代: 最新 1 世代を本ディレクトリに配置し、ローテーション時は旧版を PR ブランチ内で `reports/portfolio_samples/router_demo/archive/<yyyymmdd>/` へ退避して差分をレビュー可能にする。
- 最終更新: 2025-10-10 03:26 UTC（`telemetry.json`, `metrics/day_orb_5m_v1.json`, `metrics/tokyo_micro_mean_reversion_v0.json` の `stat` `Modify` タイムスタンプ）。
- リフレッシュ手順:
  1. 最新 run を参照しつつ `python3 scripts/build_router_snapshot.py --output runs/router_pipeline/latest --manifest configs/strategies/day_orb_5m.yaml --manifest configs/strategies/tokyo_micro_mean_reversion.yaml --manifest-run day_orb_5m_v1=<latest metrics path> --manifest-run tokyo_micro_mean_reversion_v0=<latest metrics path> --positions day_orb_5m_v1=1 --positions tokyo_micro_mean_reversion_v0=2 --correlation-window-minutes 240 --indent 2` でサンプルを再生成し、成果物を `reports/portfolio_samples/router_demo/` にコピーする。
  2. `python3 scripts/validate_portfolio_samples.py --samples-dir reports/portfolio_samples/router_demo --manifest configs/strategies/day_orb_5m.yaml --manifest configs/strategies/tokyo_micro_mean_reversion.yaml` を実行し、manifest 整合性・テレメトリ参照・エクイティカーブ形式を検証する。
  3. 差分をレビューした上で [docs/task_backlog.md#p2-04-portfolio-dataset-maintenance--rotation](../task_backlog.md#p2-04-portfolio-dataset-maintenance--rotation) と `state.md` へローテーション日時と検証ログを追記する。

> チェックが完了したら、このファイルを参照しつつ `docs/todo_next.md` / `docs/todo_next_archive.md` の同期とバックログ更新を忘れずに。レビュー担当者への共有時は、実行した CLI と成果物リンク（JSON / telemetry / metrics）を合わせて提示すること。
