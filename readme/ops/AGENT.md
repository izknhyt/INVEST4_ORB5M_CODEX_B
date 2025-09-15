# AGENTS.md — Project Guardrails for Codex

## GOAL
- USDJPY 5m ORB系（将来拡張可）のシグナル生成・検証基盤を継続改善する。
- 既存の骨格（`core/`, `strategies/`）を壊さずに品質向上。
- 変更はテストと再現手順で裏付ける。

## CONTEXT (short)
- 言語: Python（標準ライブラリ前提。必要なら最小限の追加を提案）
- 重要ディレクトリ: `core/`, `strategies/`, `tests/`, `configs/`, `schemas/`, `readme/ops/`
- このプロジェクトでは **大きなデータは読み取り専用**、成果物は `tests/runs_test/` などに吐く。

## WHAT YOU MAY DO (allowed)
- コードの追加・修正・軽いリファクタ
- `pytest -q` の実行、`configs/*.yml` の調整
- `STATE.md` を読み、**Next の先頭だけ**実行→完了後に `STATE.md` を更新してコミット

## WHAT YOU MUST NOT DO (forbidden)
- `data/` や `tests/runs_test/` の破壊的変更や消去
- `.env` 等の秘匿情報をリポへ追加／外部送信
- 大規模変更を1コミットに詰めること

## ACCEPTANCE CRITERIA
- `pytest -q` が緑（必要なら最小のテスト追加を提案）
- 影響範囲を `README.md` or コミットメッセージで簡潔に説明
- `STATE.md` の `Next`/`Done` が最新化されている

## RUN & TOOLS
- テスト: `pytest -q`
- 静的チェック（存在すれば）: `ruff`, `mypy`, `black --check`
- 例: `python -m pytest -q tests/test_runner.py`

## BRANCHING & COMMITS
- 1ミッション=1ブランチ（例: `feat/orb-threshold-tuning`）
- コミット書式: `feat|fix|chore(tests|docs): what (why)`
  - 例: `fix(core): clamp slippage in Bridge fill (stability)`
