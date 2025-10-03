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

### Ready

### Pending Review
- **Workflow Integration Guide** (Backlog: `docs/task_backlog.md` → "ワークフロー統合" section) — `state.md` 2024-06-18, 2025-09-29 <!-- anchor: docs/task_backlog.md#codex-session-operations-guide -->
  - Updated the synchronization rules between `docs/todo_next.md` and `state.md`. Added `docs/codex_workflow.md` to capture Codex session procedures. Confirm readiness for adoption before moving to Archive.
- **マルチ戦略比較バリデーション** (Backlog: `docs/task_backlog.md` → P2「マルチ戦略ポートフォリオ化」) — `state.md` 2025-09-29 <!-- anchor: docs/task_backlog.md#p2-マルチ戦略ポートフォリオ化 -->
  - Day ORB (63 trades, EV reject 1,544) と Mean Reversion (40 trades, gate_block 402, EV reject 0) を `data/sample_orb.csv` で比較し、`docs/checklists/multi_strategy_validation.md` の表を実測値で更新。
  - Mean Reversion は `zscore` カラムの追加でトレード生成が確認でき、EV プロファイル有無で `ev_reject` 差分が無いことを再現。日次 CSV にゲート/EV カウントを保存済み。次は RV High ブロック条件とウォームアップ回数の調整案を検討。

## Archive（達成済み）
- ~~**価格インジェストAPI基盤整備**~~ ✅ — `state.md` 2025-10-16, 2025-11-05, 2025-11-06, 2025-11-28 <!-- anchor: docs/task_backlog.md#p1-04-価格インジェストapi基盤整備 -->
  - `python3 scripts/run_daily_workflow.py --ingest --use-dukascopy --symbol USDJPY --mode conservative` を実行し、yfinance フォールバックで 91 行を取り込み `ops/runtime_snapshot.json.ingest_meta.USDJPY_5m.freshness_minutes=0.614` を確認。
  - 続けて `python3 scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6 --ingest-timeframe USDJPY_5m` を実行し、`ok: true`・`errors: []`・`advisories: []` を確認。`benchmark_pipeline` 側も遅延 0.59h 以内を維持。
  - `state.md` / `docs/checklists/p1-04_api_ingest.md` / `docs/api_ingest_plan.md` / `docs/state_runbook.md` / `README.md` の該当箇所を再確認し、フォールバック仕様と依存導入手順が現行運用と一致していることをレビューしたうえで todo を Archive へ移動。
- ~~**ローリング検証パイプライン**~~ ✅ — `state.md` 2025-11-27 <!-- anchor: docs/task_backlog.md#p1-01-ローリング検証パイプライン -->
  - `python3 scripts/run_benchmark_pipeline.py --windows 365,180,90 --disable-plot` を実行し、`reports/rolling/{365,180,90}/USDJPY_conservative.json` と `reports/benchmark_summary.json` に勝率・Sharpe・最大DDの最新値を反映。
  - `python3 scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6 --benchmark-freshness-max-age-hours 6` を完走させ、`ops/runtime_snapshot.json` の `benchmark_pipeline` セクションが `ok: true` で `errors` 空となることを確認。
  - README / `docs/benchmark_runbook.md` のローリング検証手順を更新し、`docs/checklists/p1-01.md` / `docs/task_backlog.md` / `state.md` / `docs/todo_next.md` の関連メモを同期。完了ログを `state.md` の `## Log` に追記済み。
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

- ~~**インシデントリプレイテンプレート**~~（バックログ: `docs/task_backlog.md` → P1「インシデントリプレイテンプレート」） — `state.md` 2024-06-14, 2024-06-15, 2024-06-21, 2025-12-01 ✅ <!-- anchor: docs/task_backlog.md#p1-02-インシデントリプレイテンプレート -->
  - 期間指定リプレイ CLI の拡張と Notebook (`analysis/incident_review.ipynb`) のテンプレ整備を完了。`docs/state_runbook.md#インシデントリプレイワークフロー` と README に再現フロー/成果物の整理手順を追記し、`ops/incidents/<incident_id>/` の出力ファイル（`replay_notes.md`・`replay_params.json`・`runs/incidents/...`）掲載先とステークホルダー共有ルールを明文化した。
