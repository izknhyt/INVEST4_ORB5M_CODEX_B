# 次のアクション（目標指標達成フロー）

## 更新ルール
- タスクを完了したら、必ず `state.md` の該当項目をログへ移し、本ファイルのセクション（In Progress / Ready / Pending Review / Archive）を同期してください。
- `state.md` に記録されていないアクティビティは、このファイルにも掲載しない方針です。新しい作業を始める前に `state.md` へ日付と目的を追加しましょう。
- フローの全体像は [docs/codex_quickstart.md](./codex_quickstart.md) / [docs/codex_workflow.md](./codex_workflow.md) を参照し、アンカーの整合チェックを忘れずに。
- Ready または In Progress へ昇格させるタスクは、[docs/templates/dod_checklist.md](./templates/dod_checklist.md) を複製し `docs/checklists/<task-slug>.md` へ保存したうえで、該当エントリからリンクするか貼り付けてください。

## Ready 昇格チェックリスト
- [ ] ビジョンガイド（例: [docs/logic_overview.md](./logic_overview.md), [docs/simulation_plan.md](./simulation_plan.md)）を再読し、昇格候補タスクが最新方針と整合していることを確認した。
- [ ] 対象フェーズの記録（`docs/progress_phase*.md`）を確認し、未完了の前提条件や検証ギャップが無い。
- [ ] 関連ランブック（例: `docs/state_runbook.md`, `docs/benchmark_runbook.md`）の手順が最新であることを確認した。
- [ ] バックログ該当項目の DoD / 進捗メモを更新し、関係者へ通知済みである。
- [ ] [docs/templates/dod_checklist.md](./templates/dod_checklist.md) を複製し、Ready 昇格タスクのチェックボックス管理を整備した。

## Current Pipeline

### In Progress

- [P4-01 長期バックテスト改善](./task_backlog.md#p4-01-長期バックテスト改善) — [検証計画](plans/phase4_validation_plan.md) と進捗ログを同期済み。`scripts/summarize_strategy_gate.py` で Conservative / Bridge のデバッグ run（2025-01-01〜2025-10-13）を解析した結果、(1) Tokyo セッションでの `router_gate`、(2) `min_or_atr_ratio=0.25` による `or_filter`、(3) EV オフ時の Kelly サイジングが `zero_qty` を生む構造を特定済み。[reports/simulations/day_orb5m_20251013_summary.md](../reports/simulations/day_orb5m_20251013_summary.md) に根拠と改善案を追記。**次ステップ:**
  1. **完了 (2026-08-17)** Runner 側に EV オフ時のフォールバック（`fallback_win_rate` / `size_floor_mult`）を実装し、`tests/test_runner.py::test_sizing_gate_ev_off_uses_fallback_quantity` でゼロサイズを防止する回帰を追加。`core/runner_entry.SizingGate` が EV バイパス時にも数量を算出できることを確認した。
  2. **完了 (2026-08-18)** LDN/NY 偏重だったセッション設定を見直し、`configs/strategies/day_orb_5m_guard_relaxed.yaml` で `allowed_sessions=[TOK,LDN,NY]` / `or_n=4` を採用した緩和マニフェストを追加。`scripts/summarize_strategy_gate.py` でのブロック分布比較を準備済み。
  3. **完了 (2026-08-18)** `min_or_atr_ratio=0.18` へ暫定緩和した同マニフェストを Conservative / Bridge 共通で利用し、`runner_config` / CLI 引数も同期。フォールバックサイジングを維持したまま ATR 閾値変更の影響を観測できる状態。
  4. **完了 (2026-08-19)** `scripts/run_sim.py --manifest configs/strategies/day_orb_5m_guard_relaxed.yaml --csv validated/USDJPY/5m.csv --symbol USDJPY --mode <mode> --out-dir runs/phase4/backtests_guard_relaxed --no-auto-state --debug --debug-sample-limit 600000` を Conservative / Bridge 両モードで実行し、`reports/diffs/conservative_guard_relaxed_metrics.json` / `reports/diffs/bridge_guard_relaxed_metrics.json` にメトリクス差分、`reports/diffs/conservative_guard_relaxed_strategy_gate.json` に `or_filter` 449 件（rv_band high 246 / mid 162 / low 41）を記録。`docs/progress_phase4.md#現状サマリ` を更新済み。
  5. **完了 (2026-10-18)** guard-relaxed ランの `or_filter` 449 件を `analysis/or_filter_guard_relaxed_summary.py` で再集計し、`rv_band=high`=246 件 (54.8%)・`mid`=162 件 (36.1%)・`low`=41 件 (9.1%) の偏りと `min_or_atr_ratio=0.18` 固定を確認。レポートを [reports/diffs/or_filter_guard_relaxed_summary.md](../reports/diffs/or_filter_guard_relaxed_summary.md) / [JSON](../reports/diffs/or_filter_guard_relaxed_summary.json) に保存済み。
  6. **完了 (2026-10-19)** `configs/strategies/day_orb_5m_guard_relaxed.yaml` に RV 帯別 `min_or_atr_ratio`（high=0.12 / mid=0.14 / low=0.18）を導入し、`python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m_guard_relaxed.yaml --csv validated/USDJPY/5m.csv --symbol USDJPY --mode conservative --out-dir runs/phase4/backtests_guard_relaxed --no-auto-state --debug --debug-sample-limit 600000` と `--mode bridge` を再実行。`reports/diffs/conservative_guard_relaxed_strategy_gate.json` / `bridge_guard_relaxed_strategy_gate.json` で `or_filter=278`（mid 137 / high 100 / low 41, `min_or_atr_ratio` 平均 ≈0.1387）へ更新し、集計レポートも差し替えた。
  7. **完了 (2026-10-27)** Conservative / Bridge の最新ガード緩和ラン
     (`runs/phase4/backtests_guard_relaxed/USDJPY_conservative_20251018_011918` /
     `USDJPY_bridge_20251018_012216`) を対象に
     `scripts/summarize_strategy_gate.py --stage loss_streak_guard --stage daily_loss_guard --stage or_filter --json`
     でガード別集計を作成。`loss_streak_guard` / `daily_loss_guard` は両モード 0 件、`or_filter` は 208 件
     （mid 110 / high 60 / low 38、`min_or_atr_ratio` 平均 ≈0.1215）まで減少したことを
     `reports/diffs/conservative_guard_relaxed_guard_stages.json` / `bridge_guard_relaxed_guard_stages.json`
     と統合サマリ（`reports/diffs/guard_stage_summary.json` / `.md`）へ反映済み。
  8. **完了 (2026-10-28)** `rv_band_min_or_atr_ratio` を {high:0.08, mid:0.10, low:0.14} に更新し、`runs/phase4/backtests_guard_relaxed/USDJPY_conservative_20251018_030339` / `USDJPY_bridge_20251018_030536` を取得。`scripts/summarize_strategy_gate.py --stage or_filter` と `analysis/or_filter_guard_relaxed_summary.py` を再実行して `or_filter` を 171 件（mid 99 / low 38 / high 34、`min_or_atr_ratio` 平均 ≈0.1049）へ更新し、`reports/diffs/*_metrics_next.json` も新ランの比較に差し替えた。
  9. **次セッション候補**
     - base_drop 0.02 の提案値（rv_band={0.06,0.08,0.12} / global=0.12）をサンドボックスで検証し、さらなる ATR フロア低減の可否を判断する。
     - 2025-06 / 2024-Q1 のショートランで `max_loss_streak=3` のみブロック増（Bridge: +9 件, Conservative: +9 or +5 件）、`max_daily_loss_pips=150〜220` は発火 0 件であることを確認済み。次セッションでは `max_loss_streak=3` / `max_daily_loss_pips=150` を組み合わせたサンドボックス再現 → 差分比較レポート化 → 長期ラン反映可否の判断、の順に進める。
  10. **完了 (2026-10-29)** Day ORB シンプル化リブートマニフェストを `min_or_atr_ratio=0.12`・RV 帯別 ATR フロア/上限
      (`rv_band_min_atr_pips={low:6.0, mid:4.0, high:0.0}` /
      `rv_band_max_atr_pips={low:45.0, mid:55.0, high:65.0}`)・
      RV 帯別 ATR 比 (`rv_band_min_or_atr_ratio={low:0.14, mid:0.12, high:0.10}` /
      `ny_high_rv_min_or_atr_ratio=0.20` /
      `ny_high_rv_or_multiplier=1.2`)・`max_loss_streak=4`・`max_daily_loss_pips=150` へ更新し、
      `strategies/day_orb_5m.DayORB5m` の ATR ガードを RV 帯別に再実装。`python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv --mode conservative --out-dir runs/phase4/backtests --no-auto-state --debug --debug-sample-limit 500000` と `--mode bridge` を実行し、23 トレード（勝率 39.1% / 25.3%、最大 DD -103.6 / -97.3 pips）と `or_filter=5` への縮減を確認。`reports/diffs/day_orb_reboot_strategy_gate.json` / `reports/diffs/day_orb_reboot_metrics.json` を再生成し、KPI・停止条件を `docs/progress_phase4.md` に記録した。
  11. **フォローアップ** Conservative Sharpe が 0 未満へ逆行、またはどちらかのモードで `trades < 15` / 最大 DD ≤ -180 pips が検知された場合のみ追加緩和を行う。次回は 2024-Q1 サンドボックスで `min_or_atr_ratio` < 0.12 と `max_loss_streak=3` の組み合わせを試験し、`reports/diffs/day_orb_reboot_metrics.json` を基準に差分を評価する。

### On Hold

- Monitor for the first production `data_quality_failure` alert to validate the acknowledgement workflow once live signals begin flowing. (P0 ops loop paused until production data triggers an alert.)
### Ready

- [P4-02 異常系テスト自動化](./task_backlog.md#p4-02-異常系テスト自動化) — 既存 `tests/test_data_robustness.py` のカバレッジ確認と追加シナリオ設計から着手。
- [P4-03 Go/No-Go チェックリスト確定](./task_backlog.md#p4-03-go-no-go-チェックリスト確定) — P4-01 の改善内容を踏まえ、チェック項目の責任者・頻度・ログテンプレを埋める。

### Pending Review

- レビュー中のタスクを再開する際は `scripts/manage_task_cycle.py --doc-section Pending Review` を用いると、`docs/todo_next.md` の配置を維持したまま `state.md` のテンプレートを再適用できる。

## Archive（達成済み）

> 過去の達成済みログは [docs/todo_next_archive.md](./todo_next_archive.md) に集約しました。履歴が必要な場合はアーカイブファイルを参照してください。
> `manage_task_cycle` のアンカープレースホルダのみ下記に残しています（削除しないでください）。

<!-- manage_task_cycle archive placeholder -->
✅ <!-- anchor placeholder to satisfy manage_task_cycle start-task detection -->
- <!-- docs/task_backlog.md#p2-マルチ戦略ポートフォリオ化 -->
  - DoD チェックリスト: [docs/templates/dod_checklist.md](./templates/dod_checklist.md) を [docs/checklists/p2_manifest.md](./checklists/p2_manifest.md) にコピーし、進捗リンクを更新する。
- 2026-06-12: Closed [P0-15 Data quality alert operations loop](./task_backlog.md#p0-15-data-quality-alert-ops) via simulated coverage failure, acknowledgement log entry (`scripts/record_data_quality_alert.py`), docs/data_quality_ops.md update, and full pytest run。
- 2026-06-13: Completed [P0-16 Data quality acknowledgement input validation](./task_backlog.md#p0-16-data-quality-ack-validation) by hardening the CLI against malformed ratios/timestamps, documenting the guardrails, and extending regression coverage.
