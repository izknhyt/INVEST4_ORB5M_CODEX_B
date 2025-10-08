# state.json 運用ガイド

EV ゲートや滑り学習などの内部状態を `state.json` として保存し、再実行時に復元するためのランブックです。セッション全体の流れは [docs/codex_quickstart.md](codex_quickstart.md) を参照し、本書では state 周辺のチェックリストをアクション単位で整理します。

## 保存チェックリスト
- [ ] `BacktestRunner` 実行終了後に `runner.export_state()` を呼び出す。
- [ ] 返却値を JSON として保存する（既定: `ops/state_archive/<strategy>/<symbol>/<mode>/`）。
- [ ] CLI (`scripts/run_sim.py`) を使う場合は `--out-dir` 配下にも `state.json` が残ることを確認する。
- [ ] 自動アーカイブ不要なら manifest の `runner.cli_args.auto_state: false` を設定する。
- [ ] EV プロファイル更新が不要な実験では `runner.cli_args.aggregate_ev: false` を指定する。
- [ ] 保存後に `scripts/aggregate_ev.py` が実行されたかログで確認し、必要に応じて `configs/ev_profiles/` を更新する。

## ロードチェックリスト
- [ ] CLI で自動ロードしたい場合は manifest を既定のままにし、`ops/state_archive/...` の最新ファイルが利用されることを確認する。
- [ ] 自動ロードを避けたいテストでは manifest をコピーし `auto_state: false` を設定する。
- [ ] コードから読む場合は `runner.load_state_file(path)` または `runner.load_state(state_dict)` を使用し、`RunnerConfig` とシンボルの整合を確認する。
- [ ] `RunnerLifecycleManager._apply_state_dict` がフォーマット変更に対応しているか確認し、差分がある場合はテストを追加する。

## オンデマンド起動（ノートPC向け）
- 基本コマンド:
  ```bash
  python3 scripts/run_daily_workflow.py --ingest --update-state --benchmarks --state-health --benchmark-summary
  ```
- 取り込み系の追加例:
  - ローカル CSV: `python3 scripts/pull_prices.py --source data/usdjpy_5m_2018-2024_utc.csv`
  - Dukascopy 標準経路: `python3 -m scripts.run_daily_workflow --ingest --use-dukascopy --symbol USDJPY --mode conservative`
  - フォールバック/制御オプション:
    - `--local-backup-csv path/to.csv` — 手元バックフィルを利用。
    - `--disable-synthetic-extension` — 合成バーを生成せず鮮度遅延を観測。
    - `--dukascopy-offer-side ask` — ASK 側での取得に切替。
- 実行後に確認するメトリクス:
  - `ops/runtime_snapshot.json.ingest_meta.<symbol>_<tf>` の `source_chain` / `freshness_minutes`。
  - `ops/logs/ingest_anomalies.jsonl` の異常記録。
  - ローカル CSV 利用時は `local_backup_path` が正しいかチェック。
- API 直接取得を再開する場合:
  - `configs/api_ingest.yml` の `activation_criteria` を満たしているか確認。
  - シークレットを暗号化ストレージに保管し、環境変数と暗号化ファイルを同期。
  - `python3 -m scripts.run_daily_workflow --ingest --use-api ...` をドライランし、フォールバックチェーンをログで確認。

## 常駐インジェスト運用
- コマンド:
  ```bash
  python3 scripts/live_ingest_worker.py --symbols USDJPY --modes conservative --interval 300
  ```
- オプションチェックリスト:
  - [ ] `--raw-root` / `--validated-root` / `--features-root` を必要に応じて変更。
  - [ ] 停止ファイルは `ops/live_ingest_worker.stop`（`--shutdown-file` で差替え可）。
  - [ ] 監視ポイント: `ops/runtime_snapshot.json.ingest.<SYMBOL>_5m`、`ops/logs/ingest_anomalies.jsonl`、`runs/active/state.json`。

## インシデントリプレイ
- **対象ディレクトリ:** `ops/incidents/<incident_id>/`
- **必要ファイル:**
  - `incident.json`（発生日、シンボル、損益、一次報告）
  - `replay_params.json`（Notebook/CLI 引数）
  - `replay_notes.md`（`## Summary` / `## Findings` / `## Actions`）
  - `artifacts/`（画像・ログなど）
- **Notebook 実行:** `analysis/incident_review.ipynb` で `scripts/run_sim.py --manifest ...` を呼び出し、成果物は `runs/incidents/<incident_id>/` へ整理する。
- **共有フロー:** `replay_notes.md` の要約を `docs/task_backlog.md` 該当項目と `state.md` の `## Log` に転記。必要に応じてステークホルダーへ共有。

## 推奨運用メモ
- **バックアップ:** `ops/state_archive/` は `scripts/prune_state_archive.py --dry-run --keep 5` で整理可能。
- **互換性:** `RunnerConfig` を大幅に変更した場合は古い state を破棄するか再計測する。
- **ヘルスチェック:** `python3 scripts/check_state_health.py` を日次実行し、`ops/health/state_checks.json` をレビュー。
- **タスク同期:** `scripts/manage_task_cycle.py` の `start-task` / `finish-task` を優先使用し、アンカーは [docs/codex_quickstart.md](codex_quickstart.md) と揃える。
- **DoD チェックリスト:** Ready 昇格時は [docs/templates/dod_checklist.md](templates/dod_checklist.md) をコピーし、`docs/checklists/<task>.md` へ配置。

## 参考リンク
- ワークフロー詳細: [docs/codex_workflow.md](codex_workflow.md)
- オンデマンド/常駐インジェストの設計: [docs/api_ingest_plan.md](api_ingest_plan.md)
- sandbox/承認ガイド: [docs/codex_cloud_notes.md](codex_cloud_notes.md)
- Incident 再現ノート: [analysis/incident_review.ipynb](../analysis/incident_review.ipynb)
