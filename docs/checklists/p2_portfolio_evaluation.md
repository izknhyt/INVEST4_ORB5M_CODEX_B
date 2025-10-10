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
- [ ] `docs/task_backlog.md` の P2 セクションへ完了メモと生成日を追記し、`docs/todo_next.md` → `docs/todo_next_archive.md` への同期、および `state.md` ログ更新を完了した。
- [ ] 成果物 (`runs/router_pipeline/latest/*`, `reports/portfolio_summary.json`) とドキュメント更新を同一コミットで反映した。
- [ ] `python3 -m pytest` を実行し、テスト結果を PR / ログに記録した。
- [ ] コマンド出力・パス・検証状況を `state.md` と関連ドキュメントにエビデンスとして残した。

> チェックが完了したら、このファイルを参照しつつ `docs/todo_next.md` / `docs/todo_next_archive.md` の同期とバックログ更新を忘れずに。レビュー担当者への共有時は、実行した CLI と成果物リンク（JSON / telemetry / metrics）を合わせて提示すること。
