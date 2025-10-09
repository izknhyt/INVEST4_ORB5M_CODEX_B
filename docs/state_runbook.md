# state.json 運用ガイド

EV ゲートや滑り学習などの内部状態を `state.json` として保存し、再実行時に復元するためのランブックです。セッション全体の流れは [docs/codex_quickstart.md](codex_quickstart.md) を参照し、本書では state 周辺のアクションをチェックリスト形式で整理します。各ドキュメントの役割は [docs/documentation_portal.md](documentation_portal.md) の Orientation Cheat Sheet で再確認し、Portal の "Documentation Hygiene Checklist" に沿って更新履歴を残してください。

## 保存チェックリスト
- [ ] `BacktestRunner` / `RunnerExecutionManager` の処理完了後に `runner.export_state()` を呼び出した。
- [ ] 返却値を JSON として保存（既定: `ops/state_archive/<strategy>/<symbol>/<mode>/`）。
- [ ] CLI (`scripts/run_sim.py`) を利用する場合は `--out-dir` 配下に `state.json` が生成されることを確認した。
- [ ] 自動アーカイブが不要な検証では manifest `runner.cli_args.auto_state: false` を設定した。
- [ ] EV プロファイル更新が不要な実験では `runner.cli_args.aggregate_ev: false` を併用し、不要な再集計を避けた。
- [ ] 保存後に `scripts/aggregate_ev.py` が走行したかログを確認し、必要に応じて `configs/ev_profiles/` を更新した。
- [ ] README / [docs/documentation_portal.md](documentation_portal.md) の該当テーブルに state アーカイブ関連の手順が反映されているか確認した。

## ロードチェックリスト
- [ ] 自動ロードを有効化する manifest では、`ops/state_archive/...` の最新ファイルが参照されることを CLI ログで確認した。
- [ ] 自動ロードを避けたいテストは manifest を複製し `auto_state: false` を明示した。
- [ ] コードからロードする場合は `runner.load_state_file(path)` または `runner.load_state(state_dict)` を利用し、`RunnerConfig` とシンボルが一致しているか検証した。
- [ ] `RunnerLifecycleManager._apply_state_dict` がフォーマット変更に追随できているか確認し、差分があればテストを追加した。
- [ ] `config_fingerprint` 変更時に古い state を再利用しない（`tests/test_runner.py::test_load_state_skips_on_config_fingerprint_mismatch` 参照）。
- [ ] Portal の Orientation Cheat Sheet に最新のロード手順が載っているか確認し、必要な差分を同じコミットで反映した。

## オンデマンド起動（ノート PC 向け）
- 基本コマンド:
  ```bash
  python3 scripts/run_daily_workflow.py --ingest --check-data-quality --update-state --benchmarks --state-health --benchmark-summary
  ```
- 取り込みの代表オプション:
  - ローカル CSV: `python3 scripts/pull_prices.py --source data/usdjpy_5m_2018-2024_utc.csv`
  - Dukascopy 標準経路: `python3 scripts/run_daily_workflow.py --ingest --use-dukascopy --symbol USDJPY --mode conservative`
  - フォールバック制御:
    - `--local-backup-csv path/to.csv` — 手元バックフィルを利用。
    - `--disable-synthetic-extension` — 合成バーを生成せず鮮度遅延を観測。
    - `--dukascopy-offer-side ask` — ASK 側取得へ切替。
- 実行後の確認ポイント:
  - `reports/data_quality/<symbol>_<tf>_summary.json` / `_gap_inventory.{csv,json}` を開き、`coverage_ratio` や
    `calendar_day_summary.warnings` がしきい値内であることを確認。必要に応じて
    `--data-quality-coverage-threshold` / `--data-quality-calendar-threshold` を調整する。Ops 通知が必要な場合は
    `--webhook` を指定し、`data_quality_failure` アラートが配信されたか（必要なら `--data-quality-webhook-timeout`
    を調整）と対応内容を `state.md` に記録する。
  - `ops/runtime_snapshot.json.ingest_meta.<symbol>_<tf>` の `source_chain` / `freshness_minutes`。
  - `ops/logs/ingest_anomalies.jsonl` の異常記録。
  - ローカル CSV 利用時に `local_backup_path` が期待通りか。
  - データ品質監査が終了コード 1 で停止した場合は `reports/data_quality/` の JSON/CSV を確認し、欠損日の再取得または
    フォールバック経路の再実行を行う。復旧後は `--check-data-quality` を再実行してアラート解消を確認し、原因と対応を
    `state.md` に記録する。
- API 直接取得を再開する場合:
  - `configs/api_ingest.yml` の `activation_criteria` を満たしているか確認。
  - シークレットの暗号化保存と環境変数同期を実施。
  - `python3 scripts/run_daily_workflow.py --ingest --use-api ...` をドライランし、フォールバックチェーンをログで確認。

## 常駐インジェスト運用
- 基本コマンド:
  ```bash
  python3 scripts/live_ingest_worker.py --symbols USDJPY --modes conservative --interval 300
  ```
- 運用チェック:
  - [ ] `--raw-root` / `--validated-root` / `--features-root` を環境に合わせて設定した。
  - [ ] 停止ファイル `ops/live_ingest_worker.stop`（`--shutdown-file` で差し替え可）を監視した。
  - [ ] 監視ポイント: `ops/runtime_snapshot.json.ingest.<SYMBOL>_5m`、`ops/logs/ingest_anomalies.jsonl`、`runs/active/state.json`。

## インシデントリプレイ
- ディレクトリ構成: `ops/incidents/<incident_id>/`
- 必須ファイル:
  - `incident.json`（発生日、シンボル、損益、一次報告）
  - `replay_params.json`（Notebook / CLI 引数）
  - `replay_notes.md`（`## Summary` / `## Findings` / `## Actions`）
  - `artifacts/`（画像・追加ログ）
- Notebook 実行: `analysis/incident_review.ipynb` で `scripts/run_sim.py --manifest ...` を呼び出し、成果物を `runs/incidents/<incident_id>/` へ整理する。
- 共有フロー: `replay_notes.md` の要約を `docs/task_backlog.md` 該当項目と `state.md` の `## Log` に転記し、必要に応じてステークホルダーへ共有する。
- Portal の "First Session Playbook" / "Documentation Hygiene Checklist" を用いて、インシデント関連ランブックのリンクが網羅されているか確認する。

## 推奨運用メモ
- `ops/state_archive/` の世代管理は `python3 scripts/prune_state_archive.py --dry-run --keep 5` で確認してから実行する。
- `RunnerConfig` を大幅に変更した場合は古い state を破棄するか再計測する。
- `python3 scripts/check_state_health.py` を日次実行し、`ops/health/state_checks.json` の異常をレビューする。
- Ready 昇格時は `python3 scripts/manage_task_cycle.py --dry-run start-task --anchor <...>` で手順をプレビューし、適用時は `python3 scripts/manage_task_cycle.py start-task --anchor <...>` を実行する（Quickstart / Workflow と同一手順）。
- Wrap-up では `python3 scripts/manage_task_cycle.py --dry-run finish-task --anchor <...>` で close-out を確認し、適用時に `python3 scripts/manage_task_cycle.py finish-task --anchor <...>` を用いる。アンカーは常に [docs/codex_quickstart.md](codex_quickstart.md) と同期させる。
- Ready 昇格時は [docs/templates/dod_checklist.md](templates/dod_checklist.md) をコピーし、`docs/checklists/<task>.md` で進捗を追跡する。

## 参考リンク
- ワークフロー詳細: [docs/codex_workflow.md](codex_workflow.md)
- オンデマンド/常駐インジェスト設計: [docs/api_ingest_plan.md](api_ingest_plan.md)
- Sandbox / 承認ガイド: [docs/codex_cloud_notes.md](codex_cloud_notes.md)
- Incident 再現ノート: [analysis/incident_review.ipynb](../analysis/incident_review.ipynb)
