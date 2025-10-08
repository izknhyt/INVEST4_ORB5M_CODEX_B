# Agent Notes

## 0. 共通原則
- コードコメント・設計メモ・コミットメッセージなどの作業ログは **英語** で記述し、ユーザーへの最終報告や結果共有は **日本語** で行う。
- 常に日本語で回答し、ターミナルコマンドを案内する際は省略せずに完全なコマンドを提示する（`...` などのプレースホルダー禁止）。
- 作業開始時に README・主要設計メモ・`docs/task_backlog.md` を確認し、着手タスクと完了定義を宣言する。

## 1. 作業フロー
1. バックログの P0/P1 から対象タスクを選定し、想定成果物（コード／ドキュメント／レポート）を英語でメモする。
2. 関連ディレクトリの README や設計資料を確認して依存スクリプトや必要テストを洗い出す。
3. 実装後は `python3 -m pytest` を実行し、必要に応じて `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv` など最小検証を追加で行う。
4. 成果を反映した後は `docs/task_backlog.md` や関連ドキュメントを更新し、リンクや補足を残す。
5. コミットメッセージと PR 説明には対応タスク・主要変更点・実行テストを英語で記載し、PR の最終サマリーは日本語でまとめる。

## 2. ディレクトリ別ガイド
- `core/`: PEP 8 と型ヒントを遵守し、該当変更に対応するユニットテストを追加／更新する。`tests/test_runner.py` など関連テストを最小実行する。
- `scripts/`: CLI 引数の互換性を維持し、README に記載の使用例がそのまま動作することを確認する。
- `configs/strategies/`: `configs/strategies/README.md` のマニフェスト仕様に従い、`pytest tests/test_strategy_manifest.py` で検証する。
- `router/` / `strategies/`: 新シグナルやロジックを追加する際は `scripts/run_compare.py` などでバックテストを行い、差分サマリーを日本語で共有する。

## 3. ドキュメント & 運用
- バックログの完了タスクは削除し、新規タスクは優先度付きで追記する（英語可）。
- 新しい運用フローやパラメータ変更があれば README および関連 Runbook を更新し、要約を日本語で共有する。
- 重要アウトプット（例: `runs/index.csv`, `reports/*`, `ops/state_archive/*`）の更新理由と再現手順をコミット／PR に記録し、報告時に日本語で説明する。
