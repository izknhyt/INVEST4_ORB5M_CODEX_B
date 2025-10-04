# DoD チェックリスト — P2-01 戦略マニフェスト整備

- チェックリスト保存先: docs/checklists/p2_manifest.md
- バックログ: [docs/task_backlog.md#p2-マルチ戦略ポートフォリオ化](../task_backlog.md#p2-マルチ戦略ポートフォリオ化)
- 参照テンプレ: [configs/strategies/templates/base_strategy.yaml](../../configs/strategies/templates/base_strategy.yaml)

> フェーズ2の初手として戦略マニフェストの標準化を進める。Ready 昇格チェックと固有 DoD を満たしたうえで、実装後は state/todo/backlog を同期して次工程へ引き継ぐ。

## Ready 昇格チェック
- [x] `state.md` / `docs/todo_next.md` に In Progress エントリを追加し、アンカーと Pending Questions を設定した。
- [x] `docs/codex_workflow.md` / `docs/state_runbook.md` の Manifest 運用手順を再読し、更新が必要か確認した。
- [x] `docs/progress_phase1.md#1-戦略別ゲート整備` を確認し、既存実装との整合を把握した。

## 目標物 (DoD)
- [x] `configs/strategies/day_orb_5m.yaml` と `configs/strategies/mean_reversion.yaml` をテンプレ基準に再構成し、必須ブロック (meta/strategy/router/risk/features/runner/state/notes) が揃っている。
- [x] 追加する新規マニフェスト（該当する場合）はテンプレを準拠し、カテゴリ・セッション・リスク上限を明示。
- [x] `configs/strategies/loader.py` / `scripts/run_sim.py` が manifest の新フィールドを問題なく取り込み、CLI フラグや RunnerConfig へ伝播する。
- [x] `run_sim.py --strategy-manifest` のサンプル実行コマンドを `docs/todo_next.md` または Runbook に追記。

## 実装タスク
- [x] 既存マニフェストの差分レビュー (`git diff`) を行い、phase1 で導入したフィールドが削除・劣化していないか確認。
- [x] 必要に応じて `configs/ev_profiles/*.yaml` との整合を確認し、manifest の `state.ev_profile` を最新に更新。
- [x] ルーター関連フィールド (allowed_sessions / allow_spread_bands / allow_rv_bands / category_cap_pct 等) のバリデーションを追加・更新。

## テスト / 検証
- [x] `python3 -m pytest tests/test_strategy_manifest.py`
- [x] `python3 -m pytest tests/test_run_sim_cli.py -k manifest`
- [ ] `python3 -m pytest tests/test_mean_reversion_strategy.py`
- [x] `python3 scripts/run_sim.py --strategy-manifest configs/strategies/tokyo_micro_mean_reversion.yaml --csv data/sample_orb.csv --symbol USDJPY --mode conservative --equity 100000 --json-out /tmp/tokyo_micro.json --dump-csv /tmp/tokyo_micro.csv --dump-daily /tmp/tokyo_micro_daily.csv`
- [x] `python3 scripts/run_sim.py --strategy-manifest configs/strategies/session_momentum_continuation.yaml --csv data/sample_orb.csv --symbol USDJPY --mode conservative --equity 150000 --json-out /tmp/session_momo.json --dump-csv /tmp/session_momo.csv --dump-daily /tmp/session_momo_daily.csv`
- [x] 追加した検証ログを `state.md` の該当ブロックへ追記。

## ドキュメント同期
- [x] `docs/todo_next.md` の In Progress 項目を最新化し、完了後は Archive へ移動。
- [x] `docs/task_backlog.md` の P2 セクションへ進捗メモを追記。
- [x] `state.md` に完了ログを記録し、Next Task を更新。

## クローズ条件
- [ ] すべての DoD 項目が達成され、関連ドキュメントに反映されている。
- [ ] テスト結果 (pytest / CLI) が `state.md` に記録され、再現時のメモが残っている。
- [ ] Backlog / todo / state が同期され、次フェーズへの引き継ぎメモが明記されている。
