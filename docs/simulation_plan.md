# シミュレーション完遂ロードマップ

## フェーズ0: ベースライン確認
- **データ品質監査**: `scripts/run_sim.py --debug` とスキーマ検証テストで2018–2024 CSVの欠損/重複/タイムゾーンを確認。異常リストを `analysis/data_quality.md` にまとめる。
- **既存ランの再現**: 代表的なパラメータセット（Bridge/Conservative両方）で `runs/index.csv` をクリーンに再構築し、過去の勝率/損益が再現できるかを検証。
- **state.json 管理体制**: `docs/state_runbook.md` に沿って初期ベースライン state を決め、以後の最適化で同一基準を使う。

## フェーズ1: 戦略とゲートの強化
- **戦略別ゲート整備**: DayORB をテンプレートに、他戦略でも `strategy_gate` / `ev_threshold` を実装できるよう共通インターフェースを整理。必要に応じて `StrategyConfig` の拡張項目を定義し、`docs/logic_overview.md#day-orb-パラメータ依存マトリクス` を参照しながら依存関係を反映する。
- **EVチューニング**: decay・prior・ウォームアップの推奨値を実測で比較し、`docs/ev_tuning.md` にケーススタディを追加。閾値自動調整の挙動をヒートマップで可視化。
- **Fillモデル検証**: `docs/broker_oco_matrix.md` の調査完了後、Bridge/Conservativeの差分を `analysis/broker_fills.ipynb` で比較し、必要に応じて `core/fill_engine.py` を拡張。

## フェーズ2: 最適化と分析パイプライン
- **ヒートマップ/時間帯分析**: `scripts/optimize_params.py` の出力を `analysis/param_surface.ipynb` で可視化し、時間帯別・セッション別の期待値差を確認。
- **Sharpe/最大DDサマリ**: `runs/index.csv` から Sharpe, 最大ドローダウン, 日次勝率などを集計する `scripts/summarize_runs.py` を追加し、定期レポートを自動生成。
- **自動探索ワークフロー**: `optimize_params.py --report` を cron/CI で定期実行し、トップパラメータと state の更新を自動化。結果を Slack 通知（`notifications/emit_signal.py`）と連携。

## フェーズ3: 運用準備とオプス
- **通知SLO運用**: `scripts/analyze_signal_latency.py` を日次ジョブ化し、p95レイテンシと失敗率を監視。SLO違反時はフォールバックログから手動通知フローを実行。
- **stateアーカイブ**: `ops/state_archive/` に state バージョニングとメタ情報を残し、復旧手順を `docs/state_runbook.md` に追記。
- **スケジューラ統合**: バックテスト/最適化/通知をまとめた orchestrator スクリプトを作り、Paper トレードに近い運用を想定。

## フェーズ4: 検証とリリースゲート
- **異常系テスト**: スプレッド急拡大・欠損バー・DB接続断などを模擬したテストケースを追加し、フェイルセーフ挙動を確認。
- **長期バックテスト**: 2018–2025 通しで conservative/bridge 両モードの成績を比較し、Sharpe・DD・年間勝率を受入基準としてまとめる。
- **運用チェックリスト**: 戦略更新前のチェック項目（stateのバックアップ、通知テスト、最適化結果レビュー）を runbook 化し、Paper 本番のGo/No-Go判定に活用。

## 成果物とマイルストーン
- 各フェーズ完了時に `docs/progress_<phase>.md` を作成し、設定ファイルや notebook サマリ・検証結果を保存。
- Paper トレードに移行する際の「完遂基準」を README と docs に明記し、誰が見ても完了条件が分かるようにする。
