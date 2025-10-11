# フェーズ4 検証計画（設計・テスト方針）

## 目的とスコープ
- フェーズ4のロードマップで要求されている以下3領域を横断的に管理し、成果物と再現手順を文書化する。
  1. **長期バックテスト改善（P4-01）** — Conservative / Bridge の2018–2025通しランを最新データと調整済みパラメータで評価し、Sharpe・最大DD・年間勝率がリリース基準を満たす状態へ引き上げる。
  2. **異常系テスト自動化（P4-02）** — 異常データやストリーム障害を常設pytestで再現し、検知とフェイルセーフ動作をCIで保証する。
  3. **Go/No-Go チェックリスト確定（P4-03）** — Paper移行前に確認すべき運用・リスク項目を確定し、承認ログと責務分担を整備する。
- 成果物: `docs/progress_phase4.md` の更新ログ、`reports/long_{mode}.json` 系の再集計結果、`tests/test_data_robustness.py` 等のテストスイート、`docs/go_nogo_checklist.md` の更新版。
- ドキュメント連携: `docs/task_backlog.md` と `docs/todo_next.md` に進捗を同期し、`state.md` に検証ログと再現コマンドを記録する。

## 作業ストリーム別方針
### 1. 長期バックテスト改善（P4-01）
- **評価軸**: 日次Sharpe ≥ 0.15、最大ドローダウン ≤ -8%、年間勝率 ≥ 52% を暫定基準とし、Bridge/Conservative双方で達成する。
- **検証手順**:
  - `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv --mode <mode> --start-ts 2018-01-01T00:00:00Z --end-ts 2025-12-31T23:55:00Z --out-json reports/long_<mode>.json --out-daily-csv reports/long_<mode>_daily.csv` をベースコマンドとして採用。
  - パラメータ探索は `threshold_lcb_pip`、`alpha_prior`、`or_n` を中心に試行し、各トライアルを `runs/phase4/backtests/<timestamp>_<mode>_<paramset>/` 以下に保存。
  - 週次レビュー時に `docs/progress_phase4.md` へ最新メトリクス表と改善サマリを追記。
- **安全策**:
  - 新パラメータで日次損失が-3σを超えるケースを `analysis/` スクリプトで抽出し、再度Runを検証する。
  - 成果反映前に `python3 -m pytest tests/test_runner.py tests/test_runner_features.py` を実行し、既存回帰が破損していないことを確認する。

### 2. 異常系テスト自動化（P4-02）
- **対象シナリオ**:
  - データ欠損: 必須カラム欠損、バー欠落（1時間連続欠損）。
  - マーケット異常: スプレッド急拡大（≥5pips）、異常ボラティリティ（価格ジャンプ > 3σ）。
  - システム障害: レイテンシ > 2秒、状態ロード不整合（config fingerprint mismatch）。
- **テスト方針**:
  - 既存 `tests/test_data_robustness.py` を拡張し、pytest parametrize で上記シナリオを網羅。
  - ダミーデータ生成ユーティリティを `tests/fixtures/data_quality.py`（新設予定）へ切り出し、異常系テスト間で再利用する。
  - 失敗時は `pytest -k robustness --maxfail=1` をCIで実行し、Slack通知（擬似）への連携をログ出力で確認する。
- **ドキュメント**:
  - `docs/state_runbook.md#incident` に異常系テストの再現手順と結果記録テンプレを追加。
  - 各シナリオの再現コマンドを `docs/progress_phase4.md` の「異常系テスト」節に一覧化。

### 3. Go/No-Go チェックリスト確定（P4-03）
- **チェック項目分類**:
  1. データ品質（カバレッジ ≥ 99.5%、欠損監視ログ更新）
  2. シミュレーション（最新長期バックテスト結果、異常系テスト結果）
  3. 運用準備（stateバックアップ、通知SLO、権限棚卸し）
  4. レビュー体制（承認者、エスカレーション窓口、レビューサイクル）
- **更新手順**:
  - `docs/go_nogo_checklist.md` に担当者・頻度・証跡リンク欄を追加。
  - モックレビュー結果を `docs/progress_phase4.md` の「運用チェックリスト」節に記録。
  - 完了後は `docs/todo_next_archive.md` にモックレビューの日付と所感を記載。

## 成果物更新とログ方針
- すべての検証コマンドは `state.md` に日付付きで記録し、再現用の引数と成果物パスを明示する。
- プランに沿った更新は、PR テンプレの「Testing」セクションでコマンドを列挙し、レビュワーが追跡できるようにする。
- 重要アーティファクト（`reports/long_*.json`, `runs/router_pipeline/latest`, `docs/go_nogo_checklist.md`）を更新した際は、PR本文に差分概要と参照リンクをまとめる。

## マイルストーン
| 週 | マイルストーン | 必須アウトプット |
| --- | --- | --- |
| Week 1 | ベースライン再実行とパラメータ探索セットアップ | 改訂`reports/long_{mode}.json`、`docs/progress_phase4.md`更新、探索用 runs ディレクトリ作成 |
| Week 2 | 異常系テストカバレッジ拡充 | 新規pytestケース、`docs/state_runbook.md`事故対応追記、CIコマンド定義 |
| Week 3 | Go/No-Go チェックリストレビュー | チェックリスト改訂版、モックレビュー記録、最終サマリPR案 |
| Week 4 | 総合レビューとフェーズ4 DoD判定 | 3領域の成果物統合ログ、`state.md`最終更新、承認サマリ |

## リスクと対応策
- **長期ランの実行時間**: 大規模レンジの再実行には数時間かかる可能性があるため、平行してショートレンジ検証を行い、進捗をブロックしない。
- **異常系データの再現性**: ダミーデータ生成が複雑化しないようテンプレ化し、fixturesで再利用する。
- **承認者アサインの遅延**: モックレビューに事前日程を設定し、`docs/go_nogo_checklist.md`で承認者・代理者を明記する。

## 今後の更新フロー
- 本ドキュメントは週次でレビューし、進行中のタスクに合わせてマイルストーンや評価軸を調整する。
- 更新時は `docs/progress_phase4.md` 冒頭にハイレベルな差分要約を記載し、レビュワーがフェーズ全体の健康状態を即時把握できるようにする。
