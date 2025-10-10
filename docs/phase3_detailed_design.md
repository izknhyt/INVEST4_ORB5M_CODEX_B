# フェーズ3 詳細設計書 — 観測性自動化

> 関連資料: [docs/plans/p3_observability_automation.md](plans/p3_observability_automation.md), [docs/observability_dashboard.md](observability_dashboard.md), [docs/state_runbook.md](state_runbook.md)

## 1. 目的・ゴール
- フェーズ3では、フェーズ2で整備したテレメトリとレポート生成フローを完全自動化し、運用担当者がダッシュボードと通知のみで健康状態を把握できる状態にする。
- 自動化対象は以下の3本柱で構成する。
  1. **シグナルレイテンシ監視** — 15分間隔のサンプリング、ロールアップ、SLO違反通知を自動化。
  2. **週次ヘルスレポート** — 主要KPIの集約とWebhook配信を標準化。
  3. **ダッシュボードデータセット** — EV/スリッページ/ターンオーバー等のデータエクスポートと配布を定期化。
- Definition of Done (DoD)
  - すべての自動化ジョブが `run_daily_workflow.py` または専用CLIで再現でき、`python3 -m pytest` と追加テストで回帰保証されている。
  - `ops/automation_runs.log` に各ジョブの `job_id` / `status` / `artefacts` / `duration_ms` が記録され、失敗時にはエスカレーション手順が runbook に明記されている。
  - Weeklyレポートとダッシュボードバンドルが60日分保持され、復旧手順が `docs/state_runbook.md` に掲載されている。

## 2. 背景と前提条件
- フェーズ2でリフレッシュした `reports/portfolio_summary.json`、router demo サンプル (`reports/portfolio_samples/router_demo/**`)、`runs/index.csv` を安定供給できることを前提とする。
- 既存の CLI (`scripts/analyze_signal_latency.py`, `scripts/summarize_runs.py`, `analysis/export_dashboard_data.py`) を拡張する設計とし、大規模な再実装は行わない。
- シークレット (`OBS_WEEKLY_WEBHOOK_URL`, `OBS_WEBHOOK_SECRET`) はオーケストレーター側で注入し、リポジトリ内では環境変数読み出しのみを行う。
- 監視対象となるログ / JSON / CSV は Git にコミットせず、`ops/` と `reports/` 配下の回転ポリシーに従って管理する。

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
- ジョブ実行は Cron もしくは CI (GitHub Actions 等) から `run_daily_workflow.py` サブコマンド、または dedicated CLI を呼び出す。
- すべてのジョブは `ops/automation_runs.log` に構造化JSON (1 行 = 1 レコード) で自己申告し、`job_id` に `YYYYMMDDThhmmssZ-<job>` 形式を採用する。
- 失敗時は exit code ≠0 とし、stdout では JSON サマリー、stderr では human readable な診断メッセージを出す。

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
    1. ロック取得 (`fcntl.flock` or portal util)。保持できない場合は警告ログを出して即終了。
    2. `ops/signal_latency.csv` へ追記。ファイルサイズ > 10MB で `ops/signal_latency_archive/YYYY/MM/<job_id>.csv` へ回転。
    3. ロールアップ生成: `analysis.latency_rollup.aggregate(samples, window="1H")`。
    4. SLO評価: `p95_latency_ms > threshold` が連続 `N` 回なら `alerts.append(...)`。
    5. 必要に応じて週次Webhookスキーマ互換の alert payload を生成し、`ops/automation_runs.log` に `alerts` ブロックを記録。
    6. 終了時にヘルスサマリー JSON を stdout へ出力 (`samples_written`, `rollups_written`, `breach_count`, `next_rotation_bytes`)。
- **依存モジュール**
  - `analysis/latency_rollup.py` (新規) — pandas 依存を避け、純Pythonで時間窓集計を行うヘルパ。
  - `scripts/_automation_logging.py` (新規) — `log_automation_event(job_id, status, payload)` を提供。各ジョブが共通利用。
- **監視と通知**
  - 連続違反が2回で warning, 3回で critical → Webhook + PD。
  - `--dry-run-alert` フラグで通知抑制しつつ payload を `out/latency_alerts/<job_id>.json` に出力。

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
    1. `runs/index.csv`, `reports/portfolio_summary.json`, `ops/signal_latency_rollup.csv` を読み込み、欠損/フォーマットを検証。
    2. 週次集計を `analysis.weekly_payload.build(context)` に委譲。
    3. JSON Schema で検証し、失敗時は詳細を stderr に出力。
    4. Webhook 送信時は HMAC-SHA256 で署名 (`X-OBS-Signature`)。レスポンスが 5xx の場合は指数バックオフ再試行。
    5. 成功時に `ops/weekly_report_history/<week_start>.json` と `.../<week_start>.sig` を保存。
    6. 送信結果と checksum (`payload_checksum_sha256`) を `ops/automation_runs.log` に記録。
- **ユーティリティ**
  - `analysis/weekly_payload.py` (新規) — 週次KPI抽出と JSON 整形を担当。単体テストで schema 遵守を確認。
  - `schemas/observability_weekly_report.schema.json` (既存予定) — blueprint の schema を実体化。

### 4.3 ダッシュボードデータセットエクスポート
- **CLI**: `analysis/export_dashboard_data.py`
  - 拡張仕様
    - `--dataset` の複数指定 (`--dataset ev_history --dataset slippage` 等)。
    - `--manifest out/dashboard/manifest.json` で export バンドルのメタデータを生成。
    - `--provenance` JSON をオプション指定し、コマンド・コミットハッシュ・入力パスを埋め込む。
    - `--heartbeat-file ops/dashboard_export_heartbeat.json` — 成功後に状態を書き込み。
    - `--upload-command` (オプション) — 共有ストレージへの転送コマンドを subprocess 経由で起動。
  - データセット要件
    1. **EV history**: `ops/state_archive/**` から最新N件を抽出。`strategy`, `symbol`, `ev_alpha`, `ev_beta`, `win_rate_lcb`。
    2. **Slippage telemetry**: `reports/portfolio_samples/router_demo/telemetry.json` を読み、`slippage_bps`, `fill_count`, `window_days` を保持。
    3. **Turnover summary**: `runs/index.csv` + `runs/<id>/daily.csv` で `avg_trades_per_day`, `drawdown_pct` を算出。
    4. **Latency rollups**: `ops/signal_latency_rollup.csv` を1時間単位で整形。
  - 出力は `out/dashboard/<dataset>.json` とし、manifest に `sequence`, `generated_at`, `checksum_sha256` を記録。
  - 8週間の履歴を `ops/dashboard_export_history/` に保持し、古いファイルを削除。

## 5. データモデル

### 5.1 CSV / JSON フィールド一覧
| Artefact | フィールド | 型 | 説明 |
| --- | --- | --- | --- |
| `ops/signal_latency.csv` | `timestamp_utc` | ISO8601 | サンプル取得時刻 (UTC)。 |
|  | `source` | string | 取得元 (router_demo, broker_api etc)。 |
|  | `latency_ms` | int | 単発サンプル (ms)。 |
| `ops/signal_latency_rollup.csv` | `hour_utc` | ISO8601 (hour) | 集計対象の時間ブロック。 |
|  | `p50_ms` | int | 中央値レイテンシ。 |
|  | `p95_ms` | int | 95% レイテンシ。 |
|  | `breach_flag` | bool | SLO違反時 true。 |
| `ops/weekly_report_history/*.json` | `schema_version` | string | JSON Schema バージョン。 |
|  | `alerts` | array | 違反サマリー (`id`, `severity`, `message`, `evidence_url`)。 |
| `out/dashboard/manifest.json` | `dataset` | string | データセット名。 |
|  | `sequence` | int | 連番。 |
|  | `checksum_sha256` | string | 出力ファイルのハッシュ。 |

### 5.2 JSON Schema (ダイジェスト)
- `schemas/observability_weekly_report.schema.json`
  - `schema_version`: enum of known versions。
  - `latency`: object (`p50_ms`, `p95_ms`, `breaches` array with minItems=0)。
  - `portfolio`: object (`budget_status`: enum[`normal`,`warning`,`breach`], `drawdown_pct`: number)。
  - `runs`: array of objects with `run_id` (pattern `^[A-Z0-9_]+`), `mode`, `start_ts`, `end_ts`, `sharpe`, `win_rate`。
  - `alerts`: array with `severity`: enum[`info`,`warning`,`critical`], `notified_channels`: array。
- `schemas/dashboard_manifest.schema.json`
  - `datasets`: array of objects with `dataset`, `sequence`, `generated_at`, `checksum_sha256`。
  - `provenance`: object storing `command`, `commit_sha`, `inputs` (array of path strings)。

## 6. ロギング & モニタリング
- `scripts/_automation_logging.py`
  - `log_automation_event(job_id, status, **kwargs)` → 1 行 JSON を `ops/automation_runs.log` に追記。
  - 代表例: `{ "job_id": "20260627T0030Z-latency", "status": "ok", "duration_ms": 3100, "artefacts": ["ops/signal_latency.csv"], "alerts": [] }`
- Heartbeatファイル
  - `ops/dashboard_export_heartbeat.json` — `{"job_id": "...", "generated_at": "...", "datasets": {"ev_history": "ok", ...}}`
  - `ops/latency_job_heartbeat.json` — レイテンシジョブが生成 (`next_run_at`, `last_breach_at`)。
- 監視対象ログは Filebeat 等で転送できるよう 1 行 JSON を維持。失敗ステータスは `status="error"` + `error_code`, `error_message`。

## 7. テスト戦略
- **ユニットテスト**
  - `tests/test_latency_rollup.py` — 集計結果、ローテーション閾値、SLO違反計数。
  - `tests/test_weekly_payload.py` — schema 準拠、欠損データ時のエラー挙動、HMAC 署名生成。
  - `tests/test_dashboard_datasets.py` — 各データセットのフィールド、値域チェック、manifest 連番更新。
- **統合テスト**
  - `tests/test_observability_automation.py`
    - `CliRunner` で `run_daily_workflow.py --observability --dry-run` を実行し、想定 artefact が生成されることを検証。
    - 連続SLO違反シナリオで webhook payload に `severity=critical` が含まれることを確認。
    - Webhook 失敗時に再試行が呼ばれ、`ops/automation_runs.log` の `attempts` が増加していることを検証。
- **エンドツーエンド**
  - ステージング環境で cron を 15分周期に設定し、24時間分のログを収集。`docs/checklists/p3_observability_automation.md` に沿って確認。
  - 週次レポートdry-runを1週間継続し、Slack模擬エンドポイントで署名検証が成功することを記録。

## 8. リリース手順
1. **M1: CLI Hardening (開発ブランチ)**
   - 各CLI拡張 + 新規モジュール/スキーマ + ユニットテスト。
   - レビュー後に main へマージし、`docs/task_backlog.md` を更新。
2. **M2: Scheduler Dry Run**
   - `run_daily_workflow.py --observability --dry-run` を cron に設定し、`ops/automation_runs.log` をチェック。
   - Dry-run 成果物を `docs/progress_phase3.md` にリンク。
3. **M3: Production Cutover**
   - Webhook/ストレージ本番URLを注入し、初回実行のログと artefact を保存。
   - 1週間監視し、失敗時の再実行手順を runbook に追記。
4. **M4: Post-launch Review**
   - KPI (SLO違反件数、再試行回数) をまとめ、バックログへ follow-up を登録。

## 9. リスクと対策 (詳細)
| リスク | 兆候 | 対策 | バックアップ |
| --- | --- | --- | --- |
| ロック取得失敗による多重実行 | `status="skipped"` が連続 | Cron 側で `flock` ラッパを追加、CLI 内で jitter を導入 | `ops/signal_latency_archive/` の CSV を nightly で整合チェック |
| Webhook署名不一致 | `response_code=401`, `error="signature_mismatch"` | 署名前に payload を canonical JSON 化し、単体テストで golden 値を検証 | `--dry-run-webhook` を用いたマニュアル送信手順を runbook に記載 |
| ダッシュボードデータ欠損 | Manifest の `checksum` が更新されない | Export後に `scripts/verify_dashboard_bundle.py` を自動実行 | 直近成功バンドルを `ops/dashboard_export_history` から復元 |
| ストレージ転送失敗 | `upload_status=error` | subprocess の戻り値を検証し再試行 | ストレージ運用チームへ即連絡、ローカル artefact を保持 |

## 10. 今後のアクション
- `docs/checklists/p3_observability_automation.md` を作成し、本設計の DoD チェック項目を列挙。
- `docs/state_runbook.md` にレイテンシ監視・週次レポート・ダッシュボードエクスポートの新規セクションを追加。
- `ops/credentials.md` (未作成) を起票し、Webhook シークレットのローテーション手順と責任者を文書化。
- ストレージアップロードコマンド (例: `aws s3 cp`) のテンプレートを `scripts/templates/` に追加検討。
