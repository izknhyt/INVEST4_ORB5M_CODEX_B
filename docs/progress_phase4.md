# フェーズ4 進捗レポート（検証とリリースゲート）

## ハイライト（2026-07-05 更新）
- `scripts/run_sim.py` に `--no-auto-state` / `--auto-state` フラグを追加し、フェーズ4長期ランを過去 state に依存せず再現できるようにした。`configs/strategies/day_orb_5m.yaml` は Bridge モードを併記し、`runs/phase4/backtests/` 配下へベースライン run を保存してパラメータ探索の足場を確保。
- 直近の `validated/USDJPY/5m.csv` が 2025-10-02 以降のみをカバーしていることを確認し、ベースライン結果（Conservative/Bridge 各 1 トレード・-1.50pips）と合わせてデータギャップを記録。2018–2024 の validated スナップショット補完を TODO に登録。
- [フェーズ4検証計画](plans/phase4_validation_plan.md) を策定し、P4-01〜P4-03 の評価軸・マイルストーン・再現コマンドを統合管理できるようにした。
- 長期バックテストの評価基準（Sharpe・最大DD・年間勝率）と再実行コマンドを明文化し、週次レビューでメトリクスを追記する運用を定義。
- 異常系テストのシナリオ棚卸しと CI 実行方針を整理し、`tests/test_data_robustness.py` 拡張時の着地点を共有。
- Go/No-Go チェックリスト更新の担当分解とログ化ルールを確定、モックレビューの証跡化手順を整備。

## 設計・テスト方針ログ
- 2026-07-05: `configs/strategies/day_orb_5m.yaml` に Bridge モードを追加し、`scripts/run_sim.py --no-auto-state` で Conservative/Bridge のベースラインを `runs/phase4/backtests/` に保存。最新 `validated/USDJPY/5m.csv` が 2025 年 10 月以降のみであることを確認し、2018–2024 の validated データ再発行を TODO に登録。
- 2026-06-27: `docs/plans/phase4_validation_plan.md` を新設。長期バックテスト改善・異常系テスト自動化・Go/No-Go チェックリスト確定の3ストリームについて、評価軸、検証コマンド、アーティファクト更新ルール、週次マイルストーン、リスク対応を定義した。
- 2025-10-11: EV プロファイル更新手順を `scripts/aggregate_ev.py` で確認し、Conservative/Bridge 双方の比較材料を整備。

## 異常系テスト
### 現状カバレッジ
- `tests/test_data_robustness.py` を追加し、以下の異常ケースを検証済み。
  - 必須カラム欠損行を含むデータでも Runner が落ちないことを確認。
  - スプレッド急拡大（5.0pips）時にトレードを発行せず安全側に振る挙動をテスト。

### 追加設計（2026-06-27 更新）
- データ欠損（連続1時間欠損）、異常ボラティリティ（3σ超ジャンプ）、レイテンシ遅延、状態ロード不整合などのシナリオを pytest parametrize で追加予定。
- ダミーデータ生成ユーティリティを `tests/fixtures/data_quality.py`（予定）へ共通化し、テストケース間で再利用する。
- CI では `pytest -k robustness --maxfail=1` を最小セットとして実行し、Slack通知（擬似）ログで失敗を検知できるようにする。

### 再現コマンド
- `python3 -m pytest tests/test_data_robustness.py`
- （スモーク）`python3 -m pytest -k robustness --maxfail=1`
- フェーズ4長期ラン（state 自動ロード無効化）: `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv --mode <mode> --start-ts 2018-01-01T00:00:00Z --end-ts 2025-12-31T23:55:00Z --out-json reports/long_<mode>.json --out-daily-csv reports/long_<mode>_daily.csv --out-dir runs/phase4/backtests --no-auto-state`

## 長期バックテスト
### 現状サマリ（2026-07-05 更新）
- Conservative (`--mode conservative --no-auto-state`) で `runs/phase4/backtests/USDJPY_conservative_20251011_223142` を生成。`reports/long_conservative.json` は 1 trade / total -1.50 pips / Sharpe 0.0 / max_drawdown -14.98 を記録し、`validated/USDJPY/5m.csv` が 2025-10-02 以降のみを含むため長期統計を得られないことが判明。
- Bridge (`--mode bridge --no-auto-state`) で `runs/phase4/backtests/USDJPY_bridge_20251011_223149` を生成。`reports/long_bridge.json` も Conservative と同一の 1 トレード結果となり、validated データの不足が主要ボトルネックであると確認。
- 日次ログは `reports/long_*_daily.csv` に保存済み。2018–2024 validated スナップショットを再構築してから Sharpe / 最大DD / 年間勝率の評価をやり直す必要がある。

### 改善計画（2026-07-05 更新）
- 日次 Sharpe ≥ 0.15 / 最大DD ≥ -8% / 年間勝率 ≥ 52% を暫定目標とし、Bridge/Conservative 双方で達成する。
- `threshold_lcb_pip`・`alpha_prior`・`or_n` を中心にパラメータ探索し、各トライアルを `runs/phase4/backtests/<timestamp>_<mode>_<paramset>/` に保存して比較。
- ベースコマンド：
  - `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv --mode <mode> --start-ts 2018-01-01T00:00:00Z --end-ts 2025-12-31T23:55:00Z --out-json reports/long_<mode>.json --out-daily-csv reports/long_<mode>_daily.csv --out-dir runs/phase4/backtests --no-auto-state`
- 週次レビューで `docs/progress_phase4.md` にメトリクス表を追記し、改善度合いをトラッキングする。
- 成果反映前に `python3 -m pytest tests/test_runner.py tests/test_runner_features.py` を実行し、既存回帰が破損していないかを確認する。

## 運用チェックリスト
- `docs/go_nogo_checklist.md` を作成し、Paper 移行前に確認すべき項目を整理。
  - データ品質・通知SLO・stateバックアップ・最適化結果レビューなどを含む。
- 2026-06-27: フェーズ4検証計画に沿って、チェック項目を「データ品質 / シミュレーション / 運用準備 / レビュー体制」に分類し、担当者・頻度・証跡リンク欄を追加予定。モックレビュー結果は本節でログ化する。

## TODO (フェーズ4 継続)
- 長期バックテスト結果を改善するためのパラメータ再検討（Bridge/Conservativeともにマイナスのため）。
- 異常系テストを `pytest` で自動実行可能になるよう環境整備（新規シナリオのfixtures共通化、CI設定追加）。
- `docs/go_nogo_checklist.md` を実際の運用で更新し、承認履歴を残す（担当者・頻度・証跡リンク欄を整備）。
- Conservative 向け EV プロファイルを用いた `threshold_lcb_pip` 探索（0.25〜0.5 pip）と OR 窓幅 (`or_n`) の感度分析を分割ランで実施、結果を `reports/long_conservative*.json` 系へ反映。
- validated/USDJPY/5m.csv を 2018–2024 期間のヘッダ付きスナップショットに差し替え、ベースライン統計を再確認する。必要に応じて `scripts/check_data_quality.py` で欠損・重複を検証したうえでフェーズ4メトリクスへ反映。
