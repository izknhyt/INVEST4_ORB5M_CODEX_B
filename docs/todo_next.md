# 次のアクション（目標指標達成フロー）

1. ~~**目標指数の定義**~~ ✅
   - `configs/targets.json` と `scripts/evaluate_targets.py` を追加済み。

2. ~~**ウォークフォワード検証**~~ ✅
   - `scripts/run_walk_forward.py` を追加し、窓ごとの最適化ログを `analysis/wf_log.json` に保存。
   - さらなる評価指標（Sharpe など）を算出するスクリプトを次に実装する。

3. **全期間最終最適化**
   - Conservative/Bridge の全期間ランは `reports/long_*` に取得。現状は目標未達（Sharpe/CAGRが負）→ 改善タスクが必要。

4. ~~**自動探索の高度化**~~ ✅
   - `scripts/run_optuna_search.py` を追加し、Optunaでの探索雛形を構築済み。今後、目的関数に複数指標を組み込む拡張が可能。

5. ~~**運用ループへの組み込み**~~ ✅
   - `scripts/run_target_loop.py` を追加し、Optuna → run_sim → 指標計算 → 目標判定のループを構築済み（現状は基準未達時にループ継続）。
   - 未達時のパラメータ調整ルールや通知強化は今後の改善項目。

6. **ドキュメントとガバナンス**
   - `docs/go_nogo_checklist.md` に目標達成判定のステップを統合。
   - Slack/Webhook 通知で達成状況を報告し、手動レビュー → 承認 → Paper移行のフローを整備。

これらを進めながら、`docs/task_backlog.md` に項目と進捗を追加していきましょう。
