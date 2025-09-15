# 投資3 — 5分足 ORB v1（Paper-ready雛形）
設計ソース: キャンバス「第一目標・詳細設計書（5分足 ORB v1）— 投資3」 v1.1

## 概要
- 戦術: 5m Opening Range Breakout（OCO/任意トレール）
- EVゲート: OCO=Beta-Binomial（勝率LCB）/ トレール=t下側分位、閾値 EV_LCB ≥ 0.5 pip
- Fill二系統: Conservative / Bridge（Brownian Bridge近似のフック）
- サイズ: 分数ケリー(0.25×) + ガード（1トレード≤0.5%, 日次DD≤2%, クールダウン）

## 使い方（簡易）
1) `configs/*.yml` を確認・調整
2) バックテスト/リプレイの実装を後続コミットで追加（この雛形は骨格）
3) `strategies/day_orb_5m.py` を中心に拡張

### 現状の実装状況（骨格）
- 戦略`day_orb_5m`はOR計算→ブレイク検出→EVゲート→分数ケリーで`qty`決定までを実装
- EVゲートは`core.ev_gate.BetaBinomialEV`を参照（`ctx['ev_oco']`にインスタンスを渡す）
- サイズ計算は`core.sizing`（`ctx['equity']`, `ctx['pip_value']`, `ctx['sizing_cfg']`が必要）
- ルーターゲートは`router/router_v0.py`（`session/spread_band/rv_band`等は`ctx`に渡す）
- 注文はOCOパラメータ（`tp_pips/sl_pips/trail_pips`）を`OrderIntent.oco`に格納

### 簡易ランナー（BT/リプレイ雛形）
- `core/runner.py` に最小限のバックテスト実行器を追加（データ契約の簡易検証/特徴量算出/ゲートCTX構築/Fillシミュレーション/EV更新/メトリクス集計）
- 使い方（例）

```python
from core.runner import BacktestRunner

runner = BacktestRunner(equity=100_000.0, symbol="USDJPY")
metrics = runner.run(bars, mode="conservative")  # barsはOHLC5mのリスト
print(metrics.as_dict())
```

備考: スプレッド帯域・RV帯域・セッション判定は簡易版（プレースホルダ）。実データに合わせて更新してください。

### CLI（MVP）
- CSVから実行し、JSONメトリクスを出力する最小CLIを追加
  - `scripts/run_sim.py`
  - 入力CSVはヘッダ行必須: `timestamp,symbol,tf,o,h,l,c,v,spread`

実行例:

```
python3 scripts/run_sim.py --csv data/ohlc5m.csv --symbol USDJPY --mode conservative --equity 100000
```

ファイル出力:

```
python3 scripts/run_sim.py --csv data/ohlc5m.csv --symbol USDJPY --json-out out.json
```

### 両Fill併走レポート
- ConservativeとBridgeを同条件で比較するCLI
  - `scripts/run_compare.py`

実行例:

```
python3 -m scripts.run_compare --csv data/usdjpy_5m_2018-2024_utc.csv --symbol USDJPY --equity 100000 --out-dir runs/
```

出力:
- `runs/compare_<symbol>_<ts>/cons.metrics.json` / `bridge.metrics.json`
- `runs/compare_<symbol>_<ts>/daily_compare.csv`
- `runs/index.csv` に比較行を追記

### 小グリッドサーチ（N_or×k_tp×k_sl）
- 複数パラメータの組み合わせを一括実行して保存
  - `scripts/run_grid.py`

実行例:

```
python3 -m scripts.run_grid \
  --csv data/usdjpy_5m_2018-2024_utc.csv --symbol USDJPY --equity 100000 \
  --or-n 6 --k-tp 0.8,1.0,1.2 --k-sl 0.6,0.8 \
  --threshold-lcb 0.2 --out-dir runs/
```

出力:
- 各組み合わせで `runs/grid_<symbol>_<mode>_or<..>_ktp<..>_ksl<..>_<ts>/` を作成
- `runs/index.csv` に各ランのサマリ行を追記（or_n/k_tp/k_sl と成績）

進捗表示:
- デフォルトで各コンボの開始時に `[i/N] ... elapsed=.. ETA=..` を標準エラーへ表示
- サイレント実行は `--quiet` を付与

開発時は、実行側で以下のような`ctx`辞書を戦略へ提供してください（例）:

```python
ctx = {
  'session': 'LDN', 'spread_band': 'normal', 'rv_band': 'mid',
  'expected_slip_pip': 0.2, 'slip_cap_pip': 1.5,
  'ev_oco': BetaBinomialEV(conf_level=0.95, decay=0.02),
  'cost_pips': 0.1, 'threshold_lcb_pip': 0.5,
  'equity': 100_000.0, 'pip_value': 10.0,
  'sizing_cfg': {'risk_per_trade_pct':0.25,'kelly_fraction':0.25,'units_cap':5.0,'max_trade_loss_pct':0.5},
}
```

## 注意
- この雛形は**設計に沿った骨格**です。実データ接続/BTランナー/ダッシュボードは以後の実装で追加します。
-　現在の設計方針及び詳細設計はreadmeフォルダを参照すること。


## Codex Cloud の使い方（必読）

> Cloudタスクは毎回まっさらな環境で動きます。**下の3ファイルだけ読めば連続作業が再開できる**設計です。

### 1. まず読むもの
- `readme/ops/AGENTS.md` … ルール・受け入れ基準
- `readme/ops/STATE.md` … 要約・Next・決定事項・履歴
- `readme/ops/missions/<当該ミッション>.md` … 1タスク=1枚（例：`readme/ops/missions/2025-09-15_orb_acceptance.md`）

### 2. Cloud に貼る定型プロンプト
    これから Cloud タスク。以下の3ファイルだけ読んで実行：
    1) readme/ops/AGENTS.md
    2) readme/ops/STATE.md
    3) readme/ops/missions/2025-09-15_orb_acceptance.md  # ←必要に応じて差し替え

    手順:
    - Steps の一番上だけやる
    - 必要な最小ファイルのみ編集
    - `pytest -q` で緑を確認
    - `readme/ops/STATE.md` の Next/Done を更新し、意味のあるメッセージでコミット
    - 失敗したら原因を STATE.md の Summary に1行で追記して再提案

### 3. 注意
- **未コミットの変更は Cloud から見えません。必ずコミットしてから実行。**
- 大きなデータや生成物は `tests/runs_test/` に出力して管理（破壊的変更は避ける）。


## タスク運用（Now / Next ルール・必読）

> 連続性は `readme/ops/STATE.md` に一本化します。Cloud/ローカル問わず **毎回ここを読んでから作業**します。

### 1) 記載場所
- **必ず** `readme/ops/STATE.md` に現在タスクと次タスクを記載します。
- ミッションの詳細手順は `readme/ops/missions/<日付_名前>.md` に1枚＝1タスクで置きます。
- プロジェクトの掟（許可/禁止/受け入れ基準）は `readme/ops/AGENTS.md` に固定します。

### 2) STATE.md の書式（固定）
```md
# STATE.md (必読)

## Summary
1–3行で現状メモ

## Now (do this first)
- [ ] いま着手すべき1件だけを書く（ミッション名や対象ファイルを具体的に）

## Next (queue)
- [ ] 次にやる候補（上から順）
- [ ] 次にやる候補

## Decisions
- 決定事項と理由（簡潔に）

## Done
- YYYY-MM-DD: 完了タスク（1行ずつ）

### 3) Cloud に貼る定型プロンプト
- これから Cloud タスク。以下の3ファイルだけ読んで実行：
- 1) readme/ops/AGENTS.md
- 2) readme/ops/STATE.md   ← **Now を必ず実行**（空なら Next の先頭を Now に昇格）
- 3) readme/ops/missions/<当該ミッション>.md

手順:
- Now の1件だけを最小編集で完了
- `pytest -q` で緑を確認
- STATE.md の Now を Done に移し、必要なら Next 先頭を Now に昇格
- 意味のあるコミットメッセージでコミット
- 失敗したら原因を STATE.md の Summary に1行追記して再提案

### 4) レビュー時のチェックリスト

- PR の内容が STATE.md の Now と一致している
- 作業後に STATE.md が更新されている（Now→Done、Next の繰り上げ）
- テストが緑（pytest -q）／受け入れ基準に合致している