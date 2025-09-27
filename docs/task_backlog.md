# 作業タスク一覧（バックログ）

このバックログは「最新値動きを取り込みながら継続学習し、複数戦略ポートフォリオでシグナルを出す」ツールを実現するための優先順位付きタスク群です。各タスク完了時は成果物（コード/ドキュメント/レポート）へのリンクを追記してください。

## P0: 即着手（オンデマンドインジェスト + 基盤整備）
- **state 更新ワーカー**: 取得済みバーを時系列順に処理し、`BacktestRunner.load_state` → `runner.run_partial()` → `runner.export_state` を繰り返す CLI を実装。`ops/state_archive/<strategy>/<symbol>/<mode>/` に最新5件を保存し、更新後に `scripts/aggregate_ev.py` を自動実行できるようにする。
- **ベースライン/ローリング run 起動ジョブ**: ORB コア設定の通し run と直近ローリング run を起動時にまとめて再計算し、`runs/index.csv`・`reports/baseline/*.json`・`reports/rolling/<window>/` を更新。前回結果との乖離が閾値超過したら Webhook 通知。

## P1: ローリング検証 + 健全性モニタリング
- **ローリング検証パイプライン**: 直近365D/180D/90Dのシミュレーションを起動バッチで更新。`scripts/run_benchmark_runs.py` と `scripts/report_benchmark_summary.py` で `reports/rolling/<window>/*.json`・`reports/benchmark_summary.json` を生成し、勝率/Sharpe/DD のトレンドを可視化する仕込みを進める。
- **state ヘルスチェック**: 最新 state から EV 下限、勝率 LCB、滑り推定値を抽出する `scripts/check_state_health.py` を活用し、結果を `ops/health/state_checks.json` に追記。逸脱時の通知/Runbook 追記を行う。
- **インシデントリプレイテンプレート**: 本番での負けトレードを `ops/incidents/` に保存し、同期間のリプレイを `scripts/run_sim.py --start-ts/--end-ts` で再実行する Notebook (`analysis/incident_review.ipynb`) にメモを残す。

## P2: マルチ戦略ポートフォリオ化
- **戦略マニフェスト整備**: スキャル/デイ/スイングの候補戦略ごとに、依存特徴量・セッション・リスク上限を YAML で定義し、ルーターが参照できるようにする (`configs/strategies/*.yaml`)。
- **ルーター拡張**: 現行ルールベース (`router/router_v0.py`) を拡張し、カテゴリ配分・相関・キャパ制約を反映。戦略ごとの state/EV/サイズ情報を統合してスコアリングする。
- **ポートフォリオ評価レポート**: 複数戦略を同時に流した場合の資本使用率・相関・ドローダウンを集計する `analysis/portfolio_monitor.ipynb` と `reports/portfolio_summary.json` を追加。

## P3: 観測性・レポート自動化
- **シグナル/レイテンシ監視自動化**: `scripts/analyze_signal_latency.py` を日次ジョブ化し、`ops/signal_latency.csv` をローテーション。SLO違反でアラート。
- **週次レポート生成**: `scripts/summarize_runs.py` を拡張し、ベースライン/ローリング run・カテゴリ別稼働率・ヘルスチェック結果をまとめて Webhook送信。
- **ダッシュボード整備**: EV 推移、滑り推定、勝率 LCB、ターンオーバーの KPI を 1 つの Notebook or BI に集約し、運用判断を迅速化。

## 継続タスク / 保守
- データスキーマ検証 (`scripts/check_data_quality.py`) を cron 化し、異常リストを `analysis/data_quality.md` に追記。
- 回帰テストセットを拡充（高スプレッド、欠損バー、レイテンシ障害等）し、CI で常時実行。
- 重要な設計・運用変更時は `readme/設計方針（投資_3_）v_1.md` と `docs/state_runbook.md` を更新し、履歴を残す。

> 補足: 着手順は P0 → P1 → P2 の順。途中で運用インシデントが発生した場合は、P1「インシデントリプレイテンプレート」の整備を優先してください。
