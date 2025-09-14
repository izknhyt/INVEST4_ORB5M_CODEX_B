# 第一目標・詳細設計書（5分足 ORB v1）— 投資3

最終更新: 2025-09-12 (Asia/Tokyo)

---

## 要約（結論先出し）

- **第一目標**: 5分足の **Opening Range Breakout（ORB）** を、**OCO/トレール対応・EVゲート（0.5pip）・分数ケリー**・保守/Bridge両Fill搭載で **E2E完成**させる。
- **完成の定義（DoD）**: 2018–2025通しで基準達成（Sharpe≥1.2/MaxDD≤10%/総益>0/プラス年過半）かつ Paper 30日でSLO達成（期待値誤差|月次平均|≤2bps/拒否≤2%）。テスト緑、結果ハッシュ化、ランブックあり。
- **展開方針**: 本戦術をテンプレ化し、5分MR、セッション別ORB、1Hスイングへ横展開。

---

## 前提 / 制約（DoR）

- **タイムフレーム**: 5m（UTC）。ライブはRESTで5分OHLC取得、メモリに直近200–1000本保持、Parquetへ追記。
- **データ契約**: JSON SchemaでOHLC/特徴量/約定ログを検証（型・単位・範囲・時間連続）。
- **コストモデル**: スプレッド（ライブ/バー）+ 期待スリッページ（EWMA）+ 手数料をpip換算。
- **EV推定**: OCO=Beta-Binomial（勝率LCB）、可変利幅=t下側分位。閾値は `EV_LCB ≥ 0.5 pip`。
- **サイズ**: 分数ケリー(0.25×)、1トレード損失≤0.5%、日次DD≤2%、クールダウン、近接指値マージ。
- **Fill**: 保守（不利側優先）/Bridge（Brownian Bridge近似）の二系統で**両合格必須**。
- **検証**: 2018-01-01〜2025-09-12の通し単一設定 + 年次“健康診断”。

---

## 代替案とトレードオフ → 採用理由（ADR要約）

- **戦術の選定**: ORB vs MR。→ **ORB採用**：パラメタ少・OCO相性◎・説明容易・5mで十分。
- **EV推定**: 平均±SE vs Beta-Binomial/t下限。→ **後者採用**：少数サンプル耐性・安全側評価。
- **Fill**: 保守のみ vs 保守+Bridge。→ **二重化採用**：順序曖昧性への感度分析を通過させる。
- **適応閾値**: 固定0.5pip vs 適応（PID/二分探索）。→ **固定で開始、日次微調整は後段**（ADR-013）。

**追加ADR（批判的レビューを踏まえて補強）**

- **ADR-021 ニュース凍結ウィンドウ**：主要経済指標の前後で新規エントリ停止（例：発表前2分〜後8分）。カレンダーフラグのみ（自動解釈なし）。
- **ADR-022 パラメータ安定性規範**：採択は\*\*高原（plateau）\*\*の中央を選ぶ。感度分析で上位20%が連結領域を作らない場合は不採択。
- **ADR-023 ネガティブコントロール**：ラベルのシフト/シャッフル、ランダム指値で**ゼロ性能**を確認。通らない場合はリーク疑いで差し戻し。
- **ADR-024 価格保護（Entry Stop-Limit）**：ブレイク時のエントリはストップ指値＋**最大許容滑り（slip\_cap）**。超過はキャンセル/再試行。
- **ADR-025 スプレッド推定子**：5分足運用では1分毎or直近ティックの**上位気配サンプル**から帯域化。ない場合は`spread_proxy = k×(high-low)`で代替。誤差はSLO監視。

**追加ADR（MVPの知見を反映）**

- **ADR-026 単位正規化**：ATR/TP/SL/Costはpipsで統一（JPY=0.01、他=0.0001）。内部は`pip_size/price_to_pips`で変換。
- **ADR-027 セッションOR**：ORはセッション開始からN本で確定。UTC→LDN/NYへマッピングし、境界で毎日リセット。
- **ADR-028 EVウォームアップ**：初期N件は最小サイズでEV門をバイパスして学習をブートストラップ（上限と終了条件を設ける）。
- **ADR-029 台帳v1**：`runs/<id>/`に`params/metrics/records/daily`を保存し、`runs/index.csv`で横断管理。
- **ADR-030 ゲート較正**：`rv_band/spread_band`はセッション分位で日次較正。固定値は初期しきい。
- **ADR-031 コスト拡張**：スリッページ/拒否率をコストに反映し、EV評価へ統合。
- **ADR-032 Bridge部分学習**：`p_tp`でBetaを部分更新（α+=p_tp, β+=(1−p_tp)）。
- **ADR-033 可観測性/ファネル**：候補詳細（records）/日次ファネル（daily）を成果物に含め、原因追跡を容易化。
- **ADR-034 CLI標準化**：パラメタ上書き・成果物保存・ランインデックスの標準I/Fを定義。

---

## システム境界（本第一目標で作る範囲）

```mermaid
flowchart LR
  subgraph Data
    REST[REST 5m OHLC]
    PQ[Parquet Store]
  end
  subgraph Core
    BL[bar_loader]
    FS[feature_store\n(ATR/ADX/OR/RV/SpreadBand)]
    FE[fill_engine\n(Conservative/Bridge)]
    EV[ev_gate\n(BetaBinomial/t-lower)]
    SZ[sizing\n(fractional Kelly + guards)]
    STG[strategy\n(day_orb_5m)]
    RT[router_v0\n(rule-based)]
    OMS[oms\n(stub)]
  end
  REST --> BL --> FS --> STG --> EV --> SZ --> FE --> OMS
  FS --> RT
  BL --> PQ
```

---

## データ契約（Data Contracts）

- **OHLC/5m**
  - `timestamp`(UTC, iso8601), `symbol`(str), `tf`("5m"), `o,h,l,c`(float), `v`(float|0可), `spread`(float≥0)。
  - 検証: `l ≤ min(o,c)`, `h ≥ max(o,c)`, `l ≤ h`, 5分間隔連続、欠損/NaN禁止。
- **特徴量**: `atr_14`, `adx_14`, `or_high/low(width_30m)`, `rv_1h`, `spread_band`(enum: narrow/normal/wide), `session`(TOK/LDN/NY)。
- **約定ログ**: `order_id`, `ts_submit/ack/fill`, `side`, `qty`, `entry_px`, `exit_px`, `slip_pip`, `pnl_pip`, `bucket_keys`, `ev_lcb_pip`, `mode(fill)`: conservative|bridge。

### Pip/単位の統一

- **pip定義**: `JPYクロス=0.01`, `その他=0.0001`。`pip_value(symbol, notional)`を共通関数で提供。
- **スプレッド推定**: 実測Bid/Askがない場合は`spread_proxy = k×(high-low)`（通貨別係数kを較正）。誤差は**期待値誤差SLI**で監視し、閾値超過で停止。
  
【追補（ADR-026）】実装では計算系の全てをpipsに正規化する。具体的には、ATRは価格単位→`atr_pips = atr_price / pip_size(symbol)`に変換し、`TP/SL/trail`は`k×atr_pips`で与える。`cost_pips = spread_price / pip_size + E[slip_pips]`。

#### データ検証手順（実務）
- スキーマ: 必須キー/型/範囲/単位（spreadは価格）。
- 連続性: 5分刻みで欠損/重複/逆順なし。DST/週末は許容スキップ。
- 価格整合: `l ≤ min(o,c)`, `h ≥ max(o,c)` に常に合致。
- ログ: 失敗コード（E001/E101..）とサンプル行を添付し、CIで停止。

---

## 特徴量とゲート

- **計算**: 5mバー到着時、ATR14/ADX14/OR幅(最初の6本=30m)/RV(過去12本=1h)を更新。
- **ゲート条件（初期）**:
  - `spread_band ∈ {narrow, normal}`
  - `rv_band ∈ {mid, high}`（RVは分位点で帯域化）
  - `session ∈ {LDN, NY}`

### 追加ゲート/保護

- **ニュース凍結**（ADR-021）: 発表前2分〜後8分は新規なし（手仕舞いは可）。
- **OR品質**: `OR幅 / ATR14 ≥ ρ_min`（例0.6）を満たす時のみ。極小ORのダマシ回避。
- **スプレッド/滑り保護**（ADR-024）: `spread_band ∈ {narrow, normal}` かつ `expected_slip ≤ slip_cap` を満たす時のみ。

【追補（ADR-027/030）】ORは「セッション開始から最初の`N_or`本」で確定し、境界で毎回リセットする。`rv_band`および`spread_band`は銘柄×セッションの分位（例: 過去20営業日の分位）で日次較正し、固定値は初期推定に留める。

---

## 戦術仕様（day\_orb\_5m v1）

- **Opening Range(OR)**: セッション開始から最初のN=6本（30分）の高値`OR_H`/安値`OR_L`。
- **エントリ**:
  - BUY: `high >= OR_H` を初回ブレイクで1回（クールダウン内は再エントリ禁止）
  - SELL: `low  <= OR_L` 同様
- **OCO/トレール**:
  - `TP = k_tp × ATR14`（例: 1.0）
  - `SL = k_sl × ATR14`（例: 0.8）
  - 追加で `trail = k_tr × ATR14` オプション（例: 0.5）
- **リスク**:
  - 1トレード損失 ≤ 0.5% of Equity
  - 日次DD ≤ 2% で当日停止
  - 同一通貨 同方向のクールダウン=3本
  - 【追補】セッション内の発注回数制限（例: 各方向1回）を推奨（実装ガードに含める）。

---

## EV推定・発注フィルタ

### OCO（既定）: Beta-Binomial

- バケツ: `[session, spread_band, rv_band, trend_flag(adx>閾)]`
- 事後: `p ~ Beta(α,β)` を EWMAで更新（α=ヒット数、β=ミス数; 初期α0=β0=1）
- 下限: `p_LCB = BetaInv(α,β; conf=95%)`
- **EV\_LCB**: `p_LCB×TP − (1−p_LCB)×SL − Cost`
- 閾値: `EV_LCB ≥ 0.5 pip` 未満は見送り

【追補（ADR-028/032）】コールドスタート時は最小サイズで`N_warmup`件のみEV門をバイパスして学習を立ち上げる。Bridgeモードでは`p_tp`を用いて`α+=p_tp, β+=(1−p_tp)`で部分更新し、Conservativeは0/1更新を維持する。

### トレール/可変利幅: t-lower

- EWMAで `mean_pip, std_pip, n_eff` を更新し、t分布の下側分位で`EV_LCB`を算出

### 安定化と小サンプル対策

- **階層ベイズ縮約**（ADR-016）: バケツ平均は全体平均へ部分プーリング。
- **近傍平滑化**: 近いバケツ（例: RV帯の隣接）を重み付き平均して急変を抑制。
- **サイズ制限 by サンプル数**: `n_eff < Nmin` のバケツは **サイズ0** または **縮小係数0.5×**。

【追補（Beta逆CDF）】実装はWilson近似から開始し、依存が許される環境では正確版（scipy.stats.beta）へ切り替える。

---

## サイズ決定（分数ケリー + ガード）

- ベース: `units_base = (r * Equity) / (pip_value * SL)`（r=0.25%）
- 強弱: OCOは `b=TP/SL`, `f* = max(0, p_LCB − (1−p_LCB)/b)`, `units = units_base * min(cap, 0.25×f*)`
- 可変利幅は `strength = sigmoid((EV_LCB−0.5)/k)` で連続スケール
- ガード: 1トレード損失上限・日次DD・クールダウン・近接指値マージ

---

## Fillエンジン（二系統）

- **Conservative**: 同バーでTP/SL両方候補時は\*\*不利側（SL）\*\*優先で充足
- **Bridge**: バー始値S/高H/安LでBrownian Bridge近似 → `P(TP先)` を推定し**期待充足**を計上
- **拒否/滑り**: `spread_band×size`で確率サンプリング、実績でEWMA更新

【追補（ADR-031/033）】コストは`spread + E[slip(size,band)]`で評価し、拒否/滑りの実績は日次ファネルと`records.csv`に要因として記録する。

---

## 受入基準（DoD・定量）

- **通し2018–2025**: 総益>0、Sharpe≥1.2、MaxDD≤10%、**プラス年が過半**

- **二重Fill**: Conservative/Bridge **両方**で上記を満たす

- **Paper≥30日**: |期待値誤差の月次平均|≤2bps、拒否≤2%、稼働安定

- **テスト**: ユニット/プロパティ/回帰（結果ハッシュ一致）、Chaos（ネットワーク断復旧）

- **パラメータ安定性**（ADR-022）: 感度マップ（`N_or, k_tp, k_sl`）で\*\*高原（上位20%連結）\*\*を確認。孤立ピークは不採択。

- **ネガティブコントロール**（ADR-023）: シフト/シャッフル/ランダム指値のスコアが**ゼロ近傍**であること。

- **ワースト日制約**: 単日損益のp1分位が `≥ −2σ` を満たす（極端なファットテールは警告）。

【追補（再現性/台帳）】ランは`runs/<id>/`に`params.json/csv, metrics.json, daily.csv, records.csv`を保存し、`runs/index.csv`に行を追記すること。受入時は同一入力でハッシュ・指標が一致すること。

---

## バックテスト計画（2018-01-01〜2025-09-12）

- 指標: 総益/CAGR/Sharpe/Sortino/MaxDD/Calmar/勝率/期待値/Turnover/Fill差分（Cons vs Bridge）

- 年次“健康診断”: 年別損益/MaxDD/最大連敗/ゲート通過率

- ファネル/原因追跡（ADR-033）: `daily.csv` に `breakouts, gate_pass, gate_block, ev_pass, ev_reject, fills, wins, pnl_pips` を日次で出力。`records.csv` に `stage(gate/ev/trade)`, `rv_band`, `spread_band`, `or_atr_ratio`, `tp_pips/sl_pips`, `cost_pips`, `ev_lcb`, `exit`, `pnl_pips` を最大N件保存。

- アーティファクト（ADR-029/034）: `runs/<id>/params.json(cvs)/metrics.json/daily.csv/records.csv` を保存し、`runs/index.csv` に1行追記。構成ハッシュ（データ範囲/主要設定/コミット）を`metrics.json`に格納。

- **ストレス項目**: Covid急変（2020-03）、円急変（2022-09/10）を**個別章**で分解。ニュース凍結の有無・slip\_capの有無で感度比較。

- **パラメータ感度**（ADR-022）: `N_or ∈ {4..8}, k_tp ∈ {0.8..1.6}, k_sl ∈ {0.6..1.2}` のグリッドでヒートマップ出力。上位20%の連結性（高原）を確認。

---

## ランブック（抜粋）

- スプレッド急拡大: ルーターで減点→自動停止、`threshold_lcb_pip`は上方へ一時引上げ
- API停止: REST再試行→失敗なら安全停止（全注文取消）
- DD超過: 当日停止、翌営業日再開には承認が必要
- 台帳運用: `runs/index.csv` を週次レビュー。ベストランへ`runs/best/`のシンボリックリンクを張替え、`params.json`で再現手順を残す。

---

## 設定ファイル（雛形）

### `configs/runtime.yml`

```yaml
bar_tf: 5m
buffer_len: 200
persist: parquet
symbols: [USDJPY, EURUSD]
sessions:
  tokyo:   { start: "00:00", end: "07:59" }
  london:  { start: "08:00", end: "12:59" }
  newyork: { start: "13:00", end: "21:59" }
or_reset: session   # session | daily
router:
  min_or_atr_ratio: 0.6
  allow_low_rv: false
cooldown_bars: 3
```

### `configs/ev_estimator.yml`

```yaml
ev_estimator:
  oco:
    mode: beta_binomial
    conf_level: 0.95
    decay: 0.02
    min_trades_per_bucket: 50
  trailing:
    mode: t_lower
    conf_level: 0.95
    decay: 0.02
cost_model:
  spread_source: live_or_bar_mid
  slippage_estimator: ewma
  slip_curve:
    narrow: { a: 0.02, b: 0.000 }   # slip_pips ≈ a*size + b
    normal: { a: 0.05, b: 0.000 }
    wide:   { a: 0.10, b: 0.000 }
buckets:
  keys: [session, spread_band, rv_band, trend_flag]
  bands:
    spread_band: [narrow, normal, wide]
    rv_band: [low, mid, high]   # 初期値。運用ではセッション分位で較正
  trend_flag:
    adx_threshold: 18
gate:
  threshold_lcb_pip: 0.5
  warmup_trades: 0
```

### `configs/sizing.yml`

```yaml
sizing:
  risk_per_trade_pct: 0.25
  method: fractional_kelly
  kelly_fraction: 0.25
  units_cap: 5.0
  cooldown_bars: 3
  max_daily_dd_pct: 2.0
  max_trade_loss_pct: 0.5
  equity_update: trade   # trade | daily
```

### `configs/acceptance.yml`

```yaml
acceptance:
  oos_2018_2025:
    total_profit_pip: "> 0"
    sharpe: ">= 1.2"
    max_dd_pct: "<= 10"
    positive_year_ratio: ">= 0.5"
  paper_30d:
    ev_bias_abs_bps: "<= 2"
    reject_rate_pct: "<= 2"
  stability:
    plateau_top20_connected: true
    neg_controls_zero_performance: true
    worst_day_p1_sigma: ">= -2"
  reproducibility:
    both_fills_ok: true
    repro_hash_match: true
```

### `configs/data_manifest.yml`

```yaml
data_manifest:
  ohlc_5m:
    provider: "broker_or_public"
    symbols: [USDJPY, EURUSD]
    start: "2018-01-01"
    end: "2025-09-12"
    storage: parquet
```

---

## 擬似コード（骨格）

```python
# strategies/day_orb_5m.py
class DayORB5m(Strategy):
    def on_bar(self, bar):
        update_or_window(bar)
        if break_up(bar):  self.signal = make_signal("BUY")
        elif break_dn(bar): self.signal = make_signal("SELL")
    def signals(self):
        if not self.signal or not pass_gates(self.ctx):
            return []
        ev_lcb = self.ctx.ev.oc o_ev_lcb(self.signal, self.ctx)  # beta-binomial or t-lower
        if ev_lcb < 0.5: return []
        units = self.ctx.sz.size(self.signal, ev_lcb, self.ctx)
        return [OrderIntent(..., oco=self.signal)]
```

---

## 品質 / テスト

- **ユニット**: OR計算・ADX/ATR・バケツ更新・BetaInv・t分位・ケリー計算
- **プロパティ**: pip換算の可逆性、OCO一意性、資産保存則
- **回帰**: 固定データ/固定乱数で結果ハッシュ一致
- **Chaos**: ネットワーク断/重複バー/遅配での自動復旧

### ネガティブコントロール/プレースボ

- **Time-Shift**: 特徴量と結果を±kバーずらして**性能が消える**ことを確認。
- **Shuffle**: エントリタイミングをランダム化 → **ゼロ性能**であることを確認。
- **Random-Limit**: 指値をノイズに置換 → **ゼロ性能**を確認。

---

### テストチェックリスト（実行順）

1) データ契約（Data Contracts）
   - JSON Schema適合: フィールド/型/範囲/単位（spreadは価格単位）。
   - 5分間隔の連続性: 欠損/重複/逆転なし、UTC一貫、DST境界の扱い確認。
   - 失敗時は理由ログを出し、CIを赤にする（サンプル行を添付）。

2) 特徴量の単体テスト（Unit）
   - ATR/ADX/OR幅/RV: 既知ケースの計算一致、端点（NaN/短窓）で安定に零/NaNへフォールバック。
   - 単位整合: `atr_price / pip_size == atr_pips` の可逆性、`pips_to_price/price_to_pips`の往復一致。

3) ルーター/ゲート（Rule）
   - `rv_band/spread_band/or_atr_ratio` の境界条件（ちょうど閾値・外側）で期待通り通過/棄却。
   - セッションOR: 境界でORがリセットされ、最初のN本のみで確定すること。

4) EV/サイズ（Unit + Property）
   - Beta逆CDF（Wilson→正確版）: 既知パラメタでLCBの単調性・境界挙動。
   - 分数ケリー: `b=TP/SL`、`p_LCB` に対する単調性、サイズ上限/1トレード損失上限の遵守。
   - t-lower: `mean/var/n_eff` に対するLCBの単調性、最小SE下限の尊重。

5) Fill（Conservative/Bridge）
   - Conservative: 同バーTP/SL両到達で不利側（SL）優先、片側のみ到達は決定的。
   - Bridge: 上下距離とドリフトの符号に対して `p_tp` が直感通り（近い方/順方向で上がる）。

6) 回帰テスト（Regression）
   - 固定CSV＋固定乱数で `metrics.json` のハッシュ一致（ピップス/件数/勝率）。
   - Conservative/Bridge の双方で基準値を保持（許容差±ε）。

7) ネガティブコントロール（Leak Check）
   - 時間シフト/シャッフル/ランダム指値で**ゼロ性能**近傍（勝率≈50%/期待値≈0）。

8) Chaos/堅牢性
   - 欠落バー/遅配/重複を挿入して無落ち（スキップ/復旧）。
   - 例外は握り潰さずに理由ログ＋フェールファスト。

9) 台帳/再現性
   - `--out-dir runs/` で `params/metrics/daily/records` が生成され、`runs/index.csv`に1行追加される。
   - 同一入力/設定で再実行し、主要指標と構成ハッシュが一致。

10) 受入（DoD）
   - 通し2018–2025での基準到達（Sharpe/MaxDD/年次過半/総益>0）。
   - Conservative/Bridgeの両立（両モードでDoD達成）。

テスト運用メモ
- ユニット/プロパティはプッシュ時に常時。回帰/Chaos/ネガコンはナイトリーや手動トリガで十分。
- 失敗時は `records.csv` の該当行を添付し、ゲート/EV/Fillのどこで落ちたかを示す。

### Conservative / Bridge 併走レポート（雛形）
- 概要: 同一パラメタ・同一データで両Fillモードを並走し、差分と整合性を確認する。
- 出力（CSV案）
  - `date, fills_cons, fills_bridge, pnl_cons_pips, pnl_bridge_pips, diff_pips, winr_cons, winr_bridge`
  - `gate_pass, ev_pass` も共通列として付与すると因果切り分けに有用。
- サマリ（metrics.json案）
  - `total_pips_cons/bridge`, `wins_cons/bridge`, `trades_cons/bridge`, `corr_daily_pnl`（両者の日次PnL相関）, `diff_stats`（平均/分散/勝率差）
- 受入の目安
  - 差分の符号・大きさが**想定範囲**（Bridgeは中立〜わずか優位、保守は安全側）
  - 併走でDoD基準を両立（両モードで Sharpe/MaxDD 基準達成）

## ロードマップ（第一目標の範囲）

1. リポ雛形＋契約＋設定（本書に沿って作成）
2. 特徴量/ゲート/戦略骨格/EV/t-lower/ケリー実装
3. Fill（保守/Bridge）実装、拒否・滑りモデル
4. 2018–2025通しBT → 年次表＆レポ → DoD判定
5. Paper 30日 → SLO評価 → リリース判定

【追加：運用MVP反映タスク】
6. セッションOR化・クールダウン実装・Equity反映（日次DD停止）
7. コストモデル拡張（スリッページ/拒否）とEV部分学習（Bridge）
8. ファネル/recordsの列拡張（rv_band/セッション内訳、コスト内訳）と自動グリッド探索

---

## 研究ワークフロー（CLI・台帳）
- 通しの基礎ラン（緩め設定）
  - 例: `--allow-low-rv --rv-cuts 0.004,0.012 --min-or-atr 0.4 --threshold-lcb 0.0 --warmup 50 --out-dir runs/`
  - 出力: `runs/<id>/params.json, metrics.json, daily.csv, records.csv`/ `runs/index.csv` に1行。
- 締め直し（現実化）
  - 門を段階的に厳格化。`index.csv` の勝率/総pips/pnl_per_tradeで比較。
- 比較（Cons vs Bridge）
  - 同パラメタで両モードを実行し、daily/recordsも比較保存。DoDは両立を要件化。
- 感度（小グリッド）
  - `N_or × k_tp × k_sl` を少数点で走らせ `index.csv` を横持ち集計（上位20%の連結性＝高原性を確認）。

---

## 既知の制約 / リスク

- ブローカー毎のスプレッド特性差 → コスト表を継続更新
- 公開データ品質のばらつき → Data Contract違反時はCIで停止
- ORBはトレンド/拡大型に偏る → MR系とポートフォリオ化が前提

---

## 変更履歴

- v1.0 初版作成（第一目標の詳細設計）
