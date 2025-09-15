# Mission: ORB 受け入れ条件の最小セット整備
Context: 先に `readme/ops/AGENTS.md` と `readme/ops/STATE.md` を読む。
Scope: `tests/test_runner.py`, `configs/acceptance.yml`, `README.md`

Steps (do top-most only):
  1. `tests/test_runner.py` に ORBブレイク境界付近の最小ケースを1つ追加
  2. `configs/acceptance.yml` を現仕様で整合するよう微調整
  3. `pytest -q` を緑にする／必要なら最小限の修正を提案
Acceptance:
  - `pytest -q` が緑
  - `README.md` に「使い方（受け入れ条件の概要）」が明文化
Deliverables:
  - 意味のあるコミットメッセージ
  - `readme/ops/STATE.md` の `Next/Done` 更新
