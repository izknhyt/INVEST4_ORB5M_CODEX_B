# フェーズ3 詳細設計書 — 観測性自動化

> 関連資料: [docs/plans/p3_observability_automation.md](plans/p3_observability_automation.md), [docs/observability_dashboard.md](observability_dashboard.md), [docs/state_runbook.md](state_runbook.md)

## レビューサマリー（すご腕SE観点）
- CI/スケジューラと CLI 群の接続、アラート手順、リテンション方針が断片的だったため、ジョブライフサイクルと責務境界を明示しました。
- 新規モジュールの I/O 契約やエラー処理が曖昧だったため、インターフェース仕様・ロック機構・再試行ポリシーを詳細化し、後続実装で迷わないよう補強しました。
- 運用・テスト観点の抜け（失敗時のフォールバック、シークレット差し替え、長期保守のための整合性チェックなど）を列挙し、DoD/ランブック更新要件と紐付けました。
- 監査証跡とデータモデルの整合性を強化するため、ログスキーマ・チェックサム計算・manifest 連番管理の仕様を具体化しました。

## 1. 目的・ゴール
- フェーズ3では、フェーズ2で整備したテレメトリとレポート生成フローを完全自動化し、運用担当者がダッシュボードと通知のみで健康状態を把握できる状態にする。
- 自動化対象は以下の3本柱で構成する。
  1. **シグナルレイテンシ監視** — 15分間隔のサンプリング、ロールアップ、SLO違反通知を自動化。
  2. **週次ヘルスレポート** — 主要KPIの集約とWebhook配信を標準化。
  3. **ダッシュボードデータセット** — EV/スリッページ/ターンオーバー等のデータエクスポートと配布を定期化。
- Definition of Done (DoD)
  - すべての自動化ジョブが `run_daily_workflow.py` または専用CLIで再現でき、`python3 -m pytest` と追加テスト（セクション7参照）で回帰保証されている。パラメータ差分は `--config-dump` 出力で比較できる。
  - `ops/automation_runs.log` に各ジョブの `job_id` / `status` / `artefacts` / `duration_ms` / `attempts` / `alerts` が記録され、失敗時にはエスカレーション手順が `docs/state_runbook.md#observability-automation` に明記されている。
  - Weeklyレポートとダッシュボードバンドルが60日分保持され、復旧手順が `docs/state_runbook.md` および `docs/checklists/p3_observability_automation.md` に掲載されている。
  - スケジューラ→CLI→artefact のトレースが 1 コマンドで検証できる（`scripts/verify_observability_job.py --job-id <...>` を追加想定）。

> **実装状況（2026-07-06）** — 上記 DoD は `scripts/analyze_signal_latency.py`・`scripts/summarize_runs.py`・`analysis/export_dashboard_data.py`・`scripts/verify_observability_job.py`・`scripts/run_daily_workflow.py --observability` の各更新で満たされ、Runbook/チェックリスト/テスト（`tests/test_analyze_signal_latency.py` ほか）にも反映済み。以降は Secrets ローテーションとスケジューラ本番化の運用タスクにフォーカスする。

## 2. 背景と前提条件
- フェーズ2でリフレッシュした `reports/portfolio_summary.json`、router demo サンプル (`reports/portfolio_samples/router_demo/**`)、`runs/index.csv` を安定供給できることを前提とする。
- 既存の CLI (`scripts/analyze_signal_latency.py`, `scripts/summarize_runs.py`, `analysis/export_dashboard_data.py`) を拡張する設計とし、大規模な再実装は行わない。
- シークレット (`OBS_WEEKLY_WEBHOOK_URL`, `OBS_WEBHOOK_SECRET`) はオーケストレーター側で注入し、リポジトリ内では環境変数読み出しのみを行う。
- フェーズ3開始前に `python3 scripts/run_daily_workflow.py --observability --dry-run` を 3 日連続で実行し、既存 artefact の欠損がないことを確認する。
- Secrets は `ops/credentials.md` のローテーション基準を満たし、少なくとも 2 系統（本番/ステージング）で管理する。差し替え時は `scripts/verify_observability_job.py --check-secrets` を用いて事前検証する。
- 監視対象となるログ / JSON / CSV は Git にコミットせず、`ops/` と `reports/` 配下の回転ポリシーに従って管理する。転送先（S3 等）との整合は Nightly の `scripts/verify_dashboard_bundle.py` で担保する。

## 3. 全体アーキテクチャ
```
┌─────────────┐   ┌────────────────────┐   ┌────────────────────┐
│Scheduler/CI│→→│run_daily_workflow.py│→→│Automation Subcommands│
└─────────────┘   └────────────────────┘   ├────────────────────┤
                                           │Latency Sampling    │
                                           │Weekly Report       │
                                           │Dashboard Export    │
                                           └────────────────────┘
                                            ↓ artefacts/logs
                                      ops/automation_runs.log
                                      ops/signal_latency*.csv
                                      ops/weekly_report_history/
                                      out/dashboard/*.json
```
- ジョブ実行は Cron もしくは CI (GitHub Actions 等) から `run_daily_workflow.py` サブコマンド、または dedicated CLI を呼び出す。Scheduler からは `--config configs/observability/<job>.yaml` を明示し、ジョブ固有の入力パス・しきい値を切り替えられるようにする。
- すべてのジョブは `ops/automation_runs.log` に構造化JSON (1 行 = 1 レコード) で自己申告し、`job_id` に `YYYYMMDDThhmmssZ-<job>` 形式を採用する。`job_id` は `scripts/_automation_logging.py.generate_job_id(job_name)` で統一生成する。
- 失敗時は exit code ≠0 とし、stdout では JSON サマリー、stderr では human readable な診断メッセージを出す。`stdout` の JSON には `status`, `duration_ms`, `artefacts`, `diagnostics` を含め、CI 側でそのままパースできるようにする。
- `run_daily_workflow.py --observability` は `latency`→`weekly`→`dashboard` の順で実行し、途中失敗時には後続ジョブをスキップした上で `status="error"` を記録するチェーン制御を持つ。
- ロックファイルは各ジョブ専用（`ops/.latency.lock` 等）とし、`fcntl.LOCK_EX | LOCK_NB` 取得失敗時は `status="skipped"` をログに残して正常終了コード (0) を返すことでダブルスケジュール時の誤検知を避ける。
- Scheduler からの環境変数（Secrets, Commit SHA 等）は `scripts/_automation_context.py` で吸い上げ、各 CLI では `AutomationContext` dataclass を経由して参照する。

## 4. コンポーネント詳細

### 4.1 シグナルレイテンシ監視
- **CLI拡張**: `scripts/analyze_signal_latency.py`
  - 新規フラグ
    - `--raw-retention-days` (既定14) — `ops/signal_latency.csv` のローテーションしきい値と連携。
    - `--rollup-retention-days` (既定90) — ロールアップCSV (`ops/signal_latency_rollup.csv`) の古い行を削除。
    - `--rollup-output ops/signal_latency_rollup.csv` — ロールアップ出力先を指定。
    - `--lock-file ops/.latency.lock` — 重複実行防止用ロックファイル。
    - `--alert-config configs/observability/latency_alert.yaml` — SLOしきい値、連続違反カウント、Webhook再試行回数を定義。
  - 実行手順
    1. ロック取得 (`fcntl.flock` or portal util)。保持できない場合は `status="skipped"`, `reason="lock_not_acquired"` をログして即終了。
    2. `ops/signal_latency.csv` へ追記。書き込み前に `--raw-retention-days` の日数より古い行を drop し、ファイルサイズ > 10MB で `ops/signal_latency_archive/YYYY/MM/<job_id>.csv` へ回転。回転時は `gzip` 圧縮し、`ops/signal_latency_archive/manifest.jsonl` に `{ "job_id": ..., "path": ..., "sha256": ..., "row_count": ... }` を追記する。manifest は 1 行 JSON 形式で、`schemas/signal_latency_archive.schema.json` で検証する。
    3. ロールアップ生成: `analysis.latency_rollup.aggregate(samples, window="1H")`。引数は `Iterable[LatencySample]`、戻り値は `List[LatencyRollup]`。生成後に `--rollup-retention-days` より古い行を削除し、`ops/signal_latency_rollup.csv` を一時ファイル→`os.replace` で原子的に更新する。
    4. SLO評価: `p95_latency_ms > threshold` が連続 `N` 回なら `alerts.append(...)`。`alerts` には `severity`, `breach_range`, `evidence_path` を含める。
    5. `alerts` が存在する場合は週次Webhookスキーマ互換の alert payload を生成し、`ops/automation_runs.log` に `alerts` ブロックを記録。`alerts` が空でも `breach_streak` を 0 にリセットする。
    6. 終了時にヘルスサマリー JSON を stdout へ出力 (`samples_written`, `rollups_written`, `breach_count`, `breach_streak`, `next_rotation_bytes`, `lock_latency_ms`)。
    7. `--dry-run-alert` 指定時は Webhook 送信を抑制しつつ `out/latency_alerts/<job_id>.json` に payload を書き出し、`ops/automation_runs.log` では `status="dry_run"` を記録する。
  - **依存モジュール**
  - `analysis/latency_rollup.py` (新規) — pandas 依存を避け、純Pythonで時間窓集計を行うヘルパ。API: `aggregate(samples: Iterable[LatencySample], window: str, tz: str = "UTC") -> List[LatencyRollup]`。
  - `scripts/_automation_logging.py` (新規) — `log_automation_event(job_id, status, payload)` を提供。各ジョブが共通利用。`payload` には `artefacts`, `alerts`, `diagnostics`, `attempts` を含める。
  - `scripts/_automation_context.py` (新規) — Secrets や commit 情報を `AutomationContext` としてまとめる。
  - **監視と通知**
  - 連続違反が2回で warning, 3回で critical → Webhook + PD。`latency_alert.yaml` では `warning_threshold`, `critical_threshold`, `backoff_seconds` を設定可能にする。
  - `ops/latency_job_heartbeat.json` を更新し、`last_success_at`, `last_breach_at`, `pending_alerts` を書き込む。
  - Filebeat/CloudWatch 転送時に誤検知を防ぐため、`ops/automation_runs.log` の 1 行 JSON は 4KB 未満に収める。

### 4.2 週次ヘルスレポート
- **CLI**: `scripts/summarize_runs.py`
  - 拡張フラグ
    - `--weekly-payload` — 週次レポートテンプレートをロードして JSON payload を生成。
    - `--payload-schema schemas/observability_weekly_report.schema.json` — JSON Schema 検証を実行。
    - `--webhook-url-env OBS_WEEKLY_WEBHOOK_URL` / `--webhook-secret-env OBS_WEBHOOK_SECRET`。
    - `--max-retries 3 --retry-wait-seconds 60`。
    - `--out-dir ops/weekly_report_history` — 成功時に `<week_start>.json` と署名ヘッダを保存。
    - `--dry-run-webhook` — 配信せず `out/weekly_report/<job_id>.json` に書き出し。
  - ペイロード構造
    ```json
    {
      "schema_version": "1.0.0",
      "generated_at": "2026-06-27T23:30:00Z",
      "week_start": "2026-06-22",
      "latency": {"p50_ms": 320, "p95_ms": 540, "breaches": [...]},
      "portfolio": {"equity_curve": {...}, "budget_status": "warning"},
      "runs": [{"run_id": "USDJPY_conservative_20251002_214013", ...}],
      "alerts": [{"id": "latency_breach", "severity": "warning", ...}]
    }
    ```
  - 実装手順
    1. `runs/index.csv`, `reports/portfolio_summary.json`, `ops/signal_latency_rollup.csv` を読み込み、欠損/フォーマットを検証。欠損時は `status="error"`, `error_code="missing_input"` とする。
    2. 週次集計を `analysis.weekly_payload.build(context)` に委譲。`context` は `WeeklyPayloadContext` dataclass（`runs`, `portfolio_summary`, `latency_rollup`, `as_of`）で受け渡す。
    3. JSON Schema で検証し、失敗時は詳細を stderr に出力。バリデーション失敗は `status="error"`, `error_code="schema_validation_failed"` を設定し、`out/weekly_report/<job_id>_invalid.json` に検証エラーを保存。
    4. Webhook 送信時は HMAC-SHA256 で署名 (`X-OBS-Signature`)。レスポンスが 5xx の場合は指数バックオフ再試行し、`attempts` をインクリメント。429 応答は `Retry-After` を尊重する。
    5. 成功時に `ops/weekly_report_history/<week_start>.json` と `.../<week_start>.sig` を保存。保存前に `checksum_sha256` を計算し manifest に追記。
    6. 送信結果と checksum (`payload_checksum_sha256`), `attempts`, `webhook_status_code`, `payload_size_bytes` を `ops/automation_runs.log` に記録。
    7. `--dry-run-webhook` 指定時は署名を生成せず、`status="dry_run"` として artefact だけを残す。
  - **ユーティリティ**
  - `analysis/weekly_payload.py` (新規) — 週次KPI抽出と JSON 整形を担当。`build(context: WeeklyPayloadContext) -> WeeklyPayload` を提供し、`ensure_complete()` メソッドで必須フィールドを検証する。
  - `schemas/observability_weekly_report.schema.json` (既存予定) — blueprint の schema を実体化。`$id` を付与し、CI でのスキーマ整合チェックを可能にする。
  - `scripts/_webhook.py` (既存) — 署名生成・再試行ロジックをカプセル化し、payload ログの PII フィルタリングも実装する。

### 4.3 ダッシュボードデータセットエクスポート
- **CLI**: `analysis/export_dashboard_data.py`
  - 拡張仕様
    - `--dataset` の複数指定 (`--dataset ev_history --dataset slippage` 等)。
    - `--manifest out/dashboard/manifest.json` で export バンドルのメタデータを生成。
    - `--provenance` JSON をオプション指定し、コマンド・コミットハッシュ・入力パスを埋め込む。
    - `--heartbeat-file ops/dashboard_export_heartbeat.json` — 成功後に状態を書き込み。
    - `--upload-command` (オプション) — 共有ストレージへの転送コマンドを subprocess 経由で起動。
  - データセット要件
    1. **EV history**: `ops/state_archive/**` から最新N件 (`--ev-history-limit` 既定=32) を抽出。`strategy`, `symbol`, `ev_alpha`, `ev_beta`, `win_rate_lcb`。
    2. **Slippage telemetry**: `reports/portfolio_samples/router_demo/telemetry.json` を読み、`slippage_bps`, `fill_count`, `window_days` を保持。
    3. **Turnover summary**: `runs/index.csv` + `runs/<id>/daily.csv` で `avg_trades_per_day`, `drawdown_pct` を算出。
    4. **Latency rollups**: `ops/signal_latency_rollup.csv` を1時間単位で整形。
  - 出力は `out/dashboard/<dataset>.json` とし、manifest に `sequence`, `generated_at`, `checksum_sha256`, `row_count` を記録。`sequence` は `manifest` 既存値 +1 で連番を保証する。更新は `tmp_manifest` を生成してから `os.replace` で差し替え、`fcntl` ロックを取って排他する。
  - 8週間の履歴を `ops/dashboard_export_history/` に保持し、古いファイルを削除。削除前に `ops/dashboard_export_archive_manifest.json` に記録する。
  - `--upload-command` が指定された場合は `subprocess.run` で実行し、`returncode != 0` なら `status="error"`, `error_code="upload_failed"` を設定。
  - `--provenance` が未指定でも `AutomationContext` から `command`, `commit_sha`, `inputs` を自動補完する。
  - `ops/dashboard_export_heartbeat.json` には `datasets`, `last_success_at`, `last_failure` (`job_id`, `error_code`) を記録。

## 5. データモデル

### 5.1 CSV / JSON フィールド一覧
| Artefact | フィールド | 型 | 説明 |
| --- | --- | --- | --- |
| `ops/signal_latency.csv` | `timestamp_utc` | ISO8601 | サンプル取得時刻 (UTC)。 |
|  | `source` | string | 取得元 (router_demo, broker_api etc)。 |
|  | `latency_ms` | int | 単発サンプル (ms)。 |
|  | `ingest_latency_ms` | int | オーケストレーター開始からサンプル採取までの遅延。 |
| `ops/signal_latency_rollup.csv` | `hour_utc` | ISO8601 (hour) | 集計対象の時間ブロック。 |
|  | `p50_ms` | int | 中央値レイテンシ。 |
|  | `p95_ms` | int | 95% レイテンシ。 |
|  | `breach_flag` | bool | SLO違反時 true。 |
|  | `breach_streak` | int | 連続違反回数。 |
| `ops/automation_runs.log` | `job_id` | string | `YYYYMMDDThhmmssZ-<job>` 形式。 |
|  | `status` | enum[`ok`,`error`,`skipped`,`dry_run`] | ジョブ結果。 |
|  | `duration_ms` | int | 実行時間。 |
|  | `attempts` | int | 再試行回数。 |
|  | `artefacts` | array | 出力パス一覧。 |
|  | `diagnostics` | object | `error_code`, `error_message`, `retry_after` 等。 |
| `ops/automation_runs.sequence` | `value` | int | 直近で発行した `sequence` 番号。原子的に更新。 |
| `ops/weekly_report_history/*.json` | `schema_version` | string | JSON Schema バージョン。 |
|  | `alerts` | array | 違反サマリー (`id`, `severity`, `message`, `evidence_url`)。 |
|  | `payload_checksum_sha256` | string | Payload のチェックサム。 |
| `out/dashboard/manifest.json` | `dataset` | string | データセット名。 |
|  | `sequence` | int | 連番。 |
|  | `checksum_sha256` | string | 出力ファイルのハッシュ。 |
|  | `row_count` | int | 出力レコード数。 |
| `ops/signal_latency_archive/manifest.jsonl` | `job_id` | string | アーカイブファイルの生成ジョブ ID。 |
|  | `path` | string | gzip されたアーカイブファイルへの相対パス。 |
|  | `sha256` | string | アーカイブファイルのハッシュ。 |
|  | `row_count` | int | アーカイブへ退避したサンプル数。 |

### 5.2 JSON Schema (ダイジェスト)
- `schemas/observability_weekly_report.schema.json`
  - `schema_version`: enum of known versions。`$schema`/`$id` を明示。
  - `latency`: object (`p50_ms`, `p95_ms`, `breaches` array with minItems=0, `pending_alerts`: integer)。
  - `portfolio`: object (`budget_status`: enum[`normal`,`warning`,`breach`], `drawdown_pct`: number, `max_drawdown_pct`: number)。
  - `runs`: array of objects with `run_id` (pattern `^[A-Z0-9_]+`), `mode`, `start_ts`, `end_ts`, `sharpe`, `win_rate`, `turnover_per_day`。
  - `alerts`: array with `severity`: enum[`info`,`warning`,`critical`], `notified_channels`: array, `evidence_path`: string。
  - `payload_checksum_sha256`: string | format `^[A-F0-9]{64}$`。
- `schemas/dashboard_manifest.schema.json`
  - `datasets`: array of objects with `dataset`, `sequence`, `generated_at`, `checksum_sha256`, `row_count`, `source_hash`。
  - `provenance`: object storing `command`, `commit_sha`, `inputs` (array of path strings)。`inputs` は minItems=1。
  - `heartbeat`: object optional, `last_success_at`, `last_failure`。
- `schemas/signal_latency_archive.schema.json`
  - `job_id`: string (`^[0-9TZ:-]+-latency$`)
  - `path`: string (relative path, `.csv.gz` suffix required)。
  - `sha256`: string (`^[a-f0-9]{64}$`)、`row_count`: integer (minimum 1)。

## 6. ロギング & モニタリング
- `scripts/_automation_logging.py`
  - `log_automation_event(job_id, status, **kwargs)` → 1 行 JSON を `ops/automation_runs.log` に追記。`fcntl` ロックで排他し、書き込み前に JSON Schema (`schemas/automation_run.schema.json`) をチェックする。
  - 代表例: `{ "job_id": "20260627T0030Z-latency", "status": "ok", "duration_ms": 3100, "attempts": 1, "artefacts": ["ops/signal_latency.csv"], "alerts": [], "diagnostics": {"config_version": "2026-06-27"} }`
  - `log_automation_event_with_sequence` を提供し、`ops/automation_runs.sequence` に保持する最終 sequence 番号を読み出して +1 した値を `sequence` として設定。書き込みと同時にシーケンスファイルを原子的に更新し、連番欠損時には `status="warning"`, `error_code="sequence_gap"` を出力してオペレーターへ通知できるようにする。
- Heartbeatファイル
  - `ops/dashboard_export_heartbeat.json` — `{"job_id": "...", "generated_at": "...", "datasets": {"ev_history": "ok", ...}}`。更新は `tempfile.NamedTemporaryFile`→`os.replace` で原子的に行う。
  - `ops/latency_job_heartbeat.json` — レイテンシジョブが生成 (`next_run_at`, `last_breach_at`, `pending_alerts`)。`pending_alerts>0` の場合は `status="warning"` をセット。
  - `ops/weekly_report_heartbeat.json` を追加し、最終成功日時と `last_webhook_status_code` を保持。
- 監視対象ログは Filebeat 等で転送できるよう 1 行 JSON を維持。失敗ステータスは `status="error"` + `error_code`, `error_message`, `diagnostics.retry_after`。ログの最大サイズは 4KB 未満に制限し、過大な payload は `diagnostics.truncated=true` でマークする。
- `scripts/verify_observability_job.py` を夜間ジョブに組み込み、`ops/automation_runs.log` の JSON Schema 準拠、心拍ファイルのタイムスタンプ鮮度 (`<6h`)、`sequence` 連番を検証。失敗時は `ops/automation_runs.log` に `status="error"`, `error_code="verification_failed"` を追記する。

## 7. テスト戦略
- **ユニットテスト**
  - `tests/test_latency_rollup.py` — 集計結果、ローテーション閾値、SLO違反計数、`breach_streak` 更新、`gzip` アーカイブ生成。
  - `tests/test_weekly_payload.py` — schema 準拠、欠損データ時のエラー挙動、HMAC 署名生成、429 応答時の再試行バックオフ。
  - `tests/test_dashboard_datasets.py` — 各データセットのフィールド、値域チェック、manifest 連番更新、`row_count`/`checksum` 整合。
  - `tests/test_automation_logging.py` — `log_automation_event` の排他制御、sequence ギャップ検出、JSON Schema 準拠。
- **統合テスト**
  - `tests/test_observability_automation.py`
    - `CliRunner` で `run_daily_workflow.py --observability --dry-run` を実行し、想定 artefact が生成されることを検証。
    - 連続SLO違反シナリオで webhook payload に `severity=critical` が含まれることを確認し、`pending_alerts` が heartbeat に反映されることを検証。
    - Webhook 失敗時に再試行が呼ばれ、`ops/automation_runs.log` の `attempts` が増加していることを検証。`sequence` 連番が崩れないことを確認。
    - `--upload-command` の異常終了が `error_code="upload_failed"` を記録するかを確認。
- **エンドツーエンド**
  - ステージング環境で cron を 15分周期に設定し、24時間分のログを収集。`docs/checklists/p3_observability_automation.md` に沿って確認し、`scripts/verify_observability_job.py` の nightly 検証結果を runbook に追記。
  - 週次レポートdry-runを1週間継続し、Slack模擬エンドポイントで署名検証が成功すること、および `last_webhook_status_code=200` が heartbeat に記録されることを確認。
  - ダッシュボードバンドルを S3 仮想環境へアップロードし、`ops/dashboard_export_archive_manifest.json` からの復元手順を演習。

## 8. リリース手順
1. **M1: CLI Hardening (開発ブランチ)**
   - 各CLI拡張 + 新規モジュール/スキーマ + ユニットテストを揃え、`python3 -m pytest tests/test_latency_rollup.py tests/test_weekly_payload.py tests/test_dashboard_datasets.py tests/test_automation_logging.py` をグリーンにする。
   - `schemas/automation_run.schema.json` / `schemas/dashboard_manifest.schema.json` を生成し、CI の schema 検証ジョブを追加。
   - レビュー後に main へマージし、`docs/task_backlog.md` / `docs/todo_next.md` / `state.md` を同期。
2. **M2: Scheduler Dry Run**
   - `run_daily_workflow.py --observability --dry-run` を cron に設定し、`ops/automation_runs.log` を `scripts/verify_observability_job.py` で検証。
   - Dry-run 成果物を `docs/progress_phase3.md` にリンクし、`ops/dashboard_export_history/` の回転が働くことを確認。
3. **M3: Production Cutover**
   - Webhook/ストレージ本番URLを注入し、初回実行のログと artefact (`ops/automation_runs.log`, `ops/weekly_report_history/`, `out/dashboard/`) を保存。
   - 1週間監視し、失敗時の再実行手順とアラートエスカレーションルート（Slack/PD/メール）を runbook に追記。
   - Secrets ローテーション手順を演習し、`ops/credentials.md` に反映。
4. **M4: Post-launch Review**
   - KPI (SLO違反件数、再試行回数、平均 export 時間、アップロード失敗率) をまとめ、`docs/progress_phase3.md` で公開。
   - バックログへ follow-up を登録し、必要なら P4 以降の自動復旧タスクを起票。

## 9. リスクと対策 (詳細)
| リスク | 兆候 | 対策 | バックアップ |
| --- | --- | --- | --- |
| ロック取得失敗による多重実行 | `status="skipped"` が連続 | Cron 側で `flock` ラッパを追加、CLI 内で jitter を導入 | `ops/signal_latency_archive/` の CSV を nightly で整合チェック |
| Webhook署名不一致 | `response_code=401`, `error="signature_mismatch"` | 署名前に payload を canonical JSON 化し、単体テストで golden 値を検証 | `--dry-run-webhook` を用いたマニュアル送信手順を runbook に記載 |
| ダッシュボードデータ欠損 | Manifest の `checksum` が更新されない | Export後に `scripts/verify_dashboard_bundle.py` を自動実行 | 直近成功バンドルを `ops/dashboard_export_history` から復元 |
| ストレージ転送失敗 | `upload_status=error` | subprocess の戻り値を検証し再試行 | ストレージ運用チームへ即連絡、ローカル artefact を保持 |
| Heartbeat ファイル破損 | `json.decoder.JSONDecodeError` / `last_success_at` 欠落 | `tempfile` 経由で原子更新、`scripts/verify_observability_job.py` で整合チェック | 最新成功ログから再生成、S3/バックアップから復旧 |
| Secrets ローテーション漏れ | `OBS_WEEKLY_WEBHOOK_URL` 期限切れ、`status="error", error_code="auth_failed"` | `ops/credentials.md` に有効期限と責任者を記載し、月次レビューで更新 | 旧 Secret を 1 週間保持し、緊急時に切り戻せるよう記録 |
| `ops/automation_runs.log` 連番欠損 | `sequence_gap` 警告が継続 | `log_automation_event_with_sequence` で検出し、CI で JSON Schema チェックを追加 | `ops/automation_runs.log` を再生成 (`scripts/rebuild_automation_log.py`) |

## 10. 今後のアクション
- `docs/checklists/p3_observability_automation.md` を作成し、本設計の DoD チェック項目を列挙。
- `docs/state_runbook.md` にレイテンシ監視・週次レポート・ダッシュボードエクスポートの新規セクションを追加。
- `ops/credentials.md` (未作成) を起票し、Webhook シークレットのローテーション手順と責任者を文書化。
- ストレージアップロードコマンド (例: `aws s3 cp`) のテンプレートを `scripts/templates/` に追加検討。
- `scripts/verify_observability_job.py` / `scripts/rebuild_automation_log.py` の仕様ドラフトを `docs/templates/` に追加。
- `docs/progress_phase3.md` に Dry Run / Cutover / Post-review の成果指標と検証ログを追記。
