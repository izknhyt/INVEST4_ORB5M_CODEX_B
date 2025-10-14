# 2025-10-13 Day ORB 5m 長期ラン結果

## 実行コマンド
- `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv --mode conservative --out-dir runs/tmp/day_orb5m_20251013_conservative --json-out reports/simulations/day_orb5m_20251013_conservative_metrics.json --out-daily-csv reports/simulations/day_orb5m_20251013_conservative_daily.csv --no-auto-state --debug --debug-sample-limit 0`
- `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv --mode bridge --out-dir runs/tmp/day_orb5m_20251013_bridge --json-out reports/simulations/day_orb5m_20251013_bridge_metrics.json --out-daily-csv reports/simulations/day_orb5m_20251013_bridge_daily.csv --no-auto-state --debug --debug-sample-limit 0`

## 集計サマリ
| Mode | Trades | Wins | Win Rate | Total Pips | Sharpe | Max DD | Gate Block | Zero Qty |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| conservative | 0 | 0.0 | — | 0.0 | — | — | 196,554 | 248,230 |
| bridge | 0 | 0.0 | — | 0.0 | — | — | 196,554 | 248,230 |

## 所見
- OR ブレイクアウト条件を満たしたバーが無かったか、もしくは `_last_gate_reason` に該当するガードで 100% ブロックされたため、どちらのモードでもトレードが発生しなかった。
- `gate_block` / `zero_qty` が突出しており、ATR 帯・日次本数・サイズ計算のいずれかで停止している可能性が高い。`records.csv` を `scripts/summarize_strategy_gate.py` で解析し、緩和対象のガードを特定する必要がある。
- 次回のシンプル化リブート検証では、同一条件でトレードが発生すること（少なくともサンプル期間で複数回の fill）を DoD に含め、パラメータ調整の優先度を上げる。

## ガード解析（2025-01-01〜2025-10-13 抜粋）
- Conservative / Bridge いずれも `gate_block=19,091` 件のすべてが `router_gate` 理由で、RV バンドは高・中が 99% を占め、スプレッドは常に `narrow` だった。すなわちスプレッド拡大ではなくルーターのセッション許可で落ちている。【F:reports/simulations/day_orb5m_20250101_conservative_gate_block.json†L1-L35】【F:reports/simulations/day_orb5m_20250101_bridge_gate_block.json†L1-L35】
- `strategy_gate=41` 件は全て `or_filter` で、`or_atr_ratio` の平均 0.18 が `min_or_atr_ratio=0.25` を割り込んでいた。低ボラティリティ環境では OR 幅が閾値未満となり、シグナルが成立しない。【F:reports/simulations/day_orb5m_20250101_conservative_strategy_gate.json†L1-L41】【F:reports/simulations/day_orb5m_20250101_bridge_strategy_gate.json†L1-L41】【F:configs/strategies/day_orb_5m.yaml†L20-L36】

## トレードゼロの主因整理
1. **セッション制約によるルーター拒否**: 上記の通り、OR シグナルの大半が `router_gate` で却下されている。`BacktestRunner._session_of_ts` は 08:00–12:59 UTC を LDN、13:00–21:59 UTC を NY と定義し、その他の時間は TOK 扱いに落ちるため、Manifest の `allowed_sessions: [LDN, NY]` では東京時間のシグナルをすべて棄却する。【F:core/runner.py†L1436-L1454】【F:configs/strategies/day_orb_5m.yaml†L40-L46】
2. **OR/ATR フィルタのしきい値不足**: `or_atr_ratio` が 0.25 に届かないケースが 41 件あり、Breakout 幅が十分でも ATR 低下でフィルタに引っ掛かっている。最小値 0.00・中央値 0.18 のレンジを見ると、現状の閾値では低ボラ期間をほぼ全て除外してしまう。【F:reports/simulations/day_orb5m_20250101_conservative_strategy_gate.json†L1-L41】
3. **EV 無効化時のサイジングが常にゼロ**: 2018–2025 通しランでは `zero_qty=248,230` 件が計測され、EV オフでも Runner 側が `manager.p_lcb()` を用いた Kelly サイジングを実行しているため、初期 LCB≈0.12 では倍率が 0 となってポジションサイズが切り捨てられる。【F:reports/simulations/day_orb5m_20251013_conservative_metrics.json†L1-L33】【F:core/runner_entry.py†L572-L604】【F:core/sizing.py†L101-L123】戦略本体は EV オフ時に `fallback_win_rate` を 0.55 に設定して同じ関数を呼び出しているが、Runner 手前で止まるため活用されていない。【F:strategies/day_orb_5m.py†L320-L358】

## 改善提案
- **EV オフ用のサイジング・フォールバックを Runner に移植**: `core/runner_entry.SizingGate` が EV オフ時も Kelly ベースで `p_lcb` を要求するため、`ev_mode="off"` かつ EV バケット未学習のケースでは `fallback_win_rate` を利用した固定勝率（例: 0.55）や `size_floor_mult` を適用する分岐を Runner 側へ追加する。これにより `zero_qty` の大量発生を防ぎ、戦略ロジックのフォールバックと整合させられる。【F:core/runner_entry.py†L572-L604】【F:strategies/day_orb_5m.py†L320-L358】
- **セッションガードと OR 窓の再調整**: `router_gate` が Tokyo 時間で集中しているため、(a) OR の観測窓を LDN 開場に合わせてシフトする、(b) Manifest の `allowed_sessions` を段階的に拡張する、のいずれかを試し、Ldn/NY 開場中のシグナルが獲得できることを確認する。調整後は `scripts/summarize_strategy_gate.py` で再度分布を確認する。【F:reports/simulations/day_orb5m_20250101_conservative_gate_block.json†L1-L35】【F:core/runner.py†L1436-L1454】
- **`min_or_atr_ratio` の暫定緩和と分布監視**: 0.25 に固定されている閾値を段階的に 0.15–0.20 へ引き下げ、`or_atr_ratio` の日次分布と勝率を比較する。緩和後は `strategy_gate` レコードで低ボラ期間の増加分と勝率劣化の有無を検証し、最終的な閾値を決定する。【F:reports/simulations/day_orb5m_20250101_conservative_strategy_gate.json†L1-L41】【F:configs/strategies/day_orb_5m.yaml†L20-L36】
