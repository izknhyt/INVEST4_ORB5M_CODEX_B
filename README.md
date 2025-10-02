# 投資3 — 5分足 ORB v1（Paper-ready雛形）
設計ソース: キャンバス「第一目標・詳細設計書（5分足 ORB v1）— 投資3」 v1.1

## 概要
- 戦術: 5m Opening Range Breakout（OCO/任意トレール）
- EVゲート: OCO=Beta-Binomial（勝率LCB）/ トレール=t下側分位、閾値はデフォルト0.5 pip（`RunnerConfig.threshold_lcb_pip` / CLI `--threshold-lcb` で調整可能）
- Fill二系統: Conservative / Bridge（Brownian Bridge近似のフック）
- サイズ: 分数ケリー(0.25×) + ガード（1トレード≤0.5%, 日次DD≤2%, クールダウン）

## 使い方（簡易）
1) `configs/*.yml` を確認・調整
2) バックテスト/リプレイの実装を後続コミットで追加（この雛形は骨格）
3) `strategies/day_orb_5m.py` を中心に拡張

### 現状の実装状況（骨格）
- 戦略`day_orb_5m`はOR計算→ブレイク検出→EVゲート→分数ケリーで`qty`決定までを実装
- EVゲートは`core.ev_gate.BetaBinomialEV`を参照（`ctx['ev_oco']`にインスタンスを渡す）
- サイズ計算は`core.sizing`（`ctx['equity']`, `ctx['pip_value']`, `ctx['sizing_cfg']`が必要）
- ルーターゲートは`router/router_v0.py`（`session/spread_band/rv_band`等は`ctx`に渡す）
- 注文はOCOパラメータ（`tp_pips/sl_pips/trail_pips`）を`OrderIntent.oco`に格納

### 簡易ランナー（BT/リプレイ雛形）
- `core/runner.py` に最小限のバックテスト実行器を追加（データ契約の簡易検証/特徴量算出/ゲートCTX構築/Fillシミュレーション/EV更新/メトリクス集計）
- 使い方（例）

```python
from core.runner import BacktestRunner

runner = BacktestRunner(equity=100_000.0, symbol="USDJPY")
metrics = runner.run(bars, mode="conservative")  # barsはOHLC5mのリスト
print(metrics.as_dict())
```

備考: スプレッド帯域・RV帯域・セッション判定は簡易版（プレースホルダ）。実データに合わせて更新してください。

### CLI（MVP）
- CSVから実行し、JSONメトリクスを出力する最小CLIを追加
  - `scripts/run_sim.py`
  - 入力CSVはヘッダ行必須: `timestamp,symbol,tf,o,h,l,c,v,spread`

## タスク同期スクリプト
`state.md` と `docs/todo_next.md` を同時に更新する場合は、`scripts/sync_task_docs.py` を利用すると手戻りを防げます（DoDアンカーで対象タスクを特定します）。日次運用では対話プロンプト付きの `scripts/manage_task_cycle.py` を使うと入力漏れを避けやすく、`--dry-run` で事前確認も可能です。

### 運用ヘルパー: `scripts/manage_task_cycle.py`

```bash
# Ready から In Progress への着手時
python3 scripts/manage_task_cycle.py --dry-run start-task \
    --anchor docs/task_backlog.md#p1-01-ローリング検証パイプライン \
    --record-date 2024-06-22 \
    --promote-date 2024-06-22 \
    --task-id P1-01 \
    --title "ローリング検証パイプライン" \
    --state-note "Sharpe/DD 指標のローテーション検証を開始" \
    --doc-note "チェックリスト整備とローリングrunの引数洗い出し" \
    --doc-section Ready \
    --runbook-links "[docs/benchmark_runbook.md](docs/benchmark_runbook.md)" \
    --pending-questions "Rollingサマリーの更新タイミングを決める"

# 完了処理（In Progress → Archive）
python3 scripts/manage_task_cycle.py --dry-run finish-task \
    --anchor docs/task_backlog.md#p1-01-ローリング検証パイプライン \
    --date 2024-06-24 \
    --note "ローリング365D/180D/90Dのrunを自動化し、state/log/docsを同期" \
    --task-id P1-01
```

`start-task` は `sync_task_docs.py record` → `promote` を順番に呼び出し、既存アンカーを検出した場合は重複登録を避けます。`finish-task` は `complete` をラップし、完了ログとアーカイブ更新を一括実行します。`--dry-run` を外すと実際に `state.md` / `docs/todo_next.md` が更新され、コマンドは実行前にエコーされるので内容を確認してから Enter できます。

1. **新規タスクの登録**
   ```bash
   python3 scripts/sync_task_docs.py record \
       --task-id P1-10 \
       --title "ローリング検証パイプライン" \
       --date 2024-06-21 \
       --anchor docs/task_backlog.md#p1-10-ローリング検証パイプライン \
       --doc-section Ready \
       --doc-note "ローリング窓の自動起動シーケンスを草案化"
   ```
   - `state.md` の `## Next Task` に行が追加され、`docs/todo_next.md` の指定セクションへ同じアンカー付きブロックが作成されます。

2. **次のタスクへ昇格（Ready → In Progress）**
   ```bash
   python3 scripts/sync_task_docs.py promote \
       --task-id P1-10 \
       --title "ローリング検証パイプライン" \
       --date 2024-06-22 \
       --anchor docs/task_backlog.md#p1-10-ローリング検証パイプライン
   ```
   - `state.md` の `## Next Task` を更新し、`docs/todo_next.md` の該当ブロックが `### In Progress` へ移動します。

3. **完了処理（In Progress/Ready/Pending Review → Archive）**
   ```bash
   python3 scripts/sync_task_docs.py complete \
       --date 2024-06-23 \
       --anchor docs/task_backlog.md#p1-10-ローリング検証パイプライン \
       --note "Sharpe/最大DD の監視とローリングrunの自動起動を整備"
   ```
   - `state.md` から当該タスクを削除し `## Log` に完了メモを追記、`docs/todo_next.md` は `## Archive` セクションへストライク付きで移動し日付/✅が補完されます。

> 補足: すべてのコマンドで `--date` は ISO 形式 (YYYY-MM-DD) を要求し、アンカーは `docs/task_backlog.md#...` で指定してください。

実行例:

```
python3 scripts/run_sim.py --csv data/ohlc5m.csv --symbol USDJPY --mode conservative --equity 100000
```

特定期間のみを対象にする場合は ISO8601 形式の `--start-ts` / `--end-ts` を指定します。

```
python3 scripts/run_sim.py --csv data/usdjpy_5m_2018-2024_utc.csv --symbol USDJPY --mode conservative \
  --start-ts 2024-01-01T00:00:00Z --end-ts 2024-03-01T00:00:00Z
```

例: EV 閾値やセッション制限を調整した実行

```
python3 scripts/run_sim.py \
  --csv data/usdjpy_5m_2018-2024_utc.csv --symbol USDJPY --mode conservative \
  --threshold-lcb 0.3 --allow-low-rv --allowed-sessions LDN,NY \
  --k-tp 1.2 --k-sl 0.4 --or-n 4 --warmup 10 --json-out out.json
```

ファイル出力:

```
python3 scripts/run_sim.py --csv data/ohlc5m.csv --symbol USDJPY --json-out out.json
```

### オンデマンドインジェスト CLI
- `scripts/pull_prices.py` はヒストリカルCSV（またはAPIエクスポート）から未処理バーを検出し、`raw/`→`validated/`→`features/` に冪等に追記する。
- `python3 scripts/run_daily_workflow.py --ingest --use-dukascopy` が現在の標準経路。Dukascopy から最新5mバーを取得し、そのまま `pull_prices.ingest_records` に渡して CSV/特徴量を同期する。Dukascopy が失敗するか、取得した最終バーが `--dukascopy-freshness-threshold-minutes`（既定 90 分）より古い場合は自動で yfinance (`period="7d"`) へ切り替わり、`--yfinance-lookback-minutes`（既定 60 分）を基準に再取得ウィンドウを決めつつ同一の CSV/特徴量更新が継続する。詳細なフォールバック手順は [docs/api_ingest_plan.md](docs/api_ingest_plan.md) を参照。
- 依存ライブラリ（任意導入）: `pip install dukascopy-python yfinance`。フォールバック経路では Yahoo Finance のシンボル変換（例: USDJPY→JPY=X）が自動適用される。
- Sandbox では企業プロキシが PyPI への直接接続を遮断するため、上記ライブラリはホワイトリスト登録後に `pip install` するか、事前にダウンロードしたホイール (`pip install dukascopy_python-*.whl yfinance-*.whl`) で導入する。未導入の場合は自動でローカル CSV → `synthetic_local` のフォールバックに切り替わり `ops/runtime_snapshot.json.ingest` を最新 5 分境界まで補完する。この間の運用メモは [readme/設計方針（投資_3_）v_1.md](readme/設計方針（投資_3_）v_1.md#sandbox-known-limitations) の Sandbox Known Limitations を参照。
- `synthetic_local` 合成バーが挿入されている間は `python3 scripts/check_benchmark_freshness.py` が `ok: true` を維持しつつ `advisories` 配列へ鮮度遅延を記録する。Sandbox では exit code=0 のまま情報共有扱いとし、PyPI 依存導入後に再取得して `advisories` が消えることを確認する。
- REST API 連携は `scripts/fetch_prices_api.py` を経由して行う設計だが、Alpha Vantage FX_INTRADAY がプレミアム専用であるため 2025-10 時点では **保留**。再開時は `configs/api_ingest.yml` の `activation_criteria`（ターゲットコスト上限 40 USD/月以内、日次最低無料枠 500 リクエスト以上、リトライ予算 15 回以内 など）を満たすか確認し、鍵は Vault / SOPS / gpg などの暗号化ストレージで一元管理する。`ALPHA_VANTAGE_API_KEY` 等を環境変数へエクスポートし、同一値を暗号化済みの `configs/api_keys.local.yml.gpg` などへ同期した後に、平文テンプレート (`configs/api_keys.yml`) はプレースホルダのまま維持する。`credential_rotation` の `cadence_days` / `next_rotation_at` / `owner` を更新し、完了時は `last_rotated_at` とレビュワーを `docs/checklists/p1-04_api_ingest.md` へ記録する。429 や SLA 違反が 2 回連続した場合は `--use-api` を停止し、Dukascopy 経路へフォールバックしつつ #ops へエスカレーションする。
- REST API 連携は `scripts/fetch_prices_api.py` を経由して行う設計だが、Alpha Vantage FX_INTRADAY がプレミアム専用であるため 2025-10 時点では **保留**。再開時は `configs/api_ingest.yml` の `activation_criteria`（ターゲットコスト上限 40 USD/月以内、日次最低無料枠 500 リクエスト以上、リトライ予算 15 回以内 など）を満たすか確認し、鍵は Vault / SOPS / gpg などの暗号化ストレージで一元管理する。`ALPHA_VANTAGE_API_KEY` 等を環境変数へエクスポートし、同一値を暗号化済みの `configs/api_keys.local.yml.gpg` などへ同期した後に、平文テンプレート (`configs/api_keys.yml`) はプレースホルダのまま維持する。`credential_rotation` の `cadence_days` / `next_rotation_at` / `owner` を更新し、完了時は `last_rotated_at` とレビュワーを `docs/checklists/p1-04_api_ingest.md` へ記録する。429 や SLA 違反が 2 回連続した場合は `--use-api` を停止し、Dukascopy 経路へフォールバックしつつ #ops へエスカレーションする。Sandbox で合成バーのみが得られる期間中は `python3 scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6` のアラートを情報共有レベルとして扱い、PyPI 依存導入後に再実行して閾値クリアを確認する。
- 直近の成功時刻は `ops/runtime_snapshot.json` の `ingest` セクションで管理し、異常は `ops/logs/ingest_anomalies.jsonl` に記録。毎回の実行後に `USDJPY_5m` の時刻と差分（目安: 90 分以内）を確認し、必要なら `--dukascopy-freshness-threshold-minutes` を一時的に調整する。
- タイムスタンプは ISO 8601 (`Z` や `+00:00` 付き)・空白区切りどちらにも対応。

実行例:

```
python3 scripts/pull_prices.py --source data/usdjpy_5m_2018-2024_utc.csv --symbol USDJPY --tf 5m
```

**Dukascopy 経由の例:**

```
python3 -m scripts.run_daily_workflow \
  --ingest --use-dukascopy --symbol USDJPY --mode conservative
```

API 再開時の例（プレミアム契約または別 API が利用可能になったときに有効化）:

```
python3 -m scripts.run_daily_workflow \
  --ingest --use-api --symbol USDJPY --mode conservative \
  --api-config configs/api_ingest.yml --api-credentials configs/api_keys.yml
```

ドライラン（スナップショット更新なし）:

```
python3 scripts/pull_prices.py --source data/usdjpy_5m_2018-2024_utc.csv --symbol USDJPY --dry-run
```

### ライブインジェストワーカー
- Dukascopy から 5 分足を 5 分間隔で取得し、`pull_prices.ingest_records` と `scripts/update_state.py` を自動実行する常駐ワーカー
  - `scripts/live_ingest_worker.py`
- 代表的な起動例:

```bash
python3 scripts/live_ingest_worker.py \
  --symbols USDJPY --modes conservative --interval 300
```

- 監視ポイント
  - `ops/logs/ingest_anomalies.jsonl`: 異常行が記録されていないか（空でない場合は Slack/ops へ共有）
  - `ops/runtime_snapshot.json.ingest.<SYMBOL>_5m`: 最新時刻が想定と乖離していないか
  - `runs/active/state.json`: 更新時刻が追従しているか（`update_state` 呼び出しで更新）
- グレースフル停止
  - 既定では `ops/live_ingest_worker.stop` が存在すると次ループ前に停止
  - 明示的に変えたい場合は `--shutdown-file path/to/flag` を指定
  - 即時終了は `Ctrl+C`（SIGINT）または `kill`（SIGTERM）で通知

### 両Fill併走レポート
- ConservativeとBridgeを同条件で比較するCLI
  - `scripts/run_compare.py`

実行例:

```
python3 -m scripts.run_compare --csv data/usdjpy_5m_2018-2024_utc.csv --symbol USDJPY --equity 100000 --out-dir runs/
```

出力:
- `runs/compare_<symbol>_<ts>/cons.metrics.json` / `bridge.metrics.json`
- `runs/compare_<symbol>_<ts>/daily_compare.csv`
- `runs/index.csv` に比較行を追記

### 小グリッドサーチ（N_or×k_tp×k_sl）
- 複数パラメータの組み合わせを一括実行して保存
  - `scripts/run_grid.py`

実行例:

```
python3 -m scripts.run_grid \
  --csv data/usdjpy_5m_2018-2024_utc.csv --symbol USDJPY --equity 100000 \
  --or-n 6 --k-tp 0.8,1.0,1.2 --k-sl 0.6,0.8 \
  --threshold-lcb 0.2 --out-dir runs/
```

出力:
- 各組み合わせで `runs/grid_<symbol>_<mode>_or<..>_ktp<..>_ksl<..>_<ts>/` を作成
- `runs/index.csv` に各ランのサマリ行を追記（or_n/k_tp/k_sl と成績）

### 最適化ヘルパ
- グリッド実行と結果要約を一括で行うスクリプト
  - `scripts/optimize_params.py`
- 補助ツール
  - `scripts/utils_runs.py`: `runs/index.csv` を読み込む共通ヘルパ
  - `analysis/param_surface.ipynb`: パラメータ別ヒートマップのノートブック
  - `scripts/summarize_runs.py`: トレード件数・勝率などのサマリ出力
  - `scripts/auto_optimize.py`: `optimize_params.py` を呼び出し、JSONレポートと通知を行う雛形

実行例:

```
python3 scripts/optimize_params.py \
  --top-k 5 --min-trades 200 --rebuild-index \
  --csv data/usdjpy_5m_2018-2024_utc.csv --symbol USDJPY --mode conservative \
  --or-n 4,6,8 --k-tp 0.6,0.8,1.0,1.2 --k-sl 0.4,0.6,0.8 \
  --threshold-lcb 0.3 --allowed-sessions LDN,NY --warmup 10 --include-expected-slip
```

出力:
- グリッド実行（`--dry-run` で実行を省略可）
- `runs/index.csv` の再構築と、標準出力/`--report` に上位パラメータのJSON要約

進捗表示:
- デフォルトで各コンボの開始時に `[i/N] ... elapsed=.. ETA=..` を標準エラーへ表示
- サイレント実行は `--quiet` を付与

### 日次ワークフロー実行
- `scripts/run_daily_workflow.py` でインジェスト、state 更新、ベンチマーク（ベースライン＋ローリング）、ヘルスチェック、サマリ生成を順番に呼び出せます。

起動時にまとめて実行する例:

```bash
python3 scripts/run_daily_workflow.py \
  --ingest --update-state --benchmarks --state-health --benchmark-summary \
  --symbol USDJPY --mode conservative --equity 100000
```

ベンチマーク窓ごとの実行スケジュールとアラート閾値の管理方針は、[docs/benchmark_runbook.md#スケジュールとアラート管理](docs/benchmark_runbook.md#スケジュールとアラート管理) を参照してください。`scripts/manage_task_cycle.py start-task` を使って `state.md` / `docs/todo_next.md` と整合を取る手順も同セクションにまとめています。

個別実行の例（必要なものだけ）:

```bash
# 値動き取り込み（未処理ぶんのみ追記）
python3 scripts/pull_prices.py --source data/usdjpy_5m_2018-2024_utc.csv --symbol USDJPY

# state 更新（チャンク処理）
python3 scripts/update_state.py --bars validated/USDJPY/5m.csv --symbol USDJPY --mode conservative --chunk-size 20000

# ベンチマーク（ベースライン + 365/180/90 日ローリング）
python3 scripts/run_benchmark_runs.py --bars validated/USDJPY/5m.csv --symbol USDJPY --mode conservative --equity 100000 --windows 365,180,90

# サマリ JSON/PNG 出力（pandas/matplotlib が必要）
python3 scripts/report_benchmark_summary.py --symbol USDJPY --mode conservative --reports-dir reports \
  --json-out reports/benchmark_summary.json --plot-out reports/benchmark_summary.png --windows 365,180,90 \
  --min-win-rate 0.55 --min-sharpe 0.5 --max-drawdown 200
```

開発時は、実行側で以下のような`ctx`辞書を戦略へ提供してください（例）:

```python
ctx = {
  'session': 'LDN', 'spread_band': 'normal', 'rv_band': 'mid',
  'expected_slip_pip': 0.2, 'slip_cap_pip': 1.5,
  'ev_oco': BetaBinomialEV(conf_level=0.95, decay=0.02),
  'cost_pips': 0.1, 'threshold_lcb_pip': 0.3,
  'equity': 100_000.0, 'pip_value': 10.0,
  'sizing_cfg': {'risk_per_trade_pct':0.25,'kelly_fraction':0.25,'units_cap':5.0,'max_trade_loss_pct':0.5},
}
```

## 注意
- この雛形は**設計に沿った骨格**です。実データ接続/BTランナー/ダッシュボードは以後の実装で追加します。
- 現在の設計方針及び詳細設計は `readme/` フォルダを参照してください。
- 今後の開発タスクは `docs/task_backlog.md` に集約しています。作業前に確認し、完了したタスクは随時更新してください。
- EV ゲートの調整方法は `docs/ev_tuning.md` にメモをまとめています。
- 通知運用とレイテンシ監視については `docs/signal_ops.md` を参照してください。
- Paper 移行前のチェックリストは `docs/go_nogo_checklist.md` を参照してください。

### 補足（追加依存について）
- ベンチマークサマリー画像の生成や Notebook 可視化では `pandas` と `matplotlib` を利用します。未導入の環境では以下を実行してください。

```
pip install pandas matplotlib
```

### テスト
- 依存が未導入の場合は `pip install pytest` を実行。
- `python3 -m pytest` でユニットテストを実行できます（通知・設定ヘルパ用のテストが含まれています）。
