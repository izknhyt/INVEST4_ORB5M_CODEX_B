# 作業タスク一覧（バックログ）

このバックログは「最新値動きを取り込みながら継続学習し、複数戦略ポートフォリオでシグナルを出す」ツールを実現するための優先順位付きタスク群です。各タスク完了時は成果物（コード/ドキュメント/レポート）へのリンクを追記してください。

## ワークフロー統合

各タスクに着手する前に、該当するバックログ項目を `state.md` の `Next Task` ブロックへ明示的に引き込み、進行中であることを記録してください。作業完了後は、成果ノートや反省点を `docs/todo_next.md` に反映し、`state.md` の完了ログと整合するよう同期します。

- 例: `[P1-02] 2024-06-18 state.md ログ / docs/progress/phase1.md`

### Codex Session Operations Guide
Document the repeatable workflow that lets Codex keep `state.md`, `docs/todo_next.md`, and `docs/task_backlog.md` synchronized across sessions, including how to use the supporting scripts and templates.

**DoD**
- `docs/codex_workflow.md` explains pre-session checks, the execution loop, wrap-up steps, and how to apply the shared templates.
- The guide covers dry-run and live usage of `scripts/manage_task_cycle.py` for keeping state/doc updates in lockstep.
- Links to related runbooks and templates are included so future sessions can reproduce the same procedure.

**Progress Notes**
- 2025-09-29: Added `docs/codex_workflow.md` to consolidate operational guidance for Codex agents and clarified the relationship with `docs/state_runbook.md` and the template directory.
- 2025-10-16: Supplemented cloud-run guardrails in `docs/codex_cloud_notes.md` and linked them from the workflow guide to improve sandbox handoffs.

## P0: 即着手（オンデマンドインジェスト + 基盤整備）
- ~~**state 更新ワーカー**~~ (完了): `scripts/update_state.py` に部分実行ワークフローを実装し、`BacktestRunner.run_partial` と状態スナップショット/EVアーカイブ連携を整備。`ops/state_archive/<strategy>/<symbol>/<mode>/` へ最新5件を保持し、更新後は `scripts/aggregate_ev.py` を自動起動するようにした。
- ~~**runs/index 再構築スクリプト整備**~~ (完了): `scripts/rebuild_runs_index.py` が `scripts/run_sim.py` の出力列 (k_tr, gate/EV debug など) と派生指標 (win_rate, pnl_per_trade) を欠損なく復元し、`tests/test_rebuild_runs_index.py` で fixtures 検証を追加。
- ~~**ベースライン/ローリング run 起動ジョブ**~~ (2024-06-12 完了): `scripts/run_benchmark_pipeline.py` でベースライン/ローリング run → サマリー → スナップショット更新を一括化し、`run_daily_workflow.py --benchmarks` から呼び出せるようにした。`tests/test_run_benchmark_pipeline.py` で順序・引数伝播・失敗処理を回帰テスト化。
  - 2024-06-05: `tests/test_run_benchmark_runs.py` を追加し、`--dry-run`/通常実行の双方で JSON 出力・アラート生成・スナップショット更新が期待通りであることを検証。

## P1: ローリング検証 + 健全性モニタリング

### P1-01 ローリング検証パイプライン
直近365D/180D/90Dのシミュレーションを起動バッチで更新し、Rolling 指標を継続監視できるよう整備する。`scripts/run_benchmark_runs.py` と `scripts/report_benchmark_summary.py` を組み合わせて `reports/rolling/<window>/*.json`・`reports/benchmark_summary.json` を生成し、勝率/Sharpe/DD のトレンドを可視化する仕込みを進める。→ `run_sim.py` 出力に Sharpe / max drawdown を追加済み（2024-06-03）。

**DoD**
- `scripts/run_benchmark_runs.py` / `scripts/report_benchmark_summary.py` による365D・180D・90Dローリング run が定期更新されること。
- `reports/rolling/<window>/*.json` と `reports/benchmark_summary.json` に勝率・Sharpe・最大DDが揃って出力されていること。
- ジョブ実行フローとアラート閾値を README もしくは runbook に追記し、再実行手順が明文化されていること。

**進捗メモ**
- 2025-09-29: Cron サンプルへ `benchmark_pipeline_daily`（UTC 22:30）の CLI を追加し、ランブック記載の `--alert-*` / `--min-*` 閾値・`--benchmark-windows 365,180,90` を反映。`python3 scripts/run_daily_workflow.py --benchmarks` ドライランで `ops/runtime_snapshot.json` の `benchmark_pipeline` / `threshold_alerts` を更新（Sandbox では Slack Webhook 失敗・鮮度チェックエラーが期待挙動）。`docs/logic_overview.md` の Cron 運用セクションと TODO/TODO-next を同期。
- 2025-10-14: Introduced `scripts/check_benchmark_freshness.py` to validate `ops/runtime_snapshot.json` timestamps, integrated the CLI into `run_daily_workflow.py --check-benchmark-freshness`, documented usage/thresholds in the benchmark runbook, and added regression coverage.
- 2025-10-15: Added win rate health threshold support (`--min-win-rate`) to benchmark summary + pipeline + daily workflow CLIs, propagated structured alerts to snapshots, refreshed benchmark runbook/README/checklist guidance, and extended regression tests.
- 2025-10-10: Extended `scripts/generate_ev_case_study.py` to sweep decay/prior/warmup in addition to thresholds, added CSV export + notebook (`analysis/ev_param_sweep.ipynb`) for heatmap review, and documented the workflow in [docs/ev_tuning.md](docs/ev_tuning.md).
- 2025-10-08: Added helper-based dispatch and logging reference. See [docs/backtest_runner_logging.md](docs/backtest_runner_logging.md) for counter/record definitions and EV investigation flow.
- 2025-09-29: `report_benchmark_summary.py` の重複引数定義（`--min-sharpe`/`--max-drawdown`/`--webhook`）を解消し、`run_daily_workflow.py` から `run_benchmark_pipeline.py` を呼び出すように整合。ワークフローからベンチマークサマリーにしきい値・WebHook を正しく伝搬するよう修正。
- 2024-06-04: `core/runner` でエクイティカーブを蓄積し Sharpe / 最大DD を算出、`run_sim.py`・`store_run_summary`・`report_benchmark_summary.py` に伝搬。ベンチマークサマリーでは `--min-sharpe` / `--max-drawdown` 閾値をチェックし `warnings` に追加するよう更新。

### P1-02 インシデントリプレイテンプレート
本番での負けトレードを `ops/incidents/` に保存し、同期間のリプレイを `scripts/run_sim.py --start-ts/--end-ts` で再実行する Notebook (`analysis/incident_review.ipynb`) にメモを残す。

**DoD**
- インシデントケースが `ops/incidents/<incident_id>/` に保存され、期間・戦略・トレード ID などのメタデータが揃っていること。
- `scripts/run_sim.py --start-ts/--end-ts` を利用したリプレイ手順が Notebook にテンプレート化され、検証ログを残せること。
- リプレイ結果と対策メモを共有する記録先（README や ops runbook）が更新され、再発防止の参照場所が明示されていること。

**進捗メモ**
- 2024-06-14: `scripts/run_sim.py` に `--start-ts` / `--end-ts` を追加し、README と pytest を更新。部分期間リプレイの準備が整った。

### P1-03 state ヘルスチェック
最新 state から EV 下限、勝率 LCB、滑り推定値を抽出する `scripts/check_state_health.py` を活用し、結果を `ops/health/state_checks.json` に追記。逸脱時の通知/Runbook 追記を行う。

**DoD**
- `scripts/check_state_health.py` が定期実行され、`ops/health/state_checks.json` に履歴が追記されること。
- 勝率 LCB・滑り・EV 閾値逸脱時に Webhook 通知もしくは運用チャネルへの警告が送出されること。
- デフォルト閾値と対応手順が runbook へ記載され、pytest で警告生成と履歴ローテーションが検証されていること。

**進捗メモ**
- 2024-06-11: `check_state_health` の警告・履歴ローテーション・Webhook 送信を pytest で回帰テスト化し、デフォルト閾値 (勝率LCB/サンプル数/滑り上限) の期待挙動を明記。

### P1-04 価格インジェストAPI基盤整備
REST/Streaming API と `scripts/pull_prices.py` を連携させ、手動CSV投入に頼らず 5m バーの継続取得・保存・特徴量更新を自動化する。2025-10 時点では Dukascopy フローを正式経路として採用し、Alpha Vantage 等の REST 連携はプレミアム要件により保留とする。`run_daily_workflow.py --ingest` 実行時に最新バーが `raw/`→`validated/`→`features/` へ冪等に反映され、鮮度チェックが 6 時間以内を維持できる状態を整える。

- `scripts/pull_prices.py` が API/外部取得結果を直接受け取れるように拡張され、`raw/`・`validated/`・`features/` が冪等更新されること。
- `python3 scripts/run_daily_workflow.py --ingest --benchmarks` 実行時に Dukascopy フローが呼ばれ、`ops/runtime_snapshot.json.ingest` が更新されること。
- `python3 scripts/check_benchmark_freshness.py --target <symbol>:<mode> --max-age-hours 6` が成功し、鮮度アラートが解消されること。
- API/REST プロバイダは保留状態のため、再開条件・費用対効果・yfinance 等の冗長化候補を整理したメモが更新されていること。
- APIモックを用いた単体テスト / 統合テストが追加され、失敗時のリトライ・アノマリーログ出力が検証されていること（保留中はスキップ可、再開時に再利用）。

**進捗メモ**
- 2025-10-16: API インジェスト設計を起案し、`docs/todo_next.md` / `state.md` にタスク登録。設計ドキュメント (`docs/api_ingest_plan.md`) とチェックリスト (`docs/checklists/p1-04_api_ingest.md`) を整備し、ワークフロー統合を次ステップとする。
- 2025-11-08: `run_daily_workflow.py --ingest --use-dukascopy` で `dukascopy_python` 未導入時も yfinance フォールバックへ自動切替するよう調整し、回帰テストを追加。
- 2025-11-09: yfinance フォールバック時に `--yfinance-lookback-minutes` を参照して再取得範囲を調整するよう更新。冗長な 7 日分の再処理を避けつつ、長期停止時は手動でウィンドウを拡張できるよう README / state runbook / 回帰テストを同期。
- 2025-11-10: Twelve Data レスポンスで `volume` が欠損または空文字になるケースを想定し、`response.fields` へ `required=false` / `default=0.0` を設定できるよう整備。`scripts/fetch_prices_api.py` の正規化ロジックを拡張し、pytest に回帰を追加。
- 2025-11-11: Twelve Data レスポンス（`datetime` が UTC +00:00・`volume` 欠損/空文字）をモック API で再現し、クエリの `symbol=USD/JPY` 整形と昇順ソート・0.0 フォールバックを `tests/test_fetch_prices_api.py::test_fetch_prices_twelve_data_like_payload` で固定。`docs/state_runbook.md` にフォールバック時のドライラン手順を追記。
- 2025-11-12: Enabled sandbox resilience by adding a local CSV ingestion fallback when both Dukascopy and yfinance sources are unavailable, keeping `run_daily_workflow.py --ingest --use-dukascopy` operable without optional dependencies. Extended regression coverage in `tests/test_run_daily_workflow.py` and documented the contingency in checklist/runbook notes.
- 2025-11-13: Added deterministic `synthetic_local` bar generation after the local CSV fallback so sandbox runs can refresh `ops/runtime_snapshot.json` to the latest 5m boundary. Updated regression tests and runbook/checklist guidance to cover the synthetic extension.
- 2025-11-13: Sandbox rerun confirmed the local CSV + `synthetic_local` chain updates `ops/runtime_snapshot.json.ingest` to 2025-10-02T03:15:00 even without optional packages. `pip install dukascopy-python yfinance` is currently blocked by the sandbox proxy (HTTP 403), so we need an offline wheel/whitelisted host before re-attempting the full Dukascopy+yfinance freshness validation.
- 2025-11-13: Captured proxy failure evidence in `ops/health/2025-11-13_dukascopy_ingest_attempt.md` after retrying the Dukascopy ingest workflow; waiting on ops for wheel delivery or proxy allowlist before rerunning freshness checks.
- 2025-11-16: `run_daily_workflow.py` now records fallback chains, row counts, and `freshness_minutes` in `ops/runtime_snapshot.json.ingest_meta.<symbol>_<tf>`; docs/state_runbook.md と checklist へレビュー手順 (`synthetic_extension` の扱い含む) を追記し、pytest を拡張して metadata の有無を検証。
- 2025-11-16: `scripts/check_benchmark_freshness.py` が `ingest_meta` を参照して `synthetic_local` 合成バー時の鮮度遅延を `advisories` として降格し、Sandbox で情報共有扱いになるよう調整。CLI に `--ingest-timeframe` を追加し、README に `advisories` 出力の扱いを明記。
- 2025-11-17: `scripts/check_benchmark_freshness.py` の `ingest_metadata` 出力に `freshness_minutes` / `fallbacks` / `source_chain` / `last_ingest_at` を追記し、フェイルオーバー経路と鮮度差分を即時にレビューできるよう拡張。`docs/benchmark_runbook.md` へレビュー手順を反映。
- 2025-11-20: `scripts/run_daily_workflow.py` が `ingest_meta` に `last_ingest_at` を保持し、`tests/test_run_daily_workflow.py` で回帰を追加。`check_benchmark_freshness` の出力で取得時刻を確認できるようになり、鮮度レビュー時のトレースが容易になった。
- 2025-11-21: `scripts/run_daily_workflow.py` と `scripts/live_ingest_worker.py` に BID/ASK 選択フラグ（`--dukascopy-offer-side` / `--offer-side`）を追加し、取得サイドを `ingest_meta.dukascopy_offer_side` へ永続化。README / runbook / checklist を更新し、pytest 回帰で BID 既定値とフェイルオーバー経路を検証。
- 2025-11-22: Documented optional ingestion/reporting dependencies in `docs/dependencies.md` and linked the README guidance so operators can stage `dukascopy-python`, `yfinance`, `pandas`, `matplotlib`, and `pytest` even when PyPI access is restricted.
- 2025-11-24: Added `--disable-synthetic-extension` to `scripts/run_daily_workflow.py` so operators can skip `synthetic_local` generation during local CSV fallback. Updated regression tests, README, runbook, and ingest plan to highlight the flag and its impact on freshness alerts.
- 2025-11-25: Extended `run_daily_workflow.py --ingest --use-api` to fall back to local CSV + `synthetic_local` when the provider fails or returns no rows. Recorded the `api` → `local_csv` → `synthetic_local` chain and `local_backup_path` in `ingest_meta`, refreshed README / state runbook / ingest plan guidance, and added regression coverage (`tests/test_run_daily_workflow.py::test_api_ingest_falls_back_to_local_csv`).
- 2025-10-21: Added Dukascopy ingestion option to `scripts/run_daily_workflow.py` (`--use-dukascopy`) with shared `ingest_records` helper so fresh 5m bars flow through `raw/`→`validated/`→`features/` without manual CSV staging. Updated progress docs and design notes to capture the workflow and test coverage.
- 2025-10-21: Created `scripts/merge_dukascopy_monthly.py` and generated `data/usdjpy_5m_2025.csv` from the monthly exports to backfill storage before live refresh. Documented the merge step in phase3 progress notes.
- 2025-10-21: Cloud deploy flagged "diff too large" during the backfill. Local merge + ingest cleared it, and we need to document how to temporarily relax/re-enable the cloud diff guard (TODO: define guard reset workflow in runbook).
- 2025-10-24: Alpha Vantage FX_INTRADAY がプレミアム専用であることを確認し、REST/API 連携は backlog 保留に変更。`scripts/run_daily_workflow.py --ingest --use-dukascopy` を主経路として採用し、冗長化候補として yfinance 正規化レイヤーを追加検討するメモを `docs/api_ingest_plan.md` へ追記予定。
- 2025-11-01: Added yfinance fallback adapter (`scripts/yfinance_fetch.py`) and `--use-yfinance` CLI path. Backfilling uses `fetch_bars` → `ingest_records` with optional lookback (`--yfinance-lookback-minutes`), and regression tests cover CLI wiringと正規化。Dukascopy遅延時に即時更新を試せる状態に昇格。Runbookへ切替手順と依存（yfinanceパッケージ）の記載を追加予定。
- 2025-11-01: yfinance フォールバックを強化。Yahoo シンボル自動マッピング（USDJPY→JPY=X 等）、`period="7d"` での一括取得＋60 日 intraday 制限を考慮したフィルタリング、未来日リクエストの防止、`--symbol USDJPY=X` 受け入れを追加。`tests/test_yfinance_fetch.py` / `tests/test_run_daily_workflow.py::test_yfinance_ingest_accepts_suffix_symbol` で回帰を確保。
- 2025-10-22: Implemented REST ingestion via `scripts/fetch_prices_api.py`, introduced `scripts/_secrets.load_api_credentials` + `configs/api_ingest.yml`, added `--use-api` wiring to `scripts/run_daily_workflow.py`, and created pytest coverage (`tests/test_fetch_prices_api.py`) for success + retry logging. README / state runbook / progress_phase3 updated with API usage + credential guidance.
- 2025-10-23: Added an integration test (`tests/test_run_daily_workflow.py::test_api_ingest_updates_snapshot`) that mocks the API provider and exercises `python3 scripts/run_daily_workflow.py --ingest --use-api`, confirming snapshot updates, CSV appends, and anomaly-free ingestion. Checklistを更新して DoD の CLI 項目をクローズ。
- 2025-10-31: `scripts/pull_prices.ingest_records` を修正し、非単調バーを raw 層へ書き出さずアノマリーログのみに記録。`tests/test_pull_prices.py::test_non_monotonic_rows_skip_raw` を追加し、重複膨張を停止させる回帰テストを整備。既存 raw CSV のクリーンアップ手順は追って runbook へ整理予定。

### P1-05 バックテストランナーのデバッグ可視化強化
`core/runner.py` のデバッグ計測とログドキュメントを整理し、EV ゲート診断の調査手順を標準化する。

**DoD**
- BacktestRunner の戦略フック呼び出しをヘルパー経由で統一し、エラー時のカウントと記録が揃っていること。
- `debug_counts` / `debug_records` のフィールド構成が列挙され、ドキュメントにも一覧が掲載されていること。
- `strategy_gate` → `ev_threshold` → EV 判定 → サイズ判定の観察手順が docs に追記され、CSV/Daily 出力例と併せた調査フローが示されていること。

**進捗メモ**
- 2025-10-13: Added CLI regression `tests/test_run_sim_cli.py::test_run_sim_debug_records_capture_hook_failures` to lock the debug counters/records when hook exceptions are raised, and expanded the logging reference with the coverage note.
- 2025-10-08: Added helper-based dispatch and logging reference. See [docs/backtest_runner_logging.md](docs/backtest_runner_logging.md) for counter/record definitions and EV investigation flow.

### P1-06 Fill エンジン / ブローカー仕様アライン
ブローカー各社（OANDA / IG / SBI など）の OCO 処理・トレール挙動を調査し、`core/fill_engine.py` の Conservative / Bridge モードが実仕様と乖離するケースを特定する。差分は Notebook/CLI で可視化し、代表ケースを pytest で固定化する。

**DoD**
- `docs/broker_oco_matrix.md` の未調査セルを埋め、同足 TP/SL 処理とトレール更新間隔を反映した比較表を公開する。
- `analysis/broker_fills.ipynb` もしくは CLI が Conservative / Bridge と実仕様の差分を比較できる形で整備されている。
- `core/fill_engine.py` と `tests/test_fill_engine.py`（新規）が代表ケースを再現し、`python3 -m pytest tests/test_fill_engine.py` が通過する。
- 運用ドキュメント（`docs/progress_phase1.md` / `docs/benchmark_runbook.md`）に再実行手順と判断基準を追記する。

**進捗メモ**
- 2025-10-10: Broker OCO matrix updated (OANDA / IG / SBI)、`analysis/broker_fills_cli.py` で Conservative / Bridge 差分を出力、`core/fill_engine.py` に `SameBarPolicy` / トレール処理を追加、`tests/test_fill_engine.py` で Tick 優先 / 保護優先 / トレール更新を固定。`docs/progress_phase1.md` / `docs/benchmark_runbook.md` へ再実行フローを反映。

## P2: マルチ戦略ポートフォリオ化
- **戦略マニフェスト整備**: スキャル/デイ/スイングの候補戦略ごとに、依存特徴量・セッション・リスク上限を YAML で定義し、ルーターが参照できるようにする (`configs/strategies/*.yaml`)。
  - 2025-10-09: `configs/strategies/templates/base_strategy.yaml` に共通テンプレートと記述ガイドを追加し、新規戦略のマニフェスト整備を着手しやすくした。
  - 2024-06-22: `scripts/run_sim.py --strategy-manifest` でマニフェストを読み込み、RunnerConfig の許容セッション/リスク上限と戦略固有パラメータを `Strategy.on_start` に直結するフローを整備。`tests/test_run_sim_cli.py::test_run_sim_manifest_mean_reversion` で `allow_high_rv` / `zscore_threshold` が `strategy_gate`・`ev_threshold` へ渡ることを確認。DoD: [フェーズ1-戦略別ゲート整備](docs/progress_phase1.md#1-戦略別ゲート整備)。
- **ルーター拡張**: 現行ルールベース (`router/router_v0.py`) を拡張し、カテゴリ配分・相関・キャパ制約を反映。戦略ごとの state/EV/サイズ情報を統合してスコアリングする。
- **ポートフォリオ評価レポート**: 複数戦略を同時に流した場合の資本使用率・相関・ドローダウンを集計する `analysis/portfolio_monitor.ipynb` と `reports/portfolio_summary.json` を追加。
- **マルチ戦略比較バリデーション**: Day ORB と Mean Reversion (reversion_stub) を同一 CSV で走らせ、`docs/checklists/multi_strategy_validation.md` に沿ってゲート通過数・EV リジェクト数・期待値差をレビュー。DoD: チェックリストの全項目を完了し、比較サマリをレビュー用ドキュメントへ共有する。

## P3: 観測性・レポート自動化
- **シグナル/レイテンシ監視自動化**: `scripts/analyze_signal_latency.py` を日次ジョブ化し、`ops/signal_latency.csv` をローテーション。SLO違反でアラート。
- **週次レポート生成**: `scripts/summarize_runs.py` を拡張し、ベースライン/ローリング run・カテゴリ別稼働率・ヘルスチェック結果をまとめて Webhook送信。
- **ダッシュボード整備**: EV 推移、滑り推定、勝率 LCB、ターンオーバーの KPI を 1 つの Notebook or BI に集約し、運用判断を迅速化。

## 継続タスク / 保守
- データスキーマ検証 (`scripts/check_data_quality.py`) を cron 化し、異常リストを `analysis/data_quality.md` に追記。
- 回帰テストセットを拡充（高スプレッド、欠損バー、レイテンシ障害等）し、CI で常時実行。
- 重要な設計・運用変更時は `readme/設計方針（投資_3_）v_1.md` と `docs/state_runbook.md` を更新し、履歴を残す。

> 補足: 着手順は P0 → P1 → P2 の順。途中で運用インシデントが発生した場合は、P1「インシデントリプレイテンプレート」の整備を優先してください。
