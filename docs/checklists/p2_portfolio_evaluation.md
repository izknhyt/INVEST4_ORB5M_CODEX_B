# DoD チェックリスト — P2 ポートフォリオ評価

- タスク名: ポートフォリオ評価レポート刷新（snapshot / summary / dashboard 連携）
- バックログ ID / アンカー: [P2-ポートフォリオ評価レポート](../task_backlog.md#p2-portfolio-evaluation)
- 担当: <!-- operator_name -->
- チェックリスト保存先: docs/checklists/p2_portfolio_evaluation.md

## Ready 昇格チェック項目
- [ ] [docs/logic_overview.md](../logic_overview.md) と [docs/observability_dashboard.md](../observability_dashboard.md) を再読し、想定する CLI / 成果物フローが最新の設計と一致している。
- [ ] `runs/index.csv`（クリーンアップ後はヘッダーのみ）を確認し、必要な run ディレクトリを再生成するコマンドまたはサンプルメトリクスの所在を把握した。
- [ ] [docs/task_backlog.md#p2-マルチ戦略ポートフォリオ化](../task_backlog.md#p2-マルチ戦略ポートフォリオ化) の進捗メモと DoD を確認し、未解決の前提条件が無いことを確認した。
- [ ] `reports/portfolio_summary.json` のスキーマ差分（`budget_status`, `budget_over_pct`, `correlation_window_minutes`, `drawdowns` 等）をレビューし、 downstream で参照するビューが対応済みである。

## DoD (Definition of Done)
- [ ] `runs/index.csv`（必要なら再生成した run を追記）から Day ORB / Tokyo Micro の最新 run 情報を記録し、`build_router_snapshot.py` の `--manifest-run` 値へ反映したメモを残した。
- [ ] ルーター snapshot を再生成する CLI 例（`python3 scripts/build_router_snapshot.py ... --correlation-window-minutes 240 --indent 2`）と成果物パス（例: `<output_dir>/telemetry.json`, `<output_dir>/metrics/*.json`）をドキュメントへ追記した。
- [ ] `python3 scripts/report_portfolio_summary.py --input runs/router_pipeline/latest --output reports/portfolio_summary.json --indent 2` を実行し、`budget_status` / `budget_over_pct` / `correlation_window_minutes` / `drawdowns` をレビューしたログを残した。
- [ ] `docs/logic_overview.md` と `docs/observability_dashboard.md` に最新の CLI 例・レビューすべきフィールド・成果物リンクを追記した。
- [ ] 予算 warning/breach 回帰テストを実行し、分岐の再現ログと検証メモを残した。
  - `python3 -m pytest tests/test_portfolio_monitor.py::test_build_portfolio_summary_reports_budget_status tests/test_report_portfolio_summary.py::test_build_router_snapshot_cli_uses_router_demo_metrics tests/test_report_portfolio_summary.py::test_report_portfolio_summary_cli_budget_status`
  - `python3 -m pytest tests/test_report_portfolio_summary.py::test_build_router_snapshot_cli_uses_router_demo_metrics`
  - 再現できない場合のトラブルシュート:
    - サンプルメトリクス（`reports/portfolio_samples/router_demo/metrics/*.json`）と `configs/strategies/*.yaml` の manifest 名称が pytest で参照するキーと一致しているかを突き合わせる。
    - 生成した `<output_dir>/telemetry.json` を開き、`budget_status` / `budget_over_pct` / `headroom` の値が Day ORB / Tokyo Micro それぞれ期待する warning/breach 状態になっているか確認する。
    - CLI で再生成した `<output_dir>/metrics/*.json` とテストフィクスチャが指すパスに差分が無いか `git status` や `python3 scripts/report_portfolio_summary.py --input <output_dir> --indent 2` の出力で検証する。
    - `python3 scripts/build_router_snapshot.py --output <output_dir> --manifest configs/strategies/day_orb_5m.yaml --manifest configs/strategies/tokyo_micro_mean_reversion.yaml --manifest-run day_orb_5m_v1=<最新 metrics パス> --manifest-run tokyo_micro_mean_reversion_v0=<最新 metrics パス> --positions day_orb_5m_v1=1 --positions tokyo_micro_mean_reversion_v0=2 --correlation-window-minutes 240 --indent 2` を再実行し、`<output_dir>/telemetry.json` の更新時刻と JSON 内容が pytest 実行時刻と揃っているかを確認する。
- [ ] `docs/task_backlog.md` の P2 セクションへ完了メモと生成日を追記し、`docs/todo_next.md` → `docs/todo_next_archive.md` への同期、および `state.md` ログ更新を完了した。
- [ ] 成果物（例: `<output_dir>/*`, `reports/portfolio_summary.json`）とドキュメント更新を同一コミットで反映した。
- [ ] `python3 -m pytest` を実行し、テスト結果を PR / ログに記録した。
- [ ] コマンド出力・パス・検証状況を `state.md` と関連ドキュメントにエビデンスとして残した。
- [ ] P2 レビュー用のまとめ（`docs/progress_phase2.md#p2-レビューハンドオフパッケージ`）へ再現コマンドと成果物リンクを反映し、レビュワーが単独で検証できることを確認した。
- [ ] 回帰スイート完了後、生成した `<output_dir>/*` や `reports/portfolio_summary.json`、pytest ログなどの成果物リンクをレビュワーへ共有し、共有先と日時を記録した。

## Router demo サンプル保守ログ (P2-04)

- 対象 artefact: `reports/portfolio_samples/router_demo/telemetry.json` と `reports/portfolio_samples/router_demo/metrics/*.json`（Day ORB 5m v1 / Tokyo Micro Mean Reversion v0）。
- 保持世代: 最新 1 世代を本ディレクトリに配置し、ローテーション時は旧版を PR ブランチ内で `reports/portfolio_samples/router_demo/archive/<yyyymmdd>/` へ退避して差分をレビュー可能にする。
- 最終更新: 2025-10-10 03:26 UTC（`telemetry.json`, `metrics/day_orb_5m_v1.json`, `metrics/tokyo_micro_mean_reversion_v0.json` の `stat` `Modify` タイムスタンプ）。
- リフレッシュ手順:
  1. 最新 run を参照しつつ `python3 scripts/build_router_snapshot.py --output runs/router_pipeline/latest --manifest configs/strategies/day_orb_5m.yaml --manifest configs/strategies/tokyo_micro_mean_reversion.yaml --manifest-run day_orb_5m_v1=<latest metrics path> --manifest-run tokyo_micro_mean_reversion_v0=<latest metrics path> --positions day_orb_5m_v1=1 --positions tokyo_micro_mean_reversion_v0=2 --correlation-window-minutes 240 --indent 2` でサンプルを再生成し、成果物を `reports/portfolio_samples/router_demo/` にコピーする。
  2. `python3 scripts/validate_portfolio_samples.py --samples-dir reports/portfolio_samples/router_demo --manifest configs/strategies/day_orb_5m.yaml --manifest configs/strategies/tokyo_micro_mean_reversion.yaml` を実行し、manifest 整合性・テレメトリ参照・エクイティカーブ形式を検証する。
  3. 差分をレビューした上で [docs/task_backlog.md#p2-04-portfolio-dataset-maintenance--rotation](../task_backlog.md#p2-04-portfolio-dataset-maintenance--rotation) と `state.md` へローテーション日時と検証ログを追記する。
  4. 整合性検証ログと共有メモは [docs/todo_next_archive.md#portfolio-dataset-maintenance--rotation](../todo_next_archive.md#portfolio-dataset-maintenance--rotation) と [`state.md` 2026-06-20 エントリ](../../state.md) から辿れるように維持する。

> チェックが完了したら、このファイルを参照しつつ `docs/todo_next.md` / `docs/todo_next_archive.md` の同期とバックログ更新を忘れずに。レビュー担当者への共有時は、実行した CLI と成果物リンク（JSON / telemetry / metrics）を合わせて提示すること。
