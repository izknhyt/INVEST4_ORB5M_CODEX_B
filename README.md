# 投資3 — 5分足 ORB v1（Paper-ready雛形）
設計ソース: キャンバス「第一目標・詳細設計書（5分足 ORB v1）— 投資3」 v1.1

## 概要
- 戦術: 5m Opening Range Breakout（OCO/任意トレール）
- EVゲート: OCO=Beta-Binomial（勝率LCB）/ トレール=t下側分位。Day ORB manifest はシンプル運用継続のため `ev_mode=off` / `runner.runner_config.threshold_lcb_pip=-10.0` で EV ゲートを無効化しており、再有効化時は `RunnerConfig.threshold_lcb_pip` や manifest の `runner.runner_config.threshold_lcb_pip` を適切な値（例: 0.5 pip 付近）へ戻す。
- Fill二系統: Conservative / Bridge（Brownian Bridge近似のフック）
- サイズ: 分数ケリー(0.25×) + ガード（`risk_per_trade_pct=0.25%`, `max_daily_dd_pct=5%`, クールダウン。値は `configs/strategies/day_orb_5m.yaml` マニフェスト基準で管理され、閾値を変更した際は README も更新する）
- 想定環境: 個人開発者が単一PCで実行する前提。社内アーティファクトサーバや大規模配布は不要で、必要な依存はローカル環境で `pip install` すればよい。

## ドキュメントハブ
- [docs/documentation_portal.md](docs/documentation_portal.md) — すべてのランブック/テンプレートへの入り口。役割と参照タイミングを一覧できます。
- [docs/codex_quickstart.md](docs/codex_quickstart.md) — 1 セッション分のチェックリスト。Portal で位置関係を把握したあとに手順通り進めてください。
- [docs/codex_workflow.md](docs/codex_workflow.md) — クイックスタートの背景説明とテンプレ/スクリプトの詳細。疑問点が出た際のリファレンスです。
- [docs/data_quality_ops.md](docs/data_quality_ops.md) — `data_quality_failure` Webhook のレビュー/エスカレーション手順。対応ログの付け方と再検証コマンドをまとめています。
- [docs/observability_dashboard.md](docs/observability_dashboard.md) — フェーズ3観測性オートメーションのクイックスタート（`run_daily_workflow.py --observability` / `scripts/verify_observability_job.py`）とダッシュボード更新手順をまとめています。
- `state.md` / [docs/todo_next.md](docs/todo_next.md) / [docs/task_backlog.md](docs/task_backlog.md) — 進捗と優先度の同期ポイント。Portal とクイックスタートの指示に従い常にアンカーを揃えます。
- [docs/logic_overview.md](docs/logic_overview.md) / [docs/simulation_plan.md](docs/simulation_plan.md) / [docs/development_roadmap.md](docs/development_roadmap.md) — アーキテクチャと評価方針の背景資料。

### Orientation Flow
**初回参加時**
1. [docs/documentation_portal.md](docs/documentation_portal.md) の Orientation Cheat Sheet で各ドキュメントの役割と入口を把握する。
2. [docs/dependencies.md](docs/dependencies.md) を確認し、必要な Python 環境と追加依存をインストールする。
3. [docs/codex_quickstart.md](docs/codex_quickstart.md) を一読し、`state.md` / `docs/task_backlog.md` / `docs/todo_next.md` の同期ルールを理解する。

**各セッション冒頭**
1. クイックスタート `1. セッション前チェック` に沿って `state.md` → [docs/task_backlog.md](docs/task_backlog.md) → [docs/todo_next.md](docs/todo_next.md) の順でアンカー整合を確認する。
2. 追加の手順や判断理由が必要になったら [docs/codex_workflow.md](docs/codex_workflow.md) の該当セクションで詳細を参照する。
3. 影響範囲が広い変更では [docs/documentation_portal.md](docs/documentation_portal.md) の各カテゴリから該当ランブック / テンプレートを開き、DoD と再現手順を揃えてから作業に入る。

## Developer Quickstart
1. Python 3.10+ 環境を準備する。初回セットアップでは `pip install pytest` を実行してテストスイートを動かせる状態にし、チャート生成や表計算が必要になった場合は `pip install pandas matplotlib` を追加する。その他の任意依存と推奨インストール順は [docs/dependencies.md](docs/dependencies.md) を参照し、必要なコマンド（例: ダカスコピー連携時の `pip install dukascopy-python`）を適宜実行する。
2. `python3 -m pytest` を実行してベースラインのテストがグリーンであることを確認。
3. `state.md` / `docs/todo_next.md` / `docs/task_backlog.md` のアンカーを揃え、作業ログとドキュメント更新を同じコミットで行う。
4. 実装後は使用したテストコマンドと生成物を `state.md` ログおよび PR 説明に記録する。
   - Day ORB パラメータレビューでは `python3 -m pytest tests/test_generate_experiment_report.py tests/test_propose_param_update.py` を追加で実行し、[詳細設計 §4.6](docs/day_orb_optimization_detailed_design.md#46-reporting--approvals-scriptsgenerate_experiment_reportpy-scriptspropose_param_updatepy) の承認フローに沿ってテンプレート生成を確認する。

## Codex セッションワークフロー
1. **準備** — `state.md` / [docs/todo_next.md](docs/todo_next.md) のアンカーを一致させ、[docs/task_backlog.md](docs/task_backlog.md) で DoD を再確認。必要に応じて `python3 scripts/manage_task_cycle.py --dry-run start-task --anchor <...>` で昇格フローをプレビュー。
2. **実装ループ** — 差分を小さく保ち、影響範囲ごとにテスト（例: `python3 -m pytest tests/test_run_sim_cli.py`）を実行。仕様変更と同じコミットで [docs/codex_quickstart.md](docs/codex_quickstart.md) / [docs/codex_workflow.md](docs/codex_workflow.md) / ランブックを更新。
3. **Wrap-up** — `python3 scripts/manage_task_cycle.py --dry-run finish-task --anchor <...>` で close-out をプレビューし、`docs/todo_next.md` → [docs/todo_next_archive.md](docs/todo_next_archive.md) 移動と `state.md` ログ更新を同じコミットで実施。

詳細なチェックリストは [docs/codex_quickstart.md](docs/codex_quickstart.md)、補足ガイドは [docs/codex_workflow.md](docs/codex_workflow.md) を参照。中期計画は [docs/development_roadmap.md](docs/development_roadmap.md)、DoD と進捗根拠は `docs/checklists/` と backlog に集約しています。

## 実装スナップショット
### 戦略スケルトン
- 戦略 `day_orb_5m` は OR 計算 → ブレイク検出 → EV ゲート → 分数ケリーで `qty` 決定までを実装。
- EV ゲートは `core.ev_gate.BetaBinomialEV` を参照（`ctx['ev_oco']` にインスタンスを渡す）。
- サイズ計算は `core.sizing`（`ctx['equity']`, `ctx['pip_value']`, `ctx['sizing_cfg']` が必要）。
- ルーティング候補のスコアリング/選定は `router/router_v1.py` の `select_candidates` を基盤にしたパイプラインで実行し、セッション/スプレッド/ポートフォリオ制約/相関評価を段階的に行う。
- 戦略ローカルでの簡易ゲートやウォームアップ抑制には `router/router_v0.py` のような軽量チェック（セッション・スプレッド帯域など）を利用。
- 注文は OCO パラメータ（`tp_pips/sl_pips/trail_pips`）を `OrderIntent.oco` に格納。

### バックテストランナー
```python
from core.runner import BacktestRunner

runner = BacktestRunner(equity=100_000.0, symbol="USDJPY")
metrics = runner.run(bars, mode="conservative")  # barsはOHLC5mのリスト
print(metrics.as_dict())
```
備考: スプレッド帯域・RV帯域・セッション判定は簡易版（プレースホルダ）。実データに合わせて更新してください。

### CLI 概要
- `scripts/run_sim.py`: CSV から実行し、JSON メトリクスを出力する最小 CLI。`timestamp` / `o` / `h` / `l` / `c` はカノニカル列として解釈され、`time` / `sym` などのエイリアスにも対応します。ヘッダが無い場合でもカノニカル順 (`timestamp,symbol,tf,o,h,l,c,v,spread`) が揃っていればフォールバックして読込可能です。`symbol` / `tf` を含まない場合はマニフェスト既定値で補完され、`v` と `spread` が空欄または欠損の場合は 0.0 として取り込み行はスキップされません。
- `scripts/manage_task_cycle.py`: `state.md` / `docs/todo_next.md` / backlog を同期する運用ヘルパー。

## CLI リファレンス
### `scripts/run_sim.py`
代表的な利用例:
```bash
python3 scripts/run_sim.py \
  --manifest configs/strategies/day_orb_5m.yaml \
  --csv validated/USDJPY/5m.csv \
  --json-out runs/quick_metrics.json

python3 scripts/run_sim.py \
  --manifest configs/strategies/day_orb_5m.yaml \
  --csv USDJPY_202501_5min.csv \
  --json-out runs/quick_metrics_basic.json

python3 scripts/run_sim.py \
  --manifest path/to/multi_instrument_manifest.yaml \
  --csv validated/EURUSD/15m.csv \
  --symbol EURUSD \
  --mode bridge \
  --json-out runs/eurusd_bridge_metrics.json

python3 scripts/run_sim.py \
  --manifest configs/strategies/day_orb_5m.yaml \
  --csv validated/USDJPY/5m.csv \
  --start-ts 2024-01-01T00:00:00Z \
  --end-ts 2024-03-01T00:00:00Z \
  --json-out runs/window_metrics.json
```
- 相対パスで指定した `--json-out runs/<name>.json` は、カレントディレクトリに関わらずリポジトリ直下の `runs/` フォルダに保存されます。
- `--out-dir <base_dir>` を指定すると `<base_dir>/<symbol>_<mode>_<timestamp>/` 以下に `params.json` / `metrics.json` / `records.csv` / `daily.csv`（存在する場合）/ `state.json` がまとめて保存され、`metrics.json` の `run_dir` からパスを辿れます。
- EV プロファイルを無効化した比較を行う場合は、`configs/strategies/mean_reversion_no_ev.yaml` のように `runner.cli_args.use_ev_profile: false` を設定した manifest を利用してください。

**トラブルシュート**
- `{"error":"csv_format","code":"missing_required_columns"}`: CSV ヘッダを確認し、最低でも `timestamp,open/high/low/close` を揃える。
- `{"error":"no_bars"}`: 期間とシンボルを再確認する。
- CSV ローダーが行をスキップした場合は `stderr` に `[run_sim] Skipped ...` の警告が出力され、`metrics.debug.csv_loader` に統計が記録される。厳格に扱いたい場合は `--strict` を併用すると `CSVFormatError` が送出される。
- 複数の `strategy.instruments` を含む manifest では `--symbol`（必要に応じて `--mode`）で対象を選択し、指定に合致しない場合は `{"error":"instrument_not_found"}` が返る。

### `scripts/analyze_signal_latency.py`
通知フローの SLO をモニタリングする場合に利用します。
```bash
python3 scripts/analyze_signal_latency.py \
  --input ops/signal_latency.csv \
  --rollup-output ops/signal_latency_rollup.csv \
  --heartbeat-file ops/latency_job_heartbeat.json \
  --alert-config configs/observability/latency_alert.yaml \
  --archive-dir ops/signal_latency_archive \
  --archive-manifest ops/signal_latency_archive/manifest.jsonl \
  --json-out reports/signal_latency_summary.json
```
- `--rollup-output`: 1時間単位のロールアップを CSV へ書き込みます。既存ファイルがあればマージされ、`--rollup-retention-days` で保持期間を制御できます。
- `--heartbeat-file`: 直近のジョブ成否・違反ステータスを JSON で保存します。`pending_alerts` と `breach_streak` が SLO 逸脱状況を示します。
- `--alert-config`: `slo_p95_ms` や `warning_threshold` を定義する YAML。CLI フラグで上書きすることも可能です。
- `--archive-dir` / `--archive-manifest`: 10MB 超の RAW CSV を gzip 化して退避し、manifest に `job_id` / `sha256` / `row_count` を追記します。
- `--json-out`: stdout のサマリーをファイルへ保存します（`samples_analyzed` / `latest_p95_ms` / `breach_count` など）。Webhook テスト時は `--dry-run-alert` を併用すると `out/latency_alerts/<job_id>.json` にペイロードが出力されます。

### `scripts/check_data_quality.py`
5m CSV のギャップや重複を集計し、JSON/CSV でサマリーを取得できます。

```bash
python3 scripts/check_data_quality.py \
  --csv validated/USDJPY/5m_with_header.csv \
  --out-json reports/data_quality/usdjpy_5m_summary.json \
  --max-gap-report 10

# 推奨: 運用と同じガードを再現する場合
python3 scripts/check_data_quality.py \
  --csv validated/USDJPY/5m_with_header.csv \
  --symbol USDJPY \
  --out-json reports/data_quality/usdjpy_5m_summary.json \
  --calendar-day-summary \
  --calendar-day-coverage-threshold 0.98 \
  --fail-under-coverage 0.995 \
  --fail-on-calendar-day-warnings \
  --fail-on-duplicate-groups 5 \
  --fail-on-duplicate-occurrences 3

python3 scripts/check_data_quality.py \
  --csv validated/USDJPY/5m_with_header.csv \
  --symbol USDJPY \
  --out-gap-csv reports/data_quality/usdjpy_5m_gaps.csv \
  --out-gap-json reports/data_quality/usdjpy_5m_gaps.json \
  --min-gap-minutes 15

`scripts/run_daily_workflow.py --check-data-quality` also prefers `validated/<SYMBOL>/5m_with_header.csv` and only falls back to the legacy headerless snapshot if needed. The audit CLI automatically detects headerless files, so coverage checks continue to run even when the fallback is used, but the headered snapshot remains the recommended source for manual investigations.
```

- デフォルトのサマリーには `missing_rows_estimate` / `total_gap_minutes` / `average_gap_minutes` / `gap_details`（上位ギャップの詳細）を含みます。
- `--max-gap-report` でサマリー内に保持するギャップ件数を制御しつつ、`--out-gap-csv` や `--out-gap-json` を指定すればフィルタ適用後のギャップ表を CSV/JSON へエクスポートできます。
- 重複タイムスタンプの監査には `--out-duplicates-csv` や `--out-duplicates-json` を用いて重複行一覧を保存し、`--max-duplicate-report` でサマリーに保持する重複グループ数を調整できます（既定 20 件）。CSV には発生行番号も記録されるため、元データの修正ポイントを特定しやすくなります。サマリー出力は発生回数の多いタイムスタンプから優先表示され、`duplicate_max_occurrences` / `duplicate_first_timestamp` / `duplicate_last_timestamp` / `duplicate_timestamp_span_minutes` の追加メトリクスで重複の分布を把握できます。軽微な重複を除外したい場合は `--min-duplicate-occurrences` でグループの発生回数しきい値を設定でき、集計結果には除外件数 (`ignored_duplicate_groups` / `ignored_duplicate_rows`) が記録されます。重大な重複を機械的にブロックしたい場合は `--fail-on-duplicate-occurrences` を併用し、許容上限を超える発生回数を検知したら終了コード 1 で失敗させられます。
- `--min-gap-minutes` を指定すると、指定値より短いギャップは集計・エクスポートの対象から除外され、代わりに `ignored_gap_count` / `ignored_gap_minutes` / `ignored_missing_rows_estimate` がサマリーに記録されます。
- `--expected-interval-minutes` で期待タイムフレームを明示すると、5m 以外のバーやカスタム期待値に合わせて欠損推定を再計算できます（未指定時は `tf` カラムまたは観測間隔から自動判定）。
- `--start-timestamp` / `--end-timestamp` で ISO-8601 形式の監査ウィンドウ（UTC 基準、両端含む）を指定でき、部分期間のギャップ調査に利用できます。サマリーには適用したフィルタ値も `start_timestamp_filter` / `end_timestamp_filter` として残ります。
- `--calendar-day-summary` を使うと UTC カレンダーベースで 1 日ごとのカバレッジ比率を集計し、`--calendar-day-coverage-threshold` で指定した下限を下回る日を `calendar_day_summary.warnings` に優先表示します（既定 0.98）。`--calendar-day-max-report` でワースト日一覧の件数を制御できます。
- `--fail-under-coverage` を指定すると、総合カバレッジ比率が下限（0〜1 の小数）を下回った場合に終了コード 1 で失敗扱いになり、サマリー出力後に理由が stderr へ表示されます。
- `--fail-on-calendar-day-warnings` は `--calendar-day-summary` と併用し、`warnings` に 1 件以上の日が出現した場合に終了コード 1 を返します。しきい値を `--calendar-day-coverage-threshold` で調整し、複数日がトリガーした場合は件数とトランケーション状況が stderr へ通知されます。
- `--fail-on-duplicate-groups` に 0 以外の閾値を指定すると、重複タイムスタンプのグループ数が閾値以上になった場合に終了コード 1 で失敗します（0 を指定するとガードを無効化）。`--fail-on-duplicate-occurrences` は同様に最大発生回数を監視し、特定グループの膨張を捕捉します。どちらのカウントも `--min-duplicate-occurrences` 適用後の値に基づいて評価されます。
- `--webhook`（カンマ区切り）を指定すると、上記の失敗条件に引っかかった際に `data_quality_failure` ペイロードを JSON で POST します。既定のタイムアウトは 5 秒ですが、必要に応じて `--webhook-timeout` で調整できます。ペイロードには `coverage_ratio` / `missing_rows_estimate` / `calendar_day_warnings` と失敗理由が含まれるため、Ops チャネルで即時にエスカレーション可能です。
- 既存の stdout / JSON レイアウトは維持されるため、既存オートメーションはフラグを追加しない限り挙動が変わりません。
- 日次ワークフロー (`scripts/run_daily_workflow.py`) からは `--check-data-quality` を指定することで監査 CLI を呼び出せます。既定では `reports/data_quality/<symbol>_<tf>_summary.json` と `reports/data_quality/<symbol>_<tf>_gap_inventory.{csv,json}` にレポートを保存し、総合カバレッジ 0.995 未満や UTC カレンダーベースの 0.98 未満日が存在すると終了コード 1 で失敗します。重複タイムスタンプについても `--data-quality-duplicate-groups-threshold` の既定値 (5) または `--data-quality-duplicate-occurrences-threshold` の既定値 (3) を超えると失敗扱いになるため、グループ数の飽和と単一タイムスタンプの膨張を双方検知できます。閾値は `--data-quality-coverage-threshold` / `--data-quality-calendar-threshold` / `--data-quality-duplicate-groups-threshold` / `--data-quality-duplicate-occurrences-threshold` で調整でき、`--webhook` を併用すると失敗時に Ops 通知が送信されます。必要に応じて `--data-quality-webhook-timeout` で POST タイムアウトを上書きしてください。

### オンデマンドインジェスト CLI
- `scripts/pull_prices.py` はヒストリカル CSV（または API エクスポート）から未処理バーを検出し、`raw/`→`validated/`→`features/` に冪等に追記する。
- 標準経路は `python3 scripts/run_daily_workflow.py --ingest --use-dukascopy`。Dukascopy から最新 5m バーを取得し、そのまま `pull_prices.ingest_records` に渡して CSV/特徴量を同期する。
- 失敗時は自動で yfinance (`period="7d"`) にフォールバックし、`--yfinance-lookback-minutes`（既定 60 分）を基準に再取得ウィンドウを決定。
- 追加依存: `pip install dukascopy-python`（Sandbox ではホワイトリストまたは事前ダウンロードが必要）。
- Sandbox で PyPI が利用できない場合はローカル CSV → `synthetic_local` へフォールバックし、`ops/runtime_snapshot.json.ingest` を最新 5 分境界まで補完。詳細は [docs/api_ingest_plan.md](docs/api_ingest_plan.md) を参照。
- ローカル CSV は `--local-backup-csv path/to.csv` で差し替え可。複数シンボルを扱う場合は対象 CSV をリポジトリ配下へ配置してから指定する。既定は `data/<symbol_lower>_5m_2018-2024_utc.csv`。
- `--disable-synthetic-extension` で合成バー挿入を無効化可能。最新バーが古い場合は `python3 scripts/check_benchmark_freshness.py` を再実行して解消を確認。
- `ops/runtime_snapshot.json.ingest_meta.<symbol>_<tf>` には `source_chain` / `fallbacks` / `freshness_minutes` / `synthetic_extension` / `local_backup_path` などのメタデータが保存される。
- REST API 連携は `scripts/fetch_prices_api.py` を想定するが、Alpha Vantage FX_INTRADAY はプレミアム専用のため保留中。API 再開時は `configs/api_ingest.yml` の `activation_criteria` を満たすことを確認し、鍵は暗号化ストレージで管理する。429 や SLA 違反が続く場合は `--use-api` を停止して Dukascopy 経路へ戻す。

## タスク同期スクリプト
`state.md` と `docs/todo_next.md` を同時に更新する場合は `scripts/sync_task_docs.py` を利用すると手戻りを防げます。日次運用では対話プロンプト付きの `scripts/manage_task_cycle.py` を使うと入力漏れを避けやすく、`--dry-run` で事前確認も可能です。

```bash
# Ready から In Progress への着手時（ドライラン）
python3 scripts/manage_task_cycle.py --dry-run start-task \
    --anchor docs/task_backlog_p1_archive.md#p1-01-ローリング検証パイプライン \
    --record-date 2024-06-22 \
    --promote-date 2024-06-22 \
    --task-id P1-01 \
    --title "ローリング検証パイプライン" \
    --state-note "Sharpe/DD 指標のローテーション検証を開始" \
    --doc-note "チェックリスト整備とローリングrunの引数洗い出し" \
    --doc-section Ready \
    --runbook-links "[docs/benchmark_runbook.md](docs/benchmark_runbook.md)" \
    --pending-questions "Rollingサマリーの更新タイミングを決める"

# 完了処理（In Progress → Archive、ドライラン）
python3 scripts/manage_task_cycle.py --dry-run finish-task \
    --anchor docs/task_backlog_p1_archive.md#p1-01-ローリング検証パイプライン \
    --date 2024-06-24 \
    --note "ローリング365D/180D/90Dのrunを自動化し、state/log/docsを同期" \
    --task-id P1-01
```
`start-task` は `sync_task_docs.py record` → `promote` を順番に呼び出し、既存アンカーを検出した場合は重複登録を避けます。`finish-task` は `complete` をラップし、完了ログとアーカイブ更新を一括実行します。`--dry-run` を外すと実際に `state.md` / `docs/todo_next.md` が更新され、コマンドは実行前にエコーされるので内容を確認してから Enter できます。

## インシデントリプレイガイド
- インシデントごとの作業フォルダは `ops/incidents/<incident_id>/` に配置し、`incident.json`（メタデータ）、`replay_params.json`（Notebook/CLI 引数のスナップショット）、`replay_notes.md`（原因分析と対策メモ）、`artifacts/`（スクリーンショットや追加ログ）をそろえる。
- `analysis/incident_review.ipynb` から `scripts/run_sim.py --manifest <manifest> --csv <source.csv> --start-ts ... --end-ts ... --json-out ...` を実行し、Notebook が生成する `metrics.json` / `daily.csv` / `source_with_header.csv` は `runs/incidents/<incident_id>/` へ移動またはシンボリックリンクする。
- `replay_notes.md` には `## Summary` / `## Findings` / `## Actions` を設け、`Summary` 冒頭の 3 行要約を [docs/task_backlog_p1_archive.md](docs/task_backlog_p1_archive.md#p1-02-インシデントリプレイテンプレート) の進捗メモと `state.md` の `## Log` に転記して共有する。詳細手順は [docs/state_runbook.md#インシデントリプレイワークフロー](docs/state_runbook.md#インシデントリプレイワークフロー) を参照。
