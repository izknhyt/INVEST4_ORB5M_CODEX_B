# DoD チェックリスト — P3 観測性自動化

- タスク名: フェーズ3 観測性オートメーション移行（レイテンシ監視・週次レポート・ダッシュボード輸出）
- バックログ ID / アンカー: [P3: 観測性・レポート自動化](../task_backlog.md#p3-観測性・レポート自動化)
- 担当: <!-- operator_name -->
- チェックリスト保存先: docs/checklists/p3_observability_automation.md

## Ready 昇格チェック項目
- [ ] [docs/plans/p3_observability_automation.md](../plans/p3_observability_automation.md) と [docs/phase3_detailed_design.md](../phase3_detailed_design.md) を再読し、実装対象 CLI・ロギング契約・テスト要件を洗い出した。
- [ ] [docs/observability_dashboard.md](../observability_dashboard.md) / [docs/state_runbook.md](../state_runbook.md) / [docs/task_backlog.md#p2-マルチ戦略ポートフォリオ化](../task_backlog.md#p2-マルチ戦略ポートフォリオ化) を確認し、フェーズ2成果物（router demo サンプル、`reports/portfolio_summary.json`, `runs/index.csv` 等）が最新で欠損なく参照できる状態である。
- [ ] `run_daily_workflow.py --observability --dry-run` を実行し、既存のチェーン（latency→weekly→dashboard）がクラッシュせずに終了することを確認したログを保存した。
- [ ] Secrets (`OBS_WEEKLY_WEBHOOK_URL`, `OBS_WEBHOOK_SECRET` など) の保管場所とローテーション責任者を `ops/credentials.md` で再確認し、プレリリース時に実行する煙試験 (`scripts/verify_observability_job.py --check-secrets`) の段取りを整理した。
- [ ] Cron / CI スケジューラから `configs/observability/*.yaml` を指定できることを確認し、必要なアクセス権限（書き込み先: `ops/`, `out/dashboard/`, 共有ストレージ）が揃っている。

## DoD (Definition of Done)
- [ ] **共通オートメーション基盤を整備した。**
  - [ ] `scripts/_automation_logging.py`（または同等ヘルパー）を実装し、`log_automation_event(job_id, status, artefacts, alerts, diagnostics, attempts, duration_ms)` が `ops/automation_runs.log` へ 1 行 JSON を追記するよう統合した。
  - [ ] `scripts/_automation_context.py`（または既存ユーティリティ）で `AutomationContext`（commit SHA, command line, secrets, config パス等）を組み立て、全ジョブが同じ経路で参照する。
- [x] `scripts/verify_observability_job.py` を追加し、`--job-id`, `--check-secrets`, `--check-log` / `--sequence-file` / `--heartbeat` / `--dashboard-manifest` でスケジューラ→CLI→成果物のトレース検証が出来るようにした。`docs/state_runbook.md` にコマンド例と失敗時の復旧ポイントを追記済み。
  - [ ] `run_daily_workflow.py --observability` サブコマンドを更新し、latency→weekly→dashboard の順にジョブを実行、失敗時に後続をスキップし `status="error"` をログへ記録するチェーン制御を実装した。

- [ ] **シグナルレイテンシ監視ジョブを自動化した。**
  - [x] `scripts/analyze_signal_latency.py` に以下の機能を実装し、ヘルプ出力とドキュメントを更新した。
    - `--raw-retention-days`, `--rollup-retention-days`, `--rollup-output`, `--lock-file`, `--alert-config`, `--dry-run-alert` フラグ。
    - ロック取得失敗時の `status="skipped"` ログ、`ops/signal_latency.csv` のローテーション（10MB 超で gzip 圧縮し manifest を更新）、ロールアップ生成 (`analysis/latency_rollup.aggregate`) と retention。
    - 連続 SLO breach の追跡、Webhook ペイロード生成、`alerts` ブロックの記録。
    - stdout JSON サマリー（`samples_written`, `rollups_written`, `breach_count`, `breach_streak`, `next_rotation_bytes`, `lock_latency_ms`）。
    - [x] `analysis/latency_rollup.py` を追加し、ロールアップ計算が CLI / pytest 双方から再利用できることを証明した。
    - [x] ローテーション時の manifest (`ops/signal_latency_archive/manifest.jsonl`) とハートビート (`ops/latency_job_heartbeat.json`) を更新し、最新エントリに `job_id` / `checksum_sha256` / `row_count` を残した。
  - [x] `python3 -m pytest tests/test_analyze_signal_latency.py`（新設）や既存テストにより、SLO breach ロジック・ローテーション・ロックガードが回帰テストで担保されることを確認し、テストコマンドをログ化した。

- [x] **週次ヘルスレポートの自動生成と配信を固定化した。**
  - [x] `scripts/summarize_runs.py` を拡張し、`--weekly-payload`, `--payload-schema`, `--webhook-url-env`, `--webhook-secret-env`, `--max-retries`, `--retry-wait-seconds`, `--out-dir`, `--dry-run-webhook` を実装した。
  - [x] 週次 payload ビルダ (`analysis/weekly_payload.py`) を実装し、`WeeklyPayloadContext` / `WeeklyPayload` dataclass で runs / portfolio / latency rollup を集約、`ensure_complete()` で必須フィールド検証を行うようにした。
  - [x] JSON Schema `schemas/observability_weekly_report.schema.json` を整備し、payload 生成時に検証エラーを `status="error"`, `error_code="schema_validation_failed"` としてログ化する流れを構築した。
  - [x] Webhook 署名 (`X-OBS-Signature`), 再試行, ドライラン artefact (`out/weekly_report/<job_id>.json`) の生成、成功時の `ops/weekly_report_history/<week_start>.json` + `.sig` 保存と manifest 追記を実装した。
  - [x] `python3 -m pytest tests/test_weekly_payload.py tests/test_summarize_runs.py::test_weekly_payload_cli_success` を通し、schema 準拠と webhook 署名ロジックの回帰を確認した。

- [x] **ダッシュボードデータセットのエクスポートを自動化した。**
  - [x] `analysis/export_dashboard_data.py` に `--dataset`, `--manifest`, `--provenance`, `--heartbeat-file`, `--upload-command` を追加し、EV history / slippage telemetry / turnover summary / latency rollups の各データセットを `out/dashboard/<dataset>.json` に出力する動線を整備した。
  - [x] 生成される manifest (`out/dashboard/manifest.json`) に `sequence`, `generated_at`, `checksum_sha256`, `row_count`, `datasets` 情報を追記し、排他制御 (`fcntl` ロック + `os.replace`) を実装した。
  - [x] `ops/dashboard_export_history/`・`ops/dashboard_export_archive_manifest.json`・`ops/dashboard_export_heartbeat.json` を更新するローテーションとヘルスビートを書き、60日/8週間の保管ポリシーが守られていることを確認した。
  - [x] `python3 -m pytest tests/test_dashboard_datasets.py`（新設）を通し、各データセットのフィールド検証と manifest 連番更新が回帰テストでカバーされていることを確認した。

- [ ] **ドキュメントと運用フローを更新した。**
  - [ ] `docs/state_runbook.md#observability-automation`（新設セクション）と [docs/observability_dashboard.md](../observability_dashboard.md) に CLI コマンド、期待 artefact、アラートエスカレーション、手動復旧手順を追記した。
  - [ ] `docs/plans/p3_observability_automation.md` / `docs/phase3_detailed_design.md` の差分（例: 新規フラグ、manifest フォーマット）を反映し、DoD チェックリストとの整合を取った。
  - [ ] `docs/task_backlog.md#p3-観測性・レポート自動化` に進捗メモと DoD リンクを追加し、`docs/todo_next.md` / `docs/todo_next_archive.md` / `state.md` と同期した。
  - [ ] `README.md` ないしドキュメントポータルへ、観測性オートメーションの再現手順・主要 CLI の導線を追記し、初見のレビュワーが該当チェックリストに辿り着けるようにした。

- [ ] **運用確認と記録を完了した。**
  - [ ] `python3 -m pytest` と観測性向けの追加テストコマンド（例: `python3 scripts/run_daily_workflow.py --observability --dry-run --config configs/observability/full_chain.yaml`, `python3 scripts/verify_observability_job.py --job-id $(date -u +%Y%m%dT%H%M%SZ)-observability --check-log ops/automation_runs.log`）を実行し、結果を `state.md` / PR ログに記録した。
  - [ ] 各ジョブの `ops/automation_runs.log` エントリと artefact（`ops/signal_latency.csv`, `ops/signal_latency_rollup.csv`, `ops/weekly_report_history/*.json`, `out/dashboard/*.json` 等）をレビューし、SLO breach・再試行・アップロード結果が DoD に沿って記録されていることを確認した。
  - [ ] 60日保管対象（週次 payload, ダッシュボード bundle）とアーカイブ manifest の整合を spot check し、破損ファイルが無いことを確認したログを保存した。
  - [ ] 成果物とログをレビュワーへ共有し、共有先・日時・確認メモを `state.md` / `docs/todo_next_archive.md` に追記した。

> チェック完了後は `docs/todo_next.md` / `docs/todo_next_archive.md` と `state.md` の同期、`docs/observability_dashboard.md` へのリンク更新、成果物フォルダの保守を忘れずに。週次/日次ジョブの運用が軌道に乗ったら、フェーズ3 以降の自動化拡張（例: フェイルセーフ/再解析ジョブ）のバックログ化も検討すること。
