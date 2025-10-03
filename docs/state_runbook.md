# state.json 運用ガイド

## 目的
EV ゲートや滑り学習などの内部状態を `state.json` として保存し、次回の実行時に引き継ぐことで、ウォームアップを短縮しつつ過去の統計を活用する。

## 保存手順
1. `BacktestRunner` 実行終了後、`runner.export_state()` を呼び出す。
2. 返却された辞書を JSON として保存する。`scripts/run_sim.py` は既定で `ops/state_archive/<strategy>/<symbol>/<mode>/` 以下へ時刻付きファイルを自動保存し、`--out-dir` 指定時は run フォルダにも `state.json` を残す。保存成功時には `scripts/aggregate_ev.py` が自動で呼び出され、EVプロファイル (YAML/CSV) を更新する。
3. 自動アーカイブを無効化したい場合は `--no-auto-state` を付ける。保存先を変えたいときは `--state-archive path/to/dir` を利用する。EVプロファイル更新をスキップしたい場合は `--no-aggregate-ev` を併用する。
4. 運用では日次または週次で最新の state を確認し、事故時に復元できるようバージョン管理する。

## ロード手順
- CLI 実行時に自動で最新 state が読み込まれる（`ops/state_archive/<strategy>/<symbol>/<mode>/` で最も新しい JSON）。
- 自動ロードを避けたい場合は `--no-auto-state` を指定する。
- コードから: `runner.load_state_file(path)` または `runner.load_state(state_dict)` を利用。

## オンデマンド起動フロー（ノートPC向け）
- PC 起動/ログイン時に以下の順で CLI を実行すると、停止中の期間を自動補完して通常運用へ復帰できます。

```
python3 scripts/run_daily_workflow.py --ingest --update-state --benchmarks --state-health --benchmark-summary
```

- 個別の実行例
  - 取り込み: `python3 scripts/pull_prices.py --source data/usdjpy_5m_2018-2024_utc.csv`
  - Dukascopy 経由（標準経路）: `python3 -m scripts.run_daily_workflow --ingest --use-dukascopy --symbol USDJPY --mode conservative`
    - 失敗時や取得データが `--dukascopy-freshness-threshold-minutes`（既定 90 分）より古い場合は自動で yfinance (`period="7d"`) へ切替。フォールバック時は `--yfinance-lookback-minutes`（既定 60 分）で再取得ウィンドウを決めるため、長期停止後に再開する際は値を大きめに設定してから実行する。`pip install dukascopy-python yfinance` を事前に実行して依存を満たす。
    - BID/ASK の取得側は `--dukascopy-offer-side` で切り替え可能（既定 BID）。取得サイドは `ops/runtime_snapshot.json.ingest_meta.<symbol>_<tf>.dukascopy_offer_side` に保存されるため、アラート調査時はメタデータで確認する。
    - ローカル CSV フォールバックで利用するファイルは `--local-backup-csv data/usdjpy_5m_2025.csv` のように明示指定できる。Sandbox で最新のバックフィルを持ち込む場合や別シンボルを検証したい場合は、対象 CSV を `data/` 以下へ配置してからフラグで差し替える。
    - フォールバック後に合成バーを挿入したくない場合は `--disable-synthetic-extension` を併用する。`synthetic_local` を生成しないため最新バーはローカル CSV の終端止まりとなり、鮮度アラートが `errors` で報告される点に留意する。
    - 実行後は `ops/runtime_snapshot.json.ingest.USDJPY_5m` の更新時刻と `ops/logs/ingest_anomalies.jsonl` を確認し、鮮度が 90 分超で推移する場合は閾値見直しや手動調査を実施する。
- `ops/runtime_snapshot.json.ingest_meta.USDJPY_5m` に補助メタデータが保存される。`primary_source`（実行フラグ）、`source_chain`（実際に利用したデータソース。例: `dukascopy` → `yfinance` → `local_csv` → `synthetic_local`）、`freshness_minutes`（`datetime.utcnow()` との差分）、`rows_validated` / `rows_raw` / `rows_featured`、`fallbacks`（発生したフォールバックの理由と次のソース）、`synthetic_extension`（ローカル合成バーで補完したか）をレビューし、Sandbox で `synthetic_extension=true` の場合は依存導入後に実データで再実行する。
- `local_csv` フォールバックが発生した場合は、同メタデータに `local_backup_path` が追加される（絶対パス）。`--local-backup-csv` で差し替えた際のトレーサビリティとして確認し、最新バックフィルの持ち込み経路と整合しているかをレビューする。
    - 2025-11-07 00:40Z Sandbox: 依存未導入のまま実行すると Dukascopy / yfinance 双方が ImportError で停止し、`ops/runtime_snapshot.json.ingest.USDJPY_5m` は 2025-10-01T14:10:00 のまま。サンドボックスでは先に依存導入を済ませた上で再取得→鮮度確認を行う。
  - 2025-11-13 Sandbox: ローカル CSV フォールバックのみで最新バーが 5 分境界より古い場合、自動で `synthetic_local` ソースの合成 OHLCV を生成し `ops/runtime_snapshot.json.ingest` を更新する。`scripts/run_daily_workflow.py::_generate_synthetic_bars` のロジックを利用し、5 分刻みでギャップを埋めてアノマリーログを出さずに鮮度チェックを再開できるようにした。
    - 2025-11-13 04:10Z: `pip install dukascopy-python yfinance` は Sandbox プロキシにより HTTP 403 (Tunnel connection failed) で失敗。依存導入が必要な場合は事前にホワイトリスト登録またはオフラインホイールを準備してから再実行する。
    - 2025-11-24 Sandbox: 実データ導入直前に鮮度遅延を可視化したいケースが発生したため、`--disable-synthetic-extension` フラグを追加。ローカル CSV の終端が `ingest_meta` の `source_chain` / `freshness_minutes` にそのまま反映され、`synthetic_local` が混入しない。
  - API 直接取得（保留中）:
    1. `configs/api_ingest.yml` の `activation_criteria` が満たされていることを確認し、必要なら `target_cost_ceiling_usd`・`minimum_free_quota_per_day`・`retry_budget_per_run` を最新値へ更新する。
    2. 認証情報を投入する前に暗号化ストレージ（Vault / SOPS / gpg など）へ保存先を作成し、`credential_rotation.storage_reference` に URI を記録する。平文ファイルを一時的に扱う場合は、コミット対象から除外されていることを `.gitignore` と CI ルールで再確認する。
    3. 取得した API キーを環境変数へエクスポートする。例:
       ```bash
       export ALPHA_VANTAGE_API_KEY="<redacted>"
       ```
       `.env` 管理時は `dotenv run` などで一時読み込みし、CI/cron はシークレット管理サービス（GitHub Actions Secrets、GCP Secret Manager など）から注入する。環境変数と同じ値を `configs/api_keys.yml`（暗号化版: `configs/api_keys.local.yml.gpg` など）へ同期し、暗号化前後の検証ログを残す。
    4. `configs/api_ingest.yml` の `credential_rotation` に `next_rotation_at`・`cadence_days`・`owner` を記録し、ローテーション予定/完了ログを `docs/checklists/p1-04_api_ingest.md` へ追記する。鍵を差し替えたら `last_rotated_at` とレビュー担当者も更新する。
    5. `python3 -m scripts.run_daily_workflow --ingest --use-api --symbol USDJPY --mode conservative` を実行する。Alpha Vantage FX_INTRADAY がプレミアム専用のため 2025-10 時点では契約後に再開予定であり、条件を外れた場合は `--use-api` を一時的に停止する。
    6. API 取得がエラー／空レスポンスになった場合でも、`run_daily_workflow` がローカル CSV → `synthetic_local` へ自動フォールバックすることをログで確認する。`ops/runtime_snapshot.json.ingest_meta.<symbol>_<tf>` の `fallbacks` と `source_chain` に `api` → `local_csv` → `synthetic_local` が記録され、`local_backup_path` に使用した CSV の絶対パスが保存されているかをレビューする。
    7. Twelve Data 無料ティアをフォールバック候補として評価する場合は、`python3 scripts/fetch_prices_api.py --provider twelve_data --symbol USDJPY --tf 5m --lookback-minutes 60 --config configs/api_ingest.yml --credentials configs/api_keys.yml --anomaly-log /tmp/ingest_anomalies.jsonl --out /tmp/twelve_data.json` のようにモックドライランを実施し、`values[].datetime` が UTC (`+00:00` または `Z`) で返ることと `volume` 欠損時に 0.0 として正規化されることを確認する。レスポンス順序は降順で届くため、`fetch_prices_api` が昇順へ整列する仕様になっている点と、空文字/NULL の `volume` でも異常ログが出ないことを `ops/logs/ingest_anomalies.jsonl` で確認する。
- state更新: `python3 scripts/update_state.py --bars validated/USDJPY/5m.csv --chunk-size 20000`
- 検証・集計: `python3 scripts/run_benchmark_runs.py --bars validated/USDJPY/5m.csv --windows 365,180,90` → `python3 scripts/report_benchmark_summary.py --plot-out reports/benchmark_summary.png`
- ヘルスチェック: `python3 scripts/check_state_health.py`

### 常駐インジェスト運用
- `python3 scripts/live_ingest_worker.py --symbols USDJPY --modes conservative --interval 300`
  - Dukascopy から 5 分足を再取得し `pull_prices.ingest_records` を通過させたのち、指定したモードで `scripts/update_state.py` を呼び出す。
  - `--raw-root` / `--validated-root` / `--features-root` / `--snapshot` で保存先を切り替え可能。テスト時はテンポラリディレクトリを指定する。
  - BID/ASK の取得側は `--offer-side` で切替（既定 BID）。CLI ログと `ingest_meta` に保存される `dukascopy_offer_side` を確認する。
- 監視ポイント
  - `ops/runtime_snapshot.json.ingest.<SYMBOL>_5m`: 直近バー時刻が遅延していないか（90 分以上の乖離は yfinance フォールバック検討）。
  - `ops/logs/ingest_anomalies.jsonl`: 非単調・欠損・整合性エラーが出力されていないか（記録が出た場合は原因特定後に再実行）。
  - `runs/active/state.json`: `update_state` 呼び出しで更新されているか、更新が停止した場合は CLI ログを確認。
- グレースフル停止
  - 既定のフラグファイル: `ops/live_ingest_worker.stop`。タッチすると次ループ開始前に終了する。
  - CLI で `--shutdown-file` を渡すと監視先を変更できる。Cron など外部から停止させる場合に指定。
  - SIGINT/SIGTERM 受信時は進行中のシンボル処理を完了してから停止する。

## インシデントリプレイワークフロー
- **対象:** `ops/incidents/<incident_id>/` に格納した本番障害・大幅ドローダウン案件の事後検証。
- **目的:** `analysis/incident_review.ipynb` で当時の相場条件を再現し、再発防止に向けた対応策とインシデント指標を整理する。

### 1. ディレクトリ準備
1. `ops/incidents/<incident_id>/` を作成し、以下のテンプレ構成をそろえる。
   ```
   ops/incidents/<incident_id>/
     ├─ incident.json      # 発生日・シンボル・損益・一次報告メモ
     ├─ replay_params.json # Notebook/CLI で使用したパラメータ控え
     ├─ replay_notes.md    # 詳細な原因分析・対応方針・TODO
     └─ artifacts/         # 画像・CSV・ログなどの補助資料（任意）
   ```
2. `incident.json` には `start_ts` / `end_ts` / `mode` / `severity` / `trigger` を記録し、Notebook 側で読み込めるよう ISO8601 (UTC) 形式を使用する。

### 2. Notebook での再現
- `analysis/incident_review.ipynb` を開き、`INCIDENT_ID` 変数に対象フォルダを設定する。
- Notebook の再現セルで `scripts/run_sim.py --start-ts --end-ts --no-auto-state --no-aggregate-ev` を呼び出し、`replay_params.json` に CLI 引数を保存するセルを実行する。
- 実行後は Notebook が生成する `metrics.json` / `daily.csv` / `source_with_header.csv` を `runs/incidents/<incident_id>/`（例: `runs/incidents/USDJPY_conservative_20251002_230924/`）へ移動またはシンボリックリンクし、追跡しやすくする。

### 3. 出力整理と共有
- `replay_notes.md` には以下の章立てを最低限用意する。
  - `## Summary`: 再現結果サマリ（損益 / 再現可否 / 主要因）。
  - `## Findings`: 原因分析・再発条件・必要な追加データ。
  - `## Actions`: 即時対応 / 恒久対策 / 未解決課題。
- `replay_params.json` は Notebook から自動保存した引数ログをそのままコミットし、再実行の正確な CLI を残す。
- Notebook 生成物や追加ログは `artifacts/` 以下に配置し、巨大ファイルは Git LFS または外部ストレージ参照を記載する。
- ステークホルダー向け要約は `replay_notes.md` の `## Summary` 冒頭に 3 行以内のダイジェストを追加し、同じ文面を `docs/task_backlog.md#p1-02-インシデントリプレイテンプレート` の進捗メモと `state.md` の `## Log` に転記する。必要に応じて #ops チャネルや週次レポートへリンクを共有する。

## 推奨運用
- **バックアップ:** 自動アーカイブされた最新ファイル（例: `ops/state_archive/.../<timestamp>_runid.json`）を基準に、必要に応じて別途バックアップを取得する。
- **互換性:** RunnerConfig（特にゲート設定・戦略パラメータ）を大幅に変更した際は、古い state がバイアスになる場合がある。必要に応じてリセット（初期化）を検討する。
- **監査ログ:** `ops/state_archive/` など保存先を決め、保存日時・使った戦略パラメータと一緒にメタ情報を付与する。
- **EVプロファイル:** `scripts/aggregate_ev.py --strategy ... --symbol ... --mode ...` を使うと、アーカイブ済み state から長期/直近期の期待値統計を集約し、`configs/ev_profiles/` に YAML プロファイルを生成できます。`run_sim.py` は該当プロファイルを自動ロードして EV バケットをシードします（`--no-ev-profile` で無効化可能）。
- **アーカイブの整理（任意）:** `ops/state_archive/` は運用で増えていきます。最新 N 件のみ残す場合は `scripts/prune_state_archive.py --base ops/state_archive --keep 5` を実行してください。`--dry-run` で削除予定を確認できます。
- **ヘルスチェック:** `scripts/check_state_health.py` を日次（`run_daily_workflow.py --state-health`）で実行し、結果を `ops/health/state_checks.json` に追記する。勝率 LCB・バケット別サンプル・滑り係数を監視し、警告が出た場合は `--webhook` で Slack 等へ通知。`--fail-on-warning` を CI/バッチに組み込むと異常時にジョブを停止できる。
- **履歴保持:** 標準では直近 90 レコードを保持する。上限を変更する場合は `--history-limit` を調整する。履歴の可視化は Notebook or BI で `checked_at` を横軸に `ev_win_lcb` やワーニング件数をプロットする。
- **タスク同期:** `state.md` と `docs/todo_next.md` の整合を保つ際は `scripts/manage_task_cycle.py` を優先利用する。`start-task` で Ready 登録→In Progress 昇格を一括実行し、既存アンカー検知で重複記録を抑止する。完了時は `finish-task` でまとめてログとアーカイブへ送る。いずれも `--dry-run` でコマンド内容を確認してから本実行する。Codex セッションにおける具体的な開始前チェックや終了処理は [docs/codex_workflow.md](codex_workflow.md) を参照する。
- **API鍵管理:** REST インジェストを有効化する場合は、暗号化ストレージに登録したシークレットを唯一の正本とし、`configs/api_keys.yml`（平文テンプレート）にはプレースホルダのみを残す。ローカル開発では `configs/api_keys.local.yml.gpg` のように暗号化したファイルを復号して利用し、CI/cron では `ALPHA_VANTAGE_API_KEY` などの環境変数をシークレットマネージャ経由で注入する。`scripts/_secrets.load_api_credentials` は環境変数を優先するため、ローテーション後は `export` した値と暗号化ストレージの両方を同期する。`configs/api_ingest.yml` の `credential_rotation` を更新したら、ローテーション日時・実施者・レビュー担当者を `docs/checklists/p1-04_api_ingest.md` に記録し、監査証跡を保持する。
- **API 運用切替:** `--use-api` を有効化する際は上記「API 直接取得」手順を踏み、初回はドライラン (`--dry-run`) でレスポンス整合性・レートリミットヘッダを確認する。`configs/api_ingest.yml` の `activation_criteria` 逸脱や `retry_budget_per_run` 超過を検知した場合は直ちに `--use-api` を無効化し、Dukascopy 経路へ戻す。
- **レート制限/ SLA エスカレーション:** 429 や SLA 違反が 2 回連続で発生した場合は `ops/logs/ingest_anomalies.jsonl` を添えて #ops チャネルへ報告し、契約窓口への連絡可否を確認する。それまでは `retry_budget_per_run` を超えない範囲で 15 分間隔の再試行にとどめ、`docs/api_ingest_plan.md#4-configuration` のコスト上限を再チェックする。
- **テンプレ適用:** `state.md` の `## Next Task` へ手動で項目を追加する場合は、必ず [docs/templates/next_task_entry.md](templates/next_task_entry.md) を貼り付けてアンカー・参照リンク・疑問点スロットを埋める。`scripts/manage_task_cycle.py start-task` を使うとテンプレが自動挿入されるため、手動調整より優先する。
- **DoD チェックリスト:** Ready へ昇格する際は [docs/templates/dod_checklist.md](templates/dod_checklist.md) をコピーし、`docs/checklists/<task-slug>.md` として保存する。テンプレート内の Ready チェック項目は昇格時点で状態を更新し、バックログ固有の DoD 箇条書きをチェックボックスへ転記する。進行中は該当タスクの `docs/todo_next.md` エントリからリンクし、完了後も `docs/checklists/` に履歴として保管する。

## 実装メモ
- `core/runner.py` の `_config_fingerprint` は state と RunnerConfig が一致しているか確認するためのハッシュ。必要に応じて起動時に照合を追加する余地あり。
- state には EV グローバル値・バケット別 EV・滑り学習情報・RV しきい値などが含まれる。
