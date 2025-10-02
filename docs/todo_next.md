# 次のアクション（目標指標達成フロー）

## 更新ルール
- タスクを完了したら、必ず `state.md` の該当項目をログへ移し、本ファイルのセクション（In Progress / Ready / Pending Review / Archive）を同期してください。
- `state.md` に記録されていないアクティビティは、このファイルにも掲載しない方針です。新しい作業を始める前に `state.md` へ日付と目的を追加しましょう。
- Ready または In Progress へ昇格させるタスクは、[docs/templates/dod_checklist.md](docs/templates/dod_checklist.md) を複製し `docs/checklists/<task-slug>.md` へ保存したうえで、該当エントリからリンクするか貼り付けてください。

## Ready 昇格チェックリスト
- 高レベルのビジョンガイド（例: [docs/logic_overview.md](docs/logic_overview.md), [docs/simulation_plan.md](docs/simulation_plan.md)）を再読し、昇格対象タスクが最新戦略方針と整合しているか確認する。
- `docs/progress_phase*.md`（特に対象フェーズの記録）を確認し、未完了の前提条件や検証ギャップがないかレビューする。
- 関連するランブック（例: `docs/state_runbook.md`, `docs/benchmark_runbook.md`）を再読し、必要なオペレーション手順が揃っているかを点検する。
- バックログ該当項目の DoD を最新化し、関係チームへ通知済みであることを確認する。
- DoD チェックリスト テンプレートをコピーし、Ready チェックの進捗とバックログ固有 DoD をチェックボックスで追跡している。

## Current Pipeline

### In Progress

- **ローリング検証パイプライン**（バックログ: `docs/task_backlog.md` → P1「ローリング検証 + 健全性モニタリング」） — `state.md` 2025-09-28, 2024-06-13, 2024-06-14, 2024-06-15, 2024-06-16 <!-- anchor: docs/task_backlog.md#p1-01-ローリング検証パイプライン -->
  - `scripts/run_benchmark_pipeline.py` の整備と `run_daily_workflow.py` 連携、期間指定リプレイ (`--start-ts` / `--end-ts`) の確認を継続中。
  - 次ステップ: ベンチマークランのローリング更新自動化と Sharpe / 最大 DD 指標の回帰監視強化。
  - 2025-10-16: 鮮度チェックが API インジェスト待ちで停止しているため、P1-04 を優先タスクとして切り出し。P1-04 完了後に再検証を予定。
  - 2025-09-29: Cron サンプルに `benchmark_pipeline_daily`（UTC 22:30）を追加し、ランブック閾値 (`--alert-*`/`--min-*`/`--benchmark-windows 365,180,90`/`--benchmark-freshness-max-age-hours 6`) を CLI へ反映。`python3 scripts/run_daily_workflow.py --benchmarks` ドライランで `ops/runtime_snapshot.json` の `benchmark_pipeline` 更新と `threshold_alerts` 保存を確認（Sandbox では Webhook 403 と鮮度アラートは既知）。
  - 2025-09-30: `manage_task_cycle.py start-task` に runbook/pending 資料の上書きオプションを追加し、`sync_task_docs.py` のテンプレ適用を共通ヘルパーへ整理。`docs/codex_workflow.md` と README の手順を更新済み。
  - 2025-09-28: 手動で `run_benchmark_pipeline.py --windows 365,180,90` を再実行し、ローリング JSON / `benchmark_summary.json` に Sharpe・最大DD・勝率が揃って出力されることを確認。ローカル環境では Slack Webhook が 403 になるため、`benchmark_runs.alert.deliveries[].detail` をランブックへ追記し、`state.md` と併せてメモ化する。
  - Backlog Anchor: [ローリング検証パイプライン (P1-01)](docs/task_backlog.md#p1-01-ローリング検証パイプライン)
  - Vision / Runbook References:
    - [docs/logic_overview.md](docs/logic_overview.md)
    - [docs/simulation_plan.md](docs/simulation_plan.md)
    - 主要ランブック: [docs/benchmark_runbook.md#スケジュールとアラート管理](docs/benchmark_runbook.md#スケジュールとアラート管理)
  - Pending Questions:
    - [ ] なし
  - Docs note: 参照: [docs/logic_overview.md](docs/logic_overview.md) / [docs/simulation_plan.md](docs/simulation_plan.md) / [docs/benchmark_runbook.md#スケジュールとアラート管理](docs/benchmark_runbook.md#スケジュールとアラート管理)
  - DoD チェックリスト: [docs/checklists/p1-01.md](docs/checklists/p1-01.md) を更新して進捗を管理する。

- **価格インジェストAPI基盤整備**（バックログ: `docs/task_backlog.md` → P1「ローリング検証 + 健全性モニタリング」） — `state.md` 2025-10-16, 2025-11-05, 2025-11-06 <!-- anchor: docs/task_backlog.md#p1-04-価格インジェストapi基盤整備 -->
  - Scope: Dukascopy 主経路の堅牢化と、REST/API ルートの保留管理・フォールバック設計（yfinance など無料ソース）。
  - Deliverables (EN): API ingestion design doc (`docs/api_ingest_plan.md`), CLI integration plan, retry/test matrix.
  - 2025-11-05: Alpha Vantage（Premium 49.99 USD/月）と Twelve Data Free（0 USD, 8req/min, 800req/日）を `activation_criteria` で比較し、Alpha Vantage は保留継続・Twelve Data はフォールバック候補として記録。`configs/api_ingest.yml` に閾値・候補ノートを追記済み。
  - 2025-11-06: 暗号化ストレージ運用と鍵ローテーション記録フローを `docs/state_runbook.md` / README / チェックリストへ反映し、`credential_rotation` プレースホルダを定義。Reviewers: ops-security（高橋）, ops-runbook（佐藤）。
  - 2025-11-07: サンドボックスで `run_daily_workflow --ingest --use-dukascopy` を実行したが、`dukascopy_python` / `yfinance` 未導入で双方失敗しスナップショット未更新。`check_benchmark_freshness --max-age-hours 6` では最新バー 18.60h / サマリー 9.31h 遅延で閾値超過を確認。依存導入→再取得→鮮度確認を次アクションに設定。
  - 2025-11-09: REST retry error_keys を構造化し、Twelve Data の `status: "ok"` 成功レスポンスと `status: "error"` エラーを正しく判別できるよう `configs/api_ingest.yml` / `scripts/fetch_prices_api.py` / pytest を同期。
  - 2025-11-10: Twelve Data の `volume` 欠損を許容するよう `response.fields` に `required=false` / `default=0.0` を導入し、`fetch_prices_api` の正規化ロジックと pytest を更新。今後は UTC パース差異とフォールバック手順の runbook 追記へ移行。
  - 2025-11-11: Twelve Data 形式のレスポンス（`datetime` +00:00 / `volume` 欠損）をモック API テストへ反映し、`tests/test_fetch_prices_api.py` に回帰を追加。`docs/state_runbook.md` へドライラン手順と確認項目を追記し、チェックリストへ進捗メモを更新。
  - 2025-11-12: Dukascopy / yfinance の双方が利用できない Sandbox でも `run_daily_workflow.py --ingest --use-dukascopy` が動作するよう、ローカル CSV フェイルオーバーを追加し、`tests/test_run_daily_workflow.py` に回帰を実装。依存導入後に再取得→鮮度チェックを実行するタスクは継続。
  - Next step: Sandbox へ `dukascopy-python` / `yfinance` を導入し、`python3 scripts/run_daily_workflow.py --ingest --use-dukascopy` → `python3 scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6` を再実行して鮮度アラートが解消されることを確認する。結果を `state.md` / `docs/checklists/p1-04_api_ingest.md` / `docs/task_backlog.md` に反映する。
  - Backlog Anchor: [価格インジェストAPI基盤整備 (P1-04)](docs/task_backlog.md#p1-04-価格インジェストapi基盤整備)
  - Vision / Runbook References:
    - [readme/設計方針（投資_3_）v_1.md](readme/設計方針（投資_3_）v_1.md)
    - [docs/state_runbook.md](docs/state_runbook.md)
    - [README.md#オンデマンドインジェスト-cli](README.md#オンデマンドインジェスト-cli)
  - Pending Questions:
    - [x] Dukascopy 経路の冪等性・鮮度検証を完了し、標準運用として承認できるか。
    - [ ] REST/API を再開する条件（コスト上限・レート制限・鍵ローテーション SOP）と、無料フォールバック（yfinance 自動切替＋鮮度監視）の仕様確定。
  - Docs note: `docs/api_ingest_plan.md` / README / `docs/state_runbook.md` を更新済み。残タスクはフォールバック仕様と保留メモを `docs/checklists/p1-04_api_ingest.md` に反映すること。
  - DoD チェックリスト: [docs/checklists/p1-04_api_ingest.md](docs/checklists/p1-04_api_ingest.md) を利用して進捗を管理する。

### Ready

### Pending Review
- **Workflow Integration Guide** (Backlog: `docs/task_backlog.md` → "ワークフロー統合" section) — `state.md` 2024-06-18, 2025-09-29 <!-- anchor: docs/task_backlog.md#codex-session-operations-guide -->
  - Updated the synchronization rules between `docs/todo_next.md` and `state.md`. Added `docs/codex_workflow.md` to capture Codex session procedures. Confirm readiness for adoption before moving to Archive.
- **マルチ戦略比較バリデーション** (Backlog: `docs/task_backlog.md` → P2「マルチ戦略ポートフォリオ化」) — `state.md` 2025-09-29 <!-- anchor: docs/task_backlog.md#p2-マルチ戦略ポートフォリオ化 -->
  - Day ORB (63 trades, EV reject 1,544) と Mean Reversion (40 trades, gate_block 402, EV reject 0) を `data/sample_orb.csv` で比較し、`docs/checklists/multi_strategy_validation.md` の表を実測値で更新。
  - Mean Reversion は `zscore` カラムの追加でトレード生成が確認でき、EV プロファイル有無で `ev_reject` 差分が無いことを再現。日次 CSV にゲート/EV カウントを保存済み。次は RV High ブロック条件とウォームアップ回数の調整案を検討。

## Archive（達成済み）
- ~~**目標指数の定義**~~ ✅ — `state.md` 2024-06-01 <!-- anchor: docs/task_backlog.md#目標指数の定義 -->
  - `configs/targets.json` と `scripts/evaluate_targets.py` を整備済み。
- ~~**ウォークフォワード検証**~~ ✅ — `state.md` 2024-06-02, 2024-06-03 <!-- anchor: docs/task_backlog.md#ウォークフォワード検証 -->
  - `scripts/run_walk_forward.py` を追加し、`analysis/wf_log.json` に窓別ログを出力。
- ~~**自動探索の高度化**~~ ✅ — `state.md` 2024-06-04 <!-- anchor: docs/task_backlog.md#自動探索の高度化 -->
  - `scripts/run_optuna_search.py` で多指標目的の探索骨子を構築。
- ~~**運用ループへの組み込み**~~ ✅ — `state.md` 2024-06-05 <!-- anchor: docs/task_backlog.md#運用ループへの組み込み -->
  - `scripts/run_target_loop.py` による Optuna → run_sim → 指標計算 → 判定のループを実装。
- ~~**state ヘルスチェック**~~ ✅ — `state.md` 2024-06-11 <!-- anchor: docs/task_backlog.md#state-ヘルスチェック -->
  - `scripts/check_state_health.py` の警告生成・履歴ローテーション・Webhook テストを追加。
- ~~**ベースライン/ローリング run 起動ジョブ**~~ ✅ — `state.md` 2024-06-12 <!-- anchor: docs/task_backlog.md#ベースラインローリング-run-起動ジョブ -->
  - `scripts/run_benchmark_pipeline.py` と `tests/test_run_benchmark_pipeline.py` を整備し、runbook を更新。
- ~~**ベンチマークサマリー閾値伝播**~~ ✅ — `state.md` 2024-06-13 <!-- anchor: docs/task_backlog.md#ベンチマークサマリー閾値伝播 -->
  - `run_daily_workflow.py` からの Webhook/閾値伝播と README 更新を完了。
- ~~**絶対パス整備と CLI テスト強化**~~ ✅ — `state.md` 2024-06-14 <!-- anchor: docs/task_backlog.md#絶対パス整備と-cli-テスト強化 -->
  - `run_daily_workflow.py` 最適化/状態アーカイブコマンドで絶対パスを使用するよう更新し、pytest で検証。

- ~~**インシデントリプレイテンプレート**~~（バックログ: `docs/task_backlog.md` → P1「インシデントリプレイテンプレート」） — `state.md` 2024-06-14, 2024-06-15, 2024-06-21 ✅ <!-- anchor: docs/task_backlog.md#p1-02-インシデントリプレイテンプレート -->
  - 期間指定リプレイ CLI の拡張は完了。Notebook (`analysis/incident_review.ipynb`) と `ops/incidents/` へのテンプレ整備を次イテレーションで着手可能。
