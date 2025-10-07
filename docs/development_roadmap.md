# Development Roadmap (Codex-first)

日々の Codex セッションが迷わず改善へ向かうよう、即応タスクから中長期の施策までを整理したロードマップ。優先度と DoD は `docs/task_backlog.md` へ随時反映すること。

## Immediate (今すぐ着手)
- **P0-12 Codex-first documentation cleanup**  
  - `docs/codex_workflow.md` / README / `docs/state_runbook.md` の導線統一を完了する。  
  - Short CLI テストマトリクスを常に更新し、変更時は README の Codex セクションにも追記する。
- **回帰テストのショートラン整備**  
  - `python3 -m pytest tests/test_run_sim_cli.py` を含む主要 CLI テストを `tox -e quick` などワンコマンド化。  
  - 実装時に必須コマンドとして `docs/codex_workflow.md` に記載し、テンプレにも明記。
- **バックログ整理**  
  - 完了済みの P0/P1 項目を backlog から排除し、`docs/todo_next.md` / `state.md` のログへ移す。  
  - 新規検知した課題は優先度・DoD を明記した上で backlog へ登録。

## Near Term (〜1ヶ月)
- **Feature Flag ベースのリリースフロー整備**  
  - リスクが高いリファクタに `--feature` 系フラグを追加し、README/設計書へ使用方針を追記。  
  - `docs/state_runbook.md` に flag 切り替え時の state 管理ガイドラインを追加。
- **データ製品更新ログのテンプレ化**  
  - `runs/index.csv` / `ops/state_archive/*` 更新時に記録するテンプレを `docs/templates/data_update_note.md` として用意。  
  - Codex が更新時に自動参照できるよう `docs/codex_workflow.md` の wrap-up 手順にリンク。
- **マルチ戦略チェックリストの刷新**  
  - `docs/checklists/multi_strategy_validation.md` を manifest ベースの CLI フローへ更新し、`--dump-*` 依存の手順を `--out-dir` と post-processing ノートへ置き換える。
- **ロードテスト & 観測性メトリクスの再整理**  
  - `docs/task_backlog.md` の P2/P3 項目を見直し、現状の実装状況を整理。  
  - 必要なら `docs/observability_plan.md` を作成して KPI/ダッシュボード更新の責務を明文化。

## Mid Term (〜3ヶ月)
- **CI/自動テスト導入**  
  - GitHub Actions などで `python3 -m pytest` と主要 CLI smoke を自動化。  
  - Sandbox 制限がある場合は `docs/codex_cloud_notes.md` にパイプライン構成を追記。
- **戦略ポートフォリオのリバランス計画**  
  - 現行戦略（Day ORB）以外の候補を `docs/strategy_portfolio_plan.md` に整理し、優先順位と想定データ要件を明確化。  
  - ルーター/配分の評価指標（Sharpe, Turnover, Capacity）を `docs/logic_overview.md` に追記。
- **EV プロファイルの自動校正手順**  
  - `scripts/aggregate_ev.py` 系のパラメタ調整手順を `docs/ev_tuning.md` とシンクさせ、バックテスト結果との比較フローを明文化。

## Long Term (3ヶ月〜)
- **Rust/C++ への I/O/Execution 移行準備**  
  - ADR-002 に沿い、移行時の API 契約や FFI 境界を `docs/architecture_migration.md` に草案化。  
  - コア Runner のボトルネック計測（プロファイリング結果）をドキュメント化。
- **観測性ダッシュボード統合**  
  - ADR-022 の要件達成に向け、ダッシュボード要件・データソース・更新間隔を `analysis/` ノートブックと合わせて仕様化。  
  - 運用時のアラート基準を `docs/signal_ops.md` と同期。
- **コンプライアンス/監査強化**  
  - ADR-020 の Artifacts Ledger を運用に載せる。`docs/audit_playbook.md` を作成し、監査証跡とハッシュ検証手順を明文化。

## 運用メモ
- 各セクションの施策が完了したら、該当タスクを backlog から除去し、ログを `state.md` / `docs/todo_next.md` / `docs/progress/` へ残す。
- ロードマップ自体も Codex セッションの対象。更新時は `P0-12` もしくは後継タスクで DoD を管理する。
