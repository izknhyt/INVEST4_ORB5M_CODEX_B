# フェーズ1タスクアーカイブ

## P1: ローリング検証 + 健全性モニタリング（Archive）

> 2026-02-13 時点でフェーズ1タスクは全て完了し、記録目的でアーカイブに残しています。

### ~~P1-01 ローリング検証パイプライン~~ ✅ (2025-11-27 クローズ)
- `python3 scripts/run_benchmark_pipeline.py --windows 365,180,90 --disable-plot` と `python3 scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6 --benchmark-freshness-max-age-hours 6` を日次ワークフローへ組み込み、`reports/rolling/<window>/*.json` / `reports/benchmark_summary.json` を安定更新。
- `docs/benchmark_runbook.md` / `docs/logic_overview.md` / `docs/checklists/p1-01.md` へ Cron 例と閾値運用を反映し、`tests/test_run_benchmark_pipeline.py` / `tests/test_run_daily_workflow.py` で CLI 伝播を回帰テスト化。

### ~~P1-02 インシデントリプレイテンプレート~~ ✅ (2025-12-01 クローズ)
- `ops/incidents/<incident_id>/` テンプレートと `analysis/incident_review.ipynb` を整備し、`docs/state_runbook.md` / README にリプレイ手順と共有フローを明文化。
- `docs/todo_next.md` / `state.md` にアーカイブログを残し、ステークホルダーへの連絡導線を同期。

### ~~P1-03 state ヘルスチェック~~ ✅ (2024-06-11 クローズ)
- `scripts/check_state_health.py` の警告生成・履歴ローテーション・Webhook 通知を `python3 -m pytest tests/test_check_state_health.py` で回帰化し、`ops/health/state_checks.json` の運用手順を runbook へ追記。
- デフォルト閾値（勝率LCB / サンプル下限 / 滑り上限）と対応フローをドキュメントへ集約し、定期ジョブ化の準備を完了。

### ~~P1-04 価格インジェストAPI基盤整備~~ ✅ (2025-11-28 クローズ)
- `python3 scripts/run_daily_workflow.py --ingest --use-dukascopy --symbol USDJPY --mode conservative` で Dukascopy と yfinance フォールバックを統合し、`ops/runtime_snapshot.json.ingest_meta` に鮮度・経路を記録。
- `python3 scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6 --benchmark-freshness-max-age-hours 6` で ingest 鮮度を監視し、`docs/benchmark_runbook.md` / `docs/api_ingest_plan.md` / `docs/checklists/p1-04_api_ingest.md` を同期。

### ~~P1-05 バックテストランナーのデバッグ可視化強化~~ ✅ (2026-02-13 クローズ)
`core/runner.py` のデバッグ計測とログドキュメントを整理し、EV ゲート診断の調査手順を標準化する。

**DoD**
- BacktestRunner の戦略フック呼び出しをヘルパー経由で統一し、エラー時のカウントと記録が揃っていること。
- `debug_counts` / `debug_records` のフィールド構成が列挙され、ドキュメントにも一覧が掲載されていること。
- `strategy_gate` → `ev_threshold` → EV 判定 → サイズ判定の観察手順が docs に追記され、CSV/Daily 出力例と併せた調査フローが示されていること。

**進捗メモ**
- 2026-02-21: Fixed a calibration regression where `_resolve_calibration_positions` stopped updating pooled EV after the calibration window elapsed. Added regression `tests/test_runner.py::test_calibration_positions_resolve_after_period` to ensure calibration trades opened during warmup continue to settle and feed EV statistics, and reran targeted pytest for the runner suite.
- 2026-02-13: Verified the counter/record documentation against the latest runner implementation, confirmed that the CSV/daily investigation flow covers `ev_bypass` warm-up tracking, and re-ran `python3 -m pytest tests/test_runner.py tests/test_run_sim_cli.py` to lock regression coverage before closing the task.
- 2026-01-18: Logged EV warm-up bypass events as `ev_bypass` debug records (capturing `warmup_left` / `warmup_total`), refreshed regression coverage in `tests/test_runner.py`, and expanded [docs/backtest_runner_logging.md](./backtest_runner_logging.md) with the new fields.
- 2025-10-13: Added CLI regression `tests/test_run_sim_cli.py::test_run_sim_debug_records_capture_hook_failures` to lock the debug counters/records when hook exceptions are raised, and expanded the logging reference with the coverage note.
- 2025-10-08: Added helper-based dispatch and logging reference. See [docs/backtest_runner_logging.md](./backtest_runner_logging.md) for counter/record definitions and EV investigation flow.

### ~~P1-06 Fill エンジン / ブローカー仕様アライン~~ ✅ (2026-02-13 クローズ)
- `core/fill_engine.py` と RunnerConfig を拡張して `SameBarPolicy` / Brownian Bridge パラメータを制御し、manifest (`runner.runner_config.fill_*`) で調整できるよう整備。`python3 -m pytest tests/test_fill_engine.py tests/test_runner.py tests/test_run_sim_cli.py` で回帰確認。
- `docs/broker_oco_matrix.md` / `docs/benchmark_runbook.md` / `docs/progress_phase1.md` / `analysis/broker_fills_cli.py` にブローカー別挙動と再現手順を反映し、Notebook/CLI で Conservative vs Bridge 差分を可視化。

### ~~P1-07 フェーズ1 バグチェック & リファクタリング運用整備~~ ✅ (2026-01-08 クローズ)
チェックリスト/テンプレート/運用ノートを統合し、フェーズ1 バグハントの継続作業を文書ベースで引き継げる状態に整備した。

**完了記録**
- `docs/checklists/p1-07_phase1_bug_refactor.md` へ調査チェックボード・テスト手順・リファクタリング計画テンプレ・ドキュメント更新チェックを追加し、DoD セクションの項目を全て充足。
- `docs/todo_next.md` の Ready から当該タスクを除外し、[docs/todo_next_archive.md](./todo_next_archive.md) へ移動。`state.md` の `## Log` に完了メモを追記し、`## Next Task` からアンカーを取り外した。
- バックログ本節をクローズ扱いに変更し、後続作業は必要に応じて新タスク（例: P2 系列）として起票する方針。

**進捗メモ（アーカイブ）**
- 2025-10-04: `scripts/run_daily_workflow.py` のパス解決を `_resolve_path_argument` へ集約し、`--bars` / `--local-backup-csv` / 最適化 CSV 引数の重複処理を統一。`tests/test_run_daily_workflow.py::test_update_state_resolves_bars_override` を追加し、相対パス指定がリポジトリルート基準で解決されることを回帰テスト化、`python3 -m pytest` 157 件を再実行してグリーンを確認。
- 2025-12-05: チェックリスト初版 (`docs/checklists/p1-07_phase1_bug_refactor.md`) を作成し、`docs/task_backlog.md` / `docs/todo_next.md` / `docs/codex_workflow.md` / `state.md` へ参照リンクと運用メモを追記。フェーズ1 バグチェックとリファクタリングのテンプレート化を Ready 状態に引き上げた。
- 2025-12-06: UTC タイムスタンプ処理を `datetime.now(timezone.utc)` 起点へ統一し、`scripts/run_daily_workflow.py` ほかフェーズ1 ワークフロー群での `datetime.utcnow()` DeprecationWarning を解消。pytest を再実行してノイズレスなバグチェック結果を共有できる状態を確認。
- 2025-12-07: `scripts/report_benchmark_summary.py` の `utcnow_iso` 参照が `main()` 実行後に解決されず NameError になる退行を修正。ヘルパー import をモジュール冒頭へ移し、ベースライン/ローリング要約生成時の `generated_at` 設定が安定することを確認。
- 2025-12-18: `core/runner.py` のスリップ学習ロジックをヘルパーへ抽出し、`tests/test_runner.py` に学習係数の回帰テストを追加。重複コードを排除しつつ `python3 -m pytest` のグリーンを維持。
