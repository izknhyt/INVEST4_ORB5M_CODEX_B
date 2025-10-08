# Development Roadmap (Codex-first)

日々の Codex セッションが迷わず改善へ向かうよう、即応タスクから中期施策までを整理します。各項目は [docs/task_backlog.md](task_backlog.md) のアンカーと紐付けてあり、DoD や最新メモはバックログ側を参照してください。

## Immediate (今すぐ着手)
- **P0-12 Codex-first documentation cleanup** — [docs/task_backlog.md#p0-12-codex-first-documentation-cleanup](task_backlog.md#p0-12-codex-first-documentation-cleanup)
  - クイックスタート / ランブック / README の導線統一、チェックリストの簡素化、`manage_task_cycle` の完了フロー検証を同一スプリントで実施する。
  - `docs/todo_next.md`・`docs/checklists/` のアンカーと DoD リンクが新フローに沿っているかセッション毎に点検する。
- **Codex ops backlog hygiene** — [docs/task_backlog.md#codex-session-operations-guide](task_backlog.md#codex-session-operations-guide)
  - `state.md` / `docs/todo_next.md` のテンプレ同期手順を再確認し、テンプレ修正時は manage_task_cycle の dry-run を添える。
  - Sandbox ガイド（`docs/codex_cloud_notes.md`）や PR テンプレの更新があれば README / ランブックと同時に反映する。

## Near Term (〜1ヶ月)
- **ポートフォリオ評価レポート整備** — [docs/task_backlog.md#p2-マルチ戦略ポートフォリオ化](task_backlog.md#p2-マルチ戦略ポートフォリオ化)
  - `analysis/portfolio_monitor.py` / `reports/portfolio_summary.json` の運用メモを最新化し、カテゴリ・相関メトリクスを日次レビューに組み込む。
  - ルーターサマリーと `docs/checklists/p2_router.md` を突き合わせ、DoD で要求するテレメトリ項目を落とし込む。
- **マルチ戦略バリデーションの継続整備** — [docs/checklists/multi_strategy_validation.md](checklists/multi_strategy_validation.md)
  - Manifest-first フローの検証ログを定期的に更新し、`runs/multi_strategy/` のサンプル維持とバックログ進捗メモを同期。
- **テストショートラン統合** — [docs/task_backlog.md#p0-07](task_backlog.md#p0-07) など CLI 回帰に関連するタスクを参考に、`python3 -m pytest -k <selector>` をまとめた `tox -e quick`（または同等スクリプト）を検討。

## Mid Term (〜3ヶ月)
- **CI / 自動テスト導入** — [docs/task_backlog.md#p3-観測性・レポート自動化](task_backlog.md#p3-観測性・レポート自動化)
  - GitHub Actions などで pytest + 主要 CLI スモークを自動化し、Sandbox 制約は `docs/codex_cloud_notes.md` に追記する。
- **戦略ポートフォリオ強化** — [docs/task_backlog.md#p2-マルチ戦略ポートフォリオ化](task_backlog.md#p2-マルチ戦略ポートフォリオ化)
  - 追加戦略の manifest 整備やカテゴリ配分強化（`docs/checklists/p2_manifest.md`, `docs/checklists/p2_router.md`）を段階的に進める。
  - ルーターの執行メトリクスを拡充し、`scripts/build_router_snapshot.py` のテレメトリ出力と `docs/router_architecture.md` の計画を同期する。
- **EV プロファイル自動校正フロー** — [docs/task_backlog.md#p3-観測性・レポート自動化](task_backlog.md#p3-観測性・レポート自動化)
  - `scripts/aggregate_ev.py` のパラメータ調整手順を `docs/ev_tuning.md`（作成予定）と連動させ、DoD に必要なテスト/ログを明示する。

## Long Term (3ヶ月〜)
- **Rust/C++ への I/O/Execution 移行準備** — [docs/task_backlog.md#継続タスク--保守](task_backlog.md#継続タスク--保守)
  - ADR で定義した API 境界と FFI 計画を `docs/architecture_migration.md` に整理し、プロファイリング結果を添付する。
- **観測性ダッシュボード統合** — [docs/task_backlog.md#p3-観測性・レポート自動化](task_backlog.md#p3-観測性・レポート自動化)
  - KPI（EV 推移、滑り推定、勝率 LCB、ターンオーバー）を Notebook/BI に統合し、`docs/observability_plan.md` を必要に応じて作成する。
- **コンプライアンス/監査強化** — [docs/task_backlog.md#継続タスク--保守](task_backlog.md#継続タスク--保守)
  - Artifacts Ledger (ADR-020) を運用へ載せ、`docs/audit_playbook.md` にハッシュ検証や承認フローを明記する。

## 運用メモ
- 各項目を進める際はバックログに進捗リンクを残し、完了後は `state.md` / `docs/todo_next.md` と同期する。
- ロードマップ自体も Codex タスクとして扱い、更新した場合は `P0-12` もしくは後継タスクで DoD を管理する。
