# docs/todo_next Archive

過去の `docs/todo_next.md` Archive セクションに掲載していた完了済みタスクのログをこのファイルへ集約しました。各エントリのアンカーコメントは従来通り維持しています。README / codex 系ワークフロードキュメント / DoD テンプレートからの参照先も本アーカイブへ統一しました。

- **Codex-first documentation cleanup** (Backlog: `docs/task_backlog.md` → [P0-12](./task_backlog.md#p0-12-codex-first-documentation-cleanup)) — 2026-05-05 完了 <!-- anchor: docs/task_backlog.md#p0-12-codex-first-documentation-cleanup -->
  - Consolidated quickstart/workflow/state runbook into aligned three-step guides, refreshed README / roadmap / todo-next anchors, and logged deliverables in `state.md` と backlog. `python3 -m pytest` を完走し、docs/todo_next アーカイブへ移動。
  - 2026-05-06: Authored [docs/documentation_portal.md](documentation_portal.md) as the navigation hub, reorganised README onboarding sections, and updated quickstart/workflow guidance to point at the new portal。`docs/todo_next.md` / `state.md` / backlog のログを同期。
- **ルーター拡張** (Backlog: `docs/task_backlog.md` → [P2-マルチ戦略ポートフォリオ化](./task_backlog.md#p2-マルチ戦略ポートフォリオ化)) — 2026-02-13 完了 <!-- anchor: docs/task_backlog.md#p2-マルチ戦略ポートフォリオ化 -->
  - Finalised PortfolioState budgeting, correlation scoring, and execution-health penalties. Synced `docs/checklists/p2_router.md`, refreshed `docs/progress_phase2.md` deliverable notes, updated backlog progress, and ran `python3 -m pytest tests/test_router_v1.py tests/test_router_pipeline.py` before closing。
- **マルチ戦略比較バリデーション** (Backlog: `docs/task_backlog.md` → [P2-マルチ戦略ポートフォリオ化](./task_backlog.md#p2-マルチ戦略ポートフォリオ化)) — 2026-02-13 完了
  - Regenerated `runs/multi_strategy/` artefacts, compared Day ORB vs Mean Reversion (`ev_reject=0` vs `330`), and confirmed `--no-ev-profile` の挙動が不変。`docs/checklists/multi_strategy_validation.md` のサマリ表と実測メモを更新し、チェックリスト完了状態を維持。
- **Fill エンジン / ブローカー仕様アライン** (Backlog: `docs/task_backlog.md` → [P1-06](./task_backlog_p1_archive.md#p1-06-fill-エンジン--ブローカー仕様アライン)) — 2026-02-13 完了
  - Added fill-engine overrides (`fill_same_bar_policy_*`, `fill_bridge_lambda`, `fill_bridge_drift_scale`) to RunnerConfig と manifest (`runner.runner_config`). Updated docs (`docs/broker_oco_matrix.md`, `docs/benchmark_runbook.md`, `docs/progress_phase1.md`) and regression suites (`tests/test_runner.py`, `tests/test_run_sim_cli.py`) before closing。
- ~~**フェーズ1 バグチェック & リファクタリング運用整備**~~ ✅ — `state.md` 2026-01-08 <!-- anchor: docs/task_backlog_p1_archive.md#p1-07-フェーズ1-バグチェック--リファクタリング運用整備 -->
  - `docs/checklists/p1-07_phase1_bug_refactor.md` に調査チェックボード・テスト手順・リファクタリング計画テンプレを追加し、運用チェック項目を全て埋めた。`scripts/manage_task_cycle.py` の start/finish 例も掲載。
  - `docs/task_backlog.md` から P1-07 をアーカイブし、`docs/todo_next.md` / `state.md` の Ready / Next Task ブロックを整理。今後はチェックボードの行追加と `state.md` ログ更新のみで継続できる。

- ~~**価格インジェストAPI基盤整備**~~ ✅ — `state.md` 2025-10-16, 2025-11-05, 2025-11-06, 2025-11-28 <!-- anchor: docs/task_backlog_p1_archive.md#p1-04-価格インジェストapi基盤整備 -->
  - `python3 scripts/run_daily_workflow.py --ingest --use-dukascopy --symbol USDJPY --mode conservative` を実行し、yfinance フォールバックで 91 行を取り込み `ops/runtime_snapshot.json.ingest_meta.USDJPY_5m.freshness_minutes=0.614` を確認。
  - 続けて `python3 scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6 --ingest-timeframe USDJPY_5m` を実行し、`ok: true`・`errors: []`・`advisories: []` を確認。`benchmark_pipeline` 側も遅延 0.59h 以内を維持。
  - `state.md` / `docs/checklists/p1-04_api_ingest.md` / `docs/api_ingest_plan.md` / `docs/state_runbook.md` / `README.md` の該当箇所を再確認し、フォールバック仕様と依存導入手順が現行運用と一致していることをレビューしたうえで todo を Archive へ移動。
- ~~**ローリング検証パイプライン**~~ ✅ — `state.md` 2025-11-27 <!-- anchor: docs/task_backlog_p1_archive.md#p1-01-ローリング検証パイプライン -->
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

- ~~**インシデントリプレイテンプレート**~~（バックログ: `docs/task_backlog.md` → P1「インシデントリプレイテンプレート」） — `state.md` 2024-06-14, 2024-06-15, 2024-06-21, 2025-12-01 ✅ <!-- anchor: docs/task_backlog_p1_archive.md#p1-02-インシデントリプレイテンプレート -->
  - 期間指定リプレイ CLI の拡張と Notebook (`analysis/incident_review.ipynb`) のテンプレ整備を完了。`docs/state_runbook.md#インシデントリプレイワークフロー` と README に再現フロー/成果物の整理手順を追記し、`ops/incidents/<incident_id>/` の出力ファイル（`replay_notes.md`・`replay_params.json`・`runs/incidents/...`）掲載先とステークホルダー共有ルールを明文化した。

 

- ~~**戦略マニフェスト整備**~~ (Backlog: `docs/task_backlog.md` → [P2-01](./task_backlog.md#p2-マルチ戦略ポートフォリオ化)) — `state.md` 2026-01-08 ✅ <!-- anchor: docs/task_backlog.md#p2-マルチ戦略ポートフォリオ化 -->
  - `configs/strategies/*.yaml` を整理し、依存特徴量・セッション・リスク上限を統一形式で記述。[docs/checklists/p2_manifest.md](./checklists/p2_manifest.md) の DoD を参照して、RunnerConfig/CLI へのパラメータ伝播を検証する。
  - `scripts/run_sim.py --manifest` の引数マッピングを再確認し、必要なら loader/CLI を更新。pytest (`tests/test_run_sim_cli.py`, `tests/test_mean_reversion_strategy.py` など) をターゲットに追加実行する。
  - 2026-01-08: `strategies/scalping_template.py` / `strategies/day_template.py` / `strategies/tokyo_micro_mean_reversion.py` / `strategies/session_momentum_continuation.py` を追加し、対応する manifest (`configs/strategies/*.yaml`) を新設。`python3 -m pytest tests/test_strategy_manifest.py` (2 passed) と `python3 -m pytest tests/test_run_sim_cli.py -k manifest` (1 passed, 4 deselected) を実行済み。
  - 2026-01-08: `python3 scripts/run_sim.py --manifest configs/strategies/tokyo_micro_mean_reversion.yaml --csv data/sample_orb.csv --json-out /tmp/tokyo_micro.json`、`python3 scripts/run_sim.py --manifest configs/strategies/session_momentum_continuation.yaml --csv data/sample_orb.csv --json-out /tmp/session_momo.json`、`python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv data/sample_orb.csv --json-out /tmp/day_orb.json` を完了。manifest 経由の CLI 配線を確認し、DoD テスト項目を更新済み。各 manifest の `runner.cli_args` で auto_state / aggregate_ev を制御しながら再実行。
  - manage_task_cycle start-task は Ready セクションのアンカー不一致で失敗したため、当面は手動更新を継続。ドキュメント更新後にアンカー修正を検討。
  - Backlog Anchor: [戦略マニフェスト整備 (P2-01)](./task_backlog.md#p2-マルチ戦略ポートフォリオ化)
  - Vision / Runbook References:
    - [docs/logic_overview.md](./logic_overview.md)
    - [docs/simulation_plan.md](./simulation_plan.md)
    - 主要ランブック: [docs/state_runbook.md](./state_runbook.md)
  - Pending Questions:
    - [ ] Clarify gating metrics, data dependencies, or open questions.
  - DoD チェックリスト: [docs/templates/dod_checklist.md](./templates/dod_checklist.md) を [p2_manifest.md](./checklists/p2_manifest.md) にコピーし、進捗リンクを更新する。

- ~~**Workflow Integration Guide**~~ (Backlog: `docs/task_backlog.md` → "ワークフロー統合" section) — `state.md` 2024-06-18, 2025-09-29, 2026-02-13, 2025-10-08 ✅ <!-- anchor: docs/task_backlog.md#codex-session-operations-guide -->
  <!-- REVIEW: Archived after confirming workflow loop, dry-run coverage, and template links met the reviewer DoD. -->
  - Documented the sandbox approval matrix (package installs, API calls, large transfers, privileged writes) and linked it from `docs/state_runbook.md`. Verified that the workflow trio (`docs/codex_workflow.md`, `docs/state_runbook.md`, `docs/todo_next.md`) now shares consistent anchors/terminology and preserves Japanese summaries while addressing reviewer feedback。
