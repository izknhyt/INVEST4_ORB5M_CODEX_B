# DoD チェックリスト — 価格インジェストAPI基盤整備

- タスク名: 価格インジェストAPI基盤整備
- バックログ ID / アンカー: P1-04 / docs/task_backlog.md#p1-04-価格インジェストapi基盤整備
- 担当: Codex Operator
- チェックリスト保存先: docs/checklists/p1-04_api_ingest.md

## Ready 昇格チェック項目
- [x] 設計方針（`readme/設計方針（投資_3_）v_1.md`）のオンデマンド起動/データ補完セクションを再読し、API化の方針と整合している。
- [x] `docs/state_runbook.md` のインジェスト手順・鍵管理ガイドを確認し、必要な更新点を洗い出した。
- [x] `docs/task_backlog.md` の DoD を最新化し、関係者へ共有済みである。
- [x] `docs/api_ingest_plan.md` がレビュー済みで、前提条件（API提供元・レート制限など）が明文化されている。

## バックログ固有の DoD
- [x] `scripts/fetch_prices_api.py` が API から5mバーを取得し、リトライ/レート制限ハンドリングを備えている。
- [x] `scripts/pull_prices.py` が `ingest_rows` 等のインタフェースを通じて API 取得結果を冪等に `raw/`・`validated/`・`features/` へ反映できる。
- [ ] `python3 scripts/run_daily_workflow.py --ingest --use-api --symbol USDJPY --mode conservative` が成功し、`ops/runtime_snapshot.json.ingest` が更新される。
- [ ] `python3 scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6` が成功し、鮮度アラートが解消される。
- [x] モックAPIを用いた単体/統合テストが `python3 -m pytest` で通過し、API失敗時のアノマリーログ出力が検証されている。

## 成果物とログ更新
- [x] `docs/state_runbook.md` と `README.md` のインジェスト手順を更新した。
- [ ] `state.md` の `## Log` に完了サマリを追記した。
- [ ] [docs/todo_next.md](../todo_next.md) の該当エントリを Archive へ移動した。
- [ ] 関連コード/設定ファイル/テストのパスを記録した。
- [ ] レビュー/承認者を記録した。

> API供給元や鍵管理ポリシーは `docs/api_ingest_plan.md` の更新と併せて、タスク完了までに最新化してください。
